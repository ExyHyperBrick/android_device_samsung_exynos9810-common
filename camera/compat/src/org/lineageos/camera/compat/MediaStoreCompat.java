/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.camera.compat;

import android.content.ContentResolver;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.ParcelFileDescriptor;
import android.provider.MediaStore;
import android.util.Log;

import java.io.IOException;
import java.io.File;
import java.io.FileInputStream;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.util.ArrayList;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Adapts the basic camera save path to Android's media database. */
public final class MediaStoreCompat {
    private static final String TAG = "CameraMediaStoreCompat";
    private static final String[] SAMSUNG_VALUES = {
        "group_id", "burst_group_id", "group_type", "sef_file_type",
        "recording_mode", "recordingtype", "video_codec_info",
        "audio_codec_info", "is_hdr10_video"
    };
    private static final Pattern LIMIT = Pattern.compile(
            "(?i)\\s+LIMIT\\s+(\\d+)\\s*$");

    private static final Pattern CLOUD_PATH = Pattern.compile(
            "(?i)\\bcloud_server_path\\s+LIKE\\s+'(?:''|[^'])*'");

    private MediaStoreCompat() {}

    private static ContentValues standardValues(ContentValues values) {
        ContentValues result = new ContentValues(values);
        for (String column : SAMSUNG_VALUES) result.remove(column);
        return result;
    }

    /** A file-based capture owns one pending row until its saving task claims it. */
    public static final class PendingImage {
        private final ContentResolver resolver;
        private final Uri uri;
        private final String displayName;
        private final String title;
        private final long dateTaken;
        private File file;
        private boolean claimed;
        private boolean finished;

        private PendingImage(ContentResolver resolver, Uri uri, File file,
                ContentValues requested) {
            this.resolver = resolver;
            this.uri = uri;
            this.file = file;
            displayName = requested.getAsString(MediaStore.MediaColumns.DISPLAY_NAME);
            title = requested.getAsString(MediaStore.MediaColumns.TITLE);
            dateTaken = System.currentTimeMillis();
        }

        public Uri getUri() {
            return uri;
        }

        public synchronized String getPath() {
            return file == null ? null : file.getPath();
        }

        public String getDisplayName() {
            return displayName;
        }

        public long getDateTaken() {
            return dateTaken;
        }

        public synchronized boolean matches(String path) {
            if (file == null || path == null) return false;
            try {
                return file.getCanonicalPath().equals(new File(path).getCanonicalPath());
            } catch (IOException | RuntimeException error) {
                return false;
            }
        }

        public synchronized Uri claim(String path) {
            if (finished || claimed || !matches(path)) return null;
            claimed = true;
            return uri;
        }

        public synchronized boolean isClaimed() {
            return claimed;
        }

        public synchronized void cancel() {
            if (!claimed) fail();
        }

        public synchronized void fail() {
            if (finished) return;
            finished = true;
            deleteFailedSave(resolver, uri);
        }

        public synchronized int publish(ContentValues values) {
            if (!claimed || finished) {
                throw new IllegalStateException("Pending image is not owned by the saving task");
            }
            try {
                if (!file.isFile() || file.length() == 0) {
                    throw new IOException("Missing panorama JPEG");
                }
                try (FileInputStream input = new FileInputStream(file)) {
                    if (input.read() != 0xff || input.read() != 0xd8) {
                        throw new IOException("Panorama output is not a JPEG");
                    }
                }
                ContentValues published = new ContentValues(values);
                published.remove(MediaStore.MediaColumns.DATA);
                published.put(MediaStore.MediaColumns.DISPLAY_NAME, displayName);
                published.put(MediaStore.MediaColumns.TITLE, title);
                published.put(MediaStore.Images.ImageColumns.DATE_TAKEN, dateTaken);
                published.put(MediaStore.MediaColumns.DATE_MODIFIED, dateTaken / 1000);
                int updated = MediaStoreCompat.publish(resolver, uri, published);
                finished = true;
                // Publishing renames the managed hidden file to its visible name.
                try {
                    file = new File(queryImagePath(resolver, uri, false));
                } catch (RuntimeException error) {
                    file = null;
                    Log.w(TAG, "Published panorama is available by URI only", error);
                }
                return updated;
            } catch (IOException | RuntimeException error) {
                fail();
                throw new IllegalStateException("Could not publish the panorama JPEG", error);
            }
        }
    }

    private static String queryImagePath(ContentResolver resolver, Uri uri,
            boolean requirePending) {
        String[] columns = {MediaStore.MediaColumns.DATA, MediaStore.MediaColumns.IS_PENDING};
        try (Cursor cursor = resolver.query(uri, columns, null, null, null)) {
            if (cursor == null || !cursor.moveToFirst()) {
                throw new IllegalStateException("MediaStore did not return the image pathname");
            }
            if (requirePending && cursor.getInt(1) != 1) {
                throw new IllegalStateException("MediaStore image is not pending");
            }
            String path = cursor.getString(0);
            if (path == null || path.isEmpty()) {
                throw new IllegalStateException("MediaStore returned an empty image pathname");
            }
            return path;
        }
    }

    public static PendingImage insertPendingFile(ContentResolver resolver, Uri collection,
            ContentValues values, String requestedPath) {
        if (requestedPath == null || requestedPath.isEmpty()) {
            throw new IllegalArgumentException("Missing panorama output pathname");
        }
        ContentValues pending = new ContentValues(values);
        pending.remove(MediaStore.MediaColumns.DATA);
        pending.put(MediaStore.MediaColumns.RELATIVE_PATH, "DCIM/Camera");
        Uri uri = insertPending(resolver, collection, pending);
        try {
            return new PendingImage(resolver, uri,
                    new File(queryImagePath(resolver, uri, true)), pending);
        } catch (RuntimeException error) {
            deleteFailedSave(resolver, uri);
            throw error;
        }
    }

    public static Uri insertPending(ContentResolver resolver, Uri collection,
            ContentValues values) {
        ContentValues pending = standardValues(values);
        pending.put(MediaStore.MediaColumns.IS_PENDING, 1);
        Uri result = resolver.insert(collection, pending);
        if (result == null) {
            throw new IllegalStateException("MediaStore did not create a pending row");
        }
        return result;
    }

    public static int publish(ContentResolver resolver, Uri item,
            ContentValues values) {
        if (item == null) throw new IllegalStateException("Missing pending media URI");
        ContentValues published = standardValues(values);
        published.put(MediaStore.MediaColumns.IS_PENDING, 0);
        int updated = resolver.update(item, published, null, null);
        if (updated != 1) {
            throw new IllegalStateException("MediaStore did not publish the saved row: "
                    + updated);
        }
        return updated;
    }

    public static boolean writeImage(ContentResolver resolver, Uri item,
            ByteBuffer picture) {
        if (item == null || picture == null || picture.limit() == 0) return false;
        try {
            ParcelFileDescriptor descriptor = resolver.openFileDescriptor(item, "w");
            if (descriptor == null) throw new IOException("No image file descriptor");
            try (ParcelFileDescriptor.AutoCloseOutputStream output =
                    new ParcelFileDescriptor.AutoCloseOutputStream(descriptor)) {
                FileChannel channel = output.getChannel();
                ByteBuffer bytes = picture.duplicate();
                bytes.rewind();
                while (bytes.hasRemaining()) {
                    if (channel.write(bytes) <= 0) {
                        throw new IOException("Image write did not make progress");
                    }
                }
            }
            return true;
        } catch (IOException | RuntimeException exception) {
            Log.e(TAG, "Could not write the captured image", exception);
            return false;
        }
    }

    public static void deleteFailedSave(ContentResolver resolver, Uri item) {
        if (item == null) return;
        try {
            if (resolver.delete(item, "is_pending=1", null) != 1) {
                Log.e(TAG, "Could not remove the failed pending media row: " + item);
            }
        } catch (RuntimeException exception) {
            Log.e(TAG, "Could not remove the failed pending media row", exception);
        }
    }

    /** Query real media; Samsung grouping/cloud fields describe no such metadata. */
    public static Cursor queryLatest(ContentResolver resolver, Uri uri,
            String[] projection, String selection, String[] arguments, String sort) {
        if (Build.VERSION.SDK_INT <= 29) {
            return resolver.query(uri, projection, selection, arguments, sort);
        }
        if (selection != null && selection.contains("burst_group_id")) {
            throw new UnsupportedOperationException("Samsung burst groups are unavailable");
        }
        String volume = "secmedia".equals(uri.getAuthority())
                ? MediaStore.VOLUME_EXTERNAL : MediaStore.getVolumeName(uri);
        Uri collection = MediaStore.Files.getContentUri(volume);
        ArrayList<String> columns = new ArrayList<>();
        for (String column : projection) {
            String actual = databaseColumn(column);
            if (actual != null && !columns.contains(actual)) columns.add(actual);
        }
        Bundle query = new Bundle();
        if (selection != null) {
            // AOSP has no Samsung cloud rows. Keep genuine local folder filters.
            selection = CLOUD_PATH.matcher(selection).replaceAll("0");
            query.putString(ContentResolver.QUERY_ARG_SQL_SELECTION,
                    "(" + selection.replace("datetime", "datetaken").replace(
                            " AND (is_hide != 1 OR is_hide is null)", "").replace(
                            " AND (is_hide != 1 OR is_hide is NULL)", "")
                            + ") AND is_pending=0");
        } else {
            query.putString(ContentResolver.QUERY_ARG_SQL_SELECTION, "is_pending=0");
        }
        if (arguments != null) {
            query.putStringArray(ContentResolver.QUERY_ARG_SQL_SELECTION_ARGS, arguments);
        }
        if (sort != null) {
            Matcher limit = LIMIT.matcher(sort);
            if (limit.find()) {
                query.putInt(ContentResolver.QUERY_ARG_LIMIT,
                        Integer.parseInt(limit.group(1)));
                sort = sort.substring(0, limit.start());
            }
            query.putString(ContentResolver.QUERY_ARG_SQL_SORT_ORDER,
                    sort.replace("datetime", "datetaken"));
        }
        try (Cursor source = resolver.query(collection, columns.toArray(new String[0]),
                query, null)) {
            if (source == null) return null;
            MatrixCursor result = new MatrixCursor(projection, source.getCount());
            while (source.moveToNext()) {
                Object[] row = new Object[projection.length];
                for (int i = 0; i < projection.length; i++) {
                    String actual = databaseColumn(projection[i]);
                    if (actual == null) {
                        row[i] = "cloud_thumb_path".equals(projection[i]) ? null : 0;
                    } else {
                        int index = source.getColumnIndexOrThrow(actual);
                        switch (source.getType(index)) {
                            case Cursor.FIELD_TYPE_INTEGER: row[i] = source.getLong(index); break;
                            case Cursor.FIELD_TYPE_FLOAT: row[i] = source.getDouble(index); break;
                            case Cursor.FIELD_TYPE_STRING: row[i] = source.getString(index); break;
                            case Cursor.FIELD_TYPE_BLOB: row[i] = source.getBlob(index); break;
                            default: row[i] = null;
                        }
                    }
                }
                result.addRow(row);
            }
            return result;
        }
    }

    private static String databaseColumn(String column) {
        switch (column) {
            case "datetime": return MediaStore.Images.ImageColumns.DATE_TAKEN;
            case "is_cloud":
            case "cloud_thumb_path":
            case "burst_group_id":
            case "group_type":
            case "sef_file_type":
            case "best_image": return null;
            default: return column;
        }
    }
}
