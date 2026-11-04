#pragma once
#include <cstdint>

namespace board_config {
constexpr int kRadarRx = 20;  // XIAO D7 <- module TX
constexpr int kRadarTx = 21;  // XIAO D6 -> module RX
constexpr int kLamp = 4;      // XIAO D2 -> 100R -> MOSFET gate
constexpr int kButton = 3;    // XIAO D1 active low, external 10k/100nF
constexpr int kSda = 6;       // XIAO D4, external pullups to 3.3V only
constexpr int kScl = 7;       // XIAO D5
constexpr uint32_t kRadarBaud = 115200;
constexpr uint8_t kPwmChannel = 0;
constexpr uint32_t kPwmFrequency = 20000;
constexpr uint8_t kAmbientAddress = 0x23; // BH1750 ADDR low, optional module
}
