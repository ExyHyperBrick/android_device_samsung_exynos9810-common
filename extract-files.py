#!/usr/bin/env -S PYTHONPATH=../../../tools/extract-utils python3
#
# SPDX-FileCopyrightText: 2024 The LineageOS Project
# SPDX-FileCopyrightText: 2026 The LineageOS Project
# SPDX-License-Identifier: Apache-2.0
#

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

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

# Apply the bounded HFD copy during extraction and accept its fixed form.
_hfd_spec = spec_from_file_location(
    'exynos9810_hfd_chroma',
    Path(__file__).parent / 'camera' / 'fixups' / 'patch_hfd_chroma.py',
)
_hfd_fixup = module_from_spec(_hfd_spec)
_hfd_spec.loader.exec_module(_hfd_fixup)

blob_fixups: blob_fixups_user_type = {
    'vendor/lib/libhfd.so': blob_fixup()
        .call(_hfd_fixup.fixup, need_tmp_dir=False),
    'system_ext/lib64/libsecimaging.camera.samsung.so': blob_fixup()
        .clear_symbol_version('jniThrowException')
        .clear_symbol_version('jniThrowExceptionFmt')
        .replace_needed('libnativehelper.so', 'libnativehelper_compat_libc++.so'),
    'system_ext/lib64/libOpenCv.camera.samsung.so': blob_fixup()
        .add_needed('libcompiler_rt.so'),
    'system_ext/lib64/libcore2nativeutil.camera.samsung.so': blob_fixup()
        .clear_symbol_version('jniThrowException')
        .clear_symbol_version('jniThrowExceptionFmt')
        .clear_symbol_version('jniThrowNullPointerException')
        .add_needed('libSamsungCameraLegacyCameraUtils.so')
        .replace_needed('libnativehelper.so', 'libnativehelper_compat_libc++.so'),

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

# The camera inputs are transformed after extraction has copied both JARs.
_camera_spec = spec_from_file_location(
    'exynos9810_camera_prepare',
    Path(__file__).parent / 'camera' / 'prepare_vendor_camera.py',
)
_camera_prepare = module_from_spec(_camera_spec)
_camera_spec.loader.exec_module(_camera_prepare)
module.proprietary_files[0].add_post_makefile_generation_fn(
    _camera_prepare.prepare_vendor_camera,
)

if __name__ == '__main__':
    utils = ExtractUtils.device(module)
    utils.run()
