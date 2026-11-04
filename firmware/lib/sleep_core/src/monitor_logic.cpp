#include "monitor_logic.h"

#include <algorithm>

namespace sleep_core {
namespace {

constexpr uint32_t kMaxIntervalMs = 0x7fffffffu;

FieldQuality invalid(QualityError error) { return {false, error}; }

bool newerObservation(uint32_t candidate, uint32_t previous) {
  const uint32_t elapsed = static_cast<uint32_t>(candidate - previous);
  return elapsed != 0 && elapsed <= kMaxIntervalMs;
}

template <typename T>
FieldQuality fieldQuality(const TimedField<T>& field, bool installed,
                          uint32_t now_ms, uint32_t freshness_ms) {
  if (!field.available) return invalid(QualityError::Missing);
  if (!installed) return invalid(QualityError::InstallationUnconfirmed);
  if (static_cast<uint32_t>(now_ms - field.updated_ms) > freshness_ms) {
    return invalid(QualityError::Stale);
  }
  return {true, QualityError::None};
}

FieldQuality measurementGate(const SensorSnapshot& sample,
                             const DataQuality& quality) {
  if (!quality.presence.valid || !quality.in_bed.valid) {
    return invalid(QualityError::OccupancyUnknown);
  }
  if (!sample.presence.value) return invalid(QualityError::NotPresent);
  if (!sample.in_bed.value) return invalid(QualityError::NotInBed);
  if (!quality.low_motion.valid) return invalid(QualityError::MotionUnknown);
  if (!sample.low_motion.value) return invalid(QualityError::Motion);
  return {true, QualityError::None};
}

FieldQuality vitalQuality(const TimedField<uint16_t>& field,
                          const SensorSnapshot& sample, const DataQuality& quality,
                          uint32_t now_ms, uint32_t freshness_ms,
                          uint16_t minimum, uint16_t maximum) {
  const auto base = fieldQuality(field, sample.installation_confirmed, now_ms,
                                 freshness_ms);
  if (!base.valid) return base;
  // These are absent/invalid readings, never evidence of breathing cessation.
  if (field.value == 0 || field.value == 255) {
    return invalid(QualityError::InvalidValue);
  }
  if (field.value < minimum || field.value > maximum) {
    return invalid(QualityError::OutOfRange);
  }
  return measurementGate(sample, quality);
}

MetricTrend summarize(std::array<uint16_t, TrendWindow::kBucketCount>& values,
                      std::size_t count) {
  MetricTrend result;
  result.valid_buckets = static_cast<uint16_t>(count);
  result.coverage = static_cast<float>(count) / TrendWindow::kBucketCount;
  result.available = count != 0;
  if (!result.available) return result;
  std::sort(values.begin(), values.begin() + count);
  const auto middle = count / 2;
  result.median = count % 2 != 0
                      ? static_cast<float>(values[middle])
                      : (static_cast<float>(values[middle - 1]) + values[middle]) /
                            2.0f;
  return result;
}

}  // namespace

DataQuality evaluate(const SensorSnapshot& sample, uint32_t now_ms,
                     QualityConfig config) {
  const auto freshness = std::min(config.freshness_ms, kMaxIntervalMs);
  DataQuality result;
  result.presence = fieldQuality(sample.presence, sample.installation_confirmed,
                                 now_ms, freshness);
  result.in_bed = fieldQuality(sample.in_bed, sample.installation_confirmed,
                               now_ms, freshness);
  result.low_motion = fieldQuality(sample.low_motion,
                                   sample.installation_confirmed, now_ms, freshness);
  if (!sample.transport_ok) {
    const auto fault = invalid(QualityError::TransportFault);
    return {fault, fault, fault, fault, fault, fault};
  }
  if (result.presence.valid && result.in_bed.valid && !sample.presence.value &&
      sample.in_bed.value) {
    result.in_bed = invalid(QualityError::ConflictingOccupancy);
  }
  result.respiration_bpm = vitalQuality(sample.respiration_bpm, sample, result,
                                       now_ms, freshness, 10, 25);
  result.heart_bpm = vitalQuality(sample.heart_bpm, sample, result, now_ms,
                                 freshness, 60, 100);
  result.module_sleep_stage = fieldQuality(sample.module_sleep_stage,
                                           sample.installation_confirmed, now_ms,
                                           freshness);
  if (result.module_sleep_stage.valid) {
    result.module_sleep_stage = sample.module_sleep_stage.value > 3
                                    ? invalid(QualityError::InvalidValue)
                                    : measurementGate(sample, result);
  }
  return result;
}

void TrendWindow::reset() {
  buckets_ = {};
  current_ = 0;
  started_ = false;
  bucket_start_ms_ = 0;
  respiration_seen_ = false;
  heart_seen_ = false;
  last_respiration_ms_ = 0;
  last_heart_ms_ = 0;
}

void TrendWindow::advance(uint32_t now_ms) {
  // Retire deduplication history with the window. Otherwise a recovery after
  // more than 2^31 ms without valid readings would look like an old replay.
  constexpr uint32_t window_ms = kBucketCount * kBucketMs;
  if (respiration_seen_ &&
      static_cast<uint32_t>(now_ms - last_respiration_ms_) >= window_ms) {
    respiration_seen_ = false;
  }
  if (heart_seen_ && static_cast<uint32_t>(now_ms - last_heart_ms_) >= window_ms) {
    heart_seen_ = false;
  }
  if (!started_) {
    started_ = true;
    bucket_start_ms_ = now_ms;
    return;
  }
  const uint32_t steps =
      static_cast<uint32_t>(now_ms - bucket_start_ms_) / kBucketMs;
  if (steps == 0) return;
  bucket_start_ms_ += steps * kBucketMs;
  if (steps >= kBucketCount) {
    buckets_ = {};
    current_ = (current_ + steps % kBucketCount) % kBucketCount;
    return;
  }
  for (uint32_t i = 0; i < steps; ++i) {
    current_ = (current_ + 1) % kBucketCount;
    buckets_[current_] = {};
  }
}

void TrendWindow::update(const SensorSnapshot& sample,
                         const DataQuality& quality, uint32_t now_ms) {
  advance(now_ms);
  auto& bucket = buckets_[current_];
  const uint32_t bucket_phase = static_cast<uint32_t>(now_ms - bucket_start_ms_);
  // An observation discarded because its bucket was full must not be counted
  // later just because the main loop rereads the same cached snapshot.
  const bool respiration_current =
      static_cast<uint32_t>(now_ms - sample.respiration_bpm.updated_ms) <= bucket_phase;
  const bool heart_current =
      static_cast<uint32_t>(now_ms - sample.heart_bpm.updated_ms) <= bucket_phase;
  if (quality.respiration_bpm.valid && respiration_current && !bucket.respiration_valid &&
      (!respiration_seen_ ||
       newerObservation(sample.respiration_bpm.updated_ms, last_respiration_ms_))) {
    bucket.respiration_valid = true;
    bucket.respiration = sample.respiration_bpm.value;
    respiration_seen_ = true;
    last_respiration_ms_ = sample.respiration_bpm.updated_ms;
  }
  if (quality.heart_bpm.valid && heart_current && !bucket.heart_valid &&
      (!heart_seen_ || newerObservation(sample.heart_bpm.updated_ms, last_heart_ms_))) {
    bucket.heart_valid = true;
    bucket.heart = sample.heart_bpm.value;
    heart_seen_ = true;
    last_heart_ms_ = sample.heart_bpm.updated_ms;
  }
}

TrendSummary TrendWindow::summary() const {
  std::array<uint16_t, kBucketCount> respiration{};
  std::array<uint16_t, kBucketCount> heart{};
  std::size_t respiration_count = 0;
  std::size_t heart_count = 0;
  for (const auto& bucket : buckets_) {
    if (bucket.respiration_valid) respiration[respiration_count++] = bucket.respiration;
    if (bucket.heart_valid) heart[heart_count++] = bucket.heart;
  }
  return {summarize(respiration, respiration_count), summarize(heart, heart_count)};
}

NightInputs makeNightInputs(const SensorSnapshot& sample,
                           const DataQuality& quality, bool dark_known,
                           bool dark) {
  const uint32_t presence_after_bed =
      static_cast<uint32_t>(sample.presence.updated_ms - sample.in_bed.updated_ms);
  const uint32_t oldest = presence_after_bed <= kMaxIntervalMs
                              ? sample.in_bed.updated_ms
                              : sample.presence.updated_ms;
  return {quality.presence.valid && quality.in_bed.valid,
          sample.presence.value && sample.in_bed.value, dark_known, dark, oldest};
}

NightLight::NightLight(NightLightConfig config) : config_(config) {
  config_.departure_confirm_ms = std::min(config_.departure_confirm_ms, kMaxIntervalMs);
  config_.on_duration_ms = std::min(config_.on_duration_ms, kMaxIntervalMs);
  config_.fade_ms = std::min(config_.fade_ms, kMaxIntervalMs);
}

uint8_t NightLight::selectedBrightness() const {
  return config_.brightness_levels[brightness_index_];
}

void NightLight::advanceFade(uint32_t now_ms) {
  if (output_ == target_) return;
  const uint32_t elapsed = static_cast<uint32_t>(now_ms - fade_start_ms_);
  if (config_.fade_ms == 0 || elapsed >= config_.fade_ms) {
    output_ = target_;
    return;
  }
  // Signed wide arithmetic also handles fading down without unsigned underflow.
  const auto delta = static_cast<int64_t>(target_) - fade_start_output_;
  output_ = static_cast<uint8_t>(static_cast<int64_t>(fade_start_output_) +
                                delta * elapsed / config_.fade_ms);
}

void NightLight::setTarget(uint8_t value, uint32_t now_ms) {
  advanceFade(now_ms);
  if (target_ == value) return;
  fade_start_output_ = output_;
  fade_start_ms_ = now_ms;
  target_ = value;
  if (config_.fade_ms == 0) output_ = value;
}

uint8_t NightLight::update(uint32_t now_ms, const NightInputs& input) {
  if (mode_ == LightMode::Manual) {
    advanceFade(now_ms);
    return output_;
  }

  // Apply the scheduled timeout before advancing to now; a delayed main-loop
  // iteration must not leave a lamp on for another full fade after expiry.
  if (automatic_on_ &&
      static_cast<uint32_t>(now_ms - automatic_start_ms_) >= config_.on_duration_ms) {
    setTarget(0, automatic_start_ms_ + config_.on_duration_ms);
    automatic_on_ = false;
  }
  advanceFade(now_ms);

  // Continuous main-loop calls can outlive a 24.8-day data outage. Once the old
  // ordering checkpoint is no longer comparable, allow fresh recovery input.
  if (occupancy_seen_ &&
      static_cast<uint32_t>(now_ms - last_occupancy_ms_) > kMaxIntervalMs) {
    occupancy_seen_ = false;
  }

  if (!input.occupancy_valid) {
    departure_pending_ = false;
    return output_;
  }
  if (occupancy_seen_) {
    const bool repeated = input.occupancy_updated_ms == last_occupancy_ms_;
    const bool older = !repeated &&
                       !newerObservation(input.occupancy_updated_ms, last_occupancy_ms_);
    if (older || (repeated && input.in_bed != last_occupancy_in_bed_)) {
      departure_pending_ = false;
      return output_;
    }
  }
  occupancy_seen_ = true;
  last_occupancy_ms_ = input.occupancy_updated_ms;
  last_occupancy_in_bed_ = input.in_bed;
  if (input.in_bed) {
    armed_ = true;
    departure_pending_ = false;
    return output_;
  }
  if (!armed_) return output_;
  if (!departure_pending_) {
    departure_pending_ = true;
    departure_start_ms_ = now_ms;
  }
  if (static_cast<uint32_t>(now_ms - departure_start_ms_) <
      config_.departure_confirm_ms) return output_;
  const uint32_t evidence_duration =
      static_cast<uint32_t>(input.occupancy_updated_ms - departure_start_ms_);
  if (evidence_duration > kMaxIntervalMs ||
      evidence_duration < config_.departure_confirm_ms) return output_;

  armed_ = false;
  departure_pending_ = false;
  if (input.dark_known && input.dark) {
    setTarget(selectedBrightness(), now_ms);
    automatic_on_ = true;
    automatic_start_ms_ = now_ms;
  }
  return output_;
}

void NightLight::shortPress(uint32_t now_ms) {
  advanceFade(now_ms);
  // Toggle the commanded state so rapid presses also work during a fade.
  const bool was_on = target_ != 0;
  mode_ = LightMode::Manual;
  automatic_on_ = false;
  armed_ = false;
  departure_pending_ = false;
  setTarget(was_on ? 0 : selectedBrightness(), now_ms);
}

void NightLight::longPress(uint32_t now_ms) {
  advanceFade(now_ms);
  const bool was_on = target_ != 0;
  brightness_index_ = (brightness_index_ + 1) % config_.brightness_levels.size();
  mode_ = LightMode::Manual;
  automatic_on_ = false;
  armed_ = false;
  departure_pending_ = false;
  setTarget(was_on ? selectedBrightness() : 0, now_ms);
}

void NightLight::setAuto(uint32_t now_ms) {
  mode_ = LightMode::Auto;
  automatic_on_ = false;
  armed_ = false;
  departure_pending_ = false;
  setTarget(0, now_ms);
}

}  // namespace sleep_core
