/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.audio.dolby;

/** User-selectable profiles from the bundled Motorola dax-default.xml. */
enum DolbyProfile {
    MUSIC(2, "dolby_profile_music", R.string.dolby_music),
    DYNAMIC(0, "dolby_profile_dynamic", R.string.dolby_dynamic),
    MOVIE(1, "dolby_profile_movie", R.string.dolby_movie),
    VOICE(9, "dolby_profile_voice", R.string.dolby_voice),
    GAME(8, "dolby_profile_game", R.string.dolby_game);

    // Native IDs are also persisted. They are not enum ordinals or Samsung DAP IDs.
    final int id;
    final String preferenceKey;
    final int titleRes;

    DolbyProfile(int id, String preferenceKey, int titleRes) {
        this.id = id;
        this.preferenceKey = preferenceKey;
        this.titleRes = titleRes;
    }

    static DolbyProfile fromId(int id) {
        for (DolbyProfile profile : values()) {
            if (profile.id == id) return profile;
        }
        return null;
    }
}
