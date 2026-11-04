#pragma once

#include <cstddef>
#include <cstdint>

namespace mianguang_platform {

struct HttpResult {
  int status = 0;
  uint32_t retry_after_ms = 0;
  char body[513]{};
  const char* error = nullptr;
};

// Call only from the single network task. No redirect, no insecure TLS, no retry.
HttpResult post_https(const char* endpoint, const char* ca_pem, const char* token,
                      const char* payload, size_t length);

}  // namespace mianguang_platform
