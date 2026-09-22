# pbfio-sdk

Reader/writer for **PBF** and **TXT** electrophysiology data, in pure Python
(NumPy). One function call gives you the samples as a NumPy array, and the
writer produces byte-identical files to the C++ toolchain it was ported from.

```python
import pbfio_sdk as pbfIO

header = pbfIO.readPBFHeader(open("demo.pbf", "rb"))
data, sampleRate = pbfIO.readPBFFile("demo.pbf")      # np.float32 array
indices, values = pbfIO.readPBFVoltage("demo.pbf")    # voltage change points
pbfIO.writePBFFile(header, "out.pbf", data)
```

* pure Python + NumPy, no compiler needed, works on Linux / Windows / macOS
* `py3-none-any` wheel: one file for every platform and Python version
* the **PBF format is open**: see [SPEC.md](SPEC.md) for the byte-level
  specification, [test_data/](test_data/) for a conformance sample
* byte compatible with the C++ implementation of the same format

**Not included on purpose:** ABF support and PBF versions other than `2`.
`.abf` files and PBF files with an unsupported `version` are rejected with
`NotImplementedError` -- convert them to PBF version 2 or TXT first.

## Installation

```bash
pip install pbfio-sdk
```

From a checkout or a release artifact:

```bash
pip install .                    # from this repository
pip install dist/pbfio_sdk-0.1.0-py3-none-any.whl
```

## Quick start

```python
import numpy as np
import pbfio_sdk as pbfIO

# --- read ---------------------------------------------------------------
data, sampleRate = pbfIO.readPBFFile("demo.pbf")
print(data.shape, data.dtype, sampleRate)     # (126976,) float32 100000

with open("demo.pbf", "rb") as f:
    header = pbfIO.readPBFHeader(f)
print(header.fileFlag, header.version, header.mRange, header.Ioffset)

# --- write --------------------------------------------------------------
ph = pbfIO.pbfHeader("XBIN", 2, 20000, sampleRate, 0)
pbfIO.writePBFFile(ph, "copy.pbf", data)                       # currents only
pbfIO.writePBFFile(ph, "annotated.pbf", data,
                   vIndex=[0, 5000], vValue=[-500, 200])       # + voltage points

# --- merge / patch ------------------------------------------------------
pbfIO.mergePBFFiles("merged.pbf", ["a.pbf", "b.pbf"])
pbfIO.setPBFSampleRate("copy.pbf", 20000)                      # in place, 4 bytes

# --- text files ---------------------------------------------------------
samples, rate = pbfIO.readTxtFile("recording.txt")
```

Read the docstrings for details; every function documents which part of the
file it touches.

### Command line

```bash
python -m pbfio_sdk info  demo.pbf    # header fields
python -m pbfio_sdk volt  demo.pbf    # voltage change records
python -m pbfio_sdk check demo.pbf    # point count and sample rate

pbfio info demo.pbf                   # same, after pip install (console script)
```

## The PBF format

The format is deliberately tiny -- an 18 byte header, a flat float32 sample
block, a sparse list of voltage change records and a trailing offset:

| offset | size | content |
|---|---|---|
| 0 | 4 | `fileFlag`, ASCII, e.g. `XBIN` (reading stops at the first `\0`) |
| 4 | 2 | `version`, int16: `2` = float32 layout (other values are rejected) |
| 6 | 4 | `mRange`, int32 |
| 10 | 4 | `sampleRate`, int32 (Hz) |
| 14 | 4 | `Ioffset`, int32 |
| 18 | N*4 | float32 current samples |
| ... | M*10 | voltage change records: int64 sample index + int16 value |
| end | 8 | `endPos`, int64 = 18 + N*4 (where the sample block ends) |

**[SPEC.md](SPEC.md) is the normative specification** (field semantics,
versioning and compatibility policy, patent statement). This README only
summarises it. If you are implementing the format in another language, start
there and validate against `test_data/sample_v2.pbf`.

Notes:

* Currents are float32 on disk, and float32 is what the readers return. Cast
  with `.astype(np.float64)` if you need more precision for calculations.
* A corrupt tail pointer does not blow up in your face: `dcInfoBegin` outside
  `18 .. fileSize-8` is treated as "no voltage records" and a warning is
  printed. Warnings are always printed; normal progress logging is controlled
  by `pbfio_sdk.VERBOSE` (0 silent, 1 default, 2 also list every voltage
  record), or `setVerbose(level)`.
* A length mismatch between `vIndex` and `vValue` truncates to the shorter one
  with a warning instead of writing garbage.

## API

| function | purpose |
|---|---|
| `pbfHeader(fileFlag, version, mRange, sampleRate, Ioffset)` | header container, `copy()`, `==`, `repr()` |
| `readPBFHeader(file)` | read the 18 byte header from an open binary file |
| `readPBFCurrents(file, count)` | read `count` float32 samples from the current position |
| `writePBFFile(header, path, currents, vIndex=None, vValue=None)` | write a complete PBF file, returns the written `endPos` |
| `readPBFFile(path)` | `(currents float32, sampleRate)` |
| `readPBFVoltage(path)` | `(int64 indices, int16 values)` of the voltage records |
| `setPBFSampleRate(path, rate)` | patch `sampleRate` in place (4 bytes), returns `(old, new)` |
| `mergePBFFiles(outputPath, inputPaths)` | concatenate files, shifting voltage indices |
| `readTxtFile(path)` | two column text file, `(float32, sampleRate)` |
| `bfReader(path)` | dispatch by extension over `.pbf` / `.txt` |
| `setVerbose(level)` / `getVerbose()` / `VERBOSE` | logging switch |

## Development

```
src/pbfio_sdk/__init__.py   the package (single module)
src/pbfio_sdk/__main__.py   the CLI entry point
SPEC.md                     the format specification (CC BY 4.0)
test_data/                  conformance samples (CC0)
tests/test_sdk.py           self-contained test suite, no external data needed
tools/build.py              test + build sdist/wheel + verify + smoke test
tools/publish.sh            upload to PyPI (twine) or a GitHub release (gh)
examples/                   three small scripts
```

```bash
python tests/test_sdk.py              # run the tests
python tools/build.py                 # everything, output in dist/
python tools/build.py --no-isolation  # offline build
python tools/build.py --clean         # remove build artifacts
```

The test suite generates every sample file on the fly, so it needs no fixtures,
and it additionally validates `test_data/sample_v2.pbf` when run from a
checkout.

### Compatibility

The writers are byte-for-byte identical to the C++ tools of the same project
(`writePBFFile` / `mergePBFFiles` / `setPBFSampleRate`), and the readers produce
identical text output (`readPBFFile` / `readPBFVoltage` / `readTxtFile`). That
equivalence is checked by a separate parity suite against the compiled C++
reference binaries.

## License

| part | license |
|---|---|
| code (`src/`, `tools/`, `tests/`, `examples/`) | **MPL-2.0** -- see [LICENSE](LICENSE) |
| specification (`SPEC.md`) | **CC BY 4.0** |
| conformance data (`test_data/`) | **CC0 1.0** |

What MPL-2.0 means in practice: you may use, modify and ship this library
inside proprietary software, including closed-source analysis tools -- the
file-level copyleft only requires that modifications **of these files** stay
under MPL-2.0 and that recipients can obtain their source. So the format stays
open and fork-proof, while your application code stays yours.

The only runtime dependency is NumPy (BSD-3).
