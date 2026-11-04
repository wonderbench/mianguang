#include "monitor_logic.h"

#include <cassert>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>

using namespace sleep_core;

namespace {

SensorSnapshot validSample(uint32_t time) {
  SensorSnapshot sample;
  sample.installation_confirmed = true;
  sample.transport_ok = true;
  sample.presence = {true, time, true};
  sample.in_bed = {true, time, true};
  sample.low_motion = {true, time, true};
  sample.respiration_bpm = {16, time, true};
  sample.heart_bpm = {72, time, true};
  sample.module_sleep_stage = {2, time, true};
  return sample;
}

NightInputs occupancy(uint32_t time, bool in_bed, bool valid = true,
                      bool dark_known = true, bool dark = true) {
  return {valid, in_bed, dark_known, dark, time};
}

void expectError(const FieldQuality& quality, QualityError error) {
  assert(!quality.valid);
  assert(quality.error == error);
}

void testQuality() {
  auto sample = validSample(100);
  auto quality = evaluate(sample, 100);
  assert(quality.presence.valid && quality.in_bed.valid && quality.low_motion.valid);
  assert(quality.respiration_bpm.valid && quality.heart_bpm.valid);
  assert(quality.module_sleep_stage.valid);
  assert(evaluate(sample, 5100).heart_bpm.valid);  // Threshold is inclusive.
  expectError(evaluate(sample, 5101).heart_bpm, QualityError::Stale);
  expectError(evaluate(sample, 2101, QualityConfig{2000}).heart_bpm,
              QualityError::Stale);

  sample = validSample(6000);
  sample.respiration_bpm.updated_ms = 0;
  quality = evaluate(sample, 6000);
  expectError(quality.respiration_bpm, QualityError::Stale);
  assert(quality.heart_bpm.valid);  // Freshness is per field.

  sample = validSample(0);
  sample.installation_confirmed = false;
  expectError(evaluate(sample, 0).heart_bpm, QualityError::InstallationUnconfirmed);
  sample = validSample(0);
  sample.transport_ok = false;
  quality = evaluate(sample, 0);
  expectError(quality.presence, QualityError::TransportFault);
  expectError(quality.respiration_bpm, QualityError::TransportFault);

  sample = validSample(0);
  sample.low_motion.value = false;
  expectError(evaluate(sample, 0).respiration_bpm, QualityError::Motion);
  expectError(evaluate(sample, 0).module_sleep_stage, QualityError::Motion);
  sample.low_motion.available = false;
  expectError(evaluate(sample, 0).heart_bpm, QualityError::MotionUnknown);

  sample = validSample(0);
  sample.in_bed.value = false;
  expectError(evaluate(sample, 0).heart_bpm, QualityError::NotInBed);
  sample.presence.value = false;
  expectError(evaluate(sample, 0).heart_bpm, QualityError::NotPresent);
  sample.in_bed.value = true;
  expectError(evaluate(sample, 0).in_bed, QualityError::ConflictingOccupancy);
  sample = validSample(0);
  sample.in_bed.available = false;
  expectError(evaluate(sample, 0).heart_bpm, QualityError::OccupancyUnknown);

  for (const uint16_t value : {0, 255}) {
    sample = validSample(0);
    sample.respiration_bpm.value = value;
    sample.heart_bpm.value = value;
    quality = evaluate(sample, 0);
    expectError(quality.respiration_bpm, QualityError::InvalidValue);
    expectError(quality.heart_bpm, QualityError::InvalidValue);
  }
  for (const uint16_t value : {9, 26}) {
    sample = validSample(0);
    sample.respiration_bpm.value = value;
    expectError(evaluate(sample, 0).respiration_bpm, QualityError::OutOfRange);
  }
  for (const uint16_t value : {59, 101}) {
    sample = validSample(0);
    sample.heart_bpm.value = value;
    expectError(evaluate(sample, 0).heart_bpm, QualityError::OutOfRange);
  }
  sample = validSample(0);
  sample.respiration_bpm.value = 10;
  sample.heart_bpm.value = 60;
  assert(evaluate(sample, 0).respiration_bpm.valid);
  assert(evaluate(sample, 0).heart_bpm.valid);
  sample.respiration_bpm.value = 25;
  sample.heart_bpm.value = 100;
  assert(evaluate(sample, 0).respiration_bpm.valid);
  assert(evaluate(sample, 0).heart_bpm.valid);
  sample.respiration_bpm.available = false;
  expectError(evaluate(sample, 0).respiration_bpm, QualityError::Missing);
  sample.module_sleep_stage.value = 255;
  expectError(evaluate(sample, 0).module_sleep_stage, QualityError::InvalidValue);
  sample = validSample(0);
  sample.module_sleep_stage.value = 3;  // Vendor "none", not an invented sleep stage.
  assert(evaluate(sample, 0).module_sleep_stage.valid);
  for (const uint8_t value : {4, 17, 254, 255}) {
    sample.module_sleep_stage.value = value;
    expectError(evaluate(sample, 0).module_sleep_stage, QualityError::InvalidValue);
  }
}

void testQualityRollover() {
  const uint32_t then = std::numeric_limits<uint32_t>::max() - 99;
  auto sample = validSample(then);
  assert(evaluate(sample, 100, QualityConfig{200}).heart_bpm.valid);
  expectError(evaluate(sample, 101, QualityConfig{200}).heart_bpm,
              QualityError::Stale);
  sample = validSample(12);
  expectError(evaluate(sample, 11).heart_bpm, QualityError::Stale);
}

void testTrendDeduplication() {
  TrendWindow window;
  auto sample = validSample(0);
  for (uint32_t now = 0; now < 1000; now += 10) {
    window.update(sample, evaluate(sample, now), now);
  }
  assert(window.summary().heart.valid_buckets == 1);
  // Re-reading the same packet in another bucket still cannot count it twice.
  window.update(sample, evaluate(sample, 1000), 1000);
  assert(window.summary().heart.valid_buckets == 1);
  sample = validSample(1200);
  sample.heart_bpm.value = 80;
  window.update(sample, evaluate(sample, 1200), 1200);
  sample = validSample(1300);
  sample.heart_bpm.value = 90;
  window.update(sample, evaluate(sample, 1300), 1300);
  const auto summary = window.summary();
  assert(summary.heart.valid_buckets == 2);
  assert(summary.heart.median == 76.0f);  // First accepted value in each bucket.
  assert(std::fabs(summary.heart.coverage - 2.0f / 60.0f) < 0.00001f);
  sample = validSample(0);  // An older replay is not a new observation.
  window.update(sample, evaluate(sample, 2000), 2000);
  assert(window.summary().heart.valid_buckets == 2);
}

void testTrendWindow() {
  TrendWindow window;
  for (uint32_t bucket = 0; bucket < 60; ++bucket) {
    auto sample = validSample(bucket * 1000);
    sample.respiration_bpm.value = bucket % 2 == 0 ? 12 : 20;
    sample.heart_bpm.value = bucket % 2 == 0 ? 64 : 84;
    window.update(sample, evaluate(sample, bucket * 1000), bucket * 1000);
  }
  auto summary = window.summary();
  assert(summary.respiration.available && summary.heart.available);
  assert(summary.respiration.valid_buckets == 60 && summary.heart.valid_buckets == 60);
  assert(summary.respiration.coverage == 1.0f);
  assert(summary.respiration.median == 16.0f && summary.heart.median == 74.0f);

  SensorSnapshot missing;
  window.update(missing, evaluate(missing, 60000), 60000);
  assert(window.summary().heart.valid_buckets == 59);
  window.update(missing, evaluate(missing, 120000), 120000);
  summary = window.summary();
  assert(!summary.heart.available && summary.heart.coverage == 0.0f);

  window.reset();
  auto sample = validSample(0);
  sample.respiration_bpm.value = 255;
  window.update(sample, evaluate(sample, 0), 0);
  assert(!window.summary().respiration.available);
  assert(window.summary().heart.valid_buckets == 1);

  window.reset();
  const uint32_t start = std::numeric_limits<uint32_t>::max() - 500;
  sample = validSample(start);
  window.update(sample, evaluate(sample, start), start);
  const uint32_t next = start + 1000;
  sample = validSample(next);
  window.update(sample, evaluate(sample, next), next);
  assert(window.summary().heart.valid_buckets == 2);
  window.update(missing, evaluate(missing, start + 61000), start + 61000);
  assert(!window.summary().heart.available);
}

void testNormalDepartureAndRearm() {
  NightLight light;
  assert(light.output() == 0 && light.mode() == LightMode::Auto);
  light.update(0, occupancy(0, false));
  light.update(4000, occupancy(4000, false));
  assert(light.target() == 0);  // Booting while out of bed does not arm.
  light.update(5000, occupancy(5000, true));
  light.update(5100, occupancy(5100, false));
  light.update(8099, occupancy(8099, false));
  assert(light.target() == 0);
  light.update(8100, occupancy(8100, false));
  assert(light.target() == 96 && light.output() == 0);
  assert(light.update(8600, occupancy(8600, false)) == 48);
  assert(light.update(9100, occupancy(9100, false)) == 96);
  assert(light.update(68100, occupancy(68100, false)) == 96);
  assert(light.update(68600, occupancy(68600, false)) == 48);
  assert(light.update(69100, occupancy(69100, false)) == 0);
  light.update(80000, occupancy(80000, false));
  assert(light.target() == 0);
  light.update(81000, occupancy(81000, true));
  light.update(82000, occupancy(82000, false));
  light.update(85000, occupancy(85000, false));
  assert(light.target() == 96);
  // A late update catches up through the timeout and completed fade.
  assert(light.update(160000, occupancy(160000, false)) == 0);
}

void testFaultsAndDarkGate() {
  NightLight light;
  light.update(0, occupancy(0, true));
  light.update(100, occupancy(100, false));
  light.update(1000, occupancy(1000, false, false));
  light.update(3100, occupancy(3100, false, false));
  assert(light.target() == 0);
  light.update(4000, occupancy(4000, false));
  light.update(6999, occupancy(6999, false));
  assert(light.target() == 0);  // A fault interrupted the original countdown.
  light.update(7000, occupancy(7000, false));
  assert(light.target() == 96);

  NightLight cached;
  auto sample = validSample(0);
  cached.update(0, makeNightInputs(sample, evaluate(sample, 0), true, true));
  sample = validSample(100);
  sample.in_bed.value = false;
  for (uint32_t now = 100; now <= 6000; now += 100) {
    cached.update(now, makeNightInputs(sample, evaluate(sample, now), true, true));
  }
  assert(cached.target() == 0);  // Stopped serial stream never confirms departure.
  sample.transport_ok = false;
  assert(!makeNightInputs(sample, evaluate(sample, 200), true, true).occupancy_valid);

  for (bool known : {false, true}) {
    NightLight ambient;
    ambient.update(0, occupancy(0, true));
    ambient.update(100, occupancy(100, false, true, known, false));
    ambient.update(3100, occupancy(3100, false, true, known, false));
    assert(ambient.target() == 0);
    ambient.update(4000, occupancy(4000, false));
    assert(ambient.target() == 0);  // No delayed trigger when it becomes dark.
    ambient.update(5000, occupancy(5000, true));
    ambient.update(6000, occupancy(6000, false));
    ambient.update(9000, occupancy(9000, false));
    assert(ambient.target() == 96);
  }
}

void testManualPriority() {
  NightLight rapid;
  rapid.shortPress(0);
  rapid.update(500, occupancy(500, false));
  rapid.shortPress(500);
  assert(rapid.target() == 0);
  rapid.shortPress(600);
  assert(rapid.target() == 96);  // A second press during fade-out turns it on.

  NightLight light;
  light.shortPress(0);
  assert(light.mode() == LightMode::Manual && light.target() == 96);
  assert(light.update(1000, occupancy(1000, false, false)) == 96);
  light.update(100000, occupancy(100000, true));
  light.update(104000, occupancy(104000, false));
  assert(light.output() == 96);  // Automatic timeout never ends manual mode.
  light.longPress(104000);
  assert(light.selectedBrightness() == 192 && light.target() == 192);
  assert(light.update(105000, occupancy(105000, false)) == 192);
  light.shortPress(105000);
  assert(light.update(106000, occupancy(106000, false)) == 0);
  light.update(107000, occupancy(107000, true));
  light.update(108000, occupancy(108000, false));
  light.update(111000, occupancy(111000, false));
  assert(light.target() == 0 && light.mode() == LightMode::Manual);
  light.longPress(111000);
  assert(light.selectedBrightness() == 32 && light.target() == 0);
  light.setAuto(112000);
  assert(light.mode() == LightMode::Auto);
  light.update(113000, occupancy(113000, false));
  light.update(117000, occupancy(117000, false));
  assert(light.target() == 0);  // Mode switch requires a new in-bed observation.
  light.update(118000, occupancy(118000, true));
  light.update(119000, occupancy(119000, false));
  light.shortPress(120000);  // Manual press cancels a pending automatic event.
  light.update(122000, occupancy(122000, false));
  assert(light.mode() == LightMode::Manual && light.target() == 32);
}

void testLightRollover() {
  NightLight light;
  const uint32_t start = std::numeric_limits<uint32_t>::max() - 1000;
  light.update(start, occupancy(start, true));
  light.update(start + 100, occupancy(start + 100, false));
  light.update(start + 3100, occupancy(start + 3100, false));
  assert(light.target() == 96);
  assert(light.update(start + 3600, occupancy(start + 3600, false)) == 48);
  assert(light.update(start + 4100, occupancy(start + 4100, false)) == 96);
  assert(light.update(start + 63600, occupancy(start + 63600, false)) == 48);
  assert(light.update(start + 64100, occupancy(start + 64100, false)) == 0);
}

}  // namespace

int main() {
  testQuality();
  testQualityRollover();
  testTrendDeduplication();
  testTrendWindow();
  testNormalDepartureAndRearm();
  testFaultsAndDarkGate();
  testManualPriority();
  testLightRollover();
  std::cout << "monitor_logic: all assertions passed\n";
}
