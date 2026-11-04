#pragma once

#include "Arduino.h"

#include <array>
#include <cstddef>
#include <cstdint>

class TwoWire {
 public:
  void begin(int, int, uint32_t) {}
  void setTimeOut(uint16_t milliseconds) { timeout_ms = milliseconds; }
  void beginTransmission(uint8_t) {}
  std::size_t write(uint8_t) { return 1; }
  uint8_t endTransmission() {
    arduino_mock::clock_ms += command_delay_ms;
    return command_result;
  }
  std::size_t requestFrom(uint8_t, uint8_t) {
    arduino_mock::clock_ms += request_delay_ms;
    read_index = 0;
    return response_size;
  }
  int available() const {
    return response_size > read_index ? static_cast<int>(response_size - read_index) : 0;
  }
  int read() {
    if (read_index >= response_size || read_index >= response.size()) return -1;
    return response[read_index++];
  }

  uint16_t timeout_ms = 0;
  uint32_t command_delay_ms = 0;
  uint32_t request_delay_ms = 25;
  uint8_t command_result = 0;
  std::size_t response_size = 2;
  std::size_t read_index = 0;
  std::array<uint8_t, 2> response{{0, 0}};
};

inline TwoWire Wire;
