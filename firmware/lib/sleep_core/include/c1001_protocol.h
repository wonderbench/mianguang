#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace sleep_radar {

constexpr std::size_t kMaxPayload = 64;
constexpr std::size_t kFrameOverhead = 9;
constexpr std::size_t kMaxFrameSize = kMaxPayload + kFrameOverhead;
// Host-side inter-byte timeout, not a sensor response deadline.
constexpr std::uint32_t kInterByteTimeoutMs = 100;

struct Frame {
    std::uint8_t control = 0;
    std::uint8_t command = 0;
    std::uint16_t length = 0;
    std::array<std::uint8_t, kMaxPayload> payload{};
};

struct ParserStats {
    std::uint32_t frames = 0;
    std::uint32_t checksum_errors = 0;
    std::uint32_t framing_errors = 0;
    std::uint32_t length_errors = 0;
    std::uint32_t timeouts = 0;
};

class Parser {
public:
    // out is unchanged unless a complete, validated frame is returned.
    bool feed(std::uint8_t byte, std::uint32_t now_ms, Frame& out);
    void tick(std::uint32_t now_ms);
    // Discards a partial frame; diagnostic counters are retained.
    void reset();
    const ParserStats& stats() const;

private:
    void discard(std::size_t count);

    std::array<std::uint8_t, kMaxFrameSize> buffer_{};
    std::size_t buffered_ = 0;
    std::uint32_t last_byte_ms_ = 0;
    ParserStats stats_{};
};

// Returns the encoded byte count, or zero without writing on invalid input.
std::size_t encodeFrame(const Frame& frame, std::uint8_t* out,
                        std::size_t capacity);
// Uses exactly the requested command; no implicit high-bit transformation.
Frame query(std::uint8_t control, std::uint8_t command);

}  // namespace sleep_radar
