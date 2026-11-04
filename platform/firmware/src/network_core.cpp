#include "network_core.h"

#include <cstring>
#include <cstdio>
#include <ctime>
#include <limits>

namespace platform_network {
namespace {
bool hex(char c) {
  return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') ||
         (c >= 'A' && c <= 'F');
}
bool hostChar(char c) {
  return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'z') ||
         (c >= 'A' && c <= 'Z') || c == '-' || c == '.';
}
const char* boolean(bool value) { return value ? "true" : "false"; }

const char* qualityReason(sleep_core::QualityError error) {
  using sleep_core::QualityError;
  switch (error) {
    case QualityError::None: return "ok";
    case QualityError::Missing: return "missing";
    case QualityError::Stale: return "stale";
    case QualityError::TransportFault: return "transport_fault";
    case QualityError::InstallationUnconfirmed: return "installation_unconfirmed";
    case QualityError::InvalidValue: return "invalid_value";
    case QualityError::OutOfRange: return "out_of_range";
    case QualityError::OccupancyUnknown: return "occupancy_unknown";
    case QualityError::NotPresent: return "not_present";
    case QualityError::NotInBed: return "not_in_bed";
    case QualityError::MotionUnknown: return "motion_unknown";
    case QualityError::Motion: return "motion";
    case QualityError::ConflictingOccupancy: return "conflicting_occupancy";
  }
  return "unknown";
}

template <typename T>
uint32_t age(const sleep_core::TimedField<T>& field, uint32_t now) {
  return field.available ? static_cast<uint32_t>(now - field.updated_ms) : 0;
}

}  // namespace

bool validUuid(const char* value) {
  if (!value || std::strlen(value) != 36) return false;
  for (std::size_t i = 0; i < 36; ++i) {
    if (i == 8 || i == 13 || i == 18 || i == 23) {
      if (value[i] != '-') return false;
    } else if (!hex(value[i])) {
      return false;
    }
  }
  return true;
}

bool validToken(const char* value) {
  // Server provisioner uses secrets.token_urlsafe(32), without '=' padding.
  if (!value || std::strlen(value) != 43) return false;
  for (const char* p = value; *p; ++p) {
    if (!((*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z') ||
          (*p >= '0' && *p <= '9') || *p == '-' || *p == '_')) return false;
  }
  return true;
}

bool validEndpoint(const char* value) {
  constexpr char path[] = "/api/device/v1/telemetry";
  if (!value || std::strlen(value) >= kEndpointCapacity ||
      std::strncmp(value, "https://", 8) != 0) return false;
  const char* host = value + 8;
  const char* end = std::strchr(host, '/');
  if (!end || end == host || std::strcmp(end, path) != 0) return false;
  const char* port = nullptr;
  for (const char* p = host; p < end; ++p) {
    if (*p == ':') {
      if (port || p == host) return false;
      port = p;
    } else if (port) {
      if (*p < '0' || *p > '9') return false;
    } else if (!hostChar(*p)) {
      return false;
    }
  }
  if (port) {
    if (port + 1 == end || end - port > 6) return false;
    unsigned number = 0;
    for (const char* p = port + 1; p < end; ++p) number = number * 10 + (*p - '0');
    if (number == 0 || number > 65535) return false;
  }
  const char* host_end = port ? port : end;
  return host[0] != '.' && host[0] != '-' && host_end[-1] != '.' &&
         host_end[-1] != '-';
}

bool validNtpServer(const char* value) {
  if (!value || !*value || std::strlen(value) > 128) return false;
  for (const char* p = value; *p; ++p) if (!hostChar(*p)) return false;
  return true;
}

bool nextSequence(uint32_t& next, bool& exhausted, uint32_t& result) {
  if (exhausted) return false;
  result = next;
  if (next == std::numeric_limits<uint32_t>::max()) exhausted = true;
  else ++next;
  return true;
}

uint32_t retryDelayMs(uint32_t failures, uint32_t entropy,
                      uint32_t retry_after_ms) {
  const uint32_t shift = failures == 0 ? 0 : (failures > 6 ? 5 : failures - 1);
  uint32_t base = 1000U << shift;
  if (base > kMaxRetryMs) base = kMaxRetryMs;
  uint32_t delay = base + entropy % (base / 4 + 1);
  if (delay < retry_after_ms) delay = retry_after_ms;
  return delay > kMaxRetryMs ? kMaxRetryMs : delay;
}

std::size_t serializeSnapshot(const Snapshot& snapshot, const char* device_id,
                              const char* binding_id, char* body, std::size_t capacity) {
  const auto& s = snapshot.sample;
  const auto& q = snapshot.quality;
  const time_t seconds = snapshot.utc_ms / 1000;
  struct tm utc;
  gmtime_r(&seconds, &utc);
  char date[32];
  std::strftime(date, sizeof(date), "%Y-%m-%dT%H:%M:%S", &utc);
  char binding[40] = "null";
  if (binding_id[0])
    std::snprintf(binding, sizeof(binding), "\"%s\"", binding_id);
  const int length = std::snprintf(body, capacity,
      "{\"schema_version\":1,\"device_id\":\"%s\",\"binding_id\":%s,"
      "\"boot_id\":%lu,\"seq\":%lu,\"captured_at\":\"%s.%03uZ\","
      "\"uptime_ms\":%llu,\"firmware_version\":\"" MIANGUANG_VERSION "\","
      "\"sample\":{\"radar_enabled\":%s,\"ready\":%s,\"installation_confirmed\":%s,"
      "\"transport_ok\":%s,"
      "\"presence\":{\"raw\":%u,\"available\":%s,\"valid\":%s,\"reason\":\"%s\",\"age_ms\":%lu},"
      "\"bed\":{\"raw\":%u,\"available\":%s,\"valid\":%s,\"reason\":\"%s\",\"age_ms\":%lu},"
      "\"rr\":{\"raw\":%u,\"available\":%s,\"valid\":%s,\"reason\":\"%s\",\"age_ms\":%lu},"
      "\"hr\":{\"raw\":%u,\"available\":%s,\"valid\":%s,\"reason\":\"%s\",\"age_ms\":%lu},"
      "\"low_motion\":{\"raw\":%u,\"available\":%s,\"valid\":%s},"
      "\"lamp\":{\"mode\":\"%s\",\"pwm\":%u,\"target\":%u}}}",
      device_id, binding, static_cast<unsigned long>(snapshot.boot_id),
      static_cast<unsigned long>(snapshot.seq), date, static_cast<unsigned>(snapshot.utc_ms % 1000),
      static_cast<unsigned long long>(snapshot.uptime_ms), boolean(snapshot.radar_enabled),
      boolean(snapshot.ready), boolean(s.installation_confirmed), boolean(s.transport_ok),
      static_cast<unsigned>(s.presence.value), boolean(s.presence.available), boolean(q.presence.valid),
      qualityReason(q.presence.error), static_cast<unsigned long>(age(s.presence, snapshot.clock_ms)),
      static_cast<unsigned>(s.in_bed.value), boolean(s.in_bed.available), boolean(q.in_bed.valid),
      qualityReason(q.in_bed.error), static_cast<unsigned long>(age(s.in_bed, snapshot.clock_ms)),
      s.respiration_bpm.value, boolean(s.respiration_bpm.available), boolean(q.respiration_bpm.valid),
      qualityReason(q.respiration_bpm.error), static_cast<unsigned long>(age(s.respiration_bpm, snapshot.clock_ms)),
      s.heart_bpm.value, boolean(s.heart_bpm.available), boolean(q.heart_bpm.valid),
      qualityReason(q.heart_bpm.error), static_cast<unsigned long>(age(s.heart_bpm, snapshot.clock_ms)),
      static_cast<unsigned>(s.low_motion.value), boolean(s.low_motion.available), boolean(q.low_motion.valid),
      snapshot.lamp_mode == sleep_core::LightMode::Auto ? "auto" : "manual", snapshot.pwm, snapshot.target);
  return length > 0 && static_cast<std::size_t>(length) < capacity
             ? static_cast<std::size_t>(length) : 0;
}

}  // namespace platform_network
