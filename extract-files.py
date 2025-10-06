#!/usr/bin/env -S PYTHONPATH=../../../tools/extract-utils python3
#
# SPDX-FileCopyrightText: 2024 The LineageOS Project
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

lib_fixups: lib_fixups_user_type = {
    libs_clang_rt_ubsan: lib_fixup_remove_arch_suffix,
    libs_proto_3_9_1: lib_fixup_vendorcompat,
    libs_proto_unversioned: lib_fixup_vendorcompat,
    libs_remove: lib_fixup_remove,
}

blob_fixups: blob_fixups_user_type = {
    (
        'vendor/lib/libsensorlistener.so',
        'vendor/lib64/libsensorlistener.so',
    ): blob_fixup()
        .add_needed('libshim_sensorndkbridge.so'),
    'vendor/lib64/libsensorlistener.so': blob_fixup()
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
