/*
 * SPDX-FileCopyrightText: The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
#define LOG_TAG "Exynos9810OutputEqualizer"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <limits>
#include <new>
#include <unistd.h>

#include <hardware/audio_effect.h>
#include <system/audio.h>

#include "OutputEqualizerInterface.h"

namespace {
using namespace output_equalizer;
constexpr effect_uuid_t kType = {
    0x32614e50, 0x20f4, 0x4e2c, 0x949b, {0x4f, 0x77, 0x07, 0x47, 0xb1, 0x01}};
constexpr effect_uuid_t kImplementation = {
    0x32614e50, 0x20f4, 0x4e2c, 0x949b, {0x4f, 0x77, 0x07, 0x47, 0xb1, 0x02}};
constexpr effect_descriptor_t kDescriptor = {
    kType, kImplementation, EFFECT_CONTROL_API_VERSION,
    EFFECT_FLAG_TYPE_INSERT | EFFECT_FLAG_INSERT_ANY | EFFECT_FLAG_DEVICE_IND |
        EFFECT_FLAG_AUDIO_MODE_IND | EFFECT_FLAG_NOT_ELIGIBLE_SUSPEND,
    100, 4, "Exynos9810 output equalizer", "LineageOS",
};
constexpr uint32_t kRequiredConfig = EFFECT_CONFIG_SMP_RATE | EFFECT_CONFIG_CHANNELS |
                                     EFFECT_CONFIG_FORMAT | EFFECT_CONFIG_ACC_MODE;
constexpr double kPi = 3.14159265358979323846;
constexpr double kQ = 1.0;

struct Coefficients {
    double b0 = 1.0, b1 = 0.0, b2 = 0.0, a1 = 0.0, a2 = 0.0;
    bool operator==(const Coefficients& other) const {
        return b0 == other.b0 && b1 == other.b1 && b2 == other.b2 &&
               a1 == other.a1 && a2 == other.a2;
    }
};
struct FilterSettings {
    std::array<Coefficients, kBandCount> bands{};
    double preamp = 1.0;
    bool flat = true;
    bool operator==(const FilterSettings& other) const {
        return bands == other.bands && preamp == other.preamp && flat == other.flat;
    }
};
struct FilterState { double z1 = 0.0, z2 = 0.0; };
struct FilterChain {
    FilterSettings settings{};
    std::array<std::array<FilterState, kBandCount>, 2> channels{};

    double process(double input, size_t channel) {
        if (settings.flat) return input;
        double sample = input * settings.preamp;
        for (size_t i = 0; i < kBandCount; ++i) {
            const auto& c = settings.bands[i];
            auto& state = channels[channel][i];
            const double output = c.b0 * sample + state.z1;
            state.z1 = c.b1 * sample - c.a1 * output + state.z2;
            state.z2 = c.b2 * sample - c.a2 * output;
            // Flush the inaudible tail to avoid denormal arithmetic on ARM.
            if (std::abs(state.z1) < 1.0e-30) state.z1 = 0.0;
            if (std::abs(state.z2) < 1.0e-30) state.z2 = 0.0;
            sample = output;
        }
        return sample;
    }
};

double responseGain(const FilterSettings& settings, double omega) {
    const double cosine = std::cos(omega), sine = std::sin(omega);
    const double cosine2 = std::cos(2 * omega), sine2 = std::sin(2 * omega);
    double power = 1.0;
    for (const auto& c : settings.bands) {
        const double nr = c.b0 + c.b1 * cosine + c.b2 * cosine2;
        const double ni = c.b1 * sine + c.b2 * sine2;
        const double dr = 1.0 + c.a1 * cosine + c.a2 * cosine2;
        const double di = c.a1 * sine + c.a2 * sine2;
        power *= (nr * nr + ni * ni) / (dr * dr + di * di);
    }
    return std::sqrt(power);
}
double headroom(const FilterSettings& settings, uint32_t sampleRate) {
    double peak = 1.0;
    const double nyquist = sampleRate / 2.0;
    constexpr int kGridPoints = 256;
    for (int i = 0; i <= kGridPoints; ++i) {
        const double fraction = static_cast<double>(i) / kGridPoints;
        peak = std::max(peak, responseGain(settings, kPi * fraction));
        const double frequency = 10.0 * std::pow(nyquist / 10.0, fraction);
        peak = std::max(peak, responseGain(settings, 2 * kPi * frequency / sampleRate));
    }
    for (int32_t frequency : kFrequenciesHz) {
        if (frequency < nyquist) {
            peak = std::max(peak, responseGain(settings, 2 * kPi * frequency / sampleRate));
        }
    }
    // One dB beyond the estimated response reduces inter-grid and transient overshoot.
    return std::pow(10.0, -1.0 / 20.0) / peak;
}
FilterSettings makeFilters(const ProfileSettings& profile, uint32_t sampleRate) {
    FilterSettings result;
    if (profile.enabled == 0) return result;
    bool positiveGain = false;
    for (size_t i = 0; i < kBandCount; ++i) {
        const int gain = profile.gains[i];
        const double frequency = kFrequenciesHz[i];
        if (gain == 0 || frequency >= sampleRate / 2.0) continue;
        result.flat = false;
        positiveGain |= gain > 0;
        // RBJ peaking-EQ coefficients; unavailable bands remain unity.
        const double amplitude = std::pow(10.0, gain / 40.0);
        const double omega = 2.0 * kPi * frequency / sampleRate;
        const double alpha = std::sin(omega) / (2.0 * kQ);
        const double cosine = std::cos(omega);
        const double a0 = 1.0 + alpha / amplitude;
        result.bands[i] = {(1.0 + alpha * amplitude) / a0, -2.0 * cosine / a0,
                          (1.0 - alpha * amplitude) / a0, -2.0 * cosine / a0,
                          (1.0 - alpha / amplitude) / a0};
    }
    if (positiveGain) result.preamp = headroom(result, sampleRate);
    return result;
}

enum class State { Initialized, Active, Draining };
struct OutputEqualizerEffect {
    const effect_interface_s* interface;
    int32_t session = 0;
    State state = State::Initialized;
    effect_config_t config{};
    bool configured = false;
    uint32_t device = AUDIO_DEVICE_NONE;
    uint32_t audioMode = AUDIO_MODE_NORMAL;
    std::array<ProfileSettings, kProfileCount> profiles{};
    std::array<FilterChain, 2> chains{};
    FilterSettings desired{};
    size_t current = 0;
    uint32_t transitionFrames = 960;
    uint32_t fadeRemaining = 0;

    int32_t profile() const {
        if (audioMode != AUDIO_MODE_NORMAL) return -1;
        switch (device) {
            case AUDIO_DEVICE_OUT_SPEAKER:
            case AUDIO_DEVICE_OUT_SPEAKER_SAFE: return kSpeaker;
            case AUDIO_DEVICE_OUT_WIRED_HEADSET:
            case AUDIO_DEVICE_OUT_WIRED_HEADPHONE: return kHeadphones;
            case AUDIO_DEVICE_OUT_USB_ACCESSORY:
            case AUDIO_DEVICE_OUT_USB_DEVICE:
            case AUDIO_DEVICE_OUT_USB_HEADSET: return kUsb;
            default: return -1;
        }
    }
    bool processing() const {
        const int32_t selected = profile();
        return configured && state == State::Active && selected >= 0 &&
               profiles[selected].enabled != 0;
    }
    size_t channelCount() const {
        return config.inputCfg.channels == AUDIO_CHANNEL_OUT_MONO ? 1 : 2;
    }
    size_t sampleSize() const {
        return config.inputCfg.format == AUDIO_FORMAT_PCM_FLOAT ? sizeof(float) : sizeof(int16_t);
    }
    void clear() {
        chains = {};
        desired = {};
        current = 0;
        fadeRemaining = 0;
    }
    void refresh() {
        const int32_t selected = profile();
        desired = state == State::Active && selected >= 0
            ? makeFilters(profiles[selected], config.inputCfg.samplingRate) : FilterSettings{};
    }
    void beginTransition() {
        if (fadeRemaining != 0 || chains[current].settings == desired) return;
        chains[1 - current] = {};
        chains[1 - current].settings = desired;
        fadeRemaining = transitionFrames;
    }
    double sample(double input, size_t channel) {
        if (!std::isfinite(input)) input = 0.0;
        const double oldSample = chains[current].process(input, channel);
        if (fadeRemaining == 0) return oldSample;
        const double newSample = chains[1 - current].process(input, channel);
        const double mix = (transitionFrames - fadeRemaining + 1.0) / transitionFrames;
        return oldSample + (newSample - oldSample) * mix;
    }
};
static_assert(offsetof(OutputEqualizerEffect, interface) == 0);

template <typename T> T readValue(const void* data) {
    T value;
    std::memcpy(&value, data, sizeof(value));
    return value;
}
bool validReply(const uint32_t* size, const void* data, uint32_t required) {
    return size != nullptr && data != nullptr && *size >= required;
}
int statusReply(uint32_t* size, void* data, int status) {
    if (!validReply(size, data, sizeof(int32_t))) return -EINVAL;
    std::memcpy(data, &status, sizeof(status));
    *size = sizeof(status);
    return 0;
}

int configure(OutputEqualizerEffect* effect, const effect_config_t& config) {
    const auto& in = config.inputCfg;
    const auto& out = config.outputCfg;
    if ((in.mask & kRequiredConfig) != kRequiredConfig ||
        (out.mask & kRequiredConfig) != kRequiredConfig ||
        in.samplingRate < 8000 || in.samplingRate > 192000 ||
        out.samplingRate != in.samplingRate ||
        (in.channels != AUDIO_CHANNEL_OUT_MONO && in.channels != AUDIO_CHANNEL_OUT_STEREO) ||
        out.channels != in.channels || in.format != out.format ||
        (in.format != AUDIO_FORMAT_PCM_16_BIT && in.format != AUDIO_FORMAT_PCM_FLOAT) ||
        in.accessMode != EFFECT_BUFFER_ACCESS_READ ||
        (out.accessMode != EFFECT_BUFFER_ACCESS_WRITE &&
         out.accessMode != EFFECT_BUFFER_ACCESS_ACCUMULATE)) return -EINVAL;
    effect->config = config;
    effect->configured = true;
    effect->transitionFrames = std::clamp(in.samplingRate / 50, 160u, 4096u);
    effect->clear();
    effect->refresh();
    return 0;
}
int initialize(OutputEqualizerEffect* effect) {
    effect->state = State::Initialized;
    effect->device = AUDIO_DEVICE_NONE;
    effect->audioMode = AUDIO_MODE_NORMAL;
    effect->profiles = {};
    effect_config_t config{};
    config.inputCfg.samplingRate = config.outputCfg.samplingRate = 48000;
    config.inputCfg.channels = config.outputCfg.channels = AUDIO_CHANNEL_OUT_STEREO;
    config.inputCfg.format = config.outputCfg.format = AUDIO_FORMAT_PCM_FLOAT;
    config.inputCfg.accessMode = EFFECT_BUFFER_ACCESS_READ;
    config.outputCfg.accessMode = EFFECT_BUFFER_ACCESS_WRITE;
    config.inputCfg.mask = config.outputCfg.mask = kRequiredConfig;
    return configure(effect, config);
}

int process(effect_handle_t self, audio_buffer_t* input, audio_buffer_t* output) {
    auto* effect = reinterpret_cast<OutputEqualizerEffect*>(self);
    if (effect == nullptr || input == nullptr || output == nullptr || input->raw == nullptr ||
        output->raw == nullptr || input->frameCount == 0 ||
        input->frameCount != output->frameCount || !effect->configured ||
        input->frameCount > std::numeric_limits<size_t>::max() /
            (effect->channelCount() * effect->sampleSize())) return -EINVAL;
    if (effect->state == State::Initialized) return -ENODATA;
    const size_t channels = effect->channelCount();
    const bool floating = effect->config.inputCfg.format == AUDIO_FORMAT_PCM_FLOAT;
    const bool accumulate = effect->config.outputCfg.accessMode == EFFECT_BUFFER_ACCESS_ACCUMULATE;
    for (size_t frame = 0; frame < input->frameCount; ++frame) {
        effect->beginTransition();
        for (size_t channel = 0; channel < channels; ++channel) {
            const size_t index = frame * channels + channel;
            const double source = floating ? static_cast<const float*>(input->raw)[index]
                : static_cast<const int16_t*>(input->raw)[index] / 32768.0;
            const double sample = effect->sample(source, channel);
            if (floating) {
                auto* destination = static_cast<float*>(output->raw);
                destination[index] = accumulate ? destination[index] + sample : sample;
            } else {
                auto* destination = static_cast<int16_t*>(output->raw);
                double value = sample * 32768.0;
                if (accumulate) value += destination[index];
                destination[index] = static_cast<int16_t>(
                    std::clamp(std::round(value), -32768.0, 32767.0));
            }
        }
        if (effect->fadeRemaining != 0 && --effect->fadeRemaining == 0) {
            effect->current = 1 - effect->current;
        }
    }
    if (effect->state == State::Draining && effect->fadeRemaining == 0 &&
        effect->chains[effect->current].settings == effect->desired) {
        effect->state = State::Initialized;
    }
    return 0;
}

int setParameter(OutputEqualizerEffect* effect, uint32_t size, const void* data) {
    constexpr uint32_t payloadSize = sizeof(effect_param_t) + 8 * sizeof(int32_t);
    if (data == nullptr || size != payloadSize) return -EINVAL;
    const auto parameter = readValue<effect_param_t>(data);
    if (parameter.psize != 2 * sizeof(int32_t) ||
        parameter.vsize != sizeof(ProfileSettings)) return -EINVAL;
    const auto* payload = static_cast<const uint8_t*>(data) + sizeof(effect_param_t);
    const int32_t id = readValue<int32_t>(payload);
    const int32_t profile = readValue<int32_t>(payload + sizeof(int32_t));
    if (id != kProfile || profile < 0 || profile >= kProfileCount) return -EINVAL;
    const auto settings = readValue<ProfileSettings>(payload + 2 * sizeof(int32_t));
    if (settings.enabled != 0 && settings.enabled != 1) return -EINVAL;
    for (const int gain : settings.gains) {
        if (gain < -kGainLimitDb || gain > kGainLimitDb) return -EINVAL;
    }
    const auto& current = effect->profiles[profile];
    if (current.enabled == settings.enabled && current.gains == settings.gains) return 0;
    effect->profiles[profile] = settings;
    if (effect->profile() == profile) effect->refresh();
    return 0;
}
int getParameter(OutputEqualizerEffect* effect, uint32_t size, const void* data,
                 uint32_t* replySize, void* replyData) {
    if (data == nullptr || size < sizeof(effect_param_t) + sizeof(int32_t)) return -EINVAL;
    const auto parameter = readValue<effect_param_t>(data);
    const auto* payload = static_cast<const uint8_t*>(data) + sizeof(effect_param_t);
    const int32_t id = readValue<int32_t>(payload);
    std::array<int32_t, 6> values{};
    uint32_t valueSize;
    if (id == kProfile) {
        if (parameter.psize != 2 * sizeof(int32_t) ||
            parameter.vsize != sizeof(ProfileSettings) ||
            size != sizeof(effect_param_t) + 2 * sizeof(int32_t)) return -EINVAL;
        const int32_t profile = readValue<int32_t>(payload + sizeof(int32_t));
        if (profile < 0 || profile >= kProfileCount) return -EINVAL;
        std::memcpy(values.data(), &effect->profiles[profile], sizeof(ProfileSettings));
        valueSize = sizeof(ProfileSettings);
    } else if (id == kStatus) {
        if (parameter.psize != sizeof(int32_t) || parameter.vsize != 4 * sizeof(int32_t) ||
            size != sizeof(effect_param_t) + sizeof(int32_t)) return -EINVAL;
        values[0] = effect->profile();
        values[1] = effect->configured ? effect->config.inputCfg.samplingRate : 0;
        values[2] = effect->audioMode;
        values[3] = effect->processing();
        valueSize = 4 * sizeof(int32_t);
    } else {
        return -EINVAL;
    }
    const uint32_t resultSize = sizeof(effect_param_t) + parameter.psize + valueSize;
    if (!validReply(replySize, replyData, resultSize)) return -EINVAL;
    const effect_param_t reply{0, parameter.psize, valueSize};
    std::memcpy(replyData, &reply, sizeof(reply));
    auto* destination = static_cast<uint8_t*>(replyData) + sizeof(reply);
    std::memmove(destination, payload, parameter.psize);
    std::memcpy(destination + parameter.psize, values.data(), valueSize);
    *replySize = resultSize;
    return 0;
}

int command(effect_handle_t self, uint32_t code, uint32_t size, void* data,
            uint32_t* replySize, void* replyData) {
    auto* effect = reinterpret_cast<OutputEqualizerEffect*>(self);
    if (effect == nullptr) return -EINVAL;
    switch (code) {
        case EFFECT_CMD_INIT:
            if (size != 0 || !validReply(replySize, replyData, sizeof(int32_t))) return -EINVAL;
            return statusReply(replySize, replyData, initialize(effect));
        case EFFECT_CMD_SET_CONFIG:
            if (data == nullptr || size != sizeof(effect_config_t) ||
                !validReply(replySize, replyData, sizeof(int32_t))) return -EINVAL;
            return statusReply(replySize, replyData, configure(effect, readValue<effect_config_t>(data)));
        case EFFECT_CMD_GET_CONFIG:
            if (size != 0 || !validReply(replySize, replyData, sizeof(effect_config_t))) return -EINVAL;
            std::memcpy(replyData, &effect->config, sizeof(effect->config));
            *replySize = sizeof(effect->config);
            return 0;
        case EFFECT_CMD_RESET:
            if (size != 0) return -EINVAL;
            effect->clear();
            effect->refresh();
            return 0;
        case EFFECT_CMD_ENABLE:
            if (size != 0 || !validReply(replySize, replyData, sizeof(int32_t))) return -EINVAL;
            if (effect->state == State::Active) return statusReply(replySize, replyData, -ENOSYS);
            effect->state = State::Active;
            effect->refresh();
            return statusReply(replySize, replyData, 0);
        case EFFECT_CMD_DISABLE:
            if (size != 0 || !validReply(replySize, replyData, sizeof(int32_t))) return -EINVAL;
            if (effect->state != State::Active) return statusReply(replySize, replyData, -ENOSYS);
            effect->state = State::Draining;
            effect->refresh();
            return statusReply(replySize, replyData, 0);
        case EFFECT_CMD_SET_PARAM:
            if (!validReply(replySize, replyData, sizeof(int32_t))) return -EINVAL;
            return statusReply(replySize, replyData, setParameter(effect, size, data));
        case EFFECT_CMD_GET_PARAM:
            return getParameter(effect, size, data, replySize, replyData);
        case EFFECT_CMD_SET_DEVICE: {
            if (data == nullptr || size != sizeof(uint32_t)) return -EINVAL;
            const uint32_t device = readValue<uint32_t>(data);
            if (device == effect->device) return 0;
            const int32_t previousProfile = effect->profile();
            effect->device = device;
            if (effect->profile() < 0) effect->clear();
            if (effect->profile() != previousProfile) effect->refresh();
            return 0;
        }
        case EFFECT_CMD_SET_AUDIO_MODE: {
            if (data == nullptr || size != sizeof(uint32_t)) return -EINVAL;
            const uint32_t mode = readValue<uint32_t>(data);
            if (mode >= AUDIO_MODE_CNT) return -EINVAL;
            if (mode == effect->audioMode) return 0;
            effect->audioMode = mode;
            if (mode != AUDIO_MODE_NORMAL) effect->clear();
            effect->refresh();
            return 0;
        }
        case EFFECT_CMD_SET_VOLUME:
            return data != nullptr && size == 2 * sizeof(uint32_t) ? 0 : -EINVAL;
        case EFFECT_CMD_DUMP:
            if (data == nullptr || size != sizeof(int)) return -EINVAL;
            dprintf(readValue<int>(data),
                    "Exynos9810 output equalizer: active=%d device=0x%x mode=%u profile=%d "
                    "rate=%u processing=%d\n", effect->state == State::Active, effect->device,
                    effect->audioMode, effect->profile(), effect->config.inputCfg.samplingRate,
                    effect->processing());
            return 0;
        default: return -EINVAL;
    }
}
int descriptor(effect_handle_t self, effect_descriptor_t* result) {
    if (self == nullptr || result == nullptr) return -EINVAL;
    *result = kDescriptor;
    return 0;
}
const effect_interface_s kInterface{process, command, descriptor, nullptr};
int create(const effect_uuid_t* uuid, int32_t session, int32_t /* io */, effect_handle_t* handle) {
    if (uuid == nullptr || handle == nullptr ||
        std::memcmp(uuid, &kImplementation, sizeof(*uuid)) != 0) return -EINVAL;
    *handle = nullptr;
    auto* effect = new (std::nothrow) OutputEqualizerEffect;
    if (effect == nullptr) return -ENOMEM;
    effect->interface = &kInterface;
    effect->session = session;
    const int result = initialize(effect);
    if (result != 0) { delete effect; return result; }
    *handle = reinterpret_cast<effect_handle_t>(effect);
    return 0;
}
int release(effect_handle_t handle) {
    if (handle == nullptr) return -EINVAL;
    delete reinterpret_cast<OutputEqualizerEffect*>(handle);
    return 0;
}
int libraryDescriptor(const effect_uuid_t* uuid, effect_descriptor_t* result) {
    if (uuid == nullptr || result == nullptr ||
        std::memcmp(uuid, &kImplementation, sizeof(*uuid)) != 0) return -EINVAL;
    *result = kDescriptor;
    return 0;
}
}  // namespace
extern "C" {
__attribute__((visibility("default"))) audio_effect_library_t AUDIO_EFFECT_LIBRARY_INFO_SYM = {
    AUDIO_EFFECT_LIBRARY_TAG, EFFECT_LIBRARY_API_VERSION, "Exynos9810 output equalizer",
    "LineageOS", create, release, libraryDescriptor, nullptr,
};
}
