#!/usr/bin/env python3
"""Remove activation-only imports and format before binding canonical source state."""

from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "codex-rs/hepta-context-compiler/src/v2/recovery.rs"
text = path.read_text(encoding="utf-8")
old = (
    "use super::delivery_disposition_code;\n"
    "use super::ensure_digest;\n"
    "use super::push_digest;\n"
    "use super::push_id;\n"
    "use super::push_u64;\n"
)
new = "use super::ensure_digest;\nuse super::push_digest;\n"
if text.count(old) != 1:
    raise SystemExit("recovery import anchor drifted")
path.write_text(text.replace(old, new, 1), encoding="utf-8")

# Canonical state records Git blob identities. Format every Rust source before
# those identities are generated so later verification is read-only and cannot
# invalidate the state projection it is checking.
subprocess.run(["cargo", "fmt", "--all"], cwd=ROOT / "codex-rs", check=True)
