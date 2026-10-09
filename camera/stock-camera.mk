# SPDX-FileCopyrightText: 2026 The LineageOS Project
# SPDX-License-Identifier: Apache-2.0

PRODUCT_PACKAGES += \
    SamsungCameraExynos9810 \
    exynos9810_stock_camera_privapp_permissions \
    exynos9810_stock_camera_default_permissions \
    libSamsungCameraSecImaging \
    libSamsungCameraSEF \
    libSamsungCameraOpenCv \
    libSamsungCameraExif \
    libSamsungCameraJpeg \
    libSamsungCameraJpegInterface \
    libSamsungCameraCore \
    SamsungCameraCameraPublicLibraries \
    SamsungCameraQuramPublicLibraries \
    libcompiler_rt \
    libnativehelper_compat_libc++ \
    org.apache.http.legacy

PRODUCT_PACKAGES += \
    exynos9810_stock_camera_camera_feature \
    exynos9810_stock_camera_floating_feature

# Dynamic JNI utility engines and their legacy framework ABI bridge
PRODUCT_PACKAGES += \
    libSamsungCameraImageCodec \
    libSamsungCameraCore2NativeUtil \
    libSamsungCameraLegacyCameraUtils

# External JPEG node dynamically loads the stock squeezing engine.
PRODUCT_PACKAGES += \
    SamsungCameraMediaPublicLibraries \
    libSamsungCameraJpegSqueezer \
    libSamsungCameraSavsCommon \
    libSamsungCameraPadm \
    libSamsungCameraSxqk
