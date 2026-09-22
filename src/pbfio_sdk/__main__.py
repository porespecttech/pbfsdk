# -*- coding: utf-8 -*-

# Copyright (c) 2026 <your name or company>
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Command line entry point of pbfio-sdk.

    python -m pbfio_sdk info  <file.pbf>    # print the PBF header
    python -m pbfio_sdk volt  <file.pbf>    # print the voltage change records
    python -m pbfio_sdk check <file.pbf>    # print point count and sample rate

After ``pip install`` the same commands are available as ``pbfio``.
"""

import sys

from . import _main


def main():
    """Console script entry point (``pbfio``); returns the process exit code."""
    return _main(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
