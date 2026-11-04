#pragma once

#include <cstddef>
#include <cstdint>
#include "monitor_logic.h"

namespace platform_network {

// All UART, lamp and local confirmation state stays owned by the caller.
void begin();
bool command(const char* line, bool radar_enabled);
void capture(uint32_t now, uint64_t uptime,
             const sleep_core::SensorSnapshot& sample,
             const sleep_core::DataQuality& quality, bool uart_enabled,
             bool ready, sleep_core::LightMode lamp_mode, uint8_t pwm,
             uint8_t target);

// Consume into the existing main-loop USB output buffer; no worker Serial I/O.
bool takeDiagnostic(char* buffer, std::size_t capacity);

}  // namespace platform_network
