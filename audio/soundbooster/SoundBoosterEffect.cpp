/*
 * SPDX-FileCopyrightText: The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 *
 * Derived from LineageOS/android_hardware_samsung soundbooster at
 * 5d20e3541d147494e074bf710d35b1960a6ed0a2. Adapted for the stock S9/S9+ ver900 and Note9 ver950
 * ABI, speaker volume table, effect protocol and PCM buffer access rules.
 */
#define LOG_TAG "Exynos9810SoundBooster"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <limits>
#include <new>
#include <unistd.h>

#include <hardware/audio_effect.h>
#include <log/log.h>
#include <system/audio.h>

#include "SoundBoosterInterface.h"

#ifndef SOUNDBOOSTER_PARAM_FILE_PATH
#define SOUNDBOOSTER_PARAM_FILE_PATH "/vendor/etc/SoundBoosterParam.txt"
#endif

namespace {
constexpr effect_uuid_t kType = {
    0xee8aeac0, 0x5d4b, 0x11e5, 0xa837, {0x08, 0x00, 0x20, 0x0c, 0x9a, 0x66}};
constexpr effect_uuid_t kImplementation = {
    0x50de45f0, 0x5d4c, 0x11e5, 0xa837, {0x08, 0x00, 0x20, 0x0c, 0x9a, 0x66}};
constexpr effect_descriptor_t kDescriptor = {
    kType, kImplementation, EFFECT_CONTROL_API_VERSION,
    EFFECT_FLAG_TYPE_INSERT | EFFECT_FLAG_INSERT_LAST | EFFECT_FLAG_DEVICE_IND |
        EFFECT_FLAG_VOLUME_IND | EFFECT_FLAG_AUDIO_MODE_IND,
    75, 25, "Exynos9810 SoundBooster", "Samsung / LineageOS",
};
constexpr size_t kChannels = 2;
constexpr size_t kScratchFrames = 4096;
constexpr uint32_t kRequiredConfig = EFFECT_CONFIG_SMP_RATE | EFFECT_CONFIG_CHANNELS |
                                     EFFECT_CONFIG_FORMAT | EFFECT_CONFIG_ACC_MODE;
enum Parameter : int32_t { kReadParameters = 0, kRotation = 1, kFlatMotion = 2 };
enum class State { Initialized, Active };

struct SoundBoosterEffect {
    const effect_interface_s* interface;
    int32_t session;
    State state = State::Initialized;
    effect_config_t config{};
    bool configured = false;
    uint32_t device = AUDIO_DEVICE_NONE;
    uint32_t audioMode = AUDIO_MODE_NORMAL;
    int32_t rotation = 0;
    int32_t flatMotion = 1;  // stock LoadParameter default, unchanged without a sensor
    float volumeDb = -100.0f;
    SoundBoosterInterface dsp;
    // Stock S9/S9+ libsamsungSoundbooster_plus.so::spkVolume. Passing a
    // null table drops Samsung's mapping from volume in dB to the DRC step.
    std::array<float, 17> volumeTable{
        0, 54, 58, 62, 65, 69, 73, 76, 79, 82, 85, 87, 90, 93, 96, 100, 1};
    // All storage exists before process(); the audio callback never allocates.
    alignas(float) std::array<uint8_t, kScratchFrames * kChannels * sizeof(float)> scratch{};

    bool speaker() const {
        return device == AUDIO_DEVICE_OUT_SPEAKER || device == AUDIO_DEVICE_OUT_SPEAKER_SAFE;
    }
    bool mediaMode() const {
        return audioMode == AUDIO_MODE_NORMAL;
    }
    bool shouldProcess() const { return configured && speaker() && mediaMode(); }
    size_t sampleSize() const {
        return config.inputCfg.format == AUDIO_FORMAT_PCM_FLOAT ? sizeof(float) : sizeof(int16_t);
    }
    int loadParameters() {
        if (access(SOUNDBOOSTER_PARAM_FILE_PATH, R_OK) != 0) return -errno;
        const int result = dsp.load(SOUNDBOOSTER_PARAM_FILE_PATH, volumeTable.data());
        if (result != 0) return result;
        const int orientation = dsp.orientation(rotation);
        return orientation != 0 ? orientation : dsp.motion(flatMotion);
    }
};
static_assert(offsetof(SoundBoosterEffect, interface) == 0);

bool validReply(uint32_t* size, void* data, uint32_t required) {
    return size != nullptr && data != nullptr && *size >= required;
}
int statusReply(uint32_t* size, void* data, int status) {
    if (!validReply(size, data, sizeof(int32_t))) return -EINVAL;
    std::memcpy(data, &status, sizeof(status));
    *size = sizeof(status);
    return 0;
}

template <typename T> T readValue(const void* data) {
    T value;
    std::memcpy(&value, data, sizeof(value));
    return value;
}

int configure(SoundBoosterEffect* effect, const effect_config_t& config) {
    const auto& in = config.inputCfg;
    const auto& out = config.outputCfg;
    if ((in.mask & kRequiredConfig) != kRequiredConfig ||
        (out.mask & kRequiredConfig) != kRequiredConfig ||
        in.samplingRate != 48000 || out.samplingRate != in.samplingRate ||
        in.channels != AUDIO_CHANNEL_OUT_STEREO || out.channels != in.channels ||
        in.format != out.format ||
        (in.format != AUDIO_FORMAT_PCM_16_BIT && in.format != AUDIO_FORMAT_PCM_FLOAT) ||
        in.accessMode != EFFECT_BUFFER_ACCESS_READ ||
        (out.accessMode != EFFECT_BUFFER_ACCESS_WRITE &&
         out.accessMode != EFFECT_BUFFER_ACCESS_ACCUMULATE)) {
        return -EINVAL;
    }
    // The stock automatic speaker stage is explicitly a 48 kHz mixer effect.
    // Reject incompatible configurations so the framework can convert them.
    if (access(SOUNDBOOSTER_PARAM_FILE_PATH, R_OK) != 0) {
        const int result = -errno;
        ALOGE("Cannot read stock SoundBooster parameters: %d", result);
        return result;
    }
    int result = effect->dsp.open();
    if (result != 0) return result;
    // Each device packages only its own stock DSP library and parameter file.
    // Note9 has a different stock volume curve as well as a different DSP.
    effect->volumeTable = effect->dsp.version() == 950
        ? std::array<float, 17>{0, 51, 56, 61, 65, 69, 72, 75, 76, 79, 81, 84, 87, 91, 95, 100, 1}
        : std::array<float, 17>{0, 54, 58, 62, 65, 69, 73, 76, 79, 82, 85, 87, 90, 93, 96, 100, 1};
    const BitDepth depth = in.format == AUDIO_FORMAT_PCM_FLOAT ? BIT_DEPTH_FLOAT : BIT_DEPTH_NONE;
    result = effect->dsp.init(depth, in.samplingRate, SOUNDBOOSTER_PARAM_FILE_PATH,
                              effect->volumeTable.data());
    if (result == 0) result = effect->dsp.orientation(effect->rotation);
    if (result == 0) result = effect->dsp.motion(effect->flatMotion);
    if (result == 0) result = effect->dsp.clear();
    if (result != 0) {
        effect->configured = false;
        ALOGE("SoundBooster configuration failed: %d", result);
        return result;
    }
    effect->config = config;
    effect->configured = true;
    return 0;
}

int initialize(SoundBoosterEffect* effect) {
    effect_config_t config{};
    config.inputCfg.samplingRate = config.outputCfg.samplingRate = 48000;
    config.inputCfg.channels = config.outputCfg.channels = AUDIO_CHANNEL_OUT_STEREO;
    config.inputCfg.format = config.outputCfg.format = AUDIO_FORMAT_PCM_FLOAT;
    config.inputCfg.accessMode = EFFECT_BUFFER_ACCESS_READ;
    config.outputCfg.accessMode = EFFECT_BUFFER_ACCESS_WRITE;
    config.inputCfg.mask = config.outputCfg.mask = kRequiredConfig;
    effect->state = State::Initialized;
    effect->device = AUDIO_DEVICE_NONE;  // bypass until the framework provides the actual route
    return configure(effect, config);
}

// Accumulation uses a distinct scratch buffer, preserving the READ input even
// when the stock DSP processes its source in place. PCM16 sums saturate.
void writeSamples(const SoundBoosterEffect* effect, const void* source, void* destination,
                  size_t samples) {
    if (effect->config.outputCfg.accessMode == EFFECT_BUFFER_ACCESS_WRITE) {
        if (source != destination) std::memcpy(destination, source, samples * effect->sampleSize());
    } else if (effect->config.inputCfg.format == AUDIO_FORMAT_PCM_FLOAT) {
        const auto* input = static_cast<const float*>(source);
        auto* output = static_cast<float*>(destination);
        for (size_t i = 0; i < samples; ++i) output[i] += input[i];
    } else {
        const auto* input = static_cast<const int16_t*>(source);
        auto* output = static_cast<int16_t*>(destination);
        for (size_t i = 0; i < samples; ++i) {
            const int sum = static_cast<int>(output[i]) + input[i];
            output[i] = static_cast<int16_t>(std::clamp(sum, -32768, 32767));
        }
    }
}

int process(effect_handle_t self, audio_buffer_t* input, audio_buffer_t* output) {
    auto* effect = reinterpret_cast<SoundBoosterEffect*>(self);
    if (effect == nullptr || input == nullptr || output == nullptr || input->raw == nullptr ||
        output->raw == nullptr || input->frameCount == 0 ||
        input->frameCount != output->frameCount || !effect->configured ||
        input->frameCount > std::numeric_limits<size_t>::max() / (kChannels * effect->sampleSize())) {
        return -EINVAL;
    }
    if (effect->state != State::Active) return -ENODATA;
    if (!effect->shouldProcess()) {
        writeSamples(effect, input->raw, output->raw, input->frameCount * kChannels);
        return 0;
    }
    const auto* source = static_cast<const uint8_t*>(input->raw);
    auto* destination = static_cast<uint8_t*>(output->raw);
    size_t remaining = input->frameCount;
    int status = 0;
    while (remaining != 0) {
        const size_t frames = std::min(remaining, kScratchFrames);
        const size_t bytes = frames * kChannels * effect->sampleSize();
        std::memcpy(effect->scratch.data(), source, bytes);
        if (status == 0) {
            status = effect->dsp.process(effect->scratch.data(), frames, effect->volumeDb);
            if (status != 0) std::memcpy(effect->scratch.data(), source, bytes);
        }
        writeSamples(effect, effect->scratch.data(), destination, frames * kChannels);
        source += bytes;
        destination += bytes;
        remaining -= frames;
    }
    return status;
}

int setParameter(SoundBoosterEffect* effect, uint32_t size, const void* data) {
    if (data == nullptr || size != sizeof(effect_param_t) + 2 * sizeof(int32_t)) return -EINVAL;
    const auto* parameter = static_cast<const effect_param_t*>(data);
    if (parameter->psize != sizeof(int32_t) || parameter->vsize != sizeof(int32_t)) return -EINVAL;
    const int32_t id = readValue<int32_t>(parameter->data);
    const int32_t value = readValue<int32_t>(parameter->data + sizeof(int32_t));
    int result;
    switch (id) {
        case kReadParameters:
            return effect->configured ? effect->loadParameters() : -ENODEV;
        case kRotation:
            if (value < 0 || value > 3) return -EINVAL;
            result = effect->configured ? effect->dsp.orientation(value) : -ENODEV;
            if (result == 0) effect->rotation = value;
            return result;
        case kFlatMotion:
            if (value != 0 && value != 1) return -EINVAL;
            result = effect->configured ? effect->dsp.motion(value) : -ENODEV;
            if (result == 0) effect->flatMotion = value;
            return result;
        default:
            return -EINVAL;
    }
}

int getParameter(SoundBoosterEffect* effect, uint32_t size, const void* data,
                 uint32_t* replySize, void* replyData) {
    constexpr uint32_t resultSize = sizeof(effect_param_t) + 2 * sizeof(int32_t);
    if (data == nullptr || size != sizeof(effect_param_t) + sizeof(int32_t) ||
        !validReply(replySize, replyData, resultSize)) return -EINVAL;
    const auto* parameter = static_cast<const effect_param_t*>(data);
    if (parameter->psize != sizeof(int32_t) || parameter->vsize != sizeof(int32_t)) return -EINVAL;
    const int32_t id = readValue<int32_t>(parameter->data);
    int32_t value = 0;
    int status = 0;
    switch (id) {
        case kReadParameters: break;
        case kRotation: value = effect->rotation; break;
        case kFlatMotion: value = effect->flatMotion; break;
        default: status = -EINVAL; break;
    }
    auto* reply = static_cast<effect_param_t*>(replyData);
    reply->status = status;
    reply->psize = reply->vsize = sizeof(int32_t);
    std::memcpy(reply->data, &id, sizeof(id));
    std::memcpy(reply->data + sizeof(id), &value, sizeof(value));
    *replySize = resultSize;
    return 0;
}

int command(effect_handle_t self, uint32_t code, uint32_t size, void* data,
            uint32_t* replySize, void* replyData) {
    auto* effect = reinterpret_cast<SoundBoosterEffect*>(self);
    if (effect == nullptr) return -EINVAL;
    switch (code) {
        case EFFECT_CMD_INIT:
            if (!validReply(replySize, replyData, sizeof(int32_t))) return -EINVAL;
            return statusReply(replySize, replyData, initialize(effect));
        case EFFECT_CMD_SET_CONFIG: {
            if (data == nullptr || size != sizeof(effect_config_t) ||
                !validReply(replySize, replyData, sizeof(int32_t))) return -EINVAL;
            const auto config = readValue<effect_config_t>(data);
            return statusReply(replySize, replyData, configure(effect, config));
        }
        case EFFECT_CMD_GET_CONFIG:
            if (!validReply(replySize, replyData, sizeof(effect_config_t))) return -EINVAL;
            std::memcpy(replyData, &effect->config, sizeof(effect->config));
            *replySize = sizeof(effect->config);
            return 0;
        case EFFECT_CMD_RESET:
            return effect->configured ? effect->dsp.clear() : -ENODEV;
        case EFFECT_CMD_ENABLE: {
            if (!validReply(replySize, replyData, sizeof(int32_t))) return -EINVAL;
            const int result = effect->configured ? effect->dsp.clear() : -ENODEV;
            if (result == 0) effect->state = State::Active;
            return statusReply(replySize, replyData, result);
        }
        case EFFECT_CMD_DISABLE: {
            if (!validReply(replySize, replyData, sizeof(int32_t))) return -EINVAL;
            effect->state = State::Initialized;
            return statusReply(replySize, replyData, effect->configured ? effect->dsp.clear() : 0);
        }
        case EFFECT_CMD_SET_PARAM:
            if (!validReply(replySize, replyData, sizeof(int32_t))) return -EINVAL;
            return statusReply(replySize, replyData, setParameter(effect, size, data));
        case EFFECT_CMD_GET_PARAM:
            return getParameter(effect, size, data, replySize, replyData);
        case EFFECT_CMD_SET_DEVICE: {
            if (data == nullptr || size != sizeof(uint32_t)) return -EINVAL;
            const bool wasProcessing = effect->shouldProcess();
            effect->device = readValue<uint32_t>(data);
            return wasProcessing != effect->shouldProcess() && effect->configured
                       ? effect->dsp.clear() : 0;
        }
        case EFFECT_CMD_SET_AUDIO_MODE: {
            if (data == nullptr || size != sizeof(uint32_t)) return -EINVAL;
            const uint32_t mode = readValue<uint32_t>(data);
            if (mode >= AUDIO_MODE_CNT) return -EINVAL;
            const bool wasProcessing = effect->shouldProcess();
            effect->audioMode = mode;
            return wasProcessing != effect->shouldProcess() && effect->configured
                       ? effect->dsp.clear() : 0;
        }
        case EFFECT_CMD_SET_VOLUME: {
            if (data == nullptr || size != 2 * sizeof(uint32_t)) return -EINVAL;
            const auto* volumes = static_cast<const uint8_t*>(data);
            const float left = readValue<uint32_t>(volumes) / 16777216.0f;
            const float right = readValue<uint32_t>(volumes + sizeof(uint32_t)) / 16777216.0f;
            effect->volumeDb = std::log(std::max(left, right) + 1.0e-5f) * 8.68589f;
            return 0;  // volume indication: the effect does not change framework gain
        }
        case EFFECT_CMD_DUMP:
            if (data == nullptr || size != sizeof(int)) return -EINVAL;
            dprintf(readValue<int>(data),
                    "Exynos9810 SoundBooster: dsp=%d active=%d configured=%d device=0x%x mode=%u "
                    "speaker=%d processing=%d rotation=%d flat=%d volumeDb=%.2f\n",
                    effect->dsp.version(), effect->state == State::Active, effect->configured, effect->device,
                    effect->audioMode, effect->speaker(), effect->shouldProcess(),
                    effect->rotation, effect->flatMotion, effect->volumeDb);
            return 0;
        default:
            return -EINVAL;
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
    auto* effect = new (std::nothrow) SoundBoosterEffect;
    if (effect == nullptr) return -ENOMEM;
    effect->interface = &kInterface;
    effect->session = session;
    const int status = initialize(effect);
    if (status != 0) { delete effect; return status; }
    *handle = reinterpret_cast<effect_handle_t>(effect);
    return 0;
}
int release(effect_handle_t handle) {
    if (handle == nullptr) return -EINVAL;
    delete reinterpret_cast<SoundBoosterEffect*>(handle);
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
    AUDIO_EFFECT_LIBRARY_TAG, EFFECT_LIBRARY_API_VERSION, "Exynos9810 SoundBooster",
    "Samsung / LineageOS", create, release, libraryDescriptor, nullptr,
};
}
