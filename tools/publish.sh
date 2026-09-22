#!/usr/bin/env bash

# Copyright (c) 2026 <your name or company>
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

# Publish the built sdist + wheel. Two routes:
#
#   1) PyPI (needs TWINE_USERNAME / TWINE_PASSWORD, e.g. __token__ + pypi-...):
#        TWINE_USERNAME=__token__ TWINE_PASSWORD=pypi-xxx bash tools/publish.sh
#   2) GitHub release (needs the gh CLI, logged in):
#        TAG=v0.1.0 bash tools/publish.sh
#
# Build first:  python tools/build.py
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SDK="$(dirname "$HERE")"
DIST="${DIST:-$SDK/dist}"
TAG="${TAG:-v0.1.0}"

if [ ! -d "$DIST" ] || ! ls "$DIST"/* >/dev/null 2>&1; then
  echo "ERROR: nothing in $DIST - run: python tools/build.py" >&2
  exit 1
fi

echo "artifacts:"
ls -1 "$DIST" | sed 's/^/  /'

if [ -n "${TWINE_PASSWORD:-}" ]; then
  echo "-> uploading to PyPI with twine"
  python3 -m twine check "$DIST"/*
  python3 -m twine upload "$DIST"/*
  exit 0
fi

echo "-> creating/updating GitHub release $TAG"
if ! command -v gh >/dev/null 2>&1; then
  echo "ERROR: gh CLI not found. Install it, or upload $DIST manually." >&2
  exit 1
fi
gh release view "$TAG" >/dev/null 2>&1 \
  || gh release create "$TAG" --title "$TAG" --notes "pbfio-sdk $TAG"
gh release upload "$TAG" "$DIST"/* --clobber
echo "done. install with:"
echo "  pip install https://github.com/<owner>/<repo>/releases/download/$TAG/$(ls -1 "$DIST" | grep '\.whl$' | head -1)"
