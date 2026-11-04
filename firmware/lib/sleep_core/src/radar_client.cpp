#include "radar_client.h"

#include <algorithm>
#include <array>

namespace sleep_radar {
namespace {

constexpr std::uint32_t kMaxIntervalMs = 0x7FFFFFFFU;

struct QueryAddress {
    std::uint8_t control;
    std::uint8_t command;
};

// Keep this order aligned with the explicit field decoding below.
constexpr std::array<QueryAddress, 6> kQueries{{
    {0x80, 0x81},  // Presence.
    {0x80, 0x82},  // Motion.
    {0x84, 0x81},  // In bed.
    {0x81, 0x82},  // Respiration.
    {0x85, 0x82},  // Heart rate.
    {0x84, 0x82},  // Vendor sleep stage.
}};

std::uint32_t interval(std::uint32_t value) {
    return std::max<std::uint32_t>(1, std::min(value, kMaxIntervalMs));
}

bool elapsed(std::uint32_t now, std::uint32_t then, std::uint32_t delay) {
    return static_cast<std::uint32_t>(now - then) >= delay;
}

}  // namespace

RadarClient::RadarClient(ClientConfig config) : config_(config), enabled_(config.enabled) {
    config_.response_timeout_ms = interval(config_.response_timeout_ms);
    config_.query_interval_ms = interval(config_.query_interval_ms);
    config_.link_timeout_ms = interval(config_.link_timeout_ms);
    config_.max_consecutive_timeouts = std::max<std::uint8_t>(
        1, config_.max_consecutive_timeouts);
    state_ = enabled_ ? ClientState::StartupWait : ClientState::Disabled;
}

void RadarClient::initialize(std::uint32_t now_ms) {
    if (!initialized_) {
        initialized_ = true;
        wait_started_ms_ = now_ms;
    }
}

void RadarClient::invalidateFields() {
    snapshot_.presence.available = false;
    snapshot_.in_bed.available = false;
    snapshot_.low_motion.available = false;
    snapshot_.respiration_bpm.available = false;
    snapshot_.heart_bpm.available = false;
    snapshot_.module_sleep_stage.available = false;
}

void RadarClient::recordFault() {
    snapshot_.transport_ok = false;
    invalidateFields();
    ++fault_generation_;
}

void RadarClient::reset(std::uint32_t now_ms) {
    recordFault();
    initialized_ = true;
    state_ = enabled_ ? ClientState::StartupWait : ClientState::Disabled;
    pending_ = false;
    pace_active_ = false;
    have_response_ = false;
    query_index_ = 0;
    consecutive_failures_ = 0;
    expected_control_ = 0;
    expected_command_ = 0;
    wait_started_ms_ = now_ms;
}

void RadarClient::setEnabled(bool enabled, std::uint32_t now_ms) {
    if (enabled_ == enabled) {
        return;
    }
    enabled_ = enabled;
    reset(now_ms);
}

void RadarClient::setInstallationConfirmed(bool confirmed) {
    if (snapshot_.installation_confirmed != confirmed) {
        snapshot_.installation_confirmed = confirmed;
        invalidateFields();
        // A changed installation gate breaks a continuous occupancy observation.
        ++fault_generation_;
    }
}

void RadarClient::failPending(std::uint32_t now_ms) {
    recordFault();
    pending_ = false;
    pace_active_ = true;
    pace_started_ms_ = now_ms;
    if (consecutive_failures_ < 255) {
        ++consecutive_failures_;
    }
    if (state_ == ClientState::Running &&
        consecutive_failures_ >= config_.max_consecutive_timeouts) {
        state_ = ClientState::ConfirmMode;
        query_index_ = 0;
        have_response_ = false;
    }
}

void RadarClient::tick(std::uint32_t now_ms) {
    initialize(now_ms);
    if (!enabled_) {
        return;
    }
    if ((state_ == ClientState::StartupWait ||
         state_ == ClientState::ModeSwitchWait) &&
        elapsed(now_ms, wait_started_ms_, kStartupWaitMs)) {
        state_ = ClientState::ConfirmMode;
        pace_active_ = false;
    }
    if (pending_ && elapsed(now_ms, pending_started_ms_, config_.response_timeout_ms)) {
        failPending(now_ms);
    }
    if (state_ == ClientState::Running && have_response_ &&
        elapsed(now_ms, last_response_ms_, config_.link_timeout_ms)) {
        // This also detects a paused transmitter / stalled main-loop query path.
        // If a query timeout just invalidated the transport, do not count twice.
        if (snapshot_.transport_ok) {
            recordFault();
        }
        pending_ = false;
        state_ = ClientState::ConfirmMode;
        query_index_ = 0;
        have_response_ = false;
        pace_active_ = true;
        pace_started_ms_ = now_ms;
    }
}

bool RadarClient::poll(std::uint32_t now_ms, Frame& out) {
    tick(now_ms);
    if (!enabled_ || pending_ ||
        (pace_active_ && !elapsed(now_ms, pace_started_ms_, config_.query_interval_ms))) {
        return false;
    }

    Frame next{};
    if (state_ == ClientState::SetSleepMode) {
        next.control = 0x02;
        next.command = 0x08;
        next.length = 1;
        next.payload[0] = 0x02;
        // Official configWorkMode sends this write and waits ten seconds. It does
        // not require a write ACK; only a subsequent 02/A8 reply confirms success.
        state_ = ClientState::ModeSwitchWait;
        wait_started_ms_ = now_ms;
        pace_active_ = false;
        snapshot_.transport_ok = false;
        invalidateFields();
    } else if (state_ == ClientState::ConfirmMode) {
        next = query(0x02, 0xA8);
        pending_ = true;
    } else if (state_ == ClientState::Running) {
        next = query(kQueries[query_index_].control, kQueries[query_index_].command);
        pending_ = true;
    } else {
        return false;
    }

    if (pending_) {
        expected_control_ = next.control;
        expected_command_ = next.command;
        pending_started_ms_ = now_ms;
    }
    out = next;
    return true;
}

bool RadarClient::accept(const Frame& frame, std::uint32_t now_ms) {
    tick(now_ms);
    if (!enabled_ || !pending_ || frame.control != expected_control_ ||
        frame.command != expected_command_) {
        return false;
    }
    if (frame.length != 1) {
        failPending(now_ms);
        return false;
    }

    const std::uint8_t value = frame.payload[0];
    const bool mode_response = state_ == ClientState::ConfirmMode;
    if ((mode_response && value != 1 && value != 2) ||
        (!mode_response &&
         (((query_index_ == 0 || query_index_ == 2) && value > 1) ||
          (query_index_ == 1 && value > 2) ||
          (query_index_ == 5 && value > 3)))) {
        failPending(now_ms);
        return false;
    }

    pending_ = false;
    consecutive_failures_ = 0;
    pace_active_ = true;
    pace_started_ms_ = now_ms;
    last_response_ms_ = now_ms;
    have_response_ = true;
    snapshot_.transport_ok = true;

    if (mode_response) {
        if (value == 2) {
            state_ = ClientState::Running;
            query_index_ = 0;
        } else {
            // A valid reply in the wrong mode cannot supply sleep evidence.
            recordFault();
            state_ = ClientState::SetSleepMode;
        }
        return true;
    }

    switch (query_index_) {
    case 0:
        snapshot_.presence = {value == 1, now_ms, true};
        break;
    case 1:
        // Motion 0 = none, 1 = still, 2 = active. None is not evidence of stillness.
        snapshot_.low_motion = {value == 1, now_ms, value != 0};
        break;
    case 2:
        snapshot_.in_bed = {value == 1, now_ms, true};
        break;
    case 3:
        snapshot_.respiration_bpm = {value, now_ms, value != 0 && value != 0xFF};
        break;
    case 4:
        snapshot_.heart_bpm = {value, now_ms, value != 0 && value != 0xFF};
        break;
    case 5:
        // 3 = None is preserved for diagnostics but cannot be sleep evidence.
        snapshot_.module_sleep_stage = {value, now_ms, value != 3};
        break;
    default:
        break;
    }
    query_index_ = static_cast<std::uint8_t>((query_index_ + 1U) % kQueries.size());
    return true;
}

void RadarClient::notifyTransportFault(std::uint32_t now_ms) {
    initialize(now_ms);
    if (!enabled_) {
        return;
    }
    recordFault();
    pending_ = false;
    pace_active_ = true;
    pace_started_ms_ = now_ms;
    have_response_ = false;
    if (state_ == ClientState::Running) {
        state_ = ClientState::ConfirmMode;
        query_index_ = 0;
    }
}

}  // namespace sleep_radar
