#!/usr/bin/env python3

# Copyright (c) 2026 <your name or company>
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Print the header of a PBF file: python 01_read_header.py demo.pbf"""
import sys
import pbfio_sdk as pbfIO

with open(sys.argv[1], "rb") as f:
    h = pbfIO.readPBFHeader(f)

print("fileFlag   :", h.fileFlag)
print("version    :", h.version)
print("mRange     :", h.mRange)
print("sampleRate :", h.sampleRate)
print("Ioffset    :", h.Ioffset)
