#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2026 <your name or company>
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Generate the public package file (``src/pbfio_sdk/__init__.py``) from the
upstream implementation (``pbfIO.py``).

Two things happen here:

1. the upstream module is copied into the package, with a short banner;
2. everything that must not be published is stripped from the copy:
   ABF support, the classic v1 reader and the legacy function aliases that only
   the internal scripts use. See ``../../SDK_BUILD_NOTES.md`` for the list and
   the rationale.

Usage::

    python tools/sync_core.py                 # regenerate the package file
    python tools/sync_core.py --core ../pbfIO.py
    python tools/sync_core.py --check         # verify the copy is up to date

The script fails loudly when a patch no longer matches or when a stripped name
still shows up in the generated file, so the public API cannot silently grow
back.
"""

import argparse
import ast
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SDK = os.path.dirname(HERE)
TARGET = os.path.join(SDK, "src", "pbfio_sdk", "__init__.py")

#: header of the generated file: copyright, MPL Exhibit A notice, maintainer note
BANNER = (
    "# Copyright (c) 2026 <your name or company>\n"
    "#\n"
    "# This Source Code Form is subject to the terms of the Mozilla Public\n"
    "# License, v. 2.0. If a copy of the MPL was not distributed with this\n"
    "# file, You can obtain one at https://mozilla.org/MPL/2.0/.\n"
    "# " + "-" * 75 + "\n"
    "# pbfio-sdk -- package entry point.\n"
    "#\n"
    "# Maintainer note: this file is generated from the upstream pbfIO.py by\n"
    "# tools/sync_core.py. If you only have this repository, edit this file\n"
    "# directly; if you have the upstream project, prefer editing pbfIO.py and\n"
    "# re-running the sync, so both copies stay identical.\n"
    "# " + "-" * 75 + "\n"
)

CANDIDATES = (
    os.path.join(SDK, os.pardir, "pbfIO.py"),
    os.path.join(SDK, os.pardir, "python", "pbfIO.py"),
    os.path.join(SDK, os.pardir, os.pardir, "python", "pbfIO.py"),
)

# ---------------------------------------------------------------------------
# what the published package leaves out (the upstream module keeps it all)
# ---------------------------------------------------------------------------

#: top level definitions removed from the public copy
STRIP_DEFS = (
    # ABF support and the classic v1 reader
    "AbfFile",
    "writeABF1",
    "readPBFClassicFile",
    "datToabf",                  # legacy alias of writeABF1
    "_importPyabf",              # only used by AbfFile
    "_roundHalfAwayFromZero",    # only used by writeABF1
    "_int32",                    # only used by writeABF1
    # legacy aliases, kept upstream only for old internal scripts
    "pbfHeadReader",
    "pbfCurrentReader",
    "pbfCurrentReader_ad",
    "_readClassicValues",        # only used by pbfCurrentReader_ad
    "pbfWriter",
    "bfVoltReader",
)

#: names removed from ``__all__``
STRIP_ALL = (
    "readPBFClassicFile",
    "AbfFile",
    "writeABF1",
    "datToabf",
    "pbfHeadReader",
    "pbfCurrentReader",
    "pbfCurrentReader_ad",
    "pbfWriter",
    "bfVoltReader",
)

#: symbols that must not appear anywhere in the generated file
FORBIDDEN = STRIP_ALL + (
    "_importPyabf",
    "_roundHalfAwayFromZero",
    "_int32",
    "_readClassicValues",
    "pyabf",
)

#: text that has to be adjusted after removing the definitions above
PATCHES = (
    # bfReader can no longer dispatch .abf files
    ('''    if lower.endswith(".abf"):
        abf = AbfFile(path)
        return abf.sweepY.astype(np.float32), int(abf.dataRate)
''',
     '''    if lower.endswith(".abf"):
        # ABF is not part of this package: convert the recording to PBF or TXT
        raise NotImplementedError(
            "reading .abf files is not supported by pbfio-sdk: convert the "
            "recording to .pbf or .txt first (%s)" % path)
'''),
    # bfReader docstring
    ('''    """Read ``.abf / .pbf / .txt`` and return ``(float32 currents, sampleRate)``.

    Counterpart of C++ ``bfReader()``: dispatch on the extension, and treat
    anything else as a text file.
    """''',
     '''    """Read ``.pbf / .txt`` and return ``(float32 currents, sampleRate)``.

    Counterpart of C++ ``bfReader()``: dispatch on the extension, and treat
    anything else as a text file. ``.abf`` raises NotImplementedError, see the
    module docstring.
    """'''),
    # module docstring: no references to the removed helpers
    ('''* Like C++ ``readPBFFile()``, version 1 files are read as float32 as well
  (a known limitation documented in the C++ source). For real classic int16
  files use :func:`readPBFClassicFile`.
* Legacy names (``pbfHeadReader`` / ``pbfCurrentReader`` / ``pbfCurrentReader_ad``
  / ``pbfWriter`` / ``bfVoltReader`` / ``datToabf``) are kept for old scripts.
"""''',
     '''* Like C++ ``readPBFFile()``, version 1 files are read as float32 as well
  (a known limitation documented in the C++ source).
* ABF reading and writing is intentionally not part of this package, and the
  legacy aliases of the upstream project are not published either.
"""'''),
    # readPBFFile log message pointed at the removed classic reader
    ('''            _log("version 1 file is read as float32 (same as C++); use "
                 "readPBFClassicFile() for classic int16 files")''',
     '''            _log("version 1 file is read as float32 (same as C++)")'''),
)


def log(msg):
    sys.stderr.write("[sync] %s\n" % msg)


def die(msg):
    sys.stderr.write("[sync] ERROR: %s\n" % msg)
    sys.exit(1)


def findCore(explicit=None):
    """Return the upstream pbfIO.py, or None when this repository stands alone."""
    for cand in ([explicit] if explicit else []) + list(CANDIDATES):
        cand = os.path.abspath(cand)
        if os.path.isfile(cand):
            return cand
    if explicit:
        die("%s does not exist" % explicit)
    return None


def removeDefs(text, names):
    """Remove top level ``def``/``class`` blocks by name.

    Everything else, comments included, is kept byte for byte.
    """
    lines = text.split("\n")
    out = []
    removed = []
    i = 0
    while i < len(lines):
        match = re.match(r"^(?:def|class)\s+(\w+)\s*[\(:]", lines[i])
        if match and match.group(1) in names:
            removed.append(match.group(1))
            # drop the blank lines and section banner that belonged to it
            while out and (out[-1].strip() == "" or out[-1].startswith("#")):
                out.pop()
            i += 1
            while i < len(lines) and (lines[i].strip() == ""
                                      or lines[i].startswith((" ", "\t", "#"))):
                i += 1
            if out and out[-1].strip() != "":
                out.append("")
            out.append("")
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out), removed


def allNames(text):
    """Read ``__all__`` from the source (order preserved)."""
    for node in ast.parse(text).body:
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "__all__" for t in node.targets):
            return list(ast.literal_eval(node.value))
    die("__all__ not found in the source file")


def filterAll(text, names):
    """Drop ``names`` from the ``__all__`` block, keeping its comments."""
    match = re.search(r"^__all__ = \[.*?^\]", text, re.S | re.M)
    if not match:
        die("could not locate the __all__ block")
    block = match.group(0)
    for name in names:
        block = re.sub(r'\s*"%s",' % re.escape(name), "", block)
    block = "\n".join(line for line in block.split("\n") if line.strip())
    return text[:match.start()] + block + text[match.end():]


def applyPatches(text):
    for old, new in PATCHES:
        count = text.count(old)
        if count != 1:
            die("patch no longer matches (found %d times):\n%s" % (count, old[:200]))
        text = text.replace(old, new)
    return text


def render(source):
    with open(source, "r", encoding="utf-8") as f:
        text = f.read()

    lines = text.split("\n")
    if lines and lines[0].startswith("# -*- coding"):
        text = lines[0] + "\n" + BANNER + "\n".join(lines[1:])
    else:
        text = BANNER + text

    text, removed = removeDefs(text, set(STRIP_DEFS))
    missing = sorted(set(STRIP_DEFS) - set(removed))
    if missing:
        die("these definitions were expected but not found: %s" % ", ".join(missing))

    text = filterAll(text, STRIP_ALL)
    text = applyPatches(text)

    leaked = [name for name in FORBIDDEN
              if re.search(r"(?<![\w.])%s(?![\w])" % re.escape(name), text)]
    if leaked:
        die("the generated file still mentions: %s" % ", ".join(leaked))

    log("stripped %d definitions: %s" % (len(removed), ", ".join(removed)))
    log("public API: %s" % ", ".join(allNames(text)))
    return text


def main():
    ap = argparse.ArgumentParser(description="Generate the public package from pbfIO.py")
    ap.add_argument("--core", help="path of pbfIO.py (default: auto-detect)")
    ap.add_argument("--check", action="store_true",
                    help="do not write, just fail if the package copy is stale")
    args = ap.parse_args()

    core = findCore(args.core)
    if core is None:
        # standalone repository: the committed package file is the source
        if not os.path.isfile(TARGET):
            die("no upstream pbfIO.py found and %s does not exist" % TARGET)
        log("no upstream pbfIO.py found, using the committed %s as-is"
            % os.path.relpath(TARGET, SDK))
        return 0

    wanted = render(core)

    current = ""
    if os.path.isfile(TARGET):
        with open(TARGET, "r", encoding="utf-8") as f:
            current = f.read()

    if args.check:
        if current == wanted:
            log("OK: %s is in sync with %s" % (TARGET, core))
            return 0
        die("%s is out of sync with %s\n       run: python tools/sync_core.py"
            % (TARGET, core))

    os.makedirs(os.path.dirname(TARGET), exist_ok=True)
    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(wanted)
    log("%s -> %s (%d lines)" % (core, TARGET, wanted.count("\n") + 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
