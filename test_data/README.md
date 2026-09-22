# Conformance sample data

| file | format version | size | contents |
|---|---|---|---|
| `sample_v2.pbf` | 2 (float32) | 17,039,396 bytes | 4,259,840 samples, 1 voltage record |

This directory contains one recorded signal trace supplied by the project owner.
The files are released under **CC0 1.0 Universal** (public domain dedication) --
see [LICENSE](LICENSE). Use them in your own test suites, no attribution
required.

## `sample_v2.pbf`

Header and layout:

| field | value |
|---|---|
| `fileFlag` | `XBIN` |
| `version` | `2` |
| `mRange` | `20000` |
| `sampleRate` | `1000000` |
| `Ioffset` | `0` |
| `N` (samples) | `4259840` |
| sample block offset | `18` |
| `M` (voltage records) | `1` |
| voltage block offset (`endPos`) | `17039378` (= 18 + 4 x 4259840) |
| file size | `17039396` (= 18 + 17039360 + 10 + 8) |

Sample block:

| value | expected |
|---|---|
| first sample (float32) | `10.52363` (`0x412860ca`) |
| last sample (float32) | `1.7858313` (`0x3fe4961f`) |
| float32 sum of all samples | `7370992.5` |

Voltage records:

| index | value |
|---|---|
| 0 | 0 |

SHA-256 of the whole file:

```
a71314313b77165265abd0fa9bb46f07d5d2e463540d62557fecc6f763c5f58a
```

## Verifying with the reference implementation

```python
import pbfio_sdk as pbfIO

header = pbfIO.readPBFHeader(open("test_data/sample_v2.pbf", "rb"))
assert (header.fileFlag, header.version, header.mRange, header.sampleRate,
        header.Ioffset) == ("XBIN", 2, 20000, 1000000, 0)

data, sampleRate = pbfIO.readPBFFile("test_data/sample_v2.pbf")
assert sampleRate == 1000000 and data.size == 4259840
assert data[0] == 10.52363 and data[-1] == 1.7858313

indices, values = pbfIO.readPBFVoltage("test_data/sample_v2.pbf")
assert indices.tolist() == [0]
assert values.tolist() == [0]
```

`tests/test_sdk.py` runs these checks (including the file hash) when the file
is present.

## Adding samples

Do not add further recordings here without explicit approval. For new
edge-case fixtures prefer small, deterministic, synthetic files and document
their expected values in this file.
