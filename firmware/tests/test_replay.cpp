#include "monitor_logic.h"

#include <cassert>
#include <cstdint>
#include <iostream>
#include <limits>

using namespace sleep_core;

namespace {

constexpr uint64_t kSecond = 1000;
constexpr uint64_t kMinute = 60 * kSecond;
constexpr uint64_t kDay = 24 * 60 * kMinute;

SensorSnapshot observation(uint64_t logical_ms, bool in_bed = true) {
  const auto timestamp = static_cast<uint32_t>(logical_ms);
  SensorSnapshot result;
  result.installation_confirmed = true;
  result.transport_ok = true;
  result.presence = {true, timestamp, true};
  result.in_bed = {in_bed, timestamp, true};
  result.low_motion = {true, timestamp, true};
  result.respiration_bpm = {16, timestamp, true};
  result.heart_bpm = {72, timestamp, true};
  result.module_sleep_stage = {2, timestamp, true};
  return result;
}

// A deterministic adapter replay: real logical time is uint64_t; the production
// interfaces receive its wrapping uint32_t clock, just like an MCU millis().
// These fixtures exercise quality -> trends -> light, not UART/hardware timing.
struct Replay {
  SensorSnapshot input;
  DataQuality quality;
  TrendWindow trends;
  NightLight light;
  uint64_t previous_logical_ms = 0;
  uint32_t now = 0;

  void tick(uint64_t logical_ms, bool dark_known = true, bool dark = true) {
    assert(logical_ms >= previous_logical_ms);
    previous_logical_ms = logical_ms;
    now = static_cast<uint32_t>(logical_ms);
    quality = evaluate(input, now);
    trends.update(input, quality, now);
    light.update(now, makeNightInputs(input, quality, dark_known, dark));
  }
};

void replayMissingStartup() {
  Replay replay;
  for (uint64_t time = 0; time <= 2 * kMinute; time += 100) {
    replay.tick(time);
    assert(!replay.quality.presence.valid);
    assert(replay.light.output() == 0 && replay.light.target() == 0);
    assert(!replay.trends.summary().heart.available);
  }
  // Fresh out-of-bed data after boot still cannot substitute for prior in-bed.
  for (uint64_t time = 2 * kMinute + 100; time <= 3 * kMinute; time += 100) {
    replay.input = observation(time, false);
    replay.tick(time);
    assert(replay.light.target() == 0);
    assert(!replay.quality.heart_bpm.valid);
  }
}

void replayEntireNight() {
  Replay replay;
  unsigned automatic_events = 0;
  uint8_t last_target = 0;
  for (uint64_t second = 0; second <= 8 * 60 * 60; ++second) {
    const uint64_t time = second * kSecond;
    const bool startup = second < 60;
    const bool fault = second >= 21600 && second < 23400;
    const bool first_departure = second >= 7200 && second < 7290;
    const bool bright_departure = second >= 14400 && second < 14500;
    const bool unknown_departure = second >= 18000 && second < 18100;
    const bool last_departure = second >= 27000 && second < 27090;
    const bool in_bed = !(first_departure || bright_departure ||
                         unknown_departure || last_departure);
    replay.input = startup || fault ? SensorSnapshot{} : observation(time, in_bed);
    if (!startup && !fault) {
      replay.input.module_sleep_stage.value = static_cast<uint8_t>(second % 4);
      if (second % 37 == 0) replay.input.heart_bpm.value = 255;
      if (second % 53 == 0) replay.input.respiration_bpm.value = 0;
      if (second >= 10000 && second < 10020) replay.input.low_motion.value = false;
    }
    replay.tick(time, !unknown_departure, !bright_departure);
    if (last_target == 0 && replay.light.target() != 0) ++automatic_events;
    last_target = replay.light.target();
    const bool expected_on = (second >= 7203 && second < 7263) ||
                             (second >= 27003 && second < 27063);
    assert((replay.light.target() != 0) == expected_on);
    const auto trend = replay.trends.summary();
    if (trend.heart.available) assert(trend.heart.median == 72.0f);
    if (trend.respiration.available) assert(trend.respiration.median == 16.0f);
    if (second >= 21660 && second < 23400) {
      assert(!trend.heart.available && !trend.respiration.available);
      assert(replay.light.output() == 0);
    }
    if (second >= 10000 && second < 10020) {
      assert(!replay.quality.heart_bpm.valid && !replay.quality.respiration_bpm.valid);
    }
  }
  assert(automatic_events == 2);
  assert(replay.light.output() == 0);
}

void replayAmbientGatesAndManual() {
  for (unsigned scenario = 0; scenario < 3; ++scenario) {
    Replay replay;
    replay.input = observation(0);
    replay.tick(0);
    for (uint64_t time = 100; time <= 10000; time += 100) {
      replay.input = observation(time, false);
      // After the departure decision, even vetoed scenes become dark. They
      // must remain consumed until a genuinely newer in-bed observation.
      const bool known = time > 3100 || scenario != 2;
      const bool dark = time > 3100 || scenario == 0;
      replay.tick(time, known, dark);
    }
    assert((replay.light.target() != 0) == (scenario == 0));
  }

  Replay manual;
  manual.light.shortPress(0);
  for (uint64_t time = 0; time <= 20 * kMinute; time += kSecond) {
    manual.input = time > 5 * kMinute && time < 10 * kMinute
                       ? SensorSnapshot{}
                       : observation(time, (time / kMinute) % 2 == 0);
    manual.tick(time, false, false);
    assert(manual.light.mode() == LightMode::Manual);
    assert(manual.light.target() == 96);
    if (time >= kSecond) assert(manual.light.output() == 96);
  }
  manual.light.shortPress(manual.now);
  manual.input = observation(20 * kMinute + kSecond, false);
  manual.tick(20 * kMinute + kSecond);
  assert(manual.light.output() == 0);
  manual.light.setAuto(manual.now);
  manual.input = observation(20 * kMinute + 5000, false);
  manual.tick(20 * kMinute + 5000);
  assert(manual.light.target() == 0);
}

void replayOldReportsAndBucketBoundaries() {
  Replay cached;
  cached.input = observation(0);
  cached.tick(0);
  cached.input = observation(999);
  cached.tick(999);
  cached.tick(1000);  // Same measurement second must not fill two buckets.
  assert(cached.trends.summary().heart.valid_buckets == 1);
  cached.input = observation(1001);
  cached.tick(1001);
  assert(cached.trends.summary().heart.valid_buckets == 2);
  cached.input = observation(999);  // Still fresh, but older than accepted data.
  cached.tick(2000);
  assert(cached.trends.summary().heart.valid_buckets == 2);

  Replay light;
  light.input = observation(0);
  light.tick(0);
  light.input = observation(100, false);
  light.tick(100);
  light.input = observation(3100, false);
  light.tick(3100);
  assert(light.light.target() == 96);
  light.input = observation(0, true);  // Old in-bed frame is still within 5 s.
  light.tick(3500);
  light.input = observation(4000, false);
  light.tick(4000);
  light.input = observation(7000, false);
  light.tick(7000);
  light.input = observation(64100, false);
  light.tick(64100);
  assert(light.light.output() == 0);  // Old in-bed did not restart the timer.

  Replay boundary;
  for (uint64_t time = 123; time <= 59123; time += kSecond) {
    boundary.input = observation(time);
    boundary.tick(time);
  }
  auto summary = boundary.trends.summary();
  assert(summary.heart.valid_buckets == 60 && summary.heart.coverage == 1.0f);
  boundary.input = {};
  boundary.tick(60122);  // Current bucket plus 59 prior buckets, before boundary.
  assert(boundary.trends.summary().heart.valid_buckets == 60);
  boundary.tick(60123);
  assert(boundary.trends.summary().heart.valid_buckets == 59);
  boundary.tick(119123);
  assert(!boundary.trends.summary().heart.available);
}

void replayTwentyFiveDayFaultRecovery() {
  Replay replay;
  replay.input = observation(0);
  replay.tick(0);
  assert(replay.trends.summary().heart.valid_buckets == 1);
  // Main loop keeps advancing. No individually observed interval exceeds the
  // uint32 ordering horizon, but the gap since the last valid reading does.
  for (uint64_t day = 1; day <= 25; ++day) {
    replay.input = {};
    replay.tick(day * kDay);
    assert(!replay.trends.summary().heart.available);
    assert(replay.light.target() == 0);
  }
  const uint64_t recovery = 25 * kDay + kSecond;
  replay.input = observation(recovery);
  replay.tick(recovery);
  assert(replay.quality.heart_bpm.valid);
  assert(replay.trends.summary().heart.valid_buckets == 1);
  replay.input = observation(recovery + 1000, false);
  replay.tick(recovery + 1000);
  replay.input = observation(recovery + 4000, false);
  replay.tick(recovery + 4000);
  assert(replay.light.target() == 96);
}

void replayFiftyDayClock() {
  Replay replay;
  uint32_t previous_clock = 0;
  unsigned rollovers = 0;
  for (uint64_t time = 0; time <= 50 * kDay; time += kMinute) {
    replay.input = observation(time);
    replay.tick(time);
    if (replay.now < previous_clock) ++rollovers;
    previous_clock = replay.now;
    assert(replay.quality.heart_bpm.valid && replay.quality.respiration_bpm.valid);
    // Sparse replay: one fresh observation per minute, not full coverage.
    assert(replay.trends.summary().heart.valid_buckets == 1);
    assert(replay.light.target() == 0);
  }
  assert(rollovers == 1);

  // A departure and both fade directions straddle the actual 2^32-ms boundary.
  Replay crossing;
  const uint64_t departure = std::numeric_limits<uint32_t>::max() - 1500ull;
  crossing.input = observation(departure - 1000);
  crossing.tick(departure - 1000);
  crossing.input = observation(departure, false);
  crossing.tick(departure);
  crossing.input = observation(departure + 3000, false);
  crossing.tick(departure + 3000);
  assert(crossing.light.target() == 96);
  crossing.input = observation(departure + 3500, false);
  crossing.tick(departure + 3500);
  assert(crossing.light.output() == 48);
  crossing.input = observation(departure + 63500, false);
  crossing.tick(departure + 63500);
  assert(crossing.light.output() == 48);
  crossing.input = observation(departure + 64000, false);
  crossing.tick(departure + 64000);
  assert(crossing.light.output() == 0);
}

}  // namespace

int main() {
  replayMissingStartup();
  replayEntireNight();
  replayAmbientGatesAndManual();
  replayOldReportsAndBucketBoundaries();
  replayTwentyFiveDayFaultRecovery();
  replayFiftyDayClock();
  std::cout << "replay: 8-hour night, 25-day fault and 50-day clock assertions passed\n";
}
