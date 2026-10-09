# SPDX-FileCopyrightText: 2026 The LineageOS Project
# SPDX-License-Identifier: Apache-2.0

"""Rebuild raw camera inputs and restore authored vendor build definitions."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile


def prepare_vendor_camera(ctx, _packages_ctx):
    from extract_utils.tools import android_root, apktool_path, java_path

    common = Path(__file__).resolve().parent
    vendor = Path(ctx.bp_out.name).resolve().parent
    proprietary = vendor / "proprietary"
    apk = proprietary / "system_ext/priv-app/SamsungCameraExynos9810/SamsungCameraExynos9810.apk"
    with zipfile.ZipFile(apk) as archive:
        marker = "assets/lineage_samsung_camera.json"
        legacy_marker = "assets/lineage_stock_camera_test.json"
        transformed = marker in archive.namelist()
        if legacy_marker in archive.namelist() or (transformed and
                json.loads(archive.read(marker)).get("port") != 13):
            raise RuntimeError("Camera payload needs runtime fixes. Re-extract "
                               "stock inputs or apply the matching vendor patch.")
    if not transformed:
        with tempfile.TemporaryDirectory(prefix="stock-camera-extract-") as temporary:
            output = Path(temporary) / "camera.apk"
            subprocess.run([
                sys.executable, str(common / "tools/transform_camera.py"),
                "--apk", str(apk),
                "--secimaging", str(proprietary / "system_ext/camera-inputs/secimaging.jar"),
                "--semextendedformat", str(proprietary / "system_ext/camera-inputs/semextendedformat.jar"),
                "--sprengine", str(proprietary / "system_ext/camera-inputs/sprengine.jar"),
                "--aosp-framework", str(Path(android_root) / "prebuilts/sdk/35/public/android.jar"),
                "--apktool", str(apktool_path), "--java", str(java_path),
                "--out", str(output),
            ], check=True)
            shutil.copyfile(output, apk)
    source = common / "vendor"
    blueprint = source / "Android.bp.in"
    if not blueprint.is_file():
        raise FileNotFoundError(f"Missing camera build template: {blueprint}")
    for item in sorted(source.rglob("*")):
        if item.is_file():
            relative = item.relative_to(source)
            if relative.name == "Android.bp.in":
                relative = relative.with_name("Android.bp")
            target = vendor / "camera" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item, target)
