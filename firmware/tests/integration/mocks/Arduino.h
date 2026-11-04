#pragma once

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <string>

constexpr int LOW = 0;
constexpr int HIGH = 1;
constexpr int INPUT = 0;
constexpr int OUTPUT = 1;
constexpr int INPUT_PULLUP = 2;
constexpr int SERIAL_8N1 = 0;

namespace arduino_mock {
inline uint32_t clock_ms = 0;
inline int button_level = HIGH;
inline uint32_t pwm = 0;
inline std::array<int, 64> pin_modes{};
inline std::array<int, 64> pin_values{};
}  // namespace arduino_mock

inline uint32_t millis() { return arduino_mock::clock_ms; }
inline void delay(uint32_t milliseconds) { arduino_mock::clock_ms += milliseconds; }
inline void pinMode(int pin, int mode) { arduino_mock::pin_modes.at(pin) = mode; }
inline void digitalWrite(int pin, int value) { arduino_mock::pin_values.at(pin) = value; }
inline int digitalRead(int) { return arduino_mock::button_level; }
inline void ledcSetup(int, uint32_t, int) {}
inline void ledcAttachPin(int, int) {}
inline void ledcWrite(int, uint32_t duty) { arduino_mock::pwm = duty; }

class HardwareSerial {
 public:
  explicit HardwareSerial(int = 0) {}
  void begin(uint32_t, int = SERIAL_8N1, int = -1, int = -1) { active = true; }
  void end() { active = false; incoming.clear(); }
  void setRxBufferSize(std::size_t) {}
  int available() const { return static_cast<int>(incoming.size()); }
  int read() {
    if (incoming.empty()) return -1;
    const int value = incoming.front();
    incoming.pop_front();
    return value;
  }
  int availableForWrite() const { return write_capacity; }
  std::size_t write(const uint8_t* bytes, std::size_t length) {
    const auto written = std::min(length, write_limit);
    outgoing.append(reinterpret_cast<const char*>(bytes), written);
    return written;
  }
  explicit operator bool() const { return connected; }
  void feed(const std::string& text) {
    for (const unsigned char byte : text) incoming.push_back(byte);
  }

  bool active = false;
  bool connected = true;
  int write_capacity = 64;
  std::size_t write_limit = 64;
  std::deque<uint8_t> incoming;
  std::string outgoing;
};

inline HardwareSerial Serial;
