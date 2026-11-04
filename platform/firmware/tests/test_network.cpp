#include "network_core.h"

#include <cassert>
#include <cstdio>
#include <cstring>
#include <limits>

namespace {
constexpr char kDevice[] = "4b9635de-4522-4fd1-8a6b-5eb3e4adba53";
constexpr char kBinding[] = "5adf1692-09c4-4b8c-8e71-d06cd72a9a54";

void emit(platform_network::Snapshot snapshot, const char* binding) {
  snapshot.quality = sleep_core::evaluate(snapshot.sample, snapshot.clock_ms);
  char first[4096]{}, retry[4096]{};
  const auto size = platform_network::serializeSnapshot(
      snapshot, kDevice, binding, first, sizeof(first));
  assert(size > 0 && size < sizeof(first));
  assert(platform_network::serializeSnapshot(
      snapshot, kDevice, binding, retry, sizeof(retry)) == size);
  assert(std::memcmp(first, retry, size + 1) == 0);
  std::puts(first);
}
}  // namespace

int main() {
  using namespace platform_network;
  constexpr uint32_t maximum = std::numeric_limits<uint32_t>::max();
  Snapshot normal;
  normal.clock_ms = 20000;
  normal.boot_id = 1;
  normal.uptime_ms = 20000;
  normal.utc_ms = 1704067200123ULL;
  normal.radar_enabled = normal.ready = true;
  normal.sample.installation_confirmed = normal.sample.transport_ok = true;
  normal.sample.presence = {true, 19900, true};
  normal.sample.in_bed = {true, 19800, true};
  normal.sample.low_motion = {true, 19700, true};
  normal.sample.respiration_bpm = {16, 19920, true};
  normal.sample.heart_bpm = {70, 19980, true};
  emit(normal, kBinding);

  Snapshot disabled;
  disabled.clock_ms = 20000;
  disabled.boot_id = 1;
  disabled.seq = 1;
  disabled.uptime_ms = 20000;
  disabled.utc_ms = normal.utc_ms;
  emit(disabled, "");

  Snapshot limits = normal;
  limits.boot_id = limits.seq = maximum;
  limits.uptime_ms = kMaxUptimeMs;
  limits.lamp_mode = sleep_core::LightMode::Manual;
  limits.pwm = limits.target = 255;
  emit(limits, kBinding);

  uint32_t next = maximum - 1, value = 0;
  bool exhausted = false;
  assert(nextSequence(next, exhausted, value) && value == maximum - 1 && !exhausted);
  assert(nextSequence(next, exhausted, value) && value == maximum && exhausted);
  value = 17;
  assert(!nextSequence(next, exhausted, value) && next == maximum && value == 17);
  for (uint32_t failures = 0; failures <= 10; ++failures) {
    for (uint32_t entropy : {0U, maximum}) {
      const auto delay = retryDelayMs(failures, entropy);
      assert(delay >= 1000 && delay <= 30000);
      assert(retryDelayMs(failures, entropy, maximum) == 30000);
    }
  }
}
