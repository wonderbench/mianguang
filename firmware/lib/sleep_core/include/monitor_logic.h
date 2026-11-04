#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace sleep_core {

// Update this timestamp only when a complete, accepted packet supplies this field.
template <typename T>
struct TimedField {
  T value{};
  uint32_t updated_ms = 0;
  bool available = false;
};

struct SensorSnapshot {
  bool installation_confirmed = false;
  // Set true after accepted transport input, false on a known parser/link fault.
  bool transport_ok = false;
  TimedField<bool> presence;
  TimedField<bool> in_bed;
  TimedField<bool> low_motion;
  TimedField<uint16_t> respiration_bpm;
  TimedField<uint16_t> heart_bpm;
  // Vendor estimate: 0..3 are known, 3 means none (not sleeping). No clinical
  // sleep staging is inferred here; unknown raw enum values are invalid.
  TimedField<uint8_t> module_sleep_stage;
};

enum class QualityError : uint8_t {
  None,
  Missing,
  Stale,
  TransportFault,
  InstallationUnconfirmed,
  InvalidValue,
  OutOfRange,
  OccupancyUnknown,
  NotPresent,
  NotInBed,
  MotionUnknown,
  Motion,
  ConflictingOccupancy
};

struct FieldQuality {
  bool valid = false;
  QualityError error = QualityError::Missing;
};

struct QualityConfig {
  // Engineering default, NOT a measured C1001 transmission interval.
  uint32_t freshness_ms = 5000;
};

struct DataQuality {
  FieldQuality presence;
  FieldQuality in_bed;
  FieldQuality low_motion;
  FieldQuality respiration_bpm;
  FieldQuality heart_bpm;
  FieldQuality module_sleep_stage;
};

// The clock and all timestamps must share one monotonically wrapping uint32_t ms
// clock. Time spans/configuration must remain below 2^31 ms.
DataQuality evaluate(const SensorSnapshot& sample, uint32_t now_ms,
                     QualityConfig config = {});

struct MetricTrend {
  bool available = false;
  float median = 0.0f;
  uint16_t valid_buckets = 0;
  // Valid buckets / 60, including the current partial bucket. This is bucket
  // observation coverage, NOT a fraction of continuously valid elapsed time.
  float coverage = 0.0f;
};

struct TrendSummary {
  MetricTrend respiration;
  MetricTrend heart;
};

// A bounded rolling window of the current one-second bucket plus 59 prior ones.
// Each field accepts at most one observation timestamped inside its current
// bucket. Cached observations never migrate into a later sampling bucket.
class TrendWindow {
 public:
  static constexpr std::size_t kBucketCount = 60;
  static constexpr uint32_t kBucketMs = 1000;

  void update(const SensorSnapshot& sample, const DataQuality& quality,
              uint32_t now_ms);
  // Call update even when no data arrives, so missing time ages existing samples.
  TrendSummary summary() const;
  void reset();

 private:
  struct Bucket {
    bool respiration_valid = false;
    bool heart_valid = false;
    uint16_t respiration = 0;
    uint16_t heart = 0;
  };
  void advance(uint32_t now_ms);
  std::array<Bucket, kBucketCount> buckets_{};
  std::size_t current_ = 0;
  bool started_ = false;
  uint32_t bucket_start_ms_ = 0;
  bool respiration_seen_ = false;
  bool heart_seen_ = false;
  uint32_t last_respiration_ms_ = 0;
  uint32_t last_heart_ms_ = 0;
};

struct NightInputs {
  // Valid means both presence and in-bed fields are fresh and installation is
  // confirmed. Unknown/faulty occupancy must not be represented as out of bed.
  bool occupancy_valid = false;
  bool in_bed = false;
  bool dark_known = false;
  bool dark = false;
  // Timestamp of the older of the two occupancy observations. Cached reports
  // cannot establish a three-second departure without new sensor evidence.
  uint32_t occupancy_updated_ms = 0;
};

NightInputs makeNightInputs(const SensorSnapshot& sample,
                           const DataQuality& quality, bool dark_known,
                           bool dark);

struct NightLightConfig {
  uint32_t departure_confirm_ms = 3000;
  uint32_t on_duration_ms = 60000;
  uint32_t fade_ms = 1000;
  std::array<uint8_t, 3> brightness_levels{{32, 96, 192}};
};

enum class LightMode : uint8_t { Auto, Manual };

// Starts in Auto with output zero. Manual mode persists until setAuto().
// Events require an observed valid in-bed state, followed by continuously valid
// out-of-bed input. Each departure is consumed once, including a bright/unknown
// ambient veto, and is rearmed only by another valid in-bed observation.
class NightLight {
 public:
  explicit NightLight(NightLightConfig config = {});
  uint8_t update(uint32_t now_ms, const NightInputs& input);
  void shortPress(uint32_t now_ms);
  // Cycles the brightness preference; if off, the lamp stays off.
  void longPress(uint32_t now_ms);
  void setAuto(uint32_t now_ms);
  uint8_t output() const { return output_; }
  uint8_t target() const { return target_; }
  uint8_t selectedBrightness() const;
  LightMode mode() const { return mode_; }

 private:
  void advanceFade(uint32_t now_ms);
  void setTarget(uint8_t value, uint32_t now_ms);
  NightLightConfig config_;
  LightMode mode_ = LightMode::Auto;
  std::size_t brightness_index_ = 1;
  uint8_t output_ = 0;
  uint8_t target_ = 0;
  uint8_t fade_start_output_ = 0;
  uint32_t fade_start_ms_ = 0;
  bool armed_ = false;
  bool departure_pending_ = false;
  uint32_t departure_start_ms_ = 0;
  bool automatic_on_ = false;
  uint32_t automatic_start_ms_ = 0;
  bool occupancy_seen_ = false;
  uint32_t last_occupancy_ms_ = 0;
  bool last_occupancy_in_bed_ = false;
};

}  // namespace sleep_core
