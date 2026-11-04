// Include the actual adapter, rather than copying its loop into a test double.
// Only Arduino/Wire calls are mocked; all sleep_core sources are linked normally.
#ifndef SLEEP_MAIN_SOURCE
#define SLEEP_MAIN_SOURCE "../../src/main.cpp"
#endif
#include SLEEP_MAIN_SOURCE

#include <cassert>
#include <iostream>
#include <limits>

namespace {

void resetFixture() {
  arduino_mock::clock_ms = 0;
  arduino_mock::button_level = HIGH;
  arduino_mock::pwm = 0;
  arduino_mock::pin_modes = {};
  arduino_mock::pin_values = {};
  Serial = HardwareSerial{};
  Wire = TwoWire{};
  parser = sleep_radar::Parser{};
  radar = sleep_radar::RadarClient{};
  trends = sleep_core::TrendWindow{};
  lamp = sleep_core::NightLight{};
  button = sleep_core::Button{};
  ambient = sleep_core::AmbientGate{};
  radar_uart = HardwareSerial{1};
  uart_enabled = false;
  fault_seen = 0;
  parser_errors_seen = 0;
  previous_ms = 0;
  uptime_ms = 0;
  log_ms = 0;
  command_length = 0;
  command_overflow = false;
  command_result = "boot_uart_high_z";
  log_length = 0;
  log_offset = 0;
  ambient_started = false;
  ambient_attempted = false;
  ambient_reading_available = false;
  estimated_lux = 0;
  ambient_attempt_ms = 0;
  ambient_sample_ms = 0;
  setup();
}

void runAt(uint32_t time) {
  arduino_mock::clock_ms = time;
  loop();
}

// Fault-injection fixture for the adapter's clock boundary. Protocol acceptance
// is tested separately; here the snapshot is deliberately placed at its expiry.
void injectOccupancy(uint32_t timestamp, bool in_bed) {
  auto& sample = const_cast<sleep_core::SensorSnapshot&>(radar.snapshot());
  sample.installation_confirmed = true;
  sample.transport_ok = true;
  sample.presence = {true, timestamp, true};
  sample.in_bed = {in_bed, timestamp, true};
  sample.low_motion = {true, timestamp, true};
  sample.respiration_bpm = {16, timestamp, true};
  sample.heart_bpm = {72, timestamp, true};
  sample.module_sleep_stage = {2, timestamp, true};
}

void emitCompleteLog(const char* fixture) {
  // Deliberately exercise partial serial writes, not just a large single write.
  Serial.write_capacity = 13;
  Serial.write_limit = 7;
  for (unsigned budget = 0; log_offset < log_length && budget < 1000; ++budget) {
    flushLog();
  }
  assert(log_offset == log_length);
  assert(!Serial.outgoing.empty() && Serial.outgoing.back() == '\n');
  std::cout << "LOG " << fixture << " " << Serial.outgoing;
}

void testI2cExpiryBeforeDecision() {
  resetFixture();
  lamp.update(0, {true, true, true, true, 0});
  lamp.update(2000, {true, false, true, true, 2000});
  injectOccupancy(5000, false);
  assert(sleep_core::evaluate(radar.snapshot(), 10000).presence.valid);
  ambient_started = true;
  ambient.setCalibrated(true);
  Wire.request_delay_ms = 25;
  runAt(10000);
  assert(millis() == 10026);  // Blocking request plus the one-ms scheduler yield.
  assert(!sleep_core::evaluate(radar.snapshot(), 10025).presence.valid);
  assert(lamp.target() == 0);  // Must not confirm using the pre-I2C timestamp.
  assert(arduino_mock::pwm == 0);
  assert(uptime_ms == 10025);
  emitCompleteLog("i2c_expiry");
}

void testConsoleUartAndManualPriority() {
  resetFixture();
  assert(!uart_enabled && !radar.enabled() && !radar_uart.active);
  assert(arduino_mock::pin_modes[kRadarTx] == INPUT);
  assert(arduino_mock::pwm == 0);
  Serial.feed("radar on\n");
  runAt(1);
  assert(uart_enabled && radar.enabled() && radar_uart.active);
  assert(radar.state() == sleep_radar::ClientState::StartupWait);
  assert(radar_uart.outgoing.empty());
  Serial.feed("radar off\n");
  runAt(2);
  assert(!uart_enabled && !radar.enabled() && !radar_uart.active);
  assert(arduino_mock::pin_modes[kRadarTx] == INPUT);

  ambient_started = true;
  Serial.feed("light toggle\n");
  runAt(2000);
  assert(lamp.mode() == sleep_core::LightMode::Manual && lamp.target() == 96);
  assert(lamp.output() > 0 && lamp.output() < 96);
  // Unknown/faulty radar input cannot cancel the user's manual lamp command.
  Serial.feed("radar off\n");
  runAt(3000);
  assert(lamp.output() == 96 && arduino_mock::pwm == 96);
  assert(lamp.mode() == sleep_core::LightMode::Manual);
  // Two complete log lines may be pending across slow writes; validate the last
  // sample separately below after clearing the already tested write transport.
  Serial.outgoing.clear();
  log_length = log_offset = 0;
  log_ms = 0;
  queueLog(3025, sleep_core::evaluate(radar.snapshot(), 3025));
  emitCompleteLog("manual_priority");
}

void testPhysicalButtonRouting() {
  resetFixture();
  Wire.request_delay_ms = 0;
  runAt(0);
  runAt(30);  // Stable boot release arms the key.
  Serial.feed("light toggle\n");
  runAt(1000);
  arduino_mock::button_level = LOW;
  runAt(1100);
  runAt(1130);
  arduino_mock::button_level = HIGH;
  runAt(2700);
  runAt(2730);
  assert(lamp.mode() == sleep_core::LightMode::Manual);
  assert(lamp.selectedBrightness() == 192 && lamp.target() == 192);

  arduino_mock::button_level = LOW;
  runAt(3000);
  runAt(3030);
  arduino_mock::button_level = HIGH;
  runAt(8000);
  runAt(8030);
  assert(lamp.mode() == sleep_core::LightMode::Auto && lamp.target() == 0);
  runAt(9030);
  assert(lamp.output() == 0 && arduino_mock::pwm == 0);
}

void testWorstCaseJsonAndPartialWrite() {
  resetFixture();
  injectOccupancy(1, true);
  auto& sample = const_cast<sleep_core::SensorSnapshot&>(radar.snapshot());
  sample.respiration_bpm.value = std::numeric_limits<uint16_t>::max();
  sample.heart_bpm.value = std::numeric_limits<uint16_t>::max();
  sample.module_sleep_stage.value = 254;
  auto& statistics = const_cast<sleep_radar::ParserStats&>(parser.stats());
  statistics.frames = std::numeric_limits<uint32_t>::max();
  statistics.checksum_errors = std::numeric_limits<uint32_t>::max();
  statistics.framing_errors = std::numeric_limits<uint32_t>::max();
  statistics.length_errors = std::numeric_limits<uint32_t>::max();
  statistics.timeouts = std::numeric_limits<uint32_t>::max();
  uptime_ms = std::numeric_limits<uint64_t>::max();
  estimated_lux = 54612;
  ambient_reading_available = true;
  command_result = "ambient_calibration_confirmed";
  queueLog(1001, sleep_core::evaluate(sample, 1001));
  assert(log_length < sizeof(log_buffer));
  emitCompleteLog("max_values");
}

}  // namespace

int main() {
  testI2cExpiryBeforeDecision();
  testConsoleUartAndManualPriority();
  testPhysicalButtonRouting();
  testWorstCaseJsonAndPartialWrite();
  std::cout << "main mock: I2C expiry, UART, manual/button routing and logs passed\n";
}
