#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The LineageOS Project
# SPDX-License-Identifier: Apache-2.0

"""Route the stock camera HAL's two legacy Fence imports to its private shim."""

from pathlib import Path

from extract_utils.tools import patchelf_version_path_map
from extract_utils.utils import run_cmd


def fixup(_ctx, _file, file_path, *_args, **_kwargs):
    run_cmd([
        patchelf_version_path_map['0_18'],
        '--rename-dynamic-symbols',
        str(Path(__file__).with_name('camera_fence_symbols.map')),
        file_path,
    ])
