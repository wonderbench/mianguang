#include "c1001_protocol.h"

#include <algorithm>

namespace sleep_radar {
namespace {

constexpr std::uint8_t kHeadFirst = 0x53;
constexpr std::uint8_t kHeadSecond = 0x59;
constexpr std::uint8_t kTailFirst = 0x54;
constexpr std::uint8_t kTailSecond = 0x43;

std::uint8_t checksum(const std::uint8_t* bytes, std::size_t count) {
    std::uint8_t sum = 0;
    for (std::size_t i = 0; i < count; ++i) {
        sum = static_cast<std::uint8_t>(sum + bytes[i]);
    }
    return sum;
}

}  // namespace

bool Parser::feed(std::uint8_t byte, std::uint32_t now_ms, Frame& out) {
    tick(now_ms);
    if (buffered_ == 0 && byte != kHeadFirst) {
        return false;
    }

    // Every incomplete accepted candidate is shorter than kMaxFrameSize.
    buffer_[buffered_++] = byte;
    last_byte_ms_ = now_ms;

    while (buffered_ != 0) {
        if (buffer_[0] != kHeadFirst) {
            discard(1);
            continue;
        }
        if (buffered_ < 2) {
            return false;
        }
        if (buffer_[1] != kHeadSecond) {
            // Retaining the suffix also handles overlapping 53 53 59 sync.
            discard(1);
            continue;
        }
        if (buffered_ < 6) {
            return false;
        }

        const auto length = static_cast<std::uint16_t>(
            (static_cast<std::uint16_t>(buffer_[4]) << 8U) | buffer_[5]);
        if (length > kMaxPayload) {
            ++stats_.length_errors;
            discard(1);
            continue;
        }

        const std::size_t checksum_index = 6U + length;
        if (buffered_ > checksum_index &&
            buffer_[checksum_index] != checksum(buffer_.data(), checksum_index)) {
            ++stats_.checksum_errors;
            discard(1);
            continue;
        }
        if (buffered_ > checksum_index + 1U &&
            buffer_[checksum_index + 1U] != kTailFirst) {
            ++stats_.framing_errors;
            discard(1);
            continue;
        }
        if (buffered_ > checksum_index + 2U &&
            buffer_[checksum_index + 2U] != kTailSecond) {
            ++stats_.framing_errors;
            discard(1);
            continue;
        }

        const std::size_t frame_size = length + kFrameOverhead;
        if (buffered_ < frame_size) {
            return false;
        }

        Frame completed{};
        completed.control = buffer_[2];
        completed.command = buffer_[3];
        completed.length = length;
        std::copy_n(buffer_.begin() + 6, length, completed.payload.begin());
        out = completed;
        discard(frame_size);
        ++stats_.frames;
        return true;
    }
    return false;
}

void Parser::tick(std::uint32_t now_ms) {
    // Unsigned subtraction is defined across the uint32_t millis rollover.
    if (buffered_ != 0 &&
        static_cast<std::uint32_t>(now_ms - last_byte_ms_) >= kInterByteTimeoutMs) {
        ++stats_.timeouts;
        reset();
    }
}

void Parser::reset() {
    buffered_ = 0;
    last_byte_ms_ = 0;
}

const ParserStats& Parser::stats() const {
    return stats_;
}

void Parser::discard(std::size_t count) {
    for (std::size_t i = count; i < buffered_; ++i) {
        buffer_[i - count] = buffer_[i];
    }
    buffered_ -= count;
}

std::size_t encodeFrame(const Frame& frame, std::uint8_t* out,
                        std::size_t capacity) {
    const std::size_t size = frame.length + kFrameOverhead;
    if (frame.length > kMaxPayload || out == nullptr || capacity < size) {
        return 0;
    }
    out[0] = kHeadFirst;
    out[1] = kHeadSecond;
    out[2] = frame.control;
    out[3] = frame.command;
    out[4] = static_cast<std::uint8_t>(frame.length >> 8U);
    out[5] = static_cast<std::uint8_t>(frame.length);
    std::copy_n(frame.payload.begin(), frame.length, out + 6);
    out[6U + frame.length] = checksum(out, 6U + frame.length);
    out[7U + frame.length] = kTailFirst;
    out[8U + frame.length] = kTailSecond;
    return size;
}

Frame query(std::uint8_t control, std::uint8_t command) {
    Frame frame{};
    frame.control = control;
    frame.command = command;
    frame.length = 1;
    frame.payload[0] = 0x0F;
    return frame;
}

}  // namespace sleep_radar
