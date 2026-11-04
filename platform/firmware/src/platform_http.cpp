#include "platform_http.h"

#include <algorithm>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <climits>
#include <strings.h>

#include "esp_timer.h"
#include "esp_tls.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "http_parser.h"
#include "lwip/dns.h"
#include "lwip/ip_addr.h"
#include "lwip/tcpip.h"

namespace mianguang_platform {
namespace {
constexpr int64_t kRequestUs = 5000000;
constexpr size_t kMaxBody = 512;
constexpr size_t kMaxHeaders = 2048;

// A timed-out DNS query still owns this slot until its callback finishes. Both
// callbacks receive static storage, never a pointer into a returned stack frame.
struct DnsLookup {
  enum State { Idle, Pending, Found, Failed };
  char host[254]{};
  ip_addr_t address{};
  std::atomic<State> state{Idle};
} dns;

void dns_found(const char*, const ip_addr_t* address, void*) {
  if (address) dns.address = *address;
  dns.state.store(address ? DnsLookup::Found : DnsLookup::Failed,
                  std::memory_order_release);
}

void start_dns(void*) {
  ip_addr_t address{};
  const err_t result = dns_gethostbyname(dns.host, &address, dns_found, nullptr);
  if (result == ERR_OK) dns_found(nullptr, &address, nullptr);
  else if (result != ERR_INPROGRESS) dns_found(nullptr, nullptr, nullptr);
}

const char* resolve(const char* host, char* address, size_t capacity,
                    int64_t deadline) {
  if (dns.state.load(std::memory_order_acquire) == DnsLookup::Pending)
    return "dns_busy";
  std::strcpy(dns.host, host);
  dns.state.store(DnsLookup::Pending, std::memory_order_release);
  if (tcpip_try_callback(start_dns, nullptr) != ERR_OK) {
    dns.state.store(DnsLookup::Idle, std::memory_order_release);
    return "dns_busy";
  }
  while (dns.state.load(std::memory_order_acquire) == DnsLookup::Pending) {
    if (esp_timer_get_time() >= deadline) return "deadline";
    vTaskDelay(1);
  }
  if (esp_timer_get_time() >= deadline) return "deadline";
  const bool found = dns.state.load(std::memory_order_acquire) == DnsLookup::Found;
  if (found) ipaddr_ntoa_r(&dns.address, address, capacity);
  dns.state.store(DnsLookup::Idle, std::memory_order_release);
  return found ? nullptr : "dns_failed";
}

bool would_block(ssize_t result) {
  return result == ESP_TLS_ERR_SSL_WANT_READ || result == ESP_TLS_ERR_SSL_WANT_WRITE;
}

struct TlsConnection {
  esp_tls_t* handle = esp_tls_init();
  ~TlsConnection() { if (handle) esp_tls_conn_destroy(handle); }
};

const char* write_all(esp_tls_t* tls, const char* data, size_t length,
                      int64_t deadline) {
  size_t offset = 0;
  while (offset < length) {
    if (esp_timer_get_time() >= deadline) return "deadline";
    const ssize_t sent = esp_tls_conn_write(tls, data + offset,
                                          std::min(length - offset, size_t{512}));
    if (sent > 0) offset += sent;
    else if (!would_block(sent)) return "write_failed";
    vTaskDelay(1);
  }
  return esp_timer_get_time() >= deadline ? "deadline" : nullptr;
}

struct Response {
  HttpResult* result;
  size_t body_length = 0;
  size_t header_bytes = 0;
  size_t field_length = 0;
  size_t value_length = 0;
  char field[32]{};
  char value[32]{};
  bool in_value = false;
  bool complete = false;
};

void finish_header(Response& response) {
  if (!strcasecmp(response.field, "Retry-After") && response.value_length) {
    char* end = nullptr;
    const unsigned long seconds = std::strtoul(response.value, &end, 10);
    if (response.value[0] >= '0' && response.value[0] <= '9' && end && !*end)
      response.result->retry_after_ms = std::min(seconds, 30UL) * 1000;
  }
}

void append(char* target, size_t capacity, size_t& used, const char* data,
            size_t length) {
  const size_t copied = std::min(length, capacity - 1 - used);
  std::memcpy(target + used, data, copied);
  used += copied;
  target[used] = '\0';
}

int header_field(http_parser* parser, const char* data, size_t length) {
  auto& response = *static_cast<Response*>(parser->data);
  if ((response.header_bytes += length) > kMaxHeaders) {
    response.result->error = "headers_too_large";
    return 1;
  }
  if (response.in_value) {
    finish_header(response);
    response.field_length = response.value_length = 0;
    response.field[0] = response.value[0] = '\0';
    response.in_value = false;
  }
  append(response.field, sizeof(response.field), response.field_length, data, length);
  return 0;
}

int header_value(http_parser* parser, const char* data, size_t length) {
  auto& response = *static_cast<Response*>(parser->data);
  if ((response.header_bytes += length) > kMaxHeaders) {
    response.result->error = "headers_too_large";
    return 1;
  }
  response.in_value = true;
  append(response.value, sizeof(response.value), response.value_length, data, length);
  return 0;
}

int headers_complete(http_parser* parser) {
  auto& response = *static_cast<Response*>(parser->data);
  finish_header(response);
  response.result->status = parser->status_code;
  if (!(parser->flags & F_CHUNKED) && parser->content_length != ULLONG_MAX &&
      parser->content_length > kMaxBody) {
    response.result->error = "response_too_large";
    return -1;
  }
  return 0;
}

int body_data(http_parser* parser, const char* data, size_t length) {
  auto& response = *static_cast<Response*>(parser->data);
  if (response.body_length + length > kMaxBody) {
    response.result->error = "response_too_large";
    return 1;
  }
  std::memcpy(response.result->body + response.body_length, data, length);
  response.body_length += length;
  response.result->body[response.body_length] = '\0';
  return 0;
}

int message_complete(http_parser* parser) {
  auto& response = *static_cast<Response*>(parser->data);
  response.complete = true;
  http_parser_pause(parser, 1);
  return 0;
}
}  // namespace

HttpResult post_https(const char* endpoint, const char* ca_pem, const char* token,
                      const char* payload, size_t length) {
  const int64_t deadline = esp_timer_get_time() + kRequestUs;
  HttpResult result;
  http_parser_url url{};
  if (!endpoint || !ca_pem || !*ca_pem || !token || !*token || !payload ||
      !length || length > 4096 || strnlen(endpoint, 512) == 512 ||
      strnlen(token, 129) == 129 || std::strpbrk(token, "\r\n") ||
      http_parser_parse_url(endpoint, std::strlen(endpoint), 0, &url) ||
      !(url.field_set & (1 << UF_SCHEMA)) || url.field_data[UF_SCHEMA].len != 5 ||
      std::strncmp(endpoint + url.field_data[UF_SCHEMA].off, "https", 5) ||
      !(url.field_set & (1 << UF_HOST)) ||
      (url.field_set & ((1 << UF_USERINFO) | (1 << UF_QUERY) | (1 << UF_FRAGMENT))) ||
      !(url.field_set & (1 << UF_PATH)) || url.field_data[UF_HOST].len >= 254 ||
      url.field_data[UF_PATH].len >= 192) {
    result.error = "invalid_config";
    return result;
  }
  char host[254]{}, path[192]{}, address[IPADDR_STRLEN_MAX]{};
  std::memcpy(host, endpoint + url.field_data[UF_HOST].off, url.field_data[UF_HOST].len);
  std::memcpy(path, endpoint + url.field_data[UF_PATH].off, url.field_data[UF_PATH].len);
  const int port = (url.field_set & (1 << UF_PORT)) ? url.port : 443;
  if (!port) { result.error = "invalid_config"; return result; }
  result.error = resolve(host, address, sizeof(address), deadline);
  if (result.error) return result;

  TlsConnection tls;
  if (!tls.handle) { result.error = "allocation_failed"; return result; }
  esp_tls_cfg_t config{};
  config.cacert_buf = reinterpret_cast<const unsigned char*>(ca_pem);
  config.cacert_bytes = std::strlen(ca_pem) + 1;
  config.common_name = host;  // IDF uses this for both verification and TLS SNI.
  config.non_block = true;
  while (true) {
    const int64_t remaining = deadline - esp_timer_get_time();
    if (remaining <= 0) { result.error = "deadline"; return result; }
    // IDF 4.4.7's async TCP select may wait. Give it only the remaining total
    // budget; a timeout reaches the deadline and the handle is then destroyed.
    config.timeout_ms = static_cast<int>((remaining + 999) / 1000);
    // Numeric address bypasses esp-tls' otherwise synchronous getaddrinfo.
    const int connected = esp_tls_conn_new_async(address, std::strlen(address),
                                                 port, &config, tls.handle);
    if (esp_timer_get_time() >= deadline) { result.error = "deadline"; return result; }
    if (connected == 1) break;
    if (connected < 0) { result.error = "tls_failed"; return result; }
    vTaskDelay(1);
  }

  char authority[272]{}, header[1024]{};
  std::snprintf(authority, sizeof(authority), std::strchr(host, ':') ? "[%s]:%d" : "%s:%d", host, port);
  const int header_length = std::snprintf(header, sizeof(header),
      "POST %s HTTP/1.1\r\nHost: %s\r\nAuthorization: Bearer %s\r\n"
      "Content-Type: application/json\r\nAccept: application/json\r\n"
      "Content-Length: %u\r\nConnection: close\r\n\r\n",
      path, authority, token, static_cast<unsigned>(length));
  if (header_length <= 0 || static_cast<size_t>(header_length) >= sizeof(header)) {
    result.error = "invalid_config";
    return result;
  }
  result.error = write_all(tls.handle, header, header_length, deadline);
  if (!result.error) result.error = write_all(tls.handle, payload, length, deadline);
  if (result.error) return result;

  Response response{&result};
  http_parser parser{};
  http_parser_init(&parser, HTTP_RESPONSE);
  parser.data = &response;
  parser.method = HTTP_POST;
  http_parser_settings settings{};
  settings.on_header_field = header_field;
  settings.on_header_value = header_value;
  settings.on_headers_complete = headers_complete;
  settings.on_body = body_data;
  settings.on_message_complete = message_complete;
  char incoming[256];
  while (!response.complete) {
    if (esp_timer_get_time() >= deadline) { result.error = "deadline"; return result; }
    const ssize_t received = esp_tls_conn_read(tls.handle, incoming, sizeof(incoming));
    if (received >= 0) {
      http_parser_execute(&parser, &settings, incoming, received);
      if (result.error) return result;
      if (HTTP_PARSER_ERRNO(&parser) != HPE_OK && HTTP_PARSER_ERRNO(&parser) != HPE_PAUSED) {
        result.error = "http_invalid";
        return result;
      }
      if (!received && !response.complete) { result.error = "response_incomplete"; return result; }
    } else if (!would_block(received)) {
      result.error = "read_failed";
      return result;
    }
    if (esp_timer_get_time() >= deadline) { result.error = "deadline"; return result; }
    if (!response.complete) vTaskDelay(1);
  }
  return result;
}

}  // namespace mianguang_platform
