// SPDX-FileCopyrightText: 2026 The LineageOS Project
// SPDX-License-Identifier: Apache-2.0
package org.lineageos.camera.compat;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;

/** Convert the packed NV21 panorama preview without the legacy native resizer. */
public final class PanoramaCompat {
    private static final int RGBA_HEADER_SIZE = 32;

    private PanoramaCompat() {}

    /**
     * Reads packed NV21 from buffer offset zero, matching the stock JNI contract.
     * Row stride and height slice describe padding, not the visible image size.
     * The source's position, limit and byte order are preserved. Invalid input
     * returns null so the node can report a failed preview rather than publish it.
     */
    public static byte[] resizeNv21ToExtendedRgba(ByteBuffer source,
            int width, int height, int rowStride, int heightSlice,
            int outWidth, int outHeight) {
        if (source == null || width <= 0 || height <= 0
                || (width & 1) != 0 || (height & 1) != 0
                || rowStride < width || (rowStride & 1) != 0
                || heightSlice < height || outWidth <= 0 || outHeight <= 0) {
            return null;
        }
        long chromaOffset = (long) rowStride * heightSlice;
        long sourceEnd = chromaOffset + (long) (height / 2 - 1)
                * rowStride + width;
        long pixels = (long) outWidth * outHeight;
        if (sourceEnd > source.limit()
                || pixels > (Integer.MAX_VALUE - RGBA_HEADER_SIZE) / 4) {
            return null;
        }

        ByteBuffer input = source.duplicate();
        byte[] rgba = new byte[RGBA_HEADER_SIZE + (int) pixels * 4];
        ByteBuffer header = ByteBuffer.wrap(rgba).order(ByteOrder.LITTLE_ENDIAN);
        header.putInt(0, 0x41424752); // Stock "RGBA" byte marker.
        header.putInt(4, outWidth);
        header.putInt(8, outHeight);
        header.putInt(24, outWidth); // Pixel stride in the stock extended header.
        // Reserved fields and rotation at offset 20 remain zero, as in stock.

        int offset = RGBA_HEADER_SIZE;
        for (int y = 0; y < outHeight; y++) {
            double srcY = Math.max(0, Math.min(height - 1,
                    (y + 0.5) * height / outHeight - 0.5));
            for (int x = 0; x < outWidth; x++) {
                double srcX = Math.max(0, Math.min(width - 1,
                        (x + 0.5) * width / outWidth - 0.5));
                int luma = sample(input, 0, rowStride, 1, width, height,
                        srcX, srcY);
                int v = sample(input, (int) chromaOffset, rowStride, 2,
                        width / 2, height / 2, srcX / 2, srcY / 2) - 128;
                int u = sample(input, (int) chromaOffset + 1, rowStride, 2,
                        width / 2, height / 2, srcX / 2, srcY / 2) - 128;
                int c = (luma - 16) * 298;
                rgba[offset++] = (byte) clamp((c + 409 * v + 128) >> 8);
                rgba[offset++] = (byte) clamp((c - 100 * u - 208 * v + 128) >> 8);
                rgba[offset++] = (byte) clamp((c + 516 * u + 128) >> 8);
                rgba[offset++] = (byte) 255;
            }
        }
        return rgba;
    }

    private static int sample(ByteBuffer input, int start, int rowStride,
            int pixelStride, int width, int height, double x, double y) {
        x = Math.max(0, Math.min(width - 1, x));
        y = Math.max(0, Math.min(height - 1, y));
        int x0 = (int) x;
        int y0 = (int) y;
        int x1 = Math.min(x0 + 1, width - 1);
        int y1 = Math.min(y0 + 1, height - 1);
        double wx = x - x0;
        double wy = y - y0;
        int top = start + y0 * rowStride;
        int bottom = start + y1 * rowStride;
        double a = (input.get(top + x0 * pixelStride) & 255) * (1 - wx)
                + (input.get(top + x1 * pixelStride) & 255) * wx;
        double b = (input.get(bottom + x0 * pixelStride) & 255) * (1 - wx)
                + (input.get(bottom + x1 * pixelStride) & 255) * wx;
        return (int) Math.round(a * (1 - wy) + b * wy);
    }

    private static int clamp(int value) {
        return Math.max(0, Math.min(255, value));
    }
}
