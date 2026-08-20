# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 The LineageOS Project

EXYNOS9810_KERNEL_SOURCE := kernel/samsung/exynos9810
EXYNOS9810_USES_MAINLINE_KERNEL := $(if $(wildcard \
    $(EXYNOS9810_KERNEL_SOURCE)/drivers/video/fbdev/exynos9810-bootfb.c),true,false)
