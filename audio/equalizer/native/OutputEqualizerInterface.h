/*
 * SPDX-FileCopyrightText: The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
#pragma once

#include <array>
#include <cstdint>

namespace output_equalizer {
constexpr int32_t kBandCount = 5;
constexpr int32_t kProfileCount = 3;
constexpr int32_t kGainLimitDb = 12;
constexpr std::array<int32_t, kBandCount> kFrequenciesHz{60, 230, 910, 3600, 14000};

enum Profile : int32_t { kSpeaker = 0, kHeadphones = 1, kUsb = 2 };
// Profile: key int32[2] = {0, profile}; value int32[6] = {enabled, gainsDb...}.
// Status: read-only key int32[1] = {1}; value int32[4] =
// {effectiveProfile (-1 for bypass), sampleRate, audioMode, processing}.
enum Parameter : int32_t { kProfile = 0, kStatus = 1 };
struct ProfileSettings {
    int32_t enabled = 0;
    std::array<int32_t, kBandCount> gains{};
};
static_assert(sizeof(ProfileSettings) == 6 * sizeof(int32_t));
}  // namespace output_equalizer
