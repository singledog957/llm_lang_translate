#!/usr/bin/env python3
"""Compatibility wrapper for the pure pragmatic evaluation workflow."""

from __future__ import annotations

import sys

from evaluate import main


if __name__ == "__main__":
    main(["pure", *sys.argv[1:]])