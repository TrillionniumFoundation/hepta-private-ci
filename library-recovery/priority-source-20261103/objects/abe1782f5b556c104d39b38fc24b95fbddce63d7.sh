#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python -m unittest discover -v -s .
python -m p0_p5_gatebook
