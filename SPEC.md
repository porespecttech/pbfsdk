# PBF File Format Specification

Revision 1.0 -- defines PBF format version `2` (float32 sample layout).
Maintained by `<your name or company>`.

This document is licensed under **Creative Commons Attribution 4.0
International (CC BY 4.0)** -- see [License of this document](#license-of-this-document).
Code snippets in this document are covered by the MPL-2.0 license of the
reference implementation.

---

## 1. Scope

PBF is a container for sampled electrophysiology signals: one current trace per
file, plus a sparse list of voltage change points (the stimulus/command
potential in effect at a given sample). It is designed to be

* **trivially readable** -- a fixed 18 byte header, a flat float32 array and a
  trailing index; no compression, no external metadata, no endianness puzzle;
* **streamable** -- a reader can memory-map the sample block and ignore
  everything else;
* **append-friendly for instruments** -- voltage changes are recorded in the
  order they happen and written after the sample block.

Out of scope: calibration metadata beyond `mRange`/`Ioffset`, multi-channel
layout, compression, acquisition metadata (device id, protocol, operator...).
Those belong in a sidecar file or in a future version of this format.

## 2. Conventions

* All integers are **little-endian** (least significant byte first).
* `int16`, `int32`, `int64` are two's complement signed integers.
* `float32` is IEEE 754 binary32.
* There is no alignment requirement: every field starts where the previous one
  ended.
* "Sample index" is a zero-based index into the current block.

## 3. File layout

```
byte offset      size          field
--------------------------------------------------------------------
0                4             fileFlag        (ASCII)
4                2             version         (int16)
6                4             mRange          (int32)
10               4             sampleRate      (int32, Hz)
14               4             Ioffset         (int32)
18               N * 4         currents        (float32[N])
18 + 4N          M * 10        voltageRecords  (record[M])
18 + 4N + 10M    8             endPos          (int64)
--------------------------------------------------------------------
file size = 18 + 4N + 10M + 8
```

### 3.1 `fileFlag` (4 bytes)

Four ASCII bytes identifying the producer/container flavour, for example
`XBIN` or `PBF_`. Readers MUST NOT reject a file because of this field; it is
informational and is compared literally when re-writing.

A reader MUST stop interpreting the field at the first `0x00` byte, so a
shorter flag may be stored NUL-padded.

### 3.2 `version` (int16)

| value | sample block encoding |
|---|---|
| `2` | `float32` sample values, already in physical units |
| `!= 2` | not defined by this revision of the specification |

Readers MUST reject a file whose `version` is not `2`. Future revisions of this
specification may define additional values; a reader that does not implement a
newer value MUST reject it rather than guess at its layout.

### 3.3 `mRange` (int32)

Full-scale range of the acquisition in the amplifier's native units. For
instruments that report a current range in pA this is typically `20000`.
It is informational metadata and MUST be preserved on rewrite.

### 3.4 `sampleRate` (int32)

Sample rate of the current block in Hz. MUST be `> 0` for a well-formed file.
The sample interval is `1 / sampleRate` seconds.

Tools that change this value MUST rewrite exactly these four bytes (offset
10), leaving samples and voltage records untouched -- see `setPBFSampleRate()`
in the reference implementation.

### 3.5 `Ioffset` (int32)

Current offset in the amplifier's native units. It is informational metadata
in this revision and MUST be preserved on rewrite.

### 3.6 `currents` (N x float32)

The signal, in physical units (typically pA for current recordings), one
`float32` per sample, in acquisition order. `N` may be zero.

There is no interleaving and no channel dimension: one file carries one trace.
Instruments that acquire several channels write several files.

### 3.7 `voltageRecords` (M x 10 bytes)

Sparse list of command-voltage changes:

| offset in record | size | field |
|---|---|---|
| 0 | 8 | `index` (int64): sample index at which this value takes effect |
| 8 | 2 | `value` (int16): voltage in the instrument's native unit |

Records MUST be sorted by `index` in non-decreasing order. The value in effect
before the first record is undefined; readers SHOULD treat it as the value of
the first record, or as `0` when `M == 0`.

`value` is a signed 16 bit quantity, so the representable range is
`-32768 .. 32767` in whatever unit the producer uses (millivolts for the
instruments this format was designed for).

When a producer has no voltage information it MUST still write exactly one
record (`index = 0`, `value = 0`) as a placeholder and set `M = 1`, so that
`endPos` remains meaningful (this is what the reference implementation does).

### 3.8 `endPos` (int64)

Byte offset at which the sample block ends, i.e. `18 + 4N`. It is the position
of the first voltage record, and it lets a reader locate the sample block
without scanning. It MUST equal `18 + 4 * N`.

A file with `endPos == 0` is tolerated by the reference reader and treated as
"no voltage records" (defensive behaviour for truncated or damaged files).
Writers MUST NOT produce `endPos == 0`.

## 4. Sizes and limits

* Maximum file size is bounded by the filesystem, not by the format: `N` is
  derived from the file size, and readers SHOULD use 64 bit arithmetic.
* A single file with a 4 GB sample block holds about 1.07e9 `float32` samples;
  at 100 kHz that is about 3 hours.
* Producers writing files larger than 2 GiB MUST NOT rely on 32 bit int
  arithmetic anywhere in their writer.

## 5. Decoding

1. read the 18 byte header and reject the file unless `version == 2`;
2. read `int64 endPos` from the last 8 bytes of the file;
3. if `18 <= endPos <= fileSize - 8`, the voltage block is
   `M = (fileSize - 8 - endPos) / 10` records starting at `endPos`;
   otherwise treat `M` as `0` (and warn);
4. `N = (fileSize - 18 - 10M - 8) / 4`;
5. the sample block is the `N` `float32` values starting at offset 18.

Implementations MUST validate that the computed `N` is not negative, and
SHOULD warn (rather than fail) when the sample block size is not a multiple of
4 or when the voltage block is truncated.

## 6. Writing

A conforming writer:

1. writes `fileFlag`, `version = 2`, `mRange`, `sampleRate`, `Ioffset`;
2. writes the `float32` samples in acquisition order;
3. writes the voltage records (at least the single placeholder record);
4. writes `endPos = 18 + 4N` as `int64`.

Sample values are stored as `float32`; a writer given `float64` input SHOULD
round to nearest `float32`, and MUST document any additional scaling it
applies (the reference implementation writes physical units unchanged).

A writer MUST NOT write any `version` other than `2` unless a later revision of
this specification defines that value and the writer implements it.

## 7. Versioning and compatibility policy

* A reader MUST reject every file whose `version` it does not implement.
  This revision implements version `2` only.
* A writer MUST write version `2`, the lowest version defined by this
  specification.
* Adding fields is a **new major version**; existing fields never change
  meaning and never move.
* Files in the wild are considered immutable records. Tools that modify a file
  (for example to correct `sampleRate`) MUST keep the byte length identical.

## 8. Conformance sample

`test_data/sample_v2.pbf` is the canonical conformance sample (4,259,840
samples, one voltage record) together with the expected values in
`test_data/README.md`. Implementations are encouraged to use it as a smoke
test.

## 9. Reference implementation

The Python reference implementation lives in this repository
(`src/pbfio_sdk/`): `readPBFHeader`, `readPBFCurrents`, `readPBFFile`,
`readPBFVoltage`, `writePBFFile`, `setPBFSampleRate`, `mergePBFFiles`.
It is a single module with no dependencies beyond NumPy, and its writers are
byte-for-byte compatible with the reference C++ toolchain for this format.

## 10. Patents

`<your name or company>` owns patents covering instrument hardware and analysis
software. **The PBF file format itself is not covered by those patents.**

To the best of our knowledge, no patent owned or controlled by us is
necessarily infringed by an implementation of this specification, and it is our
intent not to assert such patents against any implementation that conforms to
this specification.

This section is a statement of intent, not a warranty or a legal opinion; it
does not override any applicable patent rights of third parties. If you need a
formally signed non-assertion covenant or a royalty-free patent commitment for
your own legal review, contact `<your contact address>`.

*Maintainer note: have your IP counsel review this section before publishing,
and adjust the wording if you want a stronger (signed) commitment.*

## 11. License of this document

This specification is licensed under the **Creative Commons Attribution 4.0
International License (CC BY 4.0)**. You are free to share and adapt it for any
purpose, including commercially, as long as you give appropriate credit and
indicate if changes were made. Full text:
<https://creativecommons.org/licenses/by/4.0/legalcode>.

Code snippets inside this document are additionally available under the
MPL-2.0 license of the reference implementation, at your option.

The conformance data in `test_data/` is released under **CC0 1.0 Universal**
(public domain dedication) -- see `test_data/LICENSE`.
