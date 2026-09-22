#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2026 <your name or company>
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Run the tests, build the sdist + wheel and verify the wheel.

    python tools/build.py                 # everything
    python tools/build.py --no-test       # skip the test run
    python tools/build.py --no-isolation  # offline build (local setuptools/wheel)
    python tools/build.py --clean         # remove .build/, dist/ and caches

The package is pure Python, so the wheel is ``py3-none-any``: one file works on
every platform and every supported Python version.
"""

import argparse
import glob
import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SDK = os.path.dirname(HERE)
PKG = os.path.join(SDK, "src", "pbfio_sdk")
BUILD = os.path.join(SDK, ".build")
DIST = os.path.join(SDK, "dist")


def log(msg):
    sys.stderr.write("[build] %s\n" % msg)


def die(msg, code=1):
    sys.stderr.write("[build][ERROR] %s\n" % msg)
    sys.exit(code)


def run(cmd, cwd=None, verbose=False):
    log("$ " + " ".join(cmd) + ("   (cwd=%s)" % cwd if cwd else ""))
    out = None if verbose else subprocess.DEVNULL
    try:
        subprocess.check_call(cmd, cwd=cwd, stdout=out)
    except subprocess.CalledProcessError as exc:
        die("command failed (exit=%s): %s" % (exc.returncode, " ".join(cmd)))


def clean():
    for path in (BUILD, DIST, os.path.join(SDK, "build")):
        if os.path.isdir(path):
            shutil.rmtree(path)
            log("removed %s" % path)
    for path in glob.glob(os.path.join(SDK, "src", "*.egg-info")) + \
            glob.glob(os.path.join(PKG, "__pycache__")) + \
            glob.glob(os.path.join(SDK, "tests", "__pycache__")):
        shutil.rmtree(path, ignore_errors=True)
        log("removed %s" % path)


def runTests(verbose):
    test = os.path.join(SDK, "tests", "test_sdk.py")
    if not os.path.isfile(test):
        die("tests/test_sdk.py is missing")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.join(SDK, "src") + os.pathsep + env.get("PYTHONPATH", "")
    log("running tests against src/")
    if verbose:
        proc = subprocess.run([sys.executable, test], env=env)
    else:
        proc = subprocess.run([sys.executable, test], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        if not verbose:
            sys.stdout.write(proc.stdout)
        die("tests failed")


def buildDist(isolation, verbose):
    """Build with PyPA ``build`` when available, else fall back to ``pip wheel``.

    Both run from a neutral working directory and are told where the project
    is, because setuptools creates a ``build/`` folder inside the project and a
    local ``build`` directory would shadow the real ``build`` package.
    """
    neutral = os.path.join(BUILD, "cwd")
    os.makedirs(neutral, exist_ok=True)

    if _hasModule("build", neutral):
        cmd = [sys.executable, "-m", "build", "--outdir", DIST, SDK]
        if not isolation:
            cmd.append("--no-isolation")
        run(cmd, cwd=neutral, verbose=verbose)
    else:
        log("PyPA 'build' is not installed; falling back to 'pip wheel' "
            "(wheel only, no sdist)")
        log("install it with: %s -m pip install build" % sys.executable)
        run([sys.executable, "-m", "pip", "wheel", SDK, "--no-deps", "-w", DIST],
            cwd=neutral, verbose=verbose)

    wheels = sorted(glob.glob(os.path.join(DIST, "*.whl")))
    sdists = sorted(glob.glob(os.path.join(DIST, "*.tar.gz")))
    if not wheels:
        die("no wheel was produced")
    return wheels[-1], (sdists[-1] if sdists else None)


def _hasModule(name, cwd=None):
    """True when ``name`` can be imported by this interpreter (run from ``cwd``)."""
    proc = subprocess.run([sys.executable, "-c", "import %s" % name],
                          cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc.returncode == 0


def verifyDist(wheel, sdist):
    with zipfile.ZipFile(wheel) as zf:
        names = zf.namelist()
        sources = {n: zf.read(n).decode("utf-8", "replace")
                   for n in names if n.endswith(".py")}
    if not any(n.endswith("pbfio_sdk/__init__.py") for n in names):
        die("wheel does not contain pbfio_sdk/__init__.py:\n  " + "\n  ".join(names))
    binaries = [n for n in names if n.endswith((".so", ".pyd", ".dll"))]
    if binaries:
        die("unexpected binary files in a pure Python wheel: %s" % binaries)

    # licensing: MPL-2.0 text has to travel with the wheel, and every shipped
    # source file carries the Exhibit A notice
    licenses = [n for n in names if "licenses/LICENSE" in n or n.endswith(".dist-info/LICENSE")]
    if not licenses:
        die("the wheel does not contain the LICENSE file")
    with zipfile.ZipFile(wheel) as zf:
        text = zf.read(licenses[0]).decode("utf-8", "replace")
        if "Mozilla Public License" not in text:
            die("the LICENSE shipped in the wheel is not the MPL-2.0 text")
        for name, content in sources.items():
            markers = ("Mozilla Public", "mozilla.org/MPL/2.0")
            if not all(m in content for m in markers):
                die("%s does not carry the MPL Exhibit A notice" % name)
    if not os.path.basename(wheel).endswith("-py3-none-any.whl"):
        die("wheel is not platform independent: %s" % os.path.basename(wheel))

    log("wheel verified:")
    log("  file    %s (%.1f KB)" % (os.path.basename(wheel), os.path.getsize(wheel) / 1024.0))
    log("  content %s" % ", ".join(sorted(names)))
    if sdist:
        log("  sdist   %s (%.1f KB)"
            % (os.path.basename(sdist), os.path.getsize(sdist) / 1024.0))
    return names


def smokeTest():
    """Import the package from src/ and do a real write/read round trip."""
    script = r'''
import os, tempfile
import numpy as np
import pbfio_sdk as pbfIO

assert pbfIO.__version__
pbfIO.VERBOSE = 0
assert pbfIO.getVerbose() == 0
pbfIO.setVerbose(1)
assert pbfIO.getVerbose() == 1
pbfIO.VERBOSE = 0

d = tempfile.mkdtemp(prefix="pbfio_smoke_")
p = os.path.join(d, "t.pbf")
data = np.arange(1000, dtype=np.float32) * 0.5
ph = pbfIO.pbfHeader("XBIN", 2, 20000, 100000, 0)
pbfIO.writePBFFile(ph, p, data, [0, 500], [-200, 300])

h = pbfIO.readPBFHeader(open(p, "rb"))
assert (h.fileFlag, h.version, h.sampleRate) == ("XBIN", 2, 100000), h
back, sr = pbfIO.readPBFFile(p)
assert sr == 100000 and back.size == 1000 and np.array_equal(back, data)
vi, vv = pbfIO.readPBFVoltage(p)
assert list(vi) == [0, 500] and list(vv) == [-200, 300]
assert pbfIO.setPBFSampleRate(p, 50000) == (100000, 50000)
print("SMOKE OK  version=%s  api=%d" % (pbfIO.__version__, len(pbfIO.__all__)))
'''
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.join(SDK, "src") + os.pathsep + env.get("PYTHONPATH", "")
    log("smoke test")
    proc = subprocess.run([sys.executable, "-c", script], env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    sys.stdout.write(proc.stdout)
    if proc.returncode != 0:
        die("smoke test failed")


def main():
    ap = argparse.ArgumentParser(description="Build the pbfio-sdk sdist and wheel")
    ap.add_argument("--clean", action="store_true", help="remove .build/, dist/ and caches")
    ap.add_argument("--no-test", action="store_true", help="skip the test run")
    ap.add_argument("--no-smoke-test", action="store_true", help="skip the round trip check")
    ap.add_argument("--no-isolation", action="store_true",
                    help="build without an isolated environment (offline)")
    ap.add_argument("--verbose", action="store_true", help="show all subprocess output")
    args = ap.parse_args()

    if args.clean:
        clean()
        return 0

    log("Python %s (%s)" % (sys.version.split()[0], sys.platform))
    if not args.no_test:
        runTests(args.verbose)
    wheel, sdist = buildDist(not args.no_isolation, args.verbose)
    verifyDist(wheel, sdist)
    if not args.no_smoke_test:
        smokeTest()

    log("done: %s" % wheel)
    log("publish: bash tools/publish.sh          # PyPI or GitHub release")
    return 0


if __name__ == "__main__":
    sys.exit(main())
