#!/usr/bin/env python3

# Copyright (c) 2026 <your name or company>
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Merge several PBF files and print the resulting voltage change points:
python 04_merge_and_voltage.py out.pbf a.pbf b.pbf"""
import sys
import pbfio_sdk as pbfIO

out = sys.argv[1]
inputs = sys.argv[2:]

total = pbfIO.mergePBFFiles(out, inputs)
print("merged %d points -> %s" % (total, out))

indices, values = pbfIO.readPBFVoltage(out)
for i, v in zip(indices.tolist(), values.tolist()):
    print("  point %d -> %d" % (i, v))
