#!/usr/bin/env python3
"""Finalize named Agentd cognitive-context limits after the main migration."""
from __future__ import annotations

from pathlib import Path

PATH = Path("codex-rs/hepta-agentd/src/cognitive_context.rs")
text = PATH.read_text(encoding="utf-8")

old = "const MAX_CONTEXT_JSON_BYTES: usize = crate::MAX_COGNITIVE_CONTEXT_BYTES;\n"
new = (
    "const MAX_CONTEXT_JSON_BYTES: usize = crate::MAX_COGNITIVE_CONTEXT_BYTES;\n"
    "const MAX_SELECTED_CONTEXT_RECORDS: u16 = 4;\n"
)
if text.count(old) != 1:
    raise SystemExit(f"expected one context budget declaration, found {text.count(old)}")
text = text.replace(old, new, 1)

old = "!(1..=4).contains(&limit)"
new = "!(1..=MAX_SELECTED_CONTEXT_RECORDS).contains(&limit)"
if text.count(old) != 1:
    raise SystemExit(f"expected one selected-record range, found {text.count(old)}")
text = text.replace(old, new, 1)

PATH.write_text(text, encoding="utf-8")
print("cognitive.read named Agentd limits finalized")
