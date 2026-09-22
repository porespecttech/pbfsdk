#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2026 <your name or company>
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Self-contained test suite for pbfio-sdk.

No external data files, no C++ binaries and no network are needed: every sample
file is generated on the fly. Run it directly or through ``tools/build.py``::

    python tests/test_sdk.py

The published package intentionally contains no ABF support. The conformance
sample under ``test_data/`` is checked only when running from a checkout.
"""

import hashlib
import io
import os
import struct
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, "src"))
import pbfio_sdk as pbfIO  # noqa: E402

#: the complete public API of this package
EXPECTED_API = [
    "pbfHeader", "readPBFHeader", "readPBFCurrents", "writePBFFile",
    "readPBFFile", "readPBFVoltage", "readTxtFile", "bfReader",
    "setPBFSampleRate", "mergePBFFiles", "setVerbose", "getVerbose",
]

FAILS = []
SKIPS = []


def check(name, cond, detail=""):
    print("%-58s %s %s" % (name, "OK" if cond else "FAIL", detail if not cond else ""))
    if not cond:
        FAILS.append(name)


def skip(name, why):
    print("%-58s SKIP (%s)" % (name, why))
    SKIPS.append(name)


def captureStderr(func):
    """Run func() with stderr captured, returning what it wrote."""
    old, buf = sys.stderr, io.StringIO()
    sys.stderr = buf
    try:
        func()
    finally:
        sys.stderr = old
    return buf.getvalue()


# --------------------------------------------------------------------------
# 1. public API surface and logging switches
# --------------------------------------------------------------------------
def test_api():
    missing = [n for n in pbfIO.__all__ if not hasattr(pbfIO, n)]
    check("api/every name in __all__ exists", not missing, str(missing))
    check("api/__version__", isinstance(pbfIO.__version__, str) and pbfIO.__version__)

    check("api/exports exactly the documented names",
          sorted(pbfIO.__all__) == sorted(EXPECTED_API),
          "extra=%s missing=%s" % (sorted(set(pbfIO.__all__) - set(EXPECTED_API)),
                                   sorted(set(EXPECTED_API) - set(pbfIO.__all__))))
    binaries = [f for f in os.listdir(os.path.dirname(pbfIO.__file__))
                if f.endswith((".so", ".pyd", ".dll"))]
    check("api/no binary artifacts next to the package", not binaries, str(binaries))

    pbfIO.VERBOSE = 0
    check("api/VERBOSE assignment", pbfIO.getVerbose() == 0)
    pbfIO.setVerbose(2)
    check("api/setVerbose", pbfIO.VERBOSE == 2 and pbfIO.getVerbose() == 2)
    pbfIO.VERBOSE = 1


# --------------------------------------------------------------------------
# 2. header round trip and unsupported versions
# --------------------------------------------------------------------------
def test_header(T):
    ph = pbfIO.pbfHeader("XBIN", 2, 20000, 100000, -5)
    path = os.path.join(T, "header.pbf")
    pbfIO.writePBFFile(ph, path, np.zeros(4, dtype=np.float32))

    with open(path, "rb") as f:
        raw = f.read(18)
    check("header/on-disk layout",
          raw[:4] == b"XBIN" and struct.unpack_from("<hiii", raw, 4) == (2, 20000, 100000, -5),
          raw.hex())

    with open(path, "rb") as f:
        back = pbfIO.readPBFHeader(f)
    check("header/round trip", back == ph and repr(back).startswith("pbfHeader("), repr(back))
    check("header/copy()", back.copy() == ph)

    # a short fileFlag is padded, and reading stops at the first \0 like C++
    ph2 = pbfIO.pbfHeader("AB", 2, 1, 1, 0)
    p2 = os.path.join(T, "shortflag.pbf")
    pbfIO.writePBFFile(ph2, p2, np.zeros(1, dtype=np.float32))
    with open(p2, "rb") as f:
        head = pbfIO.readPBFHeader(f)
    check("header/short fileFlag padded with \\0", head.fileFlag == "AB", repr(head.fileFlag))

    tiny = os.path.join(T, "tiny.bin")
    with open(tiny, "wb") as f:
        f.write(b"XY")
    try:
        with open(tiny, "rb") as f:
            pbfIO.readPBFHeader(f)
        raised = False
    except ValueError:
        raised = True
    check("header/truncated header raises ValueError", raised)


def test_unsupported_version(T):
    """High level readers/writers only accept PBF version 2."""
    path = os.path.join(T, "badversion.pbf")
    ph = pbfIO.pbfHeader("XBIN", 0, 20000, 1000, 0)

    try:
        pbfIO.writePBFFile(ph, path, np.zeros(2, dtype=np.float32))
        raised = None
    except NotImplementedError as exc:
        raised = str(exc)
    check("version/writer rejects version != 2", raised is not None and "version 2" in raised,
          str(raised))

    with open(path, "wb") as f:
        f.write(struct.pack("<4shiii", b"XBIN", 0, 20000, 1000, 0))
        f.write(np.zeros(2, dtype=np.float32).tobytes())
        f.write(struct.pack("<q", 18 + 4 * 2))
    try:
        pbfIO.readPBFFile(path)
        raised = None
    except NotImplementedError as exc:
        raised = str(exc)
    check("version/reader rejects version != 2", raised is not None and "version 2" in raised,
          str(raised))


# --------------------------------------------------------------------------
# 3. currents and voltage records
# --------------------------------------------------------------------------
def test_roundtrip(T):
    data = (np.arange(1000, dtype=np.float64) * 0.5 - 100.0)
    idx = [0, 100, 500, 999]
    val = [-200, -500, 300, 0]
    ph = pbfIO.pbfHeader("XBIN", 2, 20000, 100000, 0)
    path = os.path.join(T, "round.pbf")
    endPos = pbfIO.writePBFFile(ph, path, data, idx, val)

    check("roundtrip/endPos = 18 + 4*N", endPos == 18 + 4 * data.size, str(endPos))
    size = os.path.getsize(path)
    check("roundtrip/file size = endPos + 10*M + 8",
          size == endPos + 10 * len(idx) + 8, "%d vs %d" % (size, endPos + 10 * len(idx) + 8))
    check("roundtrip/currents are float32",
          pbfIO.readPBFFile(path)[0].dtype == np.float32)

    back, sr = pbfIO.readPBFFile(path)
    check("roundtrip/current values",
          np.array_equal(back, data.astype(np.float32)) and sr == 100000)

    vi, vv = pbfIO.readPBFVoltage(path)
    check("roundtrip/voltage records", list(vi) == idx and list(vv) == val
          and vi.dtype == np.int64 and vv.dtype == np.int16)
    check("roundtrip/voltage not mixed into currents", back.size == data.size)

    # without explicit records one placeholder (0, 0) is written, like C++
    p2 = os.path.join(T, "plain.pbf")
    pbfIO.writePBFFile(ph, p2, data)
    vi2, vv2 = pbfIO.readPBFVoltage(p2)
    check("roundtrip/placeholder record when no voltage given",
          list(vi2) == [0] and list(vv2) == [0], "%s %s" % (list(vi2), list(vv2)))
    check("roundtrip/currents unaffected by placeholder",
          np.array_equal(pbfIO.readPBFFile(p2)[0], data.astype(np.float32)))

    # mismatched lengths are tolerated (C++ would read out of bounds)
    p3 = os.path.join(T, "mismatch.pbf")
    err = captureStderr(lambda: pbfIO.writePBFFile(ph, p3, data, [1, 2, 3], [7]))
    vi3, _ = pbfIO.readPBFVoltage(p3)
    check("roundtrip/mismatched vIndex/vValue warns and truncates",
          len(vi3) == 1 and "different lengths" in err, "%s | %s" % (list(vi3), err.strip()))
    try:
        pbfIO.writePBFFile(ph, p3, data, [1], None)
        raised = False
    except ValueError:
        raised = True
    check("roundtrip/vIndex without vValue raises", raised)

    # reading currents from an in-memory file object
    with open(p2, "rb") as f:
        raw = f.read(18 + 4 * 5)
    bio = io.BytesIO(raw)
    h = pbfIO.readPBFHeader(bio)
    vals = pbfIO.readPBFCurrents(bio, 5)
    check("roundtrip/BytesIO support", h.fileFlag == "XBIN" and vals.size == 5)


# --------------------------------------------------------------------------
# 4. edge cases of the tail pointer
# --------------------------------------------------------------------------
def test_edges(T):
    def writeRaw(name, currents, tailValue):
        p = os.path.join(T, name)
        with open(p, "wb") as f:
            f.write(struct.pack("<4shiii", b"XBIN", 2, 20000, 50000, 0))
            f.write(np.asarray(currents, dtype="<f4").tobytes())
            f.write(struct.pack("<q", tailValue))
        return p

    data = np.arange(10, dtype=np.float32)

    p = writeRaw("novolt.pbf", data, 18 + 4 * 10)
    cur, sr = pbfIO.readPBFFile(p)
    check("edge/no voltage block (endPos == size-8)",
          cur.size == 10 and sr == 50000 and np.array_equal(cur, data))

    p = writeRaw("zerotail.pbf", data, 0)
    cur, _ = pbfIO.readPBFFile(p)
    check("edge/dcInfoBegin == 0 handled", cur.size == 10 and np.array_equal(cur, data))

    p = writeRaw("badptr.pbf", data, 9)
    cur, _ = pbfIO.readPBFFile(p)
    check("edge/dcInfoBegin inside header handled", cur.size == 10 and np.array_equal(cur, data))

    p = writeRaw("badptr2.pbf", data, 10 ** 9)
    cur, _ = pbfIO.readPBFFile(p)
    check("edge/dcInfoBegin beyond EOF handled", cur.size == 10 and np.array_equal(cur, data))

    # truncated data area: only what is really there is returned
    p = os.path.join(T, "trunc.pbf")
    with open(p, "wb") as f:
        f.write(struct.pack("<4shiii", b"XBIN", 2, 20000, 50000, 0))
        f.write(np.arange(100, dtype=np.float32).tobytes()[:40 * 4])
        f.write(struct.pack("<q", 18 + 4 * 100))
    cur, _ = pbfIO.readPBFFile(p)
    check("edge/truncated data area",
          cur.size == 40 and np.array_equal(cur, np.arange(40, dtype=np.float32)),
          "n=%d" % cur.size)


# --------------------------------------------------------------------------
# 5. text files
# --------------------------------------------------------------------------
def test_txt(T):
    cases = {
        "plain": ("0.0 1.5\n0.0001 2.5\n0.0002 -3.25\n0.0003 4.0\n", 4, 10000,
                  [1.5, 2.5, -3.25, 4.0]),
        "tabs_extra": ("0\t1.5\tx\n0.0001\t2.5\ty\n0.0002\t-3.25\tz\n", 3, 10000,
                       [1.5, 2.5, -3.25]),
        "trailing_incomplete": ("0.0 1.5\n0.0001 2.5\n0.0002 3.5\n0.0003\n", 3, 10000,
                                [1.5, 2.5, 3.5]),
        "bad_middle": ("0.0 1.5\n0.0001 2.5\nnot data\n0.0002 3.5\n", 3, 10000,
                       [1.5, 2.5, 3.5]),
        "sci": ("0.0e0 1.0\n5e-5 2.0\n1e-4 3.0\n", 3, 20000, [1.0, 2.0, 3.0]),
        "header_line": ("time current\n0.0 1.0\n0.0001 2.0\n", 2, 10000, [1.0, 2.0]),
    }
    for name, (text, n, rate, values) in cases.items():
        p = os.path.join(T, "txt_%s.txt" % name)
        with open(p, "w") as f:
            f.write(text)
        cur, sr = pbfIO.readTxtFile(p)
        check("txt/%s" % name,
              cur.size == n and sr == rate and np.allclose(cur, values, atol=1e-6),
              "n=%d sr=%d %s" % (cur.size, sr, cur.tolist()))

    p = os.path.join(T, "txt_onecol.txt")
    with open(p, "w") as f:
        f.write("1.0\n2.0\n3.0\n")
    cur, sr = pbfIO.readTxtFile(p)
    check("txt/single column is rejected", cur.size == 0 and sr == 0)


# --------------------------------------------------------------------------
# 6. merge and sample rate patching
# --------------------------------------------------------------------------
def test_merge_and_rate(T):
    ph = pbfIO.pbfHeader("XBIN", 2, 20000, 100000, 0)
    p1, p2 = os.path.join(T, "m1.pbf"), os.path.join(T, "m2.pbf")
    pbfIO.writePBFFile(ph, p1, np.ones(100, dtype=np.float32), [5], [-100])
    ph2 = pbfIO.pbfHeader("XBIN", 2, 20000, 50000, 0)          # different rate
    pbfIO.writePBFFile(ph2, p2, np.full(50, 2.0, dtype=np.float32), [7], [-200])

    out = os.path.join(T, "merged.pbf")
    err = captureStderr(lambda: pbfIO.mergePBFFiles(out, [p1, p2]))
    cur, sr = pbfIO.readPBFFile(out)
    idx, val = pbfIO.readPBFVoltage(out)
    check("merge/count and header from first file",
          cur.size == 150 and sr == 100000 and cur[:100].sum() == 100 and cur[100:].sum() == 100)
    check("merge/voltage indices are shifted", list(idx) == [5, 107] and list(val) == [-100, -200])
    check("merge/sample rate mismatch only warns", "mismatch" in err, err.strip())

    try:
        pbfIO.mergePBFFiles(out, [])
        raised = False
    except ValueError:
        raised = True
    check("merge/empty input list raises", raised)

    p = os.path.join(T, "rate.pbf")
    pbfIO.writePBFFile(ph, p, np.arange(10, dtype=np.float32))
    before = open(p, "rb").read()
    old, new = pbfIO.setPBFSampleRate(p, 12345)
    after = open(p, "rb").read()
    check("setRate/only 4 bytes change",
          old == 100000 and new == 12345 and len(before) == len(after)
          and before[:10] == after[:10] and before[14:] == after[14:])
    old2, _ = pbfIO.setPBFSampleRate(p, 12345)
    check("setRate/already set is a no-op", old2 == 12345 and open(p, "rb").read() == after)
    try:
        pbfIO.setPBFSampleRate(p, 0)
        raised = False
    except ValueError:
        raised = True
    check("setRate/invalid rate raises", raised)


# --------------------------------------------------------------------------
# 7. bfReader dispatch
# --------------------------------------------------------------------------
def test_dispatch(T):
    data = np.arange(50, dtype=np.float32)
    ph = pbfIO.pbfHeader("XBIN", 2, 20000, 12345, 0)
    p = os.path.join(T, "dispatch.pbf")
    pbfIO.writePBFFile(ph, p, data)

    cur, sr = pbfIO.bfReader(p)
    check("dispatch/.pbf", cur.size == 50 and sr == 12345 and cur.dtype == np.float32)

    t = os.path.join(T, "dispatch.txt")
    with open(t, "w") as f:
        f.write("0.0 1.0\n0.0001 2.0\n")
    cur, sr = pbfIO.bfReader(t)
    check("dispatch/.txt", cur.size == 2 and sr == 10000)

    unknown = os.path.join(T, "dispatch.dat")
    with open(unknown, "w") as f:
        f.write("0.0 1.0\n0.0001 2.0\n")
    cur, sr = pbfIO.bfReader(unknown)
    check("dispatch/unknown extension falls back to text", cur.size == 2 and sr == 10000)

    abf = os.path.join(T, "dispatch.abf")
    with open(abf, "wb") as f:
        f.write(b"ABF " + b"\x00" * 100)
    try:
        pbfIO.bfReader(abf)
        raised = None
    except NotImplementedError as exc:
        raised = str(exc)
    check("dispatch/.abf is rejected with a clear message",
          raised is not None and ".pbf" in raised and ".txt" in raised, str(raised))


# --------------------------------------------------------------------------
# 8. logging behaviour
# --------------------------------------------------------------------------
def test_logging(T):
    data = np.arange(100, dtype=np.float32)
    ph = pbfIO.pbfHeader("XBIN", 2, 20000, 1000, 0)
    p = os.path.join(T, "log.pbf")
    pbfIO.writePBFFile(ph, p, data)

    pbfIO.VERBOSE = 0
    quiet = captureStderr(lambda: (pbfIO.readPBFFile(p), pbfIO.readPBFVoltage(p)))
    check("logging/VERBOSE=0 is silent", quiet == "", repr(quiet))

    pbfIO.VERBOSE = 1
    loud = captureStderr(lambda: pbfIO.readPBFFile(p))
    check("logging/VERBOSE=1 explains what it reads",
          "[PBFHeader]" in loud and "[INFO] Read 100 current values" in loud)

    pbfIO.VERBOSE = 2
    verbose = captureStderr(lambda: pbfIO.readPBFVoltage(p))
    check("logging/VERBOSE=2 lists records", verbose.count("0 0") >= 1)
    pbfIO.VERBOSE = 1

    # warnings are printed even when VERBOSE is 0
    bad = os.path.join(T, "warn.txt")
    with open(bad, "w") as f:
        f.write("1.0\n2.0\n")
    pbfIO.VERBOSE = 0
    warned = captureStderr(lambda: pbfIO.readTxtFile(bad))
    pbfIO.VERBOSE = 1
    check("logging/warnings ignore VERBOSE", "[pbfIO][WARN]" in warned, repr(warned))


# --------------------------------------------------------------------------
# 9. published conformance sample (only present in a checkout)
# --------------------------------------------------------------------------
def test_conformance_sample():
    """Validate test_data/sample_v2.pbf against the values documented in
    test_data/README.md. Skipped when the tests run against an installed wheel,
    which does not ship the data directory."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir,
                        "test_data", "sample_v2.pbf")
    if not os.path.isfile(path):
        skip("conformance/sample_v2.pbf", "not in a checkout")
        return

    expectedSize = 17039396
    expectedCount = 4259840
    expectedSha256 = ("a71314313b77165265abd0fa9bb46f07d5d2e463540d62557f"
                      "ecc6f763c5f58a")
    check("conformance/file size and identity",
          os.path.getsize(path) == expectedSize
          and hashlib.sha256(open(path, "rb").read()).hexdigest() == expectedSha256,
          "size=%d" % os.path.getsize(path))

    with open(path, "rb") as f:
        header = pbfIO.readPBFHeader(f)
    check("conformance/header fields",
          (header.fileFlag, header.version, header.mRange, header.sampleRate,
           header.Ioffset) == ("XBIN", 2, 20000, 1000000, 0), repr(header))

    data, sampleRate = pbfIO.readPBFFile(path)
    check("conformance/sample block",
          sampleRate == 1000000 and data.size == expectedCount
          and data[0].view("<u4") == 0x412860ca
          and data[-1].view("<u4") == 0x3fe4961f
          and float(data.sum()) == 7370992.5,
          "n=%s first=%s last=%s sum=%s" % (data.size, data[0], data[-1],
                                            float(data.sum())))

    indices, values = pbfIO.readPBFVoltage(path)
    check("conformance/voltage records",
          indices.tolist() == [0] and values.tolist() == [0],
          "%s %s" % (indices.tolist(), values.tolist()))
    check("conformance/layout",
          expectedSize == 18 + 4 * expectedCount + 10 * 1 + 8)


def main():
    T = tempfile.mkdtemp(prefix="pbfio_test_")
    print("temp dir: %s\n" % T)
    try:
        test_api()
        test_header(T)
        test_unsupported_version(T)
        test_roundtrip(T)
        test_edges(T)
        test_txt(T)
        test_merge_and_rate(T)
        test_dispatch(T)
        test_logging(T)
        test_conformance_sample()
    finally:
        import shutil
        shutil.rmtree(T, ignore_errors=True)

    print("\n%d checks failed, %d skipped" % (len(FAILS), len(SKIPS)))
    if FAILS:
        print("FAILED:", FAILS)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
