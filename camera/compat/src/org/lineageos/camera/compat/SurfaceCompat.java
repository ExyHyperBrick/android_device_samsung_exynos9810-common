/*
 * Copyright (C) 2026 The LineageOS Project
 * SPDX-License-Identifier: Apache-2.0
 */
package org.lineageos.camera.compat;

import android.graphics.Bitmap;
import android.os.Handler;
import android.os.HandlerThread;
import android.util.Size;
import android.view.PixelCopy;
import android.view.Surface;

import java.nio.ByteBuffer;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Copies transition snapshots without the old Samsung libgui ABI. */
public final class SurfaceCompat {
    private static final long COPY_TIMEOUT_MS = 1500;

    private SurfaceCompat() {}

    private static final class CopyHandler {
        static final Handler INSTANCE = create();

        private static Handler create() {
            HandlerThread thread = new HandlerThread("SamsungCameraPixelCopy");
            thread.setDaemon(true);
            thread.start();
            return new Handler(thread.getLooper());
        }
    }

    private static final class CopyCompletion {
        final CountDownLatch ready = new CountDownLatch(1);
        final Bitmap bitmap;
        boolean finished;
        boolean abandoned;
        int result;

        CopyCompletion(Bitmap bitmap) {
            this.bitmap = bitmap;
        }

        synchronized void finish(int copyResult) {
            result = copyResult;
            finished = true;
            // PixelCopy has stopped writing when its callback is delivered.
            if (abandoned) {
                bitmap.recycle();
            }
            ready.countDown();
        }

        synchronized boolean abandon() {
            if (finished) {
                return false;
            }
            abandoned = true;
            return true;
        }

        synchronized int getResult() {
            return result;
        }
    }

    /**
     * Writes a real snapshot as packed NV21 at offset zero. The caller's
     * buffer position and limit remain unchanged, matching the old JNI call.
     * Copy failures throw into MakerBase's existing snapshot error callback.
     */
    public static void copyPreviewToNv21(Surface surface, ByteBuffer destination,
            Size size) {
        if (surface == null || !surface.isValid()) {
            throw new IllegalArgumentException("Preview surface is unavailable");
        }
        if (destination == null || destination.isReadOnly() || size == null) {
            throw new IllegalArgumentException("Writable snapshot buffer and size required");
        }
        int width = size.getWidth();
        int height = size.getHeight();
        if (width <= 0 || height <= 0 || (width & 1) != 0 || (height & 1) != 0) {
            throw new IllegalArgumentException("Snapshot dimensions must be positive and even");
        }
        long pixelCount = (long) width * height;
        long byteCount = pixelCount + pixelCount / 2;
        if (byteCount > destination.capacity()) {
            throw new IllegalArgumentException("Snapshot buffer is too small");
        }

        Bitmap bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888);
        CopyCompletion completion = new CopyCompletion(bitmap);
        boolean callbackOwnsBitmap = false;
        try {
            PixelCopy.request(surface, bitmap, completion::finish, CopyHandler.INSTANCE);
            final boolean copied;
            try {
                copied = completion.ready.await(COPY_TIMEOUT_MS, TimeUnit.MILLISECONDS);
            } catch (InterruptedException exception) {
                callbackOwnsBitmap = completion.abandon();
                Thread.currentThread().interrupt();
                throw new IllegalStateException("Preview snapshot interrupted", exception);
            }
            if (!copied) {
                callbackOwnsBitmap = completion.abandon();
                throw new IllegalStateException("Preview snapshot timed out");
            }
            int result = completion.getResult();
            if (result != PixelCopy.SUCCESS) {
                throw new IllegalStateException("Preview snapshot PixelCopy error " + result);
            }

            int[] pixels = new int[(int) pixelCount];
            bitmap.getPixels(pixels, 0, width, 0, 0, width, height);
            byte[] nv21 = convertArgbToNv21(pixels, width, height);
            ByteBuffer output = destination.duplicate();
            output.clear();
            output.put(nv21);
        } finally {
            // A late completion must recycle its bitmap only after copying.
            if (!callbackOwnsBitmap) {
                bitmap.recycle();
            }
        }
    }

    private static byte[] convertArgbToNv21(int[] pixels, int width, int height) {
        int pixelCount = width * height;
        byte[] output = new byte[pixelCount + pixelCount / 2];
        int chromaOffset = pixelCount;
        for (int row = 0; row < height; row++) {
            for (int column = 0; column < width; column++) {
                int offset = row * width + column;
                int pixel = pixels[offset];
                int red = (pixel >> 16) & 255;
                int green = (pixel >> 8) & 255;
                int blue = pixel & 255;
                output[offset] = (byte) clamp(((66 * red + 129 * green + 25 * blue
                        + 128) >> 8) + 16);
                if ((row & 1) == 0 && (column & 1) == 0) {
                    int right = pixels[offset + 1];
                    int below = pixels[offset + width];
                    int diagonal = pixels[offset + width + 1];
                    red = (red + ((right >> 16) & 255) + ((below >> 16) & 255)
                            + ((diagonal >> 16) & 255) + 2) / 4;
                    green = (green + ((right >> 8) & 255) + ((below >> 8) & 255)
                            + ((diagonal >> 8) & 255) + 2) / 4;
                    blue = (blue + (right & 255) + (below & 255)
                            + (diagonal & 255) + 2) / 4;
                    output[chromaOffset++] = (byte) clamp(((112 * red - 94 * green
                            - 18 * blue + 128) >> 8) + 128);
                    output[chromaOffset++] = (byte) clamp(((-38 * red - 74 * green
                            + 112 * blue + 128) >> 8) + 128);
                }
            }
        }
        return output;
    }

    private static int clamp(int component) {
        return Math.max(0, Math.min(255, component));
    }
}
