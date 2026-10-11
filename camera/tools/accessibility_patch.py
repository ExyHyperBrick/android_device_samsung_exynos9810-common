# SPDX-FileCopyrightText: 2026 The LineageOS Project
# SPDX-License-Identifier: Apache-2.0

"""Describe the stock TalkBack helper separately from ordinary camera controls."""

from pathlib import Path
import xml.etree.ElementTree as ET

ANDROID = "{http://schemas.android.com/apk/res/android}"


def clarify_accessibility_service(decoded, application):
    services = [node for node in application.findall("service")
                if node.get(ANDROID + "name") ==
                "com.samsung.android.glview.AccessibilityGestureHandler"]
    if len(services) != 1:
        raise ValueError("Expected one Samsung Camera TalkBack helper")
    services[0].set(ANDROID + "label", "@string/lineage_camera_accessibility_title")
    config = Path(decoded) / "res/xml/talkbackconfig.xml"
    xml = ET.parse(config)
    if xml.getroot().tag != "accessibility-service":
        raise ValueError("Unexpected camera accessibility configuration")
    xml.getroot().set(ANDROID + "description",
                      "@string/lineage_camera_accessibility_description")
    xml.write(config, encoding="utf-8", xml_declaration=True)
