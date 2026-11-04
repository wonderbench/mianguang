#include <Arduino.h>
#include <Wire.h>
#include <algorithm>
#include <cstdio>
#include <cstring>

#include "board_config.h"
#include "c1001_protocol.h"
#include "radar_client.h"
#include "monitor_logic.h"
#include "user_input.h"
#ifdef MIANGUANG_PLATFORM
#include "platform_network.h"
#endif

namespace {
using namespace board_config;
sleep_radar::Parser parser;
sleep_radar::RadarClient radar;
sleep_core::TrendWindow trends;
sleep_core::NightLight lamp;
sleep_core::Button button;
sleep_core::AmbientGate ambient;
HardwareSerial radar_uart(1);

bool uart_enabled = false;
uint32_t fault_seen = 0;
uint32_t parser_errors_seen = 0;
uint32_t previous_ms = 0;
uint64_t uptime_ms = 0;
uint32_t log_ms = 0;
#ifdef MIANGUANG_PLATFORM
char command_buffer[8192]{};
#else
char command_buffer[64]{};
#endif
size_t command_length = 0;
bool command_overflow = false;
const char* command_result = "boot_uart_high_z";
char log_buffer[1800]{};
size_t log_length = 0;
size_t log_offset = 0;

bool ambient_started = false;
bool ambient_attempted = false;
bool ambient_reading_available = false;
float estimated_lux = 0;
uint32_t ambient_attempt_ms = 0;
uint32_t ambient_sample_ms = 0;

uint32_t refreshClock() {
  const uint32_t now = millis();
  uptime_ms += static_cast<uint32_t>(now - previous_ms);
  previous_ms = now;
  return now;
}

const char* reason(sleep_core::QualityError value) {
  using Q = sleep_core::QualityError;
  switch (value) {
    case Q::None: return "ok";
    case Q::Missing: return "missing";
    case Q::Stale: return "stale";
    case Q::TransportFault: return "transport_fault";
    case Q::InstallationUnconfirmed: return "installation_unconfirmed";
    case Q::InvalidValue: return "invalid_value";
    case Q::OutOfRange: return "out_of_range";
    case Q::OccupancyUnknown: return "occupancy_unknown";
    case Q::NotPresent: return "not_present";
    case Q::NotInBed: return "not_in_bed";
    case Q::MotionUnknown: return "motion_unknown";
    case Q::Motion: return "motion";
    case Q::ConflictingOccupancy: return "conflicting_occupancy";
  }
  return "unknown";
}
const char* boolean(bool value) { return value ? "true" : "false"; }

void consumeFault(uint32_t now) {
  if (radar.faultGeneration() == fault_seen) return;
  fault_seen = radar.faultGeneration();
  // Deliver every failure to the light even if a good frame arrives this loop.
  // Already-lit automatic timers continue; a pending departure is cancelled.
  lamp.update(now, {});
}

void checkParserFault(uint32_t now) {
  const auto& s = parser.stats();
  const uint32_t count = s.checksum_errors + s.framing_errors + s.length_errors + s.timeouts;
  if (count != parser_errors_seen) {
    parser_errors_seen = count;
    radar.notifyTransportFault(now);
    consumeFault(now);
  }
}

void setRadarEnabled(bool enabled, uint32_t now) {
  // No sensor-power detection exists on V0.1 PCB. Operator confirms real 5V
  // before enabling TX; this command is not a hardware power switch.
  if (uart_enabled) radar_uart.end();
  pinMode(kRadarRx, INPUT);
  pinMode(kRadarTx, INPUT);
  parser.reset();
  radar.setEnabled(false, now);
  uart_enabled = enabled;
  if (enabled) {
    radar_uart.setRxBufferSize(256);
    radar_uart.begin(kRadarBaud, SERIAL_8N1, kRadarRx, kRadarTx);
    radar.setEnabled(true, now);
  }
  consumeFault(now);
}

bool ambientCommand(uint8_t value) {
  Wire.beginTransmission(kAmbientAddress);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

void updateAmbient(uint32_t now) {
  if (!ambient_started) {
    if (ambient_attempted && static_cast<uint32_t>(now - ambient_attempt_ms) < 5000) return;
    ambient_attempted = true;
    ambient_attempt_ms = now;
    // BH1750: power on, MTreg=69 (high/low), continuous high-resolution mode.
    ambient_started = ambientCommand(0x01) && ambientCommand(0x42) &&
                      ambientCommand(0x65) && ambientCommand(0x10);
    ambient_sample_ms = now;
    ambient_reading_available = false;
    ambient.fault();
    return;
  }
  // 500ms exceeds the default high-resolution conversion maximum (180ms).
  if (static_cast<uint32_t>(now - ambient_sample_ms) < 500) return;
  ambient_sample_ms = now;
  const size_t received = Wire.requestFrom(kAmbientAddress, static_cast<uint8_t>(2));
  if (received != 2 || Wire.available() != 2) {
    while (Wire.available()) Wire.read();
    ambient_started = false;
    ambient_reading_available = false;
    ambient_attempt_ms = now;
    ambient.fault();
    return;
  }
  const uint16_t raw = static_cast<uint16_t>(Wire.read() << 8) | Wire.read();
  if (raw == 0xffffu) { // saturation is unknown, never dark
    ambient_reading_available = false;
    ambient.fault();
    return;
  }
  estimated_lux = raw / 1.2f;
  ambient_reading_available = true;
  ambient.observe(estimated_lux, now);
}

void command(const char* text, uint32_t now) {
#ifdef MIANGUANG_PLATFORM
  if (platform_network::command(text, uart_enabled)) {
    command_result = "network_command";
    return;
  }
#endif
  if (!std::strcmp(text, "radar on")) {
    setRadarEnabled(true, now); command_result = "radar_enabled_wait_10s";
  } else if (!std::strcmp(text, "radar off")) {
    setRadarEnabled(false, now); command_result = "radar_disabled_high_z";
  } else if (!std::strcmp(text, "install yes")) {
    radar.setInstallationConfirmed(true); command_result = "installation_confirmed";
  } else if (!std::strcmp(text, "install no")) {
    radar.setInstallationConfirmed(false); lamp.update(now, {});
    command_result = "installation_unconfirmed";
  } else if (!std::strcmp(text, "ambient yes")) {
    ambient.setCalibrated(true); command_result = "ambient_calibration_confirmed";
  } else if (!std::strcmp(text, "ambient no")) {
    ambient.setCalibrated(false); command_result = "ambient_unconfirmed";
  } else if (!std::strcmp(text, "light toggle")) {
    lamp.shortPress(now); command_result = "manual_toggle";
  } else if (!std::strcmp(text, "light level")) {
    lamp.longPress(now); command_result = "manual_level";
  } else if (!std::strcmp(text, "light auto")) {
    lamp.setAuto(now); command_result = "auto_enabled";
  } else if (!std::strcmp(text, "status")) {
    command_result = "status";
  } else {
    command_result = "unknown_command";
  }
}

void readConsole(uint32_t now) {
  for (unsigned budget = 0; budget < 32 && Serial.available(); ++budget) {
    const int byte = Serial.read();
    if (byte == '\r') continue;
    if (byte == '\n') {
      if (command_overflow) command_result = "command_too_long";
      else if (command_length) {
        command_buffer[command_length] = 0;
        command(command_buffer, now);
      }
      command_length = 0;
      command_overflow = false;
#ifdef MIANGUANG_PLATFORM
      // Configuration includes credentials; never retain or echo the USB line.
      std::memset(command_buffer, 0, sizeof(command_buffer));
#endif
    } else if (byte >= 32 && byte <= 126 && !command_overflow) {
      if (command_length + 1 < sizeof(command_buffer)) command_buffer[command_length++] = byte;
      else command_overflow = true;
    }
  }
}

template <typename T>
unsigned long age(const sleep_core::TimedField<T>& field, uint32_t now) {
  return field.available ? static_cast<unsigned long>(now - field.updated_ms) : 0;
}

void queueLog(uint32_t now, const sleep_core::DataQuality& quality) {
#ifdef MIANGUANG_PLATFORM
  if (Serial && log_length == log_offset &&
      platform_network::takeDiagnostic(log_buffer, sizeof(log_buffer) - 2)) {
    log_length = std::strlen(log_buffer);
    if (!log_length || log_buffer[log_length - 1] != '\n') log_buffer[log_length++] = '\n';
    log_buffer[log_length] = 0;
    log_offset = 0;
    return;
  }
#endif
  if (!Serial || log_length != log_offset || static_cast<uint32_t>(now - log_ms) < 1000) return;
  log_ms = now;
  const auto& s = radar.snapshot();
  const auto t = trends.summary();
  const auto a = ambient.state(now);
  const auto& p = parser.stats();
  char lux[24] = "null";
  if (ambient_reading_available) std::snprintf(lux, sizeof(lux), "%.1f", estimated_lux);
  const int length = std::snprintf(log_buffer, sizeof(log_buffer),
    "{\"schema\":1,\"type\":\"sample\",\"version\":\"%s\",\"t_ms\":%llu,\"clock_ms\":%lu,"
    "\"ready\":%s,\"client_state\":%u,\"installation_confirmed\":%s,\"transport_ok\":%s,\"fault_generation\":%lu,"
    "\"presence\":{\"raw\":%u,\"available\":%s,\"valid\":%s,\"reason\":\"%s\",\"age_ms\":%lu},"
    "\"bed\":{\"raw\":%u,\"available\":%s,\"valid\":%s,\"reason\":\"%s\",\"age_ms\":%lu},"
    "\"low_motion\":{\"raw\":%u,\"available\":%s,\"valid\":%s},"
    "\"rr\":{\"raw\":%u,\"available\":%s,\"valid\":%s,\"reason\":\"%s\",\"age_ms\":%lu},"
    "\"hr\":{\"raw\":%u,\"available\":%s,\"valid\":%s,\"reason\":\"%s\",\"age_ms\":%lu},"
    "\"vendor_stage\":{\"raw\":%u,\"available\":%s,\"valid\":%s},"
    "\"trend\":{\"rr_available\":%s,\"rr_median\":%.1f,\"rr_buckets\":%u,\"hr_available\":%s,\"hr_median\":%.1f,\"hr_buckets\":%u,\"total_buckets\":60},"
    "\"ambient\":{\"known\":%s,\"dark\":%s,\"calibrated\":%s,\"estimated_lux\":%s},"
    "\"lamp\":{\"mode\":\"%s\",\"pwm\":%u,\"target\":%u},"
    "\"parser\":{\"frames\":%lu,\"checksum\":%lu,\"framing\":%lu,\"length\":%lu,\"timeouts\":%lu},\"last_command\":\"%s\"}\n",
    MIANGUANG_VERSION, static_cast<unsigned long long>(uptime_ms), static_cast<unsigned long>(now),
    boolean(radar.ready()), static_cast<unsigned>(radar.state()), boolean(s.installation_confirmed),
    boolean(s.transport_ok), static_cast<unsigned long>(radar.faultGeneration()),
    s.presence.value, boolean(s.presence.available), boolean(quality.presence.valid), reason(quality.presence.error), age(s.presence, now),
    s.in_bed.value, boolean(s.in_bed.available), boolean(quality.in_bed.valid), reason(quality.in_bed.error), age(s.in_bed, now),
    s.low_motion.value, boolean(s.low_motion.available), boolean(quality.low_motion.valid),
    s.respiration_bpm.value, boolean(s.respiration_bpm.available), boolean(quality.respiration_bpm.valid), reason(quality.respiration_bpm.error), age(s.respiration_bpm, now),
    s.heart_bpm.value, boolean(s.heart_bpm.available), boolean(quality.heart_bpm.valid), reason(quality.heart_bpm.error), age(s.heart_bpm, now),
    s.module_sleep_stage.value, boolean(s.module_sleep_stage.available), boolean(quality.module_sleep_stage.valid),
    boolean(t.respiration.available), t.respiration.median, t.respiration.valid_buckets,
    boolean(t.heart.available), t.heart.median, t.heart.valid_buckets,
    boolean(a.known), boolean(a.dark), boolean(ambient.calibrated()), lux,
    lamp.mode() == sleep_core::LightMode::Auto ? "auto" : "manual", lamp.output(), lamp.target(),
    static_cast<unsigned long>(p.frames), static_cast<unsigned long>(p.checksum_errors), static_cast<unsigned long>(p.framing_errors),
    static_cast<unsigned long>(p.length_errors), static_cast<unsigned long>(p.timeouts), command_result);
  log_offset = 0;
  if (length > 0 && static_cast<size_t>(length) < sizeof(log_buffer)) log_length = length;
  else {
    std::strcpy(log_buffer, "{\"schema\":1,\"type\":\"error\",\"reason\":\"log_overflow\"}\n");
    log_length = std::strlen(log_buffer);
  }
}

void flushLog() {
  if (!Serial) { log_length = 0; log_offset = 0; return; }
  const int space = Serial.availableForWrite();
  if (space <= 0 || log_offset == log_length) return;
  const size_t count = std::min(log_length - log_offset, static_cast<size_t>(space));
  log_offset += Serial.write(reinterpret_cast<const uint8_t*>(log_buffer + log_offset), count);
}
}  // namespace

void setup() {
  // Set the gate low before attaching PWM; the PCB also has a gate pulldown.
  digitalWrite(kLamp, LOW);
  pinMode(kLamp, OUTPUT);
  ledcSetup(kPwmChannel, kPwmFrequency, 8);
  ledcAttachPin(kLamp, kPwmChannel);
  ledcWrite(kPwmChannel, 0);
  pinMode(kButton, INPUT_PULLUP);
  Serial.begin(115200);
  previous_ms = millis();
  setRadarEnabled(false, previous_ms);
  Wire.begin(kSda, kScl, 100000);
  Wire.setTimeOut(25);
#ifdef MIANGUANG_PLATFORM
  platform_network::begin();
#endif
}

void loop() {
  uint32_t now = refreshClock();
  readConsole(now);
  now = refreshClock();
  switch (button.update(digitalRead(kButton) == LOW, now)) {
    case sleep_core::ButtonEvent::Short: lamp.shortPress(now); break;
    case sleep_core::ButtonEvent::Long: lamp.longPress(now); break;
    case sleep_core::ButtonEvent::Auto: lamp.setAuto(now); break;
    case sleep_core::ButtonEvent::None: break;
  }
  parser.tick(now);
  checkParserFault(now);
  radar.tick(now);
  consumeFault(now);
  for (unsigned budget = 0; uart_enabled && budget < 256 && radar_uart.available(); ++budget) {
    sleep_radar::Frame frame;
    const bool complete = parser.feed(static_cast<uint8_t>(radar_uart.read()), now, frame);
    checkParserFault(now);
    if (complete) radar.accept(frame, now);
    consumeFault(now);
  }
  sleep_radar::Frame request;
  if (uart_enabled && radar.poll(now, request)) {
    uint8_t wire[sleep_radar::kMaxFrameSize];
    const size_t size = sleep_radar::encodeFrame(request, wire, sizeof(wire));
    if (size == 0 || radar_uart.write(wire, size) != size) radar.notifyTransportFault(now);
  }
  consumeFault(now);
  updateAmbient(now);
  // I2C can consume its timeout budget. Decide using the actual current time,
  // so a sample that expires during an I2C call cannot trigger a departure.
  now = refreshClock();
  parser.tick(now);
  checkParserFault(now);
  radar.tick(now);
  consumeFault(now);
  const auto quality = sleep_core::evaluate(radar.snapshot(), now);
  trends.update(radar.snapshot(), quality, now);
  const auto a = ambient.state(now);
  const auto night = sleep_core::makeNightInputs(radar.snapshot(), quality, a.known, a.dark);
  ledcWrite(kPwmChannel, lamp.update(now, night));
#ifdef MIANGUANG_PLATFORM
  platform_network::capture(now, uptime_ms, radar.snapshot(), quality,
      uart_enabled, radar.ready(), lamp.mode(), lamp.output(), lamp.target());
#endif
  queueLog(now, quality);
  flushLog();
  delay(1);  // Yield to ESP32 system tasks; no sensor waits in the main loop.
}
