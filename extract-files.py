#!/usr/bin/env -S PYTHONPATH=../../../tools/extract-utils python3
#
# SPDX-FileCopyrightText: 2024 The LineageOS Project
# SPDX-FileCopyrightText: 2026 The LineageOS Project
# SPDX-License-Identifier: Apache-2.0
#

from extract_utils.fixups_blob import (
    blob_fixup,
    blob_fixups_user_type,
)

from extract_utils.fixups_lib import (
    lib_fixup_remove,
    lib_fixup_remove_arch_suffix,
    lib_fixups,
    lib_fixups_user_type,
    lib_fixup_vendorcompat,
    libs_clang_rt_ubsan,
    libs_proto_3_9_1,
    libs_proto_unversioned,
)

from extract_utils.main import (
    ExtractUtils,
    ExtractUtilsModule,
)

namespace_imports = [
    'device/samsung/exynos9810-common',
    'hardware/samsung',
    'hardware/samsung_slsi-linaro/graphics',
    'hardware/samsung_slsi-linaro/interfaces',
    'hardware/samsung_slsi-linaro/exynos',
]

libs_remove = (
    'libkeymaster_helper_vendor',
    'libOpenCL',
    'libopenvx',
    'libwrappergps',
    'libwvhidl',
    'sound_trigger.primary.exynos9810',
)

dolby_libs = {
    'libmtdap': 'exynos9810_moto_dap',
    'libmtpparamstorage': 'exynos9810_moto_dap_params',
    'libmtbpreg': 'exynos9810_moto_dap_preg',
    'libmtagefright_foundation': 'exynos9810_moto_stagefright_compat',
    'vendor.motod.hardware.dms@2.0': 'exynos9810_moto_dms_interface',
    'libmtbdsservice': 'exynos9810_moto_dms_engine',
    'libmtlite': 'exynos9810_moto_sqlite_compat',
    'vendor.motod.hardware.dms@2.0-impl': 'exynos9810_moto_dms_impl',
}


def lib_fixup_dolby(lib: str, partition: str):
    return dolby_libs[lib] if partition == 'vendor' else lib


lib_fixups: lib_fixups_user_type = {
    tuple(dolby_libs): lib_fixup_dolby,
    libs_clang_rt_ubsan: lib_fixup_remove_arch_suffix,
    libs_proto_3_9_1: lib_fixup_vendorcompat,
    libs_proto_unversioned: lib_fixup_vendorcompat,
    libs_remove: lib_fixup_remove,
}

blob_fixups: blob_fixups_user_type = {
    # Keep the private library names and data paths used by the existing port.
    # Same-length replacements preserve the layout of the pinned firmware ELFs.
    (
        'vendor/bin/hw/vendor.motod.hardware.dms@2.0-service',
        'vendor/lib/libmtagefright_foundation.so',
        'vendor/lib/libmtbpreg.so',
        'vendor/lib/libmtpparamstorage.so',
        'vendor/lib/soundfx/libmtdap.so',
        'vendor/lib/vendor.motod.hardware.dms@2.0.so',
        'vendor/lib64/libmtagefright_foundation.so',
        'vendor/lib64/libmtbdsservice.so',
        'vendor/lib64/libmtbpreg.so',
        'vendor/lib64/libmtlite.so',
        'vendor/lib64/libmtpparamstorage.so',
        'vendor/lib64/soundfx/libmtdap.so',
        'vendor/lib64/vendor.motod.hardware.dms@2.0-impl.so',
        'vendor/lib64/vendor.motod.hardware.dms@2.0.so',
    ): blob_fixup()
        .binary_regex_replace(b'libswdap\\.so', b'libmtdap.so')
        .binary_regex_replace(b'libdapparamstorage\\.so', b'libmtpparamstorage.so')
        .binary_regex_replace(b'libdlbpreg\\.so', b'libmtbpreg.so')
        .binary_regex_replace(b'libstagefright_foundation\\.so', b'libmtagefright_foundation.so')
        .binary_regex_replace(
            b'vendor\\.dolby\\.hardware\\.dms@2\\.0\\.so',
            b'vendor.motod.hardware.dms@2.0.so',
        )
        .binary_regex_replace(b'libdlbdsservice\\.so', b'libmtbdsservice.so')
        .binary_regex_replace(b'libsqlite\\.so', b'libmtlite.so')
        .binary_regex_replace(
            b'vendor\\.dolby\\.hardware\\.dms@2\\.0\\-impl\\.so',
            b'vendor.motod.hardware.dms@2.0-impl.so',
        )
        .binary_regex_replace(b'/data/vendor/dolby', b'/data/vendor/motod')
        .binary_regex_replace(b'/vendor/etc/dolby', b'/vendor/etc/motod'),
    'vendor/etc/motod/dax-default.xml': blob_fixup()
        .regex_replace(
            '<volume-leveler-enable value="true"/>',
            '<volume-leveler-enable value="false"/>',
        )
        .patch_file('audio/dolby/dax-default'),
    'vendor/etc/media_profiles_V1_0.xml': blob_fixup()
        .regex_replace(
            r'(?s)(?!.*<CamcorderProfiles cameraId="(?:3|50)">)'
            r'(<CamcorderProfiles cameraId="2">)(.*?)(</CamcorderProfiles>)',
            r'\1\2\3\n\n'
            r'    <!-- Auxiliary Camera (enumeration index) -->\n'
            r'    <CamcorderProfiles cameraId="3">\2</CamcorderProfiles>\n\n'
            r'    <!-- Auxiliary Camera (public ID) -->\n'
            r'    <CamcorderProfiles cameraId="50">\2</CamcorderProfiles>',
        ),
    (
        'vendor/lib/libsensorlistener.so',
        'vendor/lib64/libsensorlistener.so',
    ): blob_fixup()
        .add_needed('libshim_sensorndkbridge.so'),
    (
        'vendor/lib/sensors.bio.so',
        'vendor/lib64/sensors.bio.so',
        'vendor/lib/sensors.grip.so',
        'vendor/lib64/sensors.grip.so',
    ): blob_fixup()
        .add_needed('libutils-v32.so'),
}

module = ExtractUtilsModule(
    'exynos9810-common',
    'samsung',
    blob_fixups=blob_fixups,
    lib_fixups=lib_fixups,
    namespace_imports=namespace_imports,
)

if __name__ == '__main__':
    utils = ExtractUtils.device(module)
    utils.run()
