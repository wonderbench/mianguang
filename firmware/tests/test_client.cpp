#include "radar_client.h"

#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <limits>

using sleep_radar::ClientConfig;
using sleep_radar::ClientState;
using sleep_radar::Frame;
using sleep_radar::RadarClient;

namespace {

constexpr std::array<std::array<std::uint8_t, 2>, 6> kAddresses{{
    {{0x80, 0x81}}, {{0x80, 0x82}}, {{0x84, 0x81}},
    {{0x81, 0x82}}, {{0x85, 0x82}}, {{0x84, 0x82}}}};
constexpr std::array<std::uint8_t, 6> kValidValues{{1, 1, 1, 16, 72, 0}};

ClientConfig config() {
    ClientConfig result;
    result.response_timeout_ms = 50;
    result.query_interval_ms = 10;
    result.link_timeout_ms = 2000;
    return result;
}

Frame reply(const Frame& request, std::uint8_t value) {
    Frame response = request;
    response.payload[0] = value;
    return response;
}

void checkQuery(const Frame& request, std::uint8_t control, std::uint8_t command) {
    assert(request.control == control && request.command == command);
    assert(request.length == 1 && request.payload[0] == 0x0F);
}

void noFields(const RadarClient& client) {
    const auto& sample = client.snapshot();
    assert(!sample.presence.available && !sample.in_bed.available);
    assert(!sample.low_motion.available && !sample.respiration_bpm.available);
    assert(!sample.heart_bpm.available && !sample.module_sleep_stage.available);
}

std::uint32_t start(RadarClient& client, std::uint32_t base = 0) {
    Frame request{};
    request.command = 0xEE;
    client.reset(base);
    client.setInstallationConfirmed(true);
    assert(!client.poll(base, request));
    assert(!client.poll(base + RadarClient::kStartupWaitMs - 1, request));
    assert(request.command == 0xEE);  // poll(false) preserves the caller's frame.
    const auto now = base + RadarClient::kStartupWaitMs;
    assert(client.poll(now, request));
    checkQuery(request, 0x02, 0xA8);
    assert(client.pending() && !client.ready());
    assert(client.accept(reply(request, 2), now + 1));
    assert(client.ready() && !client.pending() && client.snapshot().transport_ok);
    noFields(client);
    return now + 1;
}

Frame nextQuery(RadarClient& client, std::uint32_t& now, std::size_t index) {
    now += config().query_interval_ms;
    Frame request{};
    assert(client.poll(now, request));
    checkQuery(request, kAddresses[index][0], kAddresses[index][1]);
    assert(client.pending());
    return request;
}

void cycle(RadarClient& client, std::uint32_t& now,
           const std::array<std::uint8_t, 6>& values = kValidValues) {
    for (std::size_t i = 0; i < values.size(); ++i) {
        const auto request = nextQuery(client, now, i);
        assert(client.accept(reply(request, values[i]), ++now));
    }
}

void testStartupAndFieldCycle() {
    RadarClient client(config());
    assert(client.enabled() && !client.snapshot().installation_confirmed);
    auto now = start(client);
    const auto generation = client.faultGeneration();
    cycle(client, now);
    const auto& sample = client.snapshot();
    assert(sample.transport_ok && sample.installation_confirmed);
    assert(sample.presence.available && sample.presence.value);
    assert(sample.in_bed.available && sample.in_bed.value);
    assert(sample.low_motion.available && sample.low_motion.value);
    assert(sample.respiration_bpm.available && sample.respiration_bpm.value == 16);
    assert(sample.heart_bpm.available && sample.heart_bpm.value == 72);
    assert(sample.module_sleep_stage.available && sample.module_sleep_stage.value == 0);
    assert(sample.module_sleep_stage.updated_ms == now);
    assert(sample.presence.updated_ms < sample.heart_bpm.updated_ms);
    assert(client.faultGeneration() == generation);
    const auto quality = sleep_core::evaluate(sample, now);
    assert(quality.presence.valid && quality.in_bed.valid);
    assert(quality.respiration_bpm.valid && quality.heart_bpm.valid);
    nextQuery(client, now, 0);  // Cyclic schedule returns to presence.
}

void testModeSwitchWaitAndConfirmation() {
    RadarClient client(config());
    client.reset(0);
    Frame request{};
    assert(client.poll(10000, request));
    const auto mode_query = request;
    assert(client.accept(reply(request, 1), 10001));
    assert(client.state() == ClientState::SetSleepMode && !client.ready());
    assert(!client.snapshot().transport_ok);
    assert(!client.poll(10010, request));
    assert(client.poll(10011, request));
    assert(request.control == 0x02 && request.command == 0x08);
    assert(request.length == 1 && request.payload[0] == 2);
    assert(!client.pending());  // A write ACK is deliberately not required.
    assert(!client.accept(reply(request, 2), 10012));
    assert(!client.accept(reply(mode_query, 2), 10013));
    assert(!client.poll(20010, request));
    assert(client.poll(20011, request));
    checkQuery(request, 0x02, 0xA8);
    assert(client.accept(reply(request, 1), 20012));
    assert(client.poll(20022, request));  // Still wrong: repeat write + wait.
    assert(request.command == 0x08 && request.payload[0] == 2);
    assert(!client.poll(30021, request));
    assert(client.poll(30022, request));
    checkQuery(request, 0x02, 0xA8);
    assert(client.accept(reply(request, 2), 30023));
    assert(client.ready());
}

void testExpectedReplyAndNoConcurrentQuery() {
    RadarClient client(config());
    auto now = start(client);
    auto request = nextQuery(client, now, 0);
    const auto generation = client.faultGeneration();
    Frame ignored{};
    assert(!client.poll(now, ignored));
    assert(!client.poll(now + 1, ignored));
    auto wrong = reply(request, 1);
    wrong.control = 0x84;
    assert(!client.accept(wrong, now + 1));
    wrong = reply(request, 1);
    wrong.command = 0x01;  // No query-command high-bit clearing.
    assert(!client.accept(wrong, now + 2));
    assert(client.pending() && !client.snapshot().presence.available);
    assert(client.faultGeneration() == generation);
    assert(client.accept(reply(request, 1), now + 3));
    assert(!client.accept(reply(request, 0), now + 4));  // Duplicate is unsolicited.
    assert(client.snapshot().presence.value);
    assert(client.snapshot().presence.updated_ms == now + 3);
    now += 3;
    request = nextQuery(client, now, 1);
    wrong = reply(request, 0);
    wrong.control = 0x80;
    wrong.command = 0x81;
    assert(!client.accept(wrong, now + 1));
    assert(client.snapshot().presence.value);
}

void testTimeoutRetryAndReHandshake() {
    RadarClient client(config());
    auto now = start(client);
    cycle(client, now);
    const auto old_presence = client.snapshot().presence.value;
    auto request = nextQuery(client, now, 0);
    auto generation = client.faultGeneration();
    client.tick(now + 49);
    assert(client.pending() && client.snapshot().transport_ok);
    client.tick(now + 50);
    assert(!client.pending() && !client.snapshot().transport_ok);
    assert(client.faultGeneration() == generation + 1);
    noFields(client);
    assert(client.snapshot().presence.value == old_presence);  // Not a fake false.
    assert(!client.accept(reply(request, 0), now + 51));
    now += 50;
    for (unsigned failure = 2; failure <= 3; ++failure) {
        request = nextQuery(client, now, 0);
        client.tick(now + 50);
        now += 50;
        assert(!client.snapshot().transport_ok && !client.pending());
        assert(client.faultGeneration() == generation + failure);
    }
    assert(!client.ready() && client.state() == ClientState::ConfirmMode);
    now += 10;
    assert(client.poll(now, request));
    checkQuery(request, 0x02, 0xA8);
    client.tick(now + 50);  // Mode query also retries after repeated packet loss.
    now += 60;
    assert(client.poll(now, request));
    checkQuery(request, 0x02, 0xA8);
    assert(client.accept(reply(request, 2), ++now));
    assert(client.snapshot().transport_ok && client.ready());
    noFields(client);  // A mode reply never resurrects old field availability.
    cycle(client, now);
    assert(client.snapshot().presence.available && client.snapshot().heart_bpm.available);
}

void testExactDeadlineAndLinkLoss() {
    RadarClient client(config());
    auto now = start(client);
    const auto request = nextQuery(client, now, 0);
    const auto generation = client.faultGeneration();
    // accept() must check time itself, even if the application omitted tick().
    assert(!client.accept(reply(request, 1), now + 50));
    assert(client.faultGeneration() == generation + 1);
    assert(!client.snapshot().presence.available);

    now = start(client, 20000);
    cycle(client, now);
    const auto before_loss = client.faultGeneration();
    client.tick(now + 1999);
    assert(client.snapshot().transport_ok);
    client.tick(now + 2000);
    assert(!client.snapshot().transport_ok && !client.ready());
    noFields(client);
    assert(client.faultGeneration() == before_loss + 1);
    client.tick(now + 2010);
    assert(client.faultGeneration() == before_loss + 1);
    Frame mode{};
    assert(client.poll(now + 2010, mode));
    checkQuery(mode, 0x02, 0xA8);
}

void testMalformedRepliesAndEnumValidation() {
    for (std::uint16_t length : {0, 2, 65, 65535}) {
        RadarClient client(config());
        auto now = start(client);
        const auto request = nextQuery(client, now, 0);
        auto malformed = reply(request, 1);
        malformed.length = length;
        assert(!client.accept(malformed, ++now));
        assert(!client.pending() && !client.snapshot().transport_ok);
        noFields(client);
    }
    for (std::size_t index : {0U, 1U, 2U, 5U}) {
        const std::uint8_t first_invalid = index == 1 ? 3 : (index == 5 ? 4 : 2);
        for (auto invalid : {first_invalid, std::uint8_t{255}}) {
            RadarClient client(config());
            auto now = start(client);
            Frame request{};
            for (std::size_t i = 0; i <= index; ++i) {
                request = nextQuery(client, now, i);
                if (i != index) {
                    assert(client.accept(reply(request, kValidValues[i]), ++now));
                }
            }
            const auto generation = client.faultGeneration();
            assert(!client.accept(reply(request, invalid), ++now));
            assert(client.faultGeneration() == generation + 1);
            assert(!client.snapshot().transport_ok);
            noFields(client);
        }
    }
    for (auto invalid_mode : {0, 3, 255}) {
        RadarClient client(config());
        client.reset(0);
        Frame request{};
        assert(client.poll(10000, request));
        assert(!client.accept(reply(request, static_cast<std::uint8_t>(invalid_mode)), 10001));
        assert(!client.ready() && !client.snapshot().transport_ok);
        assert(client.poll(10011, request));
        checkQuery(request, 0x02, 0xA8);  // Do not write a mode from malformed input.
    }
}

void testKnownUnavailableMeasurementsAndStages() {
    for (const auto vital : {std::uint8_t{0}, std::uint8_t{255}}) {
        RadarClient client(config());
        auto now = start(client);
        const auto generation = client.faultGeneration();
        cycle(client, now, {{0, 0, 0, vital, vital, 3}});
        const auto& sample = client.snapshot();
        assert(sample.transport_ok);
        assert(sample.presence.available && !sample.presence.value);
        assert(sample.in_bed.available && !sample.in_bed.value);
        assert(!sample.low_motion.available);
        assert(!sample.respiration_bpm.available && sample.respiration_bpm.value == vital);
        assert(!sample.heart_bpm.available && sample.heart_bpm.value == vital);
        assert(!sample.module_sleep_stage.available && sample.module_sleep_stage.value == 3);
        assert(client.faultGeneration() == generation);
        const auto quality = sleep_core::evaluate(sample, now);
        assert(quality.presence.valid && quality.in_bed.valid);
        assert(!quality.module_sleep_stage.valid);
    }
    for (std::uint8_t stage = 0; stage <= 3; ++stage) {
        RadarClient client(config());
        auto now = start(client);
        auto values = kValidValues;
        values[5] = stage;
        cycle(client, now, values);
        assert(client.snapshot().module_sleep_stage.value == stage);
        assert(client.snapshot().module_sleep_stage.available == (stage != 3));
    }
    RadarClient client(config());
    auto now = start(client);
    cycle(client, now, {{1, 2, 1, 1, 254, 2}});
    assert(client.snapshot().low_motion.available && !client.snapshot().low_motion.value);
    assert(client.snapshot().respiration_bpm.value == 1);
    assert(client.snapshot().heart_bpm.value == 254);
    const auto quality = sleep_core::evaluate(client.snapshot(), now);
    assert(quality.respiration_bpm.error == sleep_core::QualityError::OutOfRange);
    assert(quality.heart_bpm.error == sleep_core::QualityError::OutOfRange);
}

void testDisableResetAndExplicitFault() {
    auto disabled_config = config();
    disabled_config.enabled = false;
    RadarClient disabled(disabled_config);
    Frame request{};
    assert(!disabled.poll(0, request) && !disabled.poll(20000, request));
    assert(!disabled.enabled() && disabled.state() == ClientState::Disabled);
    disabled.setEnabled(true, 30000);
    assert(!disabled.poll(39999, request));
    assert(disabled.poll(40000, request));
    checkQuery(request, 0x02, 0xA8);

    RadarClient client(config());
    auto now = start(client);
    cycle(client, now);
    const auto query = nextQuery(client, now, 0);
    auto generation = client.faultGeneration();
    client.notifyTransportFault(++now);
    assert(client.faultGeneration() == generation + 1);
    assert(!client.snapshot().transport_ok && !client.pending() && !client.ready());
    noFields(client);
    assert(!client.accept(reply(query, 0), ++now));
    client.setEnabled(false, now);
    generation = client.faultGeneration();
    assert(!client.poll(now + 20000, request));
    client.setEnabled(false, now + 20000);
    assert(client.faultGeneration() == generation);  // Idempotent setting.
    client.reset(now + 20000);
    assert(!client.enabled() && !client.pending());
    assert(client.snapshot().installation_confirmed);
    client.setEnabled(true, now + 30000);
    assert(!client.poll(now + 39999, request));
    assert(client.poll(now + 40000, request));
    checkQuery(request, 0x02, 0xA8);
    client.setInstallationConfirmed(false);
    assert(!client.snapshot().installation_confirmed);
    noFields(client);
}

void testRolloverAndImplicitStart() {
    RadarClient client(config());
    const auto maximum = std::numeric_limits<std::uint32_t>::max();
    auto now = start(client, maximum - 10050U);
    const auto request = nextQuery(client, now, 0);
    assert(now > maximum - 50U);
    const auto generation = client.faultGeneration();
    client.tick(now + 49U);
    assert(client.pending());
    client.tick(now + 50U);
    assert(!client.pending() && client.faultGeneration() == generation + 1);
    assert(!client.accept(reply(request, 1), now + 51U));
    now += 50U;
    const auto retried = nextQuery(client, now, 0);
    assert(client.accept(reply(retried, 1), ++now));
    assert(client.snapshot().presence.available);

    RadarClient late_started(config());
    Frame mode{};
    // Without an explicit reset, the ten-second wait begins at the first call.
    assert(!late_started.poll(maximum - 5000U, mode));
    assert(!late_started.poll(4998U, mode));
    assert(late_started.poll(4999U, mode));
    checkQuery(mode, 0x02, 0xA8);
}

}  // namespace

int main() {
    static_assert(sizeof(RadarClient) < 512, "Radar client remains fixed and small");
    testStartupAndFieldCycle();
    testModeSwitchWaitAndConfirmation();
    testExpectedReplyAndNoConcurrentQuery();
    testTimeoutRetryAndReHandshake();
    testExactDeadlineAndLinkLoss();
    testMalformedRepliesAndEnumValidation();
    testKnownUnavailableMeasurementsAndStages();
    testDisableResetAndExplicitFault();
    testRolloverAndImplicitStart();
    std::cout << "RadarClient tests passed\n";
}
