#pragma once

#include <cstdint>

namespace sleep_core {

enum class ButtonEvent : uint8_t { None, Short, Long, Auto };

// Active-low electrical input is converted to pressed=true by the caller.
// A key held during boot is ignored until a stable release has been seen.
class Button {
 public:
  ButtonEvent update(bool pressed, uint32_t now_ms);
 private:
  bool raw_ = true;
  bool stable_ = true;
  bool armed_ = false;
  uint32_t changed_ms_ = 0;
  uint32_t pressed_ms_ = 0;
};

struct AmbientState { bool known = false; bool dark = false; };

// Thresholds are engineering defaults in estimated lux; optical calibration
// must be explicitly confirmed before output can be known.
class AmbientGate {
 public:
  void setCalibrated(bool confirmed);
  void observe(float estimated_lux, uint32_t now_ms);
  void fault();
  AmbientState state(uint32_t now_ms) const;
  bool calibrated() const { return calibrated_; }
 private:
  bool calibrated_ = false;
  bool available_ = false;
  bool classified_ = false;
  bool dark_ = false;
  uint32_t updated_ms_ = 0;
};

}  // namespace sleep_core
