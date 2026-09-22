#!/usr/bin/env python3

# Copyright (c) 2026 <your name or company>
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Export a PBF file as two columns of text (time, current), optionally
downsampled: python 02_pbf_to_tsv.py demo.pbf [out.tsv] [step]"""
import sys
import pbfio_sdk as pbfIO

src = sys.argv[1]
dst = sys.argv[2] if len(sys.argv) > 2 else src.rsplit(".", 1)[0] + ".tsv"
step = int(sys.argv[3]) if len(sys.argv) > 3 else 1

pbfIO.VERBOSE = 0                       # keep stderr quiet
data, sampleRate = pbfIO.readPBFFile(src)
dt = step / float(sampleRate)

with open(dst, "w") as out:
    for i in range(0, data.size, step):
        out.write("%.6f\t%.6f\n" % (i * dt, data[i]))
print("wrote %s (%d points, sampleRate=%d)"
      % (dst, (data.size + step - 1) // step, sampleRate))
