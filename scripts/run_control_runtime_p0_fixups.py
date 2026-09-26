#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "scripts/control_runtime_p0_fixups.py"
source = PATCH.read_text(encoding="utf-8")
old = "updated, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)"
new = "updated, count = re.subn(pattern, lambda _match: replacement, text, count=1, flags=re.DOTALL)"
if old in source:
    source = source.replace(old, new, 1)
elif new not in source:
    raise RuntimeError("control_runtime_p0_fixups.py has an unknown sub_once implementation")
PATCH.write_text(source, encoding="utf-8")
namespace = {"__name__": "__main__", "__file__": str(PATCH)}
exec(compile(source, str(PATCH), "exec"), namespace)
