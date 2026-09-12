/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.audio.dolby;

import android.service.quicksettings.Tile;
import android.service.quicksettings.TileService;

public final class DolbyTile extends TileService {
    private final Runnable mListener = this::refresh;

    private DolbyApplication dolby() { return (DolbyApplication) getApplication(); }

    @Override
    public void onStartListening() {
        super.onStartListening();
        dolby().addListener(mListener);
        refresh();
    }

    @Override
    public void onStopListening() {
        dolby().removeListener(mListener);
        super.onStopListening();
    }

    @Override
    public void onDestroy() {
        dolby().removeListener(mListener);
        super.onDestroy();
    }

    @Override
    public void onClick() {
        super.onClick();
        if (!dolby().isReady()) return;
        if (isLocked()) unlockAndRun(this::toggle);
        else toggle();
    }

    private void toggle() {
        DolbyApplication dolby = dolby();
        if (dolby.isReady()) dolby.setEnabled(!dolby.isEnabled());
        refresh();
    }

    private void refresh() {
        Tile tile = getQsTile();
        if (tile == null) return;
        DolbyApplication dolby = dolby();
        boolean active = dolby.getStatus() == R.string.dolby_active;
        tile.setState(!dolby.isReady() ? Tile.STATE_UNAVAILABLE
                : active ? Tile.STATE_ACTIVE : Tile.STATE_INACTIVE);
        tile.setLabel(getString(R.string.dolby_title));
        if (active) {
            tile.setSubtitle(getString(dolby.getProfile() == MotorolaDolby.MUSIC
                    ? R.string.dolby_music : R.string.dolby_dynamic));
        } else {
            tile.setSubtitle(getString(!dolby.isReady()
                    || dolby.getStatus() == R.string.dolby_unavailable
                    ? R.string.dolby_tile_unavailable : dolby.getStatus()));
        }
        tile.updateTile();
    }
}
