#include "c1001_protocol.h"
#include "monitor_logic.h"
#include "radar_client.h"

#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>

namespace {

using sleep_radar::Frame;
using Values = std::array<std::uint8_t, 6>;
constexpr Values kInBed{{1, 1, 1, 16, 72, 0}};
// Still in the room, active, out of bed, no vital/stage information.
constexpr Values kOutOfBed{{1, 2, 0, 0, 0, 3}};
constexpr std::array<std::array<std::uint8_t, 2>, 6> kAddresses{{
    {{0x80, 0x81}}, {{0x80, 0x82}}, {{0x84, 0x81}},
    {{0x81, 0x82}}, {{0x85, 0x82}}, {{0x84, 0x82}}}};

struct Pipeline {
    sleep_radar::Parser receiver;
    sleep_radar::Parser simulated_sensor_receiver;
    sleep_radar::RadarClient client;
    sleep_core::TrendWindow trends;
    sleep_core::NightLight lamp;
    std::uint32_t now = 0;
    std::uint32_t seen_fault = 0;
    std::uint32_t seen_parser_errors = 0;
    std::uint32_t fault_deliveries = 0;
    std::uint32_t accepted_frames = 0;

    void consumeFault() {
        if (client.faultGeneration() != seen_fault) {
            seen_fault = client.faultGeneration();
            ++fault_deliveries;
            lamp.update(now, {});
        }
    }

    void checkParserFault() {
        const auto& stats = receiver.stats();
        const auto errors = stats.checksum_errors + stats.framing_errors +
                            stats.length_errors + stats.timeouts;
        if (errors != seen_parser_errors) {
            seen_parser_errors = errors;
            client.notifyTransportFault(now);
            consumeFault();
        }
    }

    sleep_core::NightInputs night() const {
        const auto quality = sleep_core::evaluate(client.snapshot(), now);
        return sleep_core::makeNightInputs(client.snapshot(), quality, true, true);
    }

    void updateConsumers() {
        consumeFault();
        const auto quality = sleep_core::evaluate(client.snapshot(), now);
        trends.update(client.snapshot(), quality, now);
        lamp.update(now, sleep_core::makeNightInputs(client.snapshot(), quality, true, true));
    }

    void tickTo(std::uint32_t next, bool update = true) {
        now = next;
        receiver.tick(now);
        checkParserFault();
        client.tick(now);
        consumeFault();
        if (update) {
            updateConsumers();
        }
    }

    Frame sendQuery(std::uint32_t when) {
        tickTo(when, false);
        Frame request{};
        assert(client.poll(now, request));
        consumeFault();

        // The outgoing request also traverses the wire codec before the mock
        // sensor chooses a response; there is no direct snapshot injection.
        std::array<std::uint8_t, sleep_radar::kMaxFrameSize> wire{};
        const auto size = sleep_radar::encodeFrame(request, wire.data(), wire.size());
        assert(size == 10);
        Frame decoded{};
        for (std::size_t i = 0; i < size; ++i) {
            assert(simulated_sensor_receiver.feed(wire[i], now, decoded) == (i + 1 == size));
        }
        assert(decoded.control == request.control && decoded.command == request.command);
        assert(decoded.length == 1 && decoded.payload[0] == 0x0F);
        return decoded;
    }

    unsigned receive(const Frame& response, bool broken_checksum = false) {
        std::array<std::uint8_t, sleep_radar::kMaxFrameSize> wire{};
        const auto size = sleep_radar::encodeFrame(response, wire.data(), wire.size());
        assert(size == 10);
        if (broken_checksum) {
            wire[6U + response.length] ^= 0x01;
        }
        unsigned accepted = 0;
        for (std::size_t i = 0; i < size; ++i) {
            Frame frame{};
            const auto complete = receiver.feed(wire[i], now, frame);
            // This order matches the firmware: notify on every parser error
            // before accepting a potentially recovered complete frame.
            checkParserFault();
            if (complete && client.accept(frame, now)) {
                ++accepted;
                ++accepted_frames;
            }
            consumeFault();
        }
        return accepted;
    }

    void respond(const Frame& request, std::uint8_t value, bool update = true) {
        ++now;
        Frame response = request;
        response.payload[0] = value;
        assert(receive(response) == 1);
        if (update) {
            updateConsumers();
        }
    }

    void start() {
        client.reset(0);
        client.setInstallationConfirmed(true);
        consumeFault();
        Frame untouched{};
        assert(!client.poll(9999, untouched));
        const auto mode = sendQuery(10000);
        assert(mode.control == 0x02 && mode.command == 0xA8);
        respond(mode, 2);
        assert(client.ready());
    }

    void cycle(const Values& values, bool update = true) {
        for (std::size_t i = 0; i < values.size(); ++i) {
            const auto request = sendQuery(now + 100);
            assert(request.control == kAddresses[i][0] && request.command == kAddresses[i][1]);
            respond(request, values[i], update);
        }
    }
};

void testInBedTrendsThenDarkDeparture() {
    Pipeline p;
    p.start();
    for (unsigned i = 0; i < 5; ++i) {
        p.cycle(kInBed);
    }
    assert(p.night().occupancy_valid && p.night().in_bed);
    assert(p.lamp.target() == 0);
    const auto trend = p.trends.summary();
    assert(trend.respiration.valid_buckets >= 3 && trend.heart.valid_buckets >= 3);
    assert(trend.respiration.median == 16 && trend.heart.median == 72);

    const auto before_departure = p.now;
    const auto generation = p.client.faultGeneration();
    for (unsigned i = 0; i < 8; ++i) {
        p.cycle(kOutOfBed);
        if (p.now - before_departure < 3000) {
            assert(p.lamp.target() == 0);
        }
    }
    assert(p.client.faultGeneration() == generation);
    assert(p.client.snapshot().transport_ok);
    assert(p.night().occupancy_valid && !p.night().in_bed);
    assert(!p.client.snapshot().module_sleep_stage.available);
    assert(p.client.snapshot().module_sleep_stage.value == 3);
    assert(!p.client.snapshot().respiration_bpm.available);
    assert(!p.client.snapshot().heart_bpm.available);
    assert(p.lamp.target() == 96 && p.lamp.output() == 96);
    assert(p.receiver.stats().frames == p.accepted_frames);
    assert(p.receiver.stats().checksum_errors == 0);
}

void testFaultThenGoodFramesCannotBridgeDeparture() {
    Pipeline p;
    p.start();
    for (unsigned i = 0; i < 5; ++i) {
        p.cycle(kInBed);
    }
    for (unsigned i = 0; i < 4; ++i) {
        p.cycle(kOutOfBed);
    }
    assert(p.lamp.target() == 0);  // An unconfirmed departure is pending.
    auto lamp_without_fault_delivery = p.lamp;
    const auto generation = p.client.faultGeneration();
    const auto fault_deliveries = p.fault_deliveries;

    const auto request = p.sendQuery(p.now + 100);
    Frame response = request;
    response.payload[0] = 1;
    ++p.now;
    assert(p.receive(response, true) == 0);
    // Same main-loop receive batch: corrupt reply, followed by a checksum-valid
    // late reply. The parser recovers, but the cancelled query cannot be revived.
    assert(p.receive(response) == 0);
    assert(p.receiver.stats().checksum_errors == 1);
    assert(p.client.faultGeneration() == generation + 1);
    assert(p.fault_deliveries == fault_deliveries + 1);
    assert(!p.client.snapshot().transport_ok && !p.client.pending());

    // Stress a batch that restores all data before consumers are next updated.
    // faultGeneration must already have sent {} to the lamp; looking only at
    // the now-healthy snapshot at batch end would miss the interrupted interval.
    const auto mode = p.sendQuery(p.now + 100);
    assert(mode.control == 0x02 && mode.command == 0xA8);
    p.respond(mode, 2, false);
    p.cycle(kOutOfBed, false);
    p.cycle(kOutOfBed, false);
    assert(p.client.snapshot().transport_ok && p.night().occupancy_valid);
    assert(!p.night().in_bed);
    lamp_without_fault_delivery.update(p.now, p.night());
    assert(lamp_without_fault_delivery.target() == 96);  // Demonstrates the hazard.
    p.updateConsumers();
    assert(p.lamp.target() == 0);  // Protected pipeline starts a fresh interval.

    const auto recovery_start = p.now;
    for (unsigned i = 0; i < 6; ++i) {
        p.cycle(kOutOfBed);
        if (p.now - recovery_start < 3000) {
            assert(p.lamp.target() == 0);
        }
    }
    assert(p.lamp.target() == 96);  // Fresh, continuous post-fault evidence works.
}

void testDroppedResponseInvalidatesOccupancyBeforeRecovery() {
    Pipeline p;
    p.start();
    p.cycle(kInBed);
    p.cycle(kOutOfBed);
    const auto request = p.sendQuery(p.now + 100);
    const auto generation = p.client.faultGeneration();
    p.tickTo(p.now + 500);
    assert(p.client.faultGeneration() == generation + 1);
    assert(!p.night().occupancy_valid && p.lamp.target() == 0);
    Frame late = request;
    late.payload[0] = 0;
    assert(p.receive(late) == 0);
    assert(!p.client.snapshot().presence.available);

    // One lost query retries its own address; valid incoming packets restore
    // only their own fields, never all cached availability at once.
    const auto retry = p.sendQuery(p.now + 100);
    assert(retry.control == 0x80 && retry.command == 0x81);
    p.respond(retry, 1);
    assert(p.client.snapshot().transport_ok);
    assert(!p.night().occupancy_valid);  // In-bed state still missing.
    const auto motion = p.sendQuery(p.now + 100);
    p.respond(motion, 2);
    const auto bed = p.sendQuery(p.now + 100);
    p.respond(bed, 0);
    assert(p.night().occupancy_valid && !p.night().in_bed);
    assert(p.lamp.target() == 0);
}

}  // namespace

int main() {
    testInBedTrendsThenDarkDeparture();
    testFaultThenGoodFramesCannotBridgeDeparture();
    testDroppedResponseInvalidatesOccupancyBeforeRecovery();
    std::cout << "Serial-to-light pipeline tests passed\n";
}
