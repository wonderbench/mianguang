#pragma once

#include "c1001_protocol.h"
#include "monitor_logic.h"

#include <cstdint>

namespace sleep_radar {

struct ClientConfig {
    bool enabled = true;
    std::uint32_t response_timeout_ms = 500;
    std::uint32_t query_interval_ms = 100;
    std::uint32_t link_timeout_ms = 5000;
    std::uint8_t max_consecutive_timeouts = 3;
};

enum class ClientState : std::uint8_t {
    Disabled,
    StartupWait,
    ConfirmMode,
    SetSleepMode,
    ModeSwitchWait,
    Running
};

class RadarClient {
public:
    static constexpr std::uint32_t kStartupWaitMs = 10000;

    explicit RadarClient(ClientConfig config = {});
    // Restart the handshake from now, preserving enabled/installation settings.
    void reset(std::uint32_t now_ms);
    void setEnabled(bool enabled, std::uint32_t now_ms);
    void setInstallationConfirmed(bool confirmed);

    // true reserves this request as sent. Send it immediately, or report a fault.
    // out is unchanged when false. There is at most one outstanding query.
    bool poll(std::uint32_t now_ms, Frame& out);
    // Only matching, timely, correctly sized replies can update the snapshot.
    // true also covers a valid response reporting a known unavailable measurement.
    bool accept(const Frame& frame, std::uint32_t now_ms);
    void tick(std::uint32_t now_ms);
    // Call on parser, serial I/O or send errors; invalidates cached evidence.
    void notifyTransportFault(std::uint32_t now_ms);

    const sleep_core::SensorSnapshot& snapshot() const { return snapshot_; }
    std::uint32_t faultGeneration() const { return fault_generation_; }
    bool enabled() const { return enabled_; }
    bool ready() const { return state_ == ClientState::Running; }
    bool pending() const { return pending_; }
    ClientState state() const { return state_; }

private:
    void initialize(std::uint32_t now_ms);
    void invalidateFields();
    void recordFault();
    void failPending(std::uint32_t now_ms);

    ClientConfig config_;
    sleep_core::SensorSnapshot snapshot_{};
    ClientState state_ = ClientState::StartupWait;
    bool enabled_ = true;
    bool initialized_ = false;
    bool pending_ = false;
    bool pace_active_ = false;
    bool have_response_ = false;
    std::uint8_t query_index_ = 0;
    std::uint8_t consecutive_failures_ = 0;
    std::uint8_t expected_control_ = 0;
    std::uint8_t expected_command_ = 0;
    std::uint32_t wait_started_ms_ = 0;
    std::uint32_t pending_started_ms_ = 0;
    std::uint32_t pace_started_ms_ = 0;
    std::uint32_t last_response_ms_ = 0;
    std::uint32_t fault_generation_ = 0;
};

}  // namespace sleep_radar
