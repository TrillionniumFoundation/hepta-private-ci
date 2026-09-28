#!/usr/bin/env python3
"""Narrow source repairs before the one-shot caller migration; not qualification."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path, old, new):
    file = ROOT / path
    text = file.read_text()
    if text.count(old) != 1:
        raise SystemExit(f"{path}: expected one reviewed patch anchor")
    file.write_text(text.replace(old, new))


replace("scripts/check-authbus-closed-world.py",
        '        text = path.read_text(encoding="utf-8")\n        for name, allowed',
        '        text = path.read_text(encoding="utf-8")\n        if "IssuerRegistration" not in text and "AuthBusAuthorityStore" not in text:\n            continue\n        for name, allowed')
replace("codex-rs/hepta-authbus/src/worker.rs",
        '        if *shutdown.borrow_and_update() || shutdown.changed().await.is_err() {\n            return;\n        }',
        '        let requested = *shutdown.borrow_and_update();\n        if requested {\n            return;\n        }\n        if shutdown.changed().await.is_err() {\n            return;\n        }')
replace("codex-rs/hepta-authbus/Cargo.toml", "doctest = false", "doctest = true")
