#include "user_input.h"
#include <cmath>

namespace sleep_core {

ButtonEvent Button::update(bool pressed, uint32_t now_ms) {
  if (pressed != raw_) { raw_ = pressed; changed_ms_ = now_ms; }
  if (static_cast<uint32_t>(now_ms - changed_ms_) < 30 || stable_ == raw_)
    return ButtonEvent::None;
  stable_ = raw_;
  if (stable_) { pressed_ms_ = now_ms; return ButtonEvent::None; }
  if (!armed_) { armed_ = true; return ButtonEvent::None; }
  const uint32_t held = now_ms - pressed_ms_;
  if (held >= 5000) return ButtonEvent::Auto;
  if (held >= 1500) return ButtonEvent::Long;
  return ButtonEvent::Short;
}

void AmbientGate::setCalibrated(bool confirmed) {
  calibrated_ = confirmed;
  // Calibration changes must be followed by a new physical reading.
  available_ = false;
  classified_ = false;
}
void AmbientGate::observe(float estimated_lux, uint32_t now_ms) {
  if (!std::isfinite(estimated_lux) || estimated_lux < 0 || estimated_lux > 54612) {
    fault();
    return;
  }
  if (available_ && static_cast<uint32_t>(now_ms - updated_ms_) > 2500)
    classified_ = false;
  available_ = true;
  updated_ms_ = now_ms;
  if (estimated_lux <= 5.0f) { dark_ = true; classified_ = true; }
  else if (estimated_lux >= 10.0f) { dark_ = false; classified_ = true; }
  // Initial readings in the deadband remain unknown; later readings hold state.
}
void AmbientGate::fault() { available_ = false; classified_ = false; }
AmbientState AmbientGate::state(uint32_t now_ms) const {
  return {calibrated_ && available_ && classified_ &&
              static_cast<uint32_t>(now_ms - updated_ms_) <= 2500,
          dark_};
}

}  // namespace sleep_core
