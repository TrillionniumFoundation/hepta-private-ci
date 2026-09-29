#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[2]
path = root / "codex-rs/hepta-supervisor/src/daemon_protocol.rs"
content = path.read_text()
old = (
    "    use crate::ProductionMutationStatus;\n"
    "    use codex_hepta_contracts::Sha256Digest;\n"
)
new = (
    "    use crate::ProductionMutationStatus;\n"
    "    use codex_hepta_contracts::{Sha256Digest};\n"
)
count = content.count(old)
if count != 1:
    raise RuntimeError(
        f"daemon_protocol test import context changed: expected 1, found {count}"
    )
path.write_text(content.replace(old, new, 1))
print("runtime.supervisor generated test import isolated")
