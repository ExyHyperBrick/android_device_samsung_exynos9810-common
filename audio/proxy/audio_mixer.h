/*
 * Copyright (C) 2014 The Android Open Source Project
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

#ifndef __EXYNOS_AUDIOPROXY_MIXER_H__
#define __EXYNOS_AUDIOPROXY_MIXER_H__

#include <audio_route/audio_route.h>

/* Mixer Card Definition */
#define MIXER_CARD0     0


#define MAX_PATH_NAME_LEN 50
#define MAX_GAIN_PATH_NAME_LEN 55 //"gain-" + path_name size

/* Mixer Controls for ERAP Handling */
#define MAX_MIXER_NAME_LEN 50

// Mixer Control for set MUTE Control
#define ABOX_MUTE_CONTROL_NAME "ABOX ERAP info Mute Primary"
#define ABOX_MUTE_CNT_FOR_PATH_CHANGE 15

// Mixer Control for set A-Box Early WakeUp Control
#define ABOX_TICKLE_CONTROL_NAME "ABOX Tickle"
#define ABOX_TICKLE_ON      1

typedef enum {
    MUTE_CONTROL   = 0,
    TICKLE_CONTROL,
} erap_trigger;


// Mixer Control for set Android Audio Mode
#define ABOX_AUDIOMODE_CONTROL_NAME "ABOX Audio Mode"


// Compress Offload Volume
#define OFFLOAD_VOLUME_CONTROL_NAME "ComprTx0 Volume"
#define COMPRESS_PLAYBACK_VOLUME_MAX   8192

// Compress Offload Upscaling
#define OFFLOAD_UPSCALE_CONTROL_NAME "ComprTx0 Format"

#define SPK_AMPL_POWER_NAME "Spk AmpL Power"

typedef enum {
    UPSCALE_NONE        = 0,
    UPSCALE_48K_16B,
    UPSCALE_48K_24B,
    UPSCALE_192K_24B,
    UPSCALE_384K_24B,
} upscale_factor;

// MMAP Playback Volume
#define MIXER_CTL_ABOX_MMAP_OUT_VOLUME_CONTROL  "ABOX RDMA VOL FACTOR3"
#define MMAP_PLAYBACK_VOLUME_MAX   0xFFFFFF // Decimal value : 16777215

#endif  // __EXYNOS_AUDIOPROXY_MIXER_H__
