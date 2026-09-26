#!/usr/bin/env python3
from pathlib import Path

path = Path("codex-rs/hepta-memory/src/cognitive_retrieval_adapter.rs")
text = path.read_text(encoding="utf-8")
old = "use codex_hepta_cognitive_types::lane_c::LaneCGenerationVectorV1;\n"
new = old + "use codex_hepta_contracts::Sha256Digest;\n"
if text.count(old) != 1:
    raise SystemExit("unexpected cognitive retrieval adapter import layout")
if "use codex_hepta_contracts::Sha256Digest;" in text:
    raise SystemExit("Sha256Digest import already present")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
