# SPDX-License-Identifier: Apache-2.0

PRODUCT_PACKAGES += \
    Exynos9810Dolby \
    exynos9810_moto_dap:32 \
    exynos9810_moto_dap:64 \
    exynos9810_moto_dap_params:32 \
    exynos9810_moto_dap_params:64 \
    exynos9810_moto_dap_preg:32 \
    exynos9810_moto_dap_preg:64 \
    exynos9810_moto_dms_interface:32 \
    exynos9810_moto_dms_interface:64 \
    exynos9810_moto_stagefright_compat:32 \
    exynos9810_moto_stagefright_compat:64 \
    exynos9810_moto_sqlite_compat:64 \
    exynos9810_moto_dms_engine:64 \
    exynos9810_moto_dms_impl:64 \
    exynos9810_moto_dms_service \
    exynos9810_moto_dax_config

PRODUCT_VENDOR_PROPERTIES += \
    vendor.dolby.dap.param.tee=false \
    vendor.dolby.mi.metadata.log=false
