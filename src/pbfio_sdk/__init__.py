# -*- coding: utf-8 -*-
# Copyright (c) 2026 <your name or company>
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# ---------------------------------------------------------------------------
# pbfio-sdk -- package entry point.
# ---------------------------------------------------------------------------
"""pbfIO -- PBF / TXT reader-writer for electrophysiology data (Python).

This module is the Python counterpart of ``cpp_version/pbfIO.hpp`` +
``cpp_version/pbfIO.cpp``. Function names, argument meanings, on-disk byte
layout and stderr logging are kept identical to the C++ version, so the C++
tools and Python scripts can be mixed freely (e.g. a Python script calling the
C++ binaries through ``popen``).

PBF file layout (little-endian)::

    offset  size   content
    0       4      fileFlag    ASCII, e.g. "XBIN" (truncated at \\0 when read)
    4       2      version     int16, 2 = float32 layout (lower values are rejected)
    6       4      mRange      int32
    10      4      sampleRate  int32 (Hz)
    14      4      Ioffset     int32
    18      N*4    float32 current samples (version 2)
    ...     M*10   voltage change records: int64 point index + int16 value
    end     8      endPos      int64 = 18 + N*4, i.e. where the current block
                               ends and the voltage records start

Conventions and caveats:

* Currents are stored as float32, and that is what this module returns
  (memory friendly). Cast with ``.astype(np.float64)`` when you need more
  precision for calculations.
* All logging goes to stderr, like ``std::cerr`` in the C++ version.
  Module level switch ``VERBOSE``: 0 = silent, 1 = default, 2 = also print
  every voltage record. Warnings are printed regardless of ``VERBOSE``.
* Only PBF version 2 (float32 layout) is supported. Files with another
  version are rejected by :func:`readPBFFile`, :func:`readPBFVoltage`,
  :func:`writePBFFile`, :func:`setPBFSampleRate` and :func:`mergePBFFiles`.
* ABF reading and writing and the legacy function aliases are intentionally
  not part of this package.
"""

import os
import struct
import sys

import numpy as np

__version__ = "0.1.0"

__all__ = [
    # header / low level I/O (same names as the C++ version)
    "pbfHeader", "readPBFHeader", "readPBFCurrents", "writePBFFile",
    "readPBFFile", "readPBFVoltage", "readTxtFile", "bfReader",
    # PBF utilities (ported from cpp_version/pbfSetRate.cpp, pbfMerge.cpp)
    "setPBFSampleRate", "mergePBFFiles",
    # logging helpers
    "setVerbose", "getVerbose",
]

# ====== constants ======

PBF_HEADER_SIZE = 18          # 4(fileFlag) + 2(version) + 4(mRange) + 4(sampleRate) + 4(Ioffset)
VOLT_RECORD_SIZE = 10         # int64 point index + int16 voltage value
SAMPLE_RATE_OFFSET = 10       # fileFlag(4) + version(2)

_WRITE_CHUNK_BYTES = 1 << 24  # write in chunks, avoids a second full copy for big files

# log level: 0 silent / 1 default / 2 also print every voltage record
VERBOSE = 1


def _log(msg, level=1):
    """Log to stderr, the counterpart of C++ ``std::cerr``."""
    if VERBOSE >= level:
        sys.stderr.write(str(msg) + "\n")


def _warn(msg):
    """Warn about unexpected data; not affected by ``VERBOSE``."""
    sys.stderr.write("[pbfIO][WARN] " + str(msg) + "\n")


def _requireVersion2(header, action):
    """Reject PBF files this package cannot interpret correctly."""
    if int(header.version) != 2:
        raise NotImplementedError(
            "%s only supports PBF version 2 (float32 layout), got version %r"
            % (action, header.version))


def setVerbose(level):
    """Set the log level of this module: 0 silent, 1 default, 2 per record."""
    global VERBOSE
    VERBOSE = int(level)
    return VERBOSE


def getVerbose():
    """Return the current log level."""
    return int(VERBOSE)


# =====================================================================
#                          PBF header / low level I/O
# =====================================================================

class pbfHeader(object):
    """PBF file header (the counterpart of C++ ``struct PBFHeader``)."""

    def __init__(self, fileFlag, version, mRange, sampleRate, Ioffset):
        self.fileFlag = fileFlag
        self.version = version
        self.mRange = mRange
        self.sampleRate = sampleRate
        self.Ioffset = Ioffset

    def copy(self):
        return pbfHeader(self.fileFlag, self.version, self.mRange,
                         self.sampleRate, self.Ioffset)

    def __repr__(self):
        return ("pbfHeader(fileFlag=%r, version=%r, mRange=%r, sampleRate=%r, Ioffset=%r)"
                % (self.fileFlag, self.version, self.mRange,
                   self.sampleRate, self.Ioffset))

    def __eq__(self, other):
        if not isinstance(other, pbfHeader):
            return NotImplemented
        return (self.fileFlag == other.fileFlag and self.version == other.version
                and self.mRange == other.mRange and self.sampleRate == other.sampleRate
                and self.Ioffset == other.Ioffset)


def _packHeader(header):
    """Pack a PBFHeader into 18 bytes (same field order as C++ writePBFFile)."""
    flag = header.fileFlag
    if isinstance(flag, bytes):
        flag = flag.decode("ascii", "replace")
    flagBytes = flag.encode("ascii", "replace")[:4]
    if len(flagBytes) < 4:
        # C++ reads past the end of a short fileFlag; pad with \0 so it reads back
        _warn("fileFlag %r is shorter than 4 bytes, padding with \\0" % (flag,))
        flagBytes = flagBytes + b"\x00" * (4 - len(flagBytes))
    return struct.pack("<4shiii", flagBytes, int(header.version), int(header.mRange),
                       int(header.sampleRate), int(header.Ioffset))


def readPBFHeader(file):
    """Read the 18 byte PBF header from an open binary file.

    ``file`` only needs a ``read()`` method; its position advances by 18 bytes
    (counterpart of C++ ``readPBFHeader(std::ifstream&)``). This low level
    function does not validate ``version``; the high level readers do.
    """
    raw = file.read(PBF_HEADER_SIZE)
    if raw is None or len(raw) < PBF_HEADER_SIZE:
        raise ValueError("truncated PBF header: got %d bytes, need %d"
                         % (0 if raw is None else len(raw), PBF_HEADER_SIZE))

    # C++ builds a std::string from a char[5], so it stops at the first \0
    fileFlag = raw[:4].split(b"\x00")[0].decode("ascii", "replace")
    version, mRange, sampleRate, Ioffset = struct.unpack_from("<hiii", raw, 4)

    header = pbfHeader(fileFlag, version, mRange, sampleRate, Ioffset)
    _log("[PBFHeader] %s ver=%d range=%d rate=%d offset=%d"
         % (header.fileFlag, header.version, header.mRange,
            header.sampleRate, header.Ioffset))
    return header


def readPBFCurrents(file, count):
    """Read ``count`` float32 currents from the current position.

    Counterpart of C++ ``readPBFCurrents()``: a truncated file is zero padded
    to ``count`` samples, exactly like C++ ``std::vector<float>(count)``, and a
    warning is emitted.
    """
    count = int(count)
    if count < 0:
        raise ValueError("count must not be negative: %d" % count)
    if count == 0:
        return np.zeros(0, dtype=np.float32)

    try:
        data = np.fromfile(file, dtype="<f4", count=count)
    except (AttributeError, TypeError, OSError, ValueError):
        # objects without fileno() (e.g. BytesIO): fall back to read()
        raw = file.read(count * 4)
        data = np.frombuffer(raw if raw is not None else b"", dtype="<f4")

    if data.size < count:
        _warn("readPBFCurrents: wanted %d values but only %d were available "
              "(truncated file?)" % (count, data.size))
        padded = np.zeros(count, dtype=np.float32)
        padded[:data.size] = data
        data = padded
    return data


def writePBFFile(header, path, currents, vIndex=None, vValue=None):
    """Write a complete PBF file and return the written endPos (byte offset).

    Counterpart of C++ ``writePBFFile(header, path, currents, vIndex, vValue)``:

    * an empty ``vIndex`` writes one placeholder record (0, 0), as C++ does;
    * otherwise every entry is written as ``int64 index + int16 value``;
    * the trailing ``endPos = 18 + 4 * len(currents)`` finishes the file.
    """
    _requireVersion2(header, "writePBFFile")

    currents = np.ascontiguousarray(currents, dtype="<f4")
    nPoints = int(currents.size)
    endPos = PBF_HEADER_SIZE + 4 * nPoints

    with open(path, "wb") as file:
        file.write(_packHeader(header))
        _writeArray(file, currents)

        if vIndex is None or len(vIndex) == 0:
            if vValue is not None and len(vValue) > 0:
                _warn("writePBFFile: vValue given without vIndex, "
                      "voltage records are ignored")
            file.write(struct.pack("<qh", 0, 0))
        else:
            if vValue is None:
                raise ValueError("writePBFFile: vIndex requires vValue")
            vIndex = np.asarray(vIndex)
            vValue = np.asarray(vValue)
            nRec = min(vIndex.size, vValue.size)
            if vIndex.size != vValue.size:
                # C++ would read out of bounds; use the shorter length and warn
                _warn("writePBFFile: vIndex(%d) and vValue(%d) have different "
                      "lengths, writing only %d records"
                      % (vIndex.size, vValue.size, nRec))
            rec = np.empty(nRec, dtype=np.dtype([("i", "<i8"), ("v", "<i2")]))
            rec["i"] = vIndex[:nRec]
            rec["v"] = vValue[:nRec]
            _writeArray(file, rec)

        file.write(struct.pack("<q", endPos))

    _log("[PBFWriter] File written, total bytes=%d" % endPos)
    return endPos


def _writeArray(file, arr):
    """Write a numpy array in chunks, avoiding one extra full copy as bytes."""
    step = max(1, _WRITE_CHUNK_BYTES // arr.dtype.itemsize)
    if arr.size <= step:
        file.write(arr.tobytes())
        return
    for start in range(0, arr.size, step):
        file.write(arr[start:start + step].tobytes())


# =====================================================================
#                        PBF tail / high level readers
# =====================================================================

def _scanPBFVoltage(file, fileSize, collect=True):
    """Scan the voltage change records at the end of a PBF file.

    Returns ``(indices, values, dcInfoSize, dcInfoBegin)``. With
    ``collect=False`` only the size is computed, matching what C++
    ``readPBFFile`` does when it reads the records just to size the tail.
    """
    lastByteSize = fileSize - 8                     # the last 8 bytes hold endPos
    if lastByteSize < PBF_HEADER_SIZE:
        raise ValueError("file is too small to be a PBF file: %d bytes" % fileSize)

    file.seek(lastByteSize)
    dcInfoBegin = struct.unpack("<q", file.read(8))[0]
    _log("lastByteSize %d" % lastByteSize)
    _log("dcInfoBegin %d" % dcInfoBegin)

    # Sanity check: 0 means "no voltage block"; a valid start must be at least
    # past the 18 byte header (endPos >= 18). Anything else means the tail
    # pointer is corrupt, and treating it as "no voltage records" keeps us from
    # reading the whole file as records.
    if dcInfoBegin == 0:
        return (np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int16), 0, dcInfoBegin)
    if not (PBF_HEADER_SIZE <= dcInfoBegin <= lastByteSize):
        _warn("dcInfoBegin=%d is out of range (%d..%d), assuming no voltage records"
              % (dcInfoBegin, PBF_HEADER_SIZE, lastByteSize))
        return (np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int16), 0, dcInfoBegin)

    nRec = (lastByteSize - dcInfoBegin) // VOLT_RECORD_SIZE
    file.seek(dcInfoBegin)
    if nRec <= 0:
        return (np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int16), 0, dcInfoBegin)

    buf = file.read(nRec * VOLT_RECORD_SIZE)
    if buf is None:
        buf = b""
    if len(buf) < nRec * VOLT_RECORD_SIZE:
        nRec = len(buf) // VOLT_RECORD_SIZE
        _warn("voltage record block is truncated, only %d records were read" % nRec)
        buf = buf[:nRec * VOLT_RECORD_SIZE]

    dcInfoSize = VOLT_RECORD_SIZE * nRec
    if not collect:
        return (np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int16), dcInfoSize, dcInfoBegin)

    rec = np.frombuffer(buf, dtype=np.dtype([("i", "<i8"), ("v", "<i2")]))
    indices = np.ascontiguousarray(rec["i"])
    values = np.ascontiguousarray(rec["v"])
    if VERBOSE >= 2:
        for i in range(indices.size):
            _log("%d %d" % (indices[i], values[i]), level=2)
    return (indices, values, dcInfoSize, dcInfoBegin)


def readPBFFile(path):
    """Read a PBF file, returning ``(currents as float32 array, sampleRate)``.

    Counterpart of C++ ``readPBFFile()``. The whole current block is loaded
    into memory; the voltage records are only used to size it (use
    :func:`readPBFVoltage` to get the values themselves).
    """
    fileSize = os.path.getsize(path)
    with open(path, "rb") as file:
        header = readPBFHeader(file)
        _requireVersion2(header, "readPBFFile")
        nowPos = file.tell()

        _log("binFileSize %d" % fileSize)

        _, _, dcInfoSize, _ = _scanPBFVoltage(file, fileSize, collect=False)

        currentDataBytes = fileSize - PBF_HEADER_SIZE - (dcInfoSize + 8)
        if currentDataBytes < 0:
            raise ValueError("broken file layout: current block would be %d bytes "
                             "long, file %s" % (currentDataBytes, path))
        if currentDataBytes % 4:
            _warn("current block is %d bytes, not a multiple of 4; ignoring the "
                  "last %d bytes" % (currentDataBytes, currentDataBytes % 4))
        currentValuesLen = currentDataBytes // 4

        file.seek(nowPos)
        currentValues = readPBFCurrents(file, currentValuesLen)
        _log("[INFO] Read %d current values" % currentValuesLen)

    return currentValues, header.sampleRate


def readPBFVoltage(path):
    """Read only the voltage change records: ``(int64 indices, int16 values)``.

    Counterpart of C++ ``readPBFVoltage()``; an invalid ``dcInfoBegin``
    (0 or out of range) yields two empty arrays.
    """
    fileSize = os.path.getsize(path)
    with open(path, "rb") as file:
        header = readPBFHeader(file)
        _requireVersion2(header, "readPBFVoltage")
        indices, values, _, dcInfoBegin = _scanPBFVoltage(file, fileSize, collect=True)
        _log("[PBF] dcInfoBegin=%d" % dcInfoBegin)
    return indices, values


def readTxtFile(path):
    """Read a two column text file (time, current) as ``(float32, sampleRate)``.

    Counterpart of C++ ``readTxtFile()``: the sample rate comes from the first
    two timestamps, ``round(1/(t1-t0))``. Lines without two parsable numbers
    are skipped, exactly like a failed ``iss >> col1 >> col2`` in C++.
    """
    data = None
    try:
        # fast path: let numpy parse it (raises on ragged rows / bad values)
        data = np.loadtxt(path, dtype=np.float64, ndmin=2)
        if data.ndim != 2 or data.shape[1] < 2:
            data = None
    except Exception:
        data = None

    if data is None:
        data = _parseTxtTolerant(path)

    if data is None or data.size == 0:
        _warn("readTxtFile: no parsable 'time current' rows in %s" % path)
        return np.zeros(0, dtype=np.float32), 0

    sampleRate = 0
    if data.shape[0] >= 2:
        interval = float(data[1, 0]) - float(data[0, 0])
        if interval > 0.0:
            sampleRate = int(round(1.0 / interval))
            _log("[TXTReader] Detected sample rate: %d Hz" % sampleRate)

    return data[:, 1].astype(np.float32), sampleRate


def _parseTxtTolerant(path):
    """Tolerant two column parser (skips bad rows), returns an (N,2) float64 array."""
    times = []
    currents = []
    skipped = 0
    with open(path, "r", errors="replace") as file:
        for line in file:
            parts = line.split()
            if len(parts) < 2:
                if parts:
                    skipped += 1
                continue
            try:
                t = float(parts[0])
                v = float(parts[1])
            except ValueError:
                skipped += 1
                continue
            times.append(t)
            currents.append(v)
    if skipped:
        _warn("readTxtFile: skipped %d unparsable rows" % skipped)
    if not times:
        return np.zeros((0, 2), dtype=np.float64)
    return np.column_stack((np.asarray(times, dtype=np.float64),
                            np.asarray(currents, dtype=np.float64)))


def bfReader(path):
    """Read ``.pbf / .txt`` and return ``(float32 currents, sampleRate)``.

    Counterpart of C++ ``bfReader()``: dispatch on the extension, and treat
    anything else as a text file. ``.abf`` raises NotImplementedError, see the
    module docstring.
    """
    lower = str(path).lower()
    if lower.endswith(".abf"):
        # ABF is not part of this package: convert the recording to PBF or TXT
        raise NotImplementedError(
            "reading .abf files is not supported by pbfio-sdk: convert the "
            "recording to .pbf or .txt first (%s)" % path)
    if lower.endswith(".pbf"):
        return readPBFFile(path)
    if lower.endswith(".txt"):
        return readTxtFile(path)

    _warn("bfReader: unknown extension for %s, reading it as a text file" % path)
    return readTxtFile(path)


# =====================================================================
#                       PBF utilities (pbfSetRate / pbfMerge)
# =====================================================================

def setPBFSampleRate(path, newSampleRate):
    """Patch the sampleRate field in place (4 bytes at offset 10).

    Counterpart of ``cpp_version/pbfSetRate.cpp``: only these 4 bytes change,
    the data block, voltage block and trailing endPos stay untouched, so even
    multi-GB files are done in no time. Returns ``(oldRate, newRate)``.
    """
    newRate = int(newSampleRate)
    if newRate <= 0:
        raise ValueError("sampleRate must be positive: %r" % (newSampleRate,))

    with open(path, "rb") as file:
        header = readPBFHeader(file)
        _requireVersion2(header, "setPBFSampleRate")
        oldRate = header.sampleRate

    if oldRate == newRate:
        _log("%s: SampleRate already %d, nothing to do" % (path, newRate))
        return oldRate, newRate

    with open(path, "r+b") as file:
        file.seek(SAMPLE_RATE_OFFSET, os.SEEK_SET)
        file.write(struct.pack("<i", newRate))
        file.flush()
        os.fsync(file.fileno())

    with open(path, "rb") as file:
        checkRate = readPBFHeader(file).sampleRate
    if checkRate != newRate:
        raise IOError("read back check failed: %s has sampleRate %d, expected %d"
                      % (path, checkRate, newRate))

    _log("%s: SampleRate %d -> %d" % (path, oldRate, checkRate))
    return oldRate, checkRate


def mergePBFFiles(outputPath, inputPaths):
    """Concatenate several PBF files, returning the number of current samples.

    Counterpart of ``cpp_version/pbfMerge.cpp``:

    * the header of the first file becomes the output header (a sample rate
      mismatch only produces a warning);
    * current samples are appended in order;
    * voltage record indices are shifted by the number of samples before them.
    """
    inputPaths = list(inputPaths)
    if not inputPaths:
        raise ValueError("mergePBFFiles: at least one input file is required")

    with open(inputPaths[0], "rb") as file:
        outHeader = readPBFHeader(file)
        _requireVersion2(outHeader, "mergePBFFiles")

    parts = []
    totalPoints = 0
    for path in inputPaths:
        currents, sampleRate = readPBFFile(path)
        if sampleRate != outHeader.sampleRate:
            _warn("sample rate mismatch in %s (%d vs %d)"
                  % (path, sampleRate, outHeader.sampleRate))
        indices, values = readPBFVoltage(path)
        parts.append((currents, indices, values))
        totalPoints += int(currents.size)

    allCurrents = np.empty(totalPoints, dtype=np.float32)
    nVolt = sum(int(p[1].size) for p in parts)
    allVoltIdx = np.empty(nVolt, dtype=np.int64)
    allVoltVal = np.empty(nVolt, dtype=np.int16)

    offset = 0
    vOffset = 0
    for path, (currents, indices, values) in zip(inputPaths, parts):
        n = int(currents.size)
        allCurrents[offset:offset + n] = currents
        nv = int(indices.size)
        if nv:
            allVoltIdx[vOffset:vOffset + nv] = indices + offset
            allVoltVal[vOffset:vOffset + nv] = values
        offset += n
        vOffset += nv
        _log("[Merge] Added %d points from %s" % (n, path))

    writePBFFile(outHeader, outputPath, allCurrents, allVoltIdx, allVoltVal)
    _log("[Merge] Wrote %d points to %s" % (totalPoints, outputPath))
    return totalPoints


def _main(argv):
    if len(argv) < 3:
        sys.stderr.write(
            "Usage:\n"
            "  %s info  <file.pbf>          # print the PBF header\n"
            "  %s volt  <file.pbf>          # print the voltage change records\n"
            "  %s check <file.pbf>          # print point count and sample rate\n"
            % (argv[0], argv[0], argv[0]))
        return 1

    cmd = argv[1]
    path = argv[2]
    if cmd == "info":
        with open(path, "rb") as file:
            header = readPBFHeader(file)
        print("======== PBF Header Information ========")
        print("File:       %s" % path)
        print("File Flag:  %s" % header.fileFlag)
        print("Version:    %d" % header.version)
        print("mRange:     %d" % header.mRange)
        print("SampleRate: %d" % header.sampleRate)
        print("Ioffset:    %d" % header.Ioffset)
        print("========================================")
        return 0

    if cmd == "volt":
        indices, values = readPBFVoltage(path)
        for i in range(indices.size):
            print("%d\t%d" % (indices[i], values[i]))
        return 0

    if cmd == "check":
        currents, sampleRate = readPBFFile(path)
        print("%s: %d points, sampleRate=%d" % (path, currents.size, sampleRate))
        return 0

    sys.stderr.write("unknown command: %s\n" % cmd)
    return 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
