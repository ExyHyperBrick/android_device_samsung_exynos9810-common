# SPDX-FileCopyrightText: 2026 The LineageOS Project
# SPDX-License-Identifier: Apache-2.0

"""Use an adaptive camera icon without the legacy bitmap's second mask."""

from pathlib import Path
import shutil

ANDROID = "{http://schemas.android.com/apk/res/android}"


def adapt_launcher_icon(decoded, application):
    resources = Path(__file__).resolve().parent.parent / "resources/res"
    shutil.copytree(resources, Path(decoded) / "res", dirs_exist_ok=True)
    icon = "@mipmap/lineage_camera_icon"
    application.set(ANDROID + "icon", icon)
    application.set(ANDROID + "roundIcon", icon)
    targets = {"com.sec.android.app.camera.Camera",
               "com.sec.android.app.camera.LauncherActivity"}
    components = [node for node in application
                  if node.get(ANDROID + "name") in targets]
    if len(components) != 2:
        raise ValueError("Expected Camera and its launcher alias for icon update")
    for node in components:
        node.set(ANDROID + "icon", icon)
