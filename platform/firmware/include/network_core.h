#pragma once

#include <cstddef>
#include <cstdint>
#include "monitor_logic.h"

namespace platform_network {

constexpr uint32_t kSnapshotIntervalMs = 10000;
constexpr uint32_t kMaxRetryMs = 30000;
constexpr uint64_t kMaxUptimeMs = 9007199254740991ULL;
constexpr std::size_t kCommandCapacity = 8192;
constexpr std::size_t kEndpointCapacity = 193;

struct Snapshot {
  sleep_core::SensorSnapshot sample;
  sleep_core::DataQuality quality;
  uint32_t clock_ms = 0;
  uint32_t boot_id = 0;
  uint32_t seq = 0;
  uint64_t uptime_ms = 0;
  uint64_t utc_ms = 0;
  uint64_t monotonic_ms = 0;
  bool radar_enabled = false;
  bool ready = false;
  sleep_core::LightMode lamp_mode = sleep_core::LightMode::Auto;
  uint8_t pwm = 0;
  uint8_t target = 0;
};

std::size_t serializeSnapshot(const Snapshot& snapshot, const char* device_id,
                              const char* binding_id, char* body, std::size_t capacity);

bool validUuid(const char* value);
bool validToken(const char* value);
bool validEndpoint(const char* value);
bool validNtpServer(const char* value);

// Exhaustion never wraps a sequence back to zero in the same boot.
bool nextSequence(uint32_t& next, bool& exhausted, uint32_t& result);
uint32_t retryDelayMs(uint32_t failures, uint32_t entropy,
                      uint32_t retry_after_ms = 0);

}  // namespace platform_network
