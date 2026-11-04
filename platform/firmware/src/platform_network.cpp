#include "platform_network.h"
#include "network_core.h"
#include "platform_http.h"

#include <Arduino.h>
#include <WiFi.h>
#include <cJSON.h>
#include <esp_sntp.h>
#include <esp_system.h>
#include <esp_timer.h>
#include <mbedtls/x509_crt.h>
#include <nvs.h>
#include <sys/time.h>
#include <cstddef>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <limits>

namespace platform_network {
namespace {

constexpr uint32_t kConfigVersion = 0x4d470001;
constexpr uint32_t kBootVersion = 0x4d474201;
constexpr uint64_t kMinimumUtcMs = 1704067200000ULL;  // 2024-01-01
constexpr uint64_t kMaximumUtcMs = 4102444800000ULL;  // 2100-01-01

struct Configuration {
  uint32_t version;
  char device_id[37];
  char binding_id[37];
  char endpoint[kEndpointCapacity];
  char token[44];
  char wifi_ssid[33];
  char wifi_password[65];
  char ntp_server[129];
  char ca_pem[4097];
  uint32_t checksum;
};

struct BootRecord {
  uint32_t version;
  char device_id[37];
  uint32_t counter;
  uint32_t checksum;
};

struct State {
  bool task_running = false;
  bool configured = false;
  bool upload_enabled = false;
  bool utc_trusted = false;
  bool wifi_connected = false;
  bool resync_requested = false;
  bool has_sequence = false;
  uint32_t boot_id = 0;
  uint32_t last_seq = 0;
  uint32_t failures = 0;
  uint32_t wifi_connections = 0;
  int last_http = 0;
  const char* reason = "starting";
};

portMUX_TYPE mutex = portMUX_INITIALIZER_UNLOCKED;
State state;
Snapshot latest;
bool latest_ready = false;
bool command_busy = false;
bool command_ready = false;
char pending_command[kCommandCapacity]{};
char diagnostic[512]{};
bool diagnostic_ready = false;
Configuration configuration{};
Configuration candidate{};
BootRecord boot_record{};
// Reused for the NVS read-back, never allocated per upload.
uint8_t readback[sizeof(Configuration)]{};
nvs_handle_t storage = 0;
bool storage_open = false;
TaskHandle_t network_task = nullptr;
bool configuration_valid = false;
bool boot_valid = false;
uint64_t restart_at = 0;
uint32_t capture_marker = 0;
uint32_t capture_interval = kSnapshotIntervalMs;
uint32_t sequence = 0;
bool sequence_exhausted = false;
uint64_t last_capture_utc = 0;
uint64_t last_capture_uptime = 0;

uint64_t monotonicMs() {
  return static_cast<uint64_t>(esp_timer_get_time()) / 1000;
}

const char* boolean(bool value) { return value ? "true" : "false"; }

void queueDiagnostic(const char* text, bool reply = false) {
  const std::size_t length = std::strlen(text);
  if (length >= sizeof(diagnostic)) return;
  portENTER_CRITICAL(&mutex);
  if (!diagnostic_ready || reply) {
    std::memcpy(diagnostic, text, length + 1);
    diagnostic_ready = true;
  }
  portEXIT_CRITICAL(&mutex);
}

void report(const char* status, const char* reason, bool reply = false) {
  char output[256];
  std::snprintf(output, sizeof(output),
                "{\"type\":\"network\",\"status\":\"%s\",\"reason\":\"%s\"}\n",
                status, reason);
  queueDiagnostic(output, reply);
}

void statusReply() {
  portENTER_CRITICAL(&mutex);
  const State copy = state;
  portEXIT_CRITICAL(&mutex);
  // ESP-IDF 4.4's uxTaskGetStackHighWaterMark reports bytes, not words.
  const unsigned long stack_free = network_task ? uxTaskGetStackHighWaterMark(network_task) : 0;
  char output[512];
  std::snprintf(output, sizeof(output),
      "{\"type\":\"network\",\"status\":\"status\",\"configured\":%s,"
      "\"upload_enabled\":%s,\"wifi_connected\":%s,\"utc_trusted\":%s,"
      "\"boot_id\":%lu,\"has_sequence\":%s,\"last_seq\":%lu,"
      "\"last_http\":%d,\"failures\":%lu,\"reason\":\"%s\","
      "\"heap_free_bytes\":%lu,\"heap_min_free_bytes\":%lu,"
      "\"network_stack_min_free_bytes\":%lu,\"wifi_connections\":%lu}\n",
      boolean(copy.configured), boolean(copy.upload_enabled),
      boolean(copy.wifi_connected), boolean(copy.utc_trusted),
      static_cast<unsigned long>(copy.boot_id), boolean(copy.has_sequence),
      static_cast<unsigned long>(copy.last_seq), copy.last_http,
      static_cast<unsigned long>(copy.failures), copy.reason,
      static_cast<unsigned long>(ESP.getFreeHeap()),
      static_cast<unsigned long>(ESP.getMinFreeHeap()), stack_free,
      static_cast<unsigned long>(copy.wifi_connections));
  queueDiagnostic(output, true);
}

void halt(const char* reason) {
  portENTER_CRITICAL(&mutex);
  state.upload_enabled = false;
  state.reason = reason;
  latest_ready = false;
  portEXIT_CRITICAL(&mutex);
  report("stopped", reason);
}

uint32_t checksum(const void* bytes, std::size_t length) {
  uint32_t crc = 0xffffffffU;
  const auto* data = static_cast<const uint8_t*>(bytes);
  for (std::size_t i = 0; i < length; ++i) {
    crc ^= data[i];
    for (unsigned bit = 0; bit < 8; ++bit)
      crc = (crc >> 1) ^ (0xedb88320U & (0U - (crc & 1U)));
  }
  return ~crc;
}

template <typename Record>
bool readRecord(const char* key, Record& record) {
  std::size_t length = sizeof(record);
  return nvs_get_blob(storage, key, &record, &length) == ESP_OK &&
         length == sizeof(record) &&
         record.checksum == checksum(&record, offsetof(Record, checksum));
}

template <typename Record>
bool commitRecord(const char* key, Record& record) {
  record.checksum = checksum(&record, offsetof(Record, checksum));
  if (nvs_set_blob(storage, key, &record, sizeof(record)) != ESP_OK ||
      nvs_commit(storage) != ESP_OK) return false;
  std::size_t length = sizeof(record);
  const bool ok = nvs_get_blob(storage, key, readback, &length) == ESP_OK &&
                  length == sizeof(record) &&
                  std::memcmp(readback, &record, sizeof(record)) == 0;
  std::memset(readback, 0, sizeof(readback));
  return ok;
}

bool storedConfigurationValid() {
  // The CRC also covers terminators; reject malformed records before string use.
  return configuration.version == kConfigVersion &&
      configuration.device_id[36] == 0 && configuration.binding_id[36] == 0 &&
      configuration.endpoint[sizeof(configuration.endpoint) - 1] == 0 &&
      configuration.token[43] == 0 && configuration.wifi_ssid[32] == 0 &&
      configuration.wifi_password[64] == 0 && configuration.ntp_server[128] == 0 &&
      configuration.ca_pem[4096] == 0 && validUuid(configuration.device_id) &&
      (!configuration.binding_id[0] || validUuid(configuration.binding_id)) &&
      validEndpoint(configuration.endpoint) && validToken(configuration.token) &&
      configuration.wifi_ssid[0] && validNtpServer(configuration.ntp_server) &&
      configuration.ca_pem[0];
}

void loadIdentity() {
  if (nvs_open("mg_network", NVS_READWRITE, &storage) != ESP_OK) {
    halt("storage_unavailable");
    return;
  }
  storage_open = true;
  configuration_valid = readRecord("config", configuration) && storedConfigurationValid();
  boot_valid = readRecord("boot", boot_record) && boot_record.version == kBootVersion &&
               boot_record.device_id[36] == 0 && validUuid(boot_record.device_id);
  portENTER_CRITICAL(&mutex);
  state.configured = configuration_valid;
  portEXIT_CRITICAL(&mutex);
  if (!configuration_valid) {
    halt("unconfigured_or_corrupt");
    return;
  }
  if (!boot_valid || std::strcmp(configuration.device_id, boot_record.device_id) != 0) {
    halt("boot_missing_or_corrupt");
    return;
  }
  if (boot_record.counter == std::numeric_limits<uint32_t>::max()) {
    halt("boot_exhausted");
    return;
  }
  ++boot_record.counter;
  if (!commitRecord("boot", boot_record)) {
    boot_valid = false;
    halt("boot_commit_failed");
    return;
  }
  portENTER_CRITICAL(&mutex);
  state.boot_id = boot_record.counter;
  state.upload_enabled = true;
  state.reason = "waiting_for_wifi";
  portEXIT_CRITICAL(&mutex);
}

template <std::size_t N>
bool copyString(const cJSON* object, const char* key, char (&output)[N], bool allow_empty = false) {
  const cJSON* item = cJSON_GetObjectItemCaseSensitive(object, key);
  if (!cJSON_IsString(item) || !item->valuestring) return false;
  const std::size_t length = std::strlen(item->valuestring);
  if ((!allow_empty && !length) || length >= N) return false;
  std::memcpy(output, item->valuestring, length + 1);
  return true;
}

void lowerUuid(char* value) {
  for (; *value; ++value) if (*value >= 'A' && *value <= 'F') *value += 'a' - 'A';
}

const char* parseConfiguration(bool& new_identity) {
  std::memset(&candidate, 0, sizeof(candidate));
  cJSON* object = cJSON_ParseWithOpts(pending_command, nullptr, true);
  if (!cJSON_IsObject(object)) {
    cJSON_Delete(object);
    return "invalid_json";
  }
  constexpr const char* keys[] = {"device_id", "binding_id", "endpoint", "token",
      "wifi_ssid", "wifi_password", "ntp_server", "ca_pem", "new_identity"};
  unsigned seen = 0;
  bool shape_ok = true;
  const cJSON* item;
  cJSON_ArrayForEach(item, object) {
    unsigned index = 0;
    while (index < 9 && std::strcmp(item->string, keys[index]) != 0) ++index;
    if (index == 9 || (seen & (1U << index))) { shape_ok = false; break; }
    seen |= 1U << index;
  }
  const cJSON* identity = cJSON_GetObjectItemCaseSensitive(object, "new_identity");
  const cJSON* binding = cJSON_GetObjectItemCaseSensitive(object, "binding_id");
  const bool fields_ok = shape_ok && seen == 0x1ff && cJSON_IsBool(identity) &&
      copyString(object, "device_id", candidate.device_id) &&
      (cJSON_IsNull(binding) || copyString(object, "binding_id", candidate.binding_id)) &&
      copyString(object, "endpoint", candidate.endpoint) &&
      copyString(object, "token", candidate.token) &&
      copyString(object, "wifi_ssid", candidate.wifi_ssid) &&
      copyString(object, "wifi_password", candidate.wifi_password, true) &&
      copyString(object, "ntp_server", candidate.ntp_server) &&
      copyString(object, "ca_pem", candidate.ca_pem);
  new_identity = cJSON_IsTrue(identity);
  cJSON_Delete(object);
  if (!fields_ok || !validUuid(candidate.device_id) ||
      (candidate.binding_id[0] && !validUuid(candidate.binding_id)) ||
      !validEndpoint(candidate.endpoint) || !validToken(candidate.token) ||
      !validNtpServer(candidate.ntp_server)) return "invalid_configuration";
  lowerUuid(candidate.device_id);
  lowerUuid(candidate.binding_id);
  mbedtls_x509_crt certificate;
  mbedtls_x509_crt_init(&certificate);
  const int parsed = mbedtls_x509_crt_parse(&certificate,
      reinterpret_cast<const unsigned char*>(candidate.ca_pem),
      std::strlen(candidate.ca_pem) + 1);
  mbedtls_x509_crt_free(&certificate);
  if (parsed != 0) return "invalid_ca_certificate";
  candidate.version = kConfigVersion;
  return nullptr;
}

void configure() {
  bool new_identity = false;
  const char* error = parseConfiguration(new_identity);
  if (!error && !storage_open) error = "storage_unavailable";
  if (!error) {
    // Retain even an intact UUID from a corrupt record as a reset prohibition.
    const bool same_config = std::memcmp(candidate.device_id, configuration.device_id, 37) == 0;
    const bool same_boot = std::memcmp(candidate.device_id, boot_record.device_id, 37) == 0;
    if (same_config || same_boot) {
      if (!boot_valid || !same_boot) error = "boot_missing_or_corrupt";
      else if (boot_record.counter == std::numeric_limits<uint32_t>::max()) error = "boot_exhausted";
      else if (new_identity && (same_config || boot_record.counter != 0)) error = "identity_already_exists";
    } else if (!new_identity) {
      error = "new_identity_required";
    }
    if (!error) {
      halt("configuration_changed");
      if (!same_boot) {
        boot_record = {};
        boot_record.version = kBootVersion;
        std::memcpy(boot_record.device_id, candidate.device_id, sizeof(boot_record.device_id));
        boot_valid = commitRecord("boot", boot_record);
        if (!boot_valid) error = "boot_commit_failed";
      }
      if (!error && !commitRecord("config", candidate)) error = "configuration_commit_failed";
      if (!error) {
        queueDiagnostic("{\"type\":\"network\",\"status\":\"configured\",\"restarting\":true}\n", true);
        restart_at = monotonicMs() + 1000;
      }
    }
  }
  if (error) report("config_error", error, true);
  std::memset(&candidate, 0, sizeof(candidate));
  std::memset(pending_command, 0, sizeof(pending_command));
  portENTER_CRITICAL(&mutex);
  command_ready = false;
  command_busy = false;
  portEXIT_CRITICAL(&mutex);
}

void timeSynchronized(struct timeval* now) {
  const uint64_t utc = static_cast<uint64_t>(now->tv_sec) * 1000 + now->tv_usec / 1000;
  portENTER_CRITICAL(&mutex);
  state.utc_trusted = utc >= kMinimumUtcMs && utc < kMaximumUtcMs;
  portEXIT_CRITICAL(&mutex);
}

void distrustClock() {
  portENTER_CRITICAL(&mutex);
  state.utc_trusted = false;
  state.resync_requested = true;
  state.reason = "clock_untrusted";
  latest_ready = false;
  portEXIT_CRITICAL(&mutex);
}

bool acknowledged(const cJSON* response, const Snapshot& snapshot) {
  const cJSON* status = cJSON_GetObjectItemCaseSensitive(response, "status");
  const cJSON* boot = cJSON_GetObjectItemCaseSensitive(response, "boot_id");
  const cJSON* seq = cJSON_GetObjectItemCaseSensitive(response, "seq");
  return cJSON_IsString(status) &&
      (std::strcmp(status->valuestring, "accepted") == 0 || std::strcmp(status->valuestring, "duplicate") == 0) &&
      cJSON_IsNumber(boot) && boot->valuedouble == snapshot.boot_id &&
      cJSON_IsNumber(seq) && seq->valuedouble == snapshot.seq;
}

bool errorCode(const cJSON* response, const char* code) {
  const cJSON* error = cJSON_GetObjectItemCaseSensitive(response, "error");
  const cJSON* value = cJSON_GetObjectItemCaseSensitive(error, "code");
  return cJSON_IsString(value) && std::strcmp(value->valuestring, code) == 0;
}

void networkTask(void*) {
  loadIdentity();
  WiFi.persistent(false);
  WiFi.setAutoReconnect(false);
  sntp_set_time_sync_notification_cb(timeSynchronized);
  Snapshot in_flight;
  bool have_in_flight = false;
  static char payload[4096];
  std::size_t payload_length = 0;
  uint32_t retry_failures = 0;
  uint64_t retry_at = 0;
  uint64_t wifi_attempt_at = 0;
  uint64_t last_sntp_start = 0;
  bool sntp_started = false;
  for (;;) {
    vTaskDelay(pdMS_TO_TICKS(20));
    const uint64_t now = monotonicMs();
    if (restart_at) {
      if (now >= restart_at) ESP.restart();
      continue;
    }
    portENTER_CRITICAL(&mutex);
    const bool configure_pending = command_ready;
    const bool enabled = state.upload_enabled;
    portEXIT_CRITICAL(&mutex);
    if (configure_pending) { configure(); have_in_flight = false; continue; }
    if (!enabled) { have_in_flight = false; continue; }
    const bool connected = WiFi.status() == WL_CONNECTED;
    portENTER_CRITICAL(&mutex);
    if (connected && !state.wifi_connected &&
        state.wifi_connections != std::numeric_limits<uint32_t>::max()) ++state.wifi_connections;
    state.wifi_connected = connected;
    portEXIT_CRITICAL(&mutex);
    if (!connected) {
      if (now >= wifi_attempt_at) {
        WiFi.mode(WIFI_STA);
        WiFi.begin(configuration.wifi_ssid, configuration.wifi_password);
        wifi_attempt_at = now + kMaxRetryMs;
      }
      continue;
    }
    portENTER_CRITICAL(&mutex);
    const bool resync = state.resync_requested;
    const bool trusted = state.utc_trusted;
    portEXIT_CRITICAL(&mutex);
    if (!sntp_started || (resync && now - last_sntp_start >= kMaxRetryMs)) {
      portENTER_CRITICAL(&mutex);
      state.resync_requested = false;
      state.reason = "waiting_for_time";
      portEXIT_CRITICAL(&mutex);
      configTime(0, 0, configuration.ntp_server);
      sntp_started = true;
      last_sntp_start = now;
    }
    if (!trusted) { have_in_flight = false; continue; }
    if (now < retry_at) continue;
    portENTER_CRITICAL(&mutex);
    if (latest_ready) {
      in_flight = latest;
      latest_ready = false;
      have_in_flight = true;
      payload_length = 0;
    }
    portEXIT_CRITICAL(&mutex);
    if (!have_in_flight) continue;
    // Leave room for the five-second HTTP budget within the 20-second window.
    if (now - in_flight.monotonic_ms > 15000) { have_in_flight = false; continue; }
    if (!payload_length) payload_length = serializeSnapshot(in_flight, configuration.device_id,
        configuration.binding_id, payload, sizeof(payload));
    if (!payload_length) { halt("serialization_failed"); continue; }
    const auto result = mianguang_platform::post_https(configuration.endpoint,
        configuration.ca_pem, configuration.token, payload, payload_length);
    cJSON* response = cJSON_Parse(result.body);
    const bool success = !result.error && result.status == 200 && acknowledged(response, in_flight);
    const bool stopped = result.status == 401 || result.status == 403 ||
        (result.status == 409 && errorCode(response, "binding_mismatch"));
    const bool clock_error = result.status == 422 && errorCode(response, "clock_out_of_window");
    cJSON_Delete(response);
    portENTER_CRITICAL(&mutex);
    state.last_http = result.status;
    if (!success && state.failures != std::numeric_limits<uint32_t>::max()) ++state.failures;
    state.reason = success ? "reported" : "upload_failed";
    portEXIT_CRITICAL(&mutex);
    if (success) {
      have_in_flight = false;
      retry_failures = 0;
      retry_at = 0;
      report("reported", "accepted_or_duplicate");
    } else if (stopped) {
      halt("reconfigure_required");
      have_in_flight = false;
    } else if (clock_error) {
      distrustClock();
      have_in_flight = false;
      report("waiting", "clock_untrusted");
    } else if (result.error || result.status == 0 || result.status == 429 || result.status >= 500 || result.status == 200) {
      if (retry_failures < 6) ++retry_failures;
      retry_at = monotonicMs() + retryDelayMs(retry_failures, esp_random(), result.retry_after_ms);
      report("retrying", "transport_or_server_error");
    } else {
      have_in_flight = false;
      report("dropped", "http_rejected");
    }
  }
}

}  // namespace

void begin() {
  capture_marker = millis();
  capture_interval = kSnapshotIntervalMs + esp_random() % 2001;
  const bool created = xTaskCreate(networkTask, "mianguang_net", 12288, nullptr, 1, &network_task) == pdPASS;
  portENTER_CRITICAL(&mutex);
  state.task_running = created;
  portEXIT_CRITICAL(&mutex);
  if (!created) halt("task_creation_failed");
}

bool command(const char* line, bool radar_enabled) {
  if (std::strncmp(line, "net ", 4) != 0 && std::strcmp(line, "net") != 0) return false;
  if (std::strcmp(line, "net status") == 0) { statusReply(); return true; }
  constexpr char prefix[] = "net configure ";
  if (std::strncmp(line, prefix, sizeof(prefix) - 1) != 0) {
    report("config_error", "unknown_network_command", true);
    return true;
  }
  if (radar_enabled) { report("config_error", "radar_must_be_disabled", true); return true; }
  const char* json = line + sizeof(prefix) - 1;
  const std::size_t length = std::strlen(json);
  if (length >= sizeof(pending_command)) { report("config_error", "command_too_long", true); return true; }
  portENTER_CRITICAL(&mutex);
  const bool unavailable = command_busy || !state.task_running;
  if (!unavailable) command_busy = true;
  portEXIT_CRITICAL(&mutex);
  if (unavailable) { report("config_error", "busy_or_unavailable", true); return true; }
  std::memcpy(pending_command, json, length + 1);
  queueDiagnostic("{\"type\":\"network\",\"status\":\"configuring\"}\n", true);
  portENTER_CRITICAL(&mutex);
  command_ready = true;
  portEXIT_CRITICAL(&mutex);
  return true;
}

void capture(uint32_t now, uint64_t uptime, const sleep_core::SensorSnapshot& sample,
             const sleep_core::DataQuality& quality, bool uart_enabled, bool ready,
             sleep_core::LightMode lamp_mode, uint8_t pwm, uint8_t target) {
  if (static_cast<uint32_t>(now - capture_marker) < capture_interval) return;
  capture_marker = now;
  capture_interval = kSnapshotIntervalMs;
  portENTER_CRITICAL(&mutex);
  const bool allowed = state.upload_enabled && state.utc_trusted;
  const uint32_t boot_id = state.boot_id;
  const bool has_sequence = state.has_sequence;
  portEXIT_CRITICAL(&mutex);
  if (!allowed) return;
  if (uptime > kMaxUptimeMs || (has_sequence && uptime <= last_capture_uptime)) {
    halt("uptime_exhausted_or_regressed");
    return;
  }
  struct timeval time;
  gettimeofday(&time, nullptr);
  const uint64_t utc_ms = static_cast<uint64_t>(time.tv_sec) * 1000 + time.tv_usec / 1000;
  if (utc_ms < kMinimumUtcMs || utc_ms >= kMaximumUtcMs || utc_ms <= last_capture_utc) {
    distrustClock();
    report("waiting", "clock_untrusted");
    return;
  }
  Snapshot snapshot;
  snapshot.sample = sample;
  snapshot.quality = quality;
  snapshot.clock_ms = now;
  snapshot.boot_id = boot_id;
  snapshot.uptime_ms = uptime;
  snapshot.utc_ms = utc_ms;
  snapshot.monotonic_ms = monotonicMs();
  snapshot.radar_enabled = uart_enabled;
  snapshot.ready = ready;
  snapshot.lamp_mode = lamp_mode;
  snapshot.pwm = pwm;
  snapshot.target = target;
  if (!nextSequence(sequence, sequence_exhausted, snapshot.seq)) {
    halt("sequence_exhausted");
    return;
  }
  last_capture_utc = utc_ms;
  last_capture_uptime = uptime;
  portENTER_CRITICAL(&mutex);
  if (state.upload_enabled && state.utc_trusted) {
    latest = snapshot;
    latest_ready = true;
    state.has_sequence = true;
    state.last_seq = snapshot.seq;
  }
  portEXIT_CRITICAL(&mutex);
}

bool takeDiagnostic(char* buffer, std::size_t capacity) {
  portENTER_CRITICAL(&mutex);
  const bool available = diagnostic_ready && capacity > std::strlen(diagnostic);
  if (available) {
    std::memcpy(buffer, diagnostic, std::strlen(diagnostic) + 1);
    diagnostic_ready = false;
  }
  portEXIT_CRITICAL(&mutex);
  return available;
}

}  // namespace platform_network
