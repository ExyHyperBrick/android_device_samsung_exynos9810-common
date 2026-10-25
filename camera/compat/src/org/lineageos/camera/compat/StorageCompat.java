/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.camera.compat;

import android.content.ContentValues;
import android.content.Context;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Environment;
import android.os.storage.StorageManager;
import android.os.storage.StorageVolume;
import android.provider.MediaStore;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

/** Per-user destinations shared by the camera UI and all capture writers. */
public final class StorageCompat {
    private static final String PREFERENCES = "lineage_camera_storage";
    private static final String VOLUME = "volume";
    private static final String FOLDER = "folder";
    private static volatile Context sContext;

    private StorageCompat() {}

    public static void initialize(Context context) {
        sContext = context.getApplicationContext();
    }

    private static Context context() {
        Context context = sContext;
        if (context == null) throw new IllegalStateException("Camera storage is not initialized");
        return context;
    }

    private static SharedPreferences preferences() {
        return context().getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE);
    }

    public static List<StorageVolume> removableVolumes(Context context) {
        StorageManager manager = context.getSystemService(StorageManager.class);
        ArrayList<StorageVolume> result = new ArrayList<>();
        if (manager != null) for (StorageVolume volume : manager.getStorageVolumes()) {
            if (!volume.isPrimary() && volume.isRemovable()
                    && Environment.MEDIA_MOUNTED.equals(volume.getState())
                    && volume.getDirectory() != null && volume.getMediaStoreVolumeName() != null) {
                result.add(volume);
            }
        }
        return result;
    }

    /** A removed card is never silently replaced with a different card. */
    public static StorageVolume selectedRemovableVolume() {
        String selected = preferences().getString(VOLUME, MediaStore.VOLUME_EXTERNAL_PRIMARY);
        for (StorageVolume volume : removableVolumes(context())) {
            if (selected.equals(volume.getMediaStoreVolumeName())) return volume;
        }
        return null;
    }

    public static StorageVolume firstRemovableVolume(Context context) {
        initialize(context);
        StorageVolume selected = selectedRemovableVolume();
        if (selected != null) return selected;
        List<StorageVolume> volumes = removableVolumes(context);
        return volumes.isEmpty() ? null : volumes.get(0);
    }

    public static int getStorage() {
        return selectedRemovableVolume() == null ? 0 : 1;
    }

    public static String selectedVolumeName() {
        return preferences().getString(VOLUME, MediaStore.VOLUME_EXTERNAL_PRIMARY);
    }

    public static String folder() {
        return preferences().getString(FOLDER, "Camera");
    }

    /** MediaStore accepts camera photos and videos under DCIM on both volumes. */
    public static String relativePath() {
        return "DCIM/" + folder();
    }

    public static String folderSelection() {
        // Escape the user-selected name before adding it to a stock SQL filter.
        return "relative_path = '" + relativePath().replace("'", "''") + "/'";
    }

    public static String imageSavingDir(int storage) {
        StorageVolume removable = storage == 1 ? selectedRemovableVolume() : null;
        File root = removable == null ? Environment.getExternalStorageDirectory()
                : removable.getDirectory();
        return new File(root, relativePath()).getPath();
    }

    public static Uri collection(Uri collection, int storage) {
        StorageVolume removable = storage == 1 ? selectedRemovableVolume() : null;
        String volume = removable == null ? MediaStore.VOLUME_EXTERNAL_PRIMARY
                : removable.getMediaStoreVolumeName();
        List<String> segments = collection.getPathSegments();
        if (!"media".equals(collection.getAuthority()) || segments.size() < 2) {
            throw new IllegalArgumentException("Unsupported media collection: " + collection);
        }
        Uri.Builder builder = collection.buildUpon().path(null);
        builder.appendPath(volume);
        for (int i = 1; i < segments.size(); i++) builder.appendPath(segments.get(i));
        return builder.build();
    }

    /** Remove legacy absolute paths; the provider owns the final pathname. */
    public static ContentValues pendingValues(ContentValues requested) {
        ContentValues values = new ContentValues(requested);
        String path = values.getAsString(MediaStore.MediaColumns.DATA);
        values.remove(MediaStore.MediaColumns.DATA);
        if (!values.containsKey(MediaStore.MediaColumns.DISPLAY_NAME) && path != null) {
            values.put(MediaStore.MediaColumns.DISPLAY_NAME, new File(path).getName());
        }
        values.put(MediaStore.MediaColumns.RELATIVE_PATH, relativePath());
        return values;
    }

    static String validateFolder(String folder) {
        folder = folder.trim();
        if (folder.isEmpty() || folder.length() > 200) {
            throw new IllegalArgumentException("Choose a folder below DCIM");
        }
        for (String segment : folder.split("/", -1)) {
            if (segment.isEmpty() || segment.startsWith(".") || segment.endsWith(".")
                    || !segment.equals(segment.trim())
                    || segment.getBytes(StandardCharsets.UTF_8).length > 255
                    || segment.matches("(?s).*[\\\\:*?\"<>|\\p{Cntrl}].*")) {
                throw new IllegalArgumentException("Use folder names without reserved characters");
            }
        }
        return folder;
    }

    static boolean save(String volumeName, String folder) {
        folder = validateFolder(folder);
        if (!MediaStore.VOLUME_EXTERNAL_PRIMARY.equals(volumeName)) {
            boolean mounted = false;
            for (StorageVolume volume : removableVolumes(context())) {
                if (volumeName.equals(volume.getMediaStoreVolumeName())) mounted = true;
            }
            if (!mounted) throw new IllegalArgumentException("The selected storage is unavailable");
        }
        return preferences().edit().putString(VOLUME, volumeName).putString(FOLDER, folder).commit();
    }
}
