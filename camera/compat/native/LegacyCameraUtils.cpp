/*
 * Copyright (C) 2026 The LineageOS Project
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#include <stdint.h>

namespace android {
class CameraMetadata;
}

// This bridge uses the exact exported C++ ABI without including private
// CameraUtils headers. The metadata stays opaque and belongs to the platform.
extern "C" int32_t currentRotationTransform(const android::CameraMetadata& metadata,
                                           int mirrorMode, bool inverseDisplay,
                                           int32_t* transform)
        asm("_ZN7android11CameraUtils20getRotationTransformERKNS_14CameraMetadataEibPi");

extern "C" __attribute__((visibility("default"))) int32_t legacyRotationTransform(
        const android::CameraMetadata& metadata, int32_t* transform)
        asm("_ZN7android11CameraUtils20getRotationTransformERKNS_14CameraMetadataEPi");

int32_t legacyRotationTransform(const android::CameraMetadata& metadata, int32_t* transform) {
    // Android 10 mirrors front-facing cameras automatically and always adds
    // NATIVE_WINDOW_TRANSFORM_INVERSE_DISPLAY. The current API retains this
    // behavior with MIRROR_MODE_AUTO (0) and inverseDisplay enabled.
    return currentRotationTransform(metadata, 0, true, transform);
}
