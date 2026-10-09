#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The LineageOS Project
# SPDX-License-Identifier: Apache-2.0

"""Bound the stock ARM HFD chroma copy to its allocated plane size."""

from pathlib import Path
import struct
import sys

# HFD_CnnPreProcess::CropAndReplicateIfNeeded(int), Thumb code at 0xa640.
# The stock loop reads 32 interleaved bytes and writes 16 bytes per plane,
# including when fewer than 16 plane bytes remain. The replacement from
# hfd_chroma_copy.S copies exactly r5 bytes to each plane and preserves
# the following delete[](r10). Its size and all surrounding code stay fixed.
ORIGINAL = bytes.fromhex(
    "0020b0eb560f0ed00020514661f90d0308eb0002"
    "0beb00031030a84243f90f0a42f90f2af2d3"
)
REPLACEMENT = bytes.fromhex(
    "0020514642465b46a8420cd211f801cb03f801cb"
    "11f801cb02f801cb0130a842f4d300bf00bf"
)


def _occurrences(data, pattern):
    result = []
    start = 0
    while True:
        offset = data.find(pattern, start)
        if offset < 0:
            return result
        result.append(offset)
        start = offset + 1


def _executable_ranges(data):
    if len(data) < 52 or data[:7] != b"\x7fELF\x01\x01\x01":
        raise ValueError("HFD chroma fix requires a little-endian ELF32")
    header = struct.unpack_from("<16sHHIIIIIHHHHHH", data)
    if header[2] != 40 or header[3] != 1:
        raise ValueError("HFD chroma fix requires an ARM ELF")
    phoff, phentsize, phnum = header[5], header[9], header[10]
    if phentsize < 32 or phoff + phentsize * phnum > len(data):
        raise ValueError("HFD chroma fix found invalid ELF program headers")
    ranges = []
    for index in range(phnum):
        entry = struct.unpack_from("<IIIIIIII", data, phoff + phentsize * index)
        kind, offset, size, flags = entry[0], entry[1], entry[4], entry[6]
        if offset + size > len(data):
            raise ValueError("HFD chroma fix found an invalid ELF segment")
        if kind == 1 and flags & 1:
            ranges.append((offset, offset + size))
    return ranges


def patch_hfd(path):
    path = Path(path)
    data = path.read_bytes()
    ranges = _executable_ranges(data)
    original = _occurrences(data, ORIGINAL)
    replacement = _occurrences(data, REPLACEMENT)
    if len(original) + len(replacement) != 1:
        raise ValueError("HFD chroma fix: expected one stock or fixed code sequence")
    offset = (original or replacement)[0]
    if not any(start <= offset and offset + len(ORIGINAL) <= end
               for start, end in ranges):
        raise ValueError("HFD chroma fix: code sequence is outside executable data")
    if replacement:
        return False
    assert len(ORIGINAL) == len(REPLACEMENT)
    path.write_bytes(data[:offset] + REPLACEMENT + data[offset + len(ORIGINAL):])
    return True


def fixup(_ctx, _file, file_path, *_args, **_kwargs):
    patch_hfd(file_path)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: patch_hfd_chroma.py libhfd.so")
    print("HFD chroma copy patched" if patch_hfd(sys.argv[1])
          else "HFD chroma copy already patched")
