#!/usr/bin/env python3
"""Keep the one-shot bootstrap push outside .github/workflows.

The repository GitHub Actions token can write source content but cannot create or
remove workflow files. The connected administrator installs the permanent
workflow after this source-only bootstrap lands.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
bootstrap = ROOT / "scripts/cognitive_store_convergence_bootstrap.py"
text = bootstrap.read_text(encoding="utf-8")
old_path = ".github/workflows/cognitive-store-qualification.yml"
new_path = "docs/modules/cognitive.store/cognitive-store-qualification.generated.yml"
if old_path not in text:
    raise SystemExit("bootstrap qualification workflow path is missing")
text = text.replace(old_path, new_path)
old_cleanup = '''for temporary in (
    "scripts/cognitive_store_convergence_bootstrap.py",
    ".github/workflows/cognitive-store-convergence-bootstrap.yml",
):'''
new_cleanup = '''for temporary in (
    "scripts/cognitive_store_convergence_bootstrap.py",
):'''
if text.count(old_cleanup) != 1:
    raise SystemExit("bootstrap cleanup block drifted")
text = text.replace(old_cleanup, new_cleanup)
bootstrap.write_text(text, encoding="utf-8")
Path(__file__).unlink()
print('{"status":"workflow-permission-patched"}')
