# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2022 The LineageOS Project

LOCAL_PATH := $(call my-dir)

include $(CLEAR_VARS)

LOCAL_SRC_FILES := ASensorManager.cpp
LOCAL_SHARED_LIBRARIES := \
    libbase \
    libsensorndkbridge
LOCAL_MODULE := libshim_sensorndkbridge
LOCAL_MODULE_TAGS := optional
LOCAL_MODULE_CLASS := SHARED_LIBRARIES
LOCAL_VENDOR_MODULE := true

LOCAL_C_INCLUDES += system/core/base/include
LOCAL_C_INCLUDES += system/core/libutils/include
LOCAL_C_INCLUDES += frameworks/hardware/interfaces/sensorservice/libsensorndkbridge

include $(BUILD_SHARED_LIBRARY)
