// SPDX-FileCopyrightText: 2026 The LineageOS Project
// SPDX-License-Identifier: Apache-2.0
package org.lineageos.camera.compat;

import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.provider.MediaStore;
import android.util.Log;

/** Keep the selected media in a gallery that supports recent-media review. */
public final class GalleryCompat {
    private static final String TAG = "StockCameraCompat";

    private GalleryCompat() {}

    public static void prepareReviewIntent(
            Context context, Intent intent, boolean secure) {
        if (secure || context == null || intent == null
                || !Intent.ACTION_VIEW.equals(intent.getAction())
                || intent.getData() == null) {
            return;
        }
        String type = intent.getType();
        if (type == null || !(type.startsWith("image/")
                || type.startsWith("video/"))) {
            return;
        }

        // Resolve an implicit review request before changing the working viewer
        // intent. Preserve its selected URI, MIME type, extras and read grant.
        Intent review = new Intent(intent);
        review.setAction(MediaStore.ACTION_REVIEW);
        review.setComponent(null);
        try {
            PackageManager manager = context.getPackageManager();
            if (manager != null && manager.resolveActivity(
                    review, PackageManager.MATCH_DEFAULT_ONLY) != null) {
                intent.setAction(MediaStore.ACTION_REVIEW);
                intent.setComponent(null);
            }
        } catch (RuntimeException error) {
            Log.w(TAG, "Cannot resolve gallery review; retaining media viewer", error);
        }
    }
}
