#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The LineageOS Project
# SPDX-License-Identifier: Apache-2.0

"""Append freshly compiled app-local compatibility DEX to the camera APK."""

import argparse
import re
import zipfile


def dex_index(name):
    match = re.fullmatch(r"classes(\d*)\.dex", name)
    return int(match[1] or 1) if match else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", required=True)
    parser.add_argument("--compat-dex-jar", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    with zipfile.ZipFile(args.apk) as apk, zipfile.ZipFile(args.compat_dex_jar) as compat:
        apk_dex = [dex_index(name) for name in apk.namelist() if dex_index(name)]
        new_dex = sorted((name for name in compat.namelist() if dex_index(name)),
                         key=dex_index)
        if not apk_dex or not new_dex:
            raise ValueError("Both the camera APK and compatibility JAR must contain DEX")
        with zipfile.ZipFile(args.out, "w") as output:
            for item in apk.infolist():
                if item.filename.upper().startswith("META-INF/") and item.filename.upper().endswith(
                        (".RSA", ".DSA", ".EC", ".SF", "MANIFEST.MF")):
                    continue
                output.writestr(item, apk.read(item))
            for index, name in enumerate(new_dex, max(apk_dex) + 1):
                info = zipfile.ZipInfo(f"classes{index}.dex", (2009, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_STORED
                output.writestr(info, compat.read(name))


if __name__ == "__main__":
    main()
