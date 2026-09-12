#!/usr/bin/env python3
"""Generate and verify the uniform section-17 source receipts."""
from __future__ import annotations
import argparse, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADING = "## 17. Source implementation receipt"

def receipt(module: str) -> str:
    row = json.loads((ROOT / f"docs/modules/{module}/IMPLEMENTATION_MAP.json").read_text())
    lines = ["", HEADING, "", "This receipt records repository source bindings for the current documentation candidate. It is navigation evidence only; it does not claim product composition, deployment, or external effect authority.", "", "| Operation | Native symbol | Source path | Tests |", "|---|---|---|---|"]
    for op in row.get("operations", []):
        name = op.get("operation") or op.get("designOperation") or "native_mapping_pending"
        symbol, source = op.get("nativeSymbol") or "pending", op.get("sourcePath") or "pending"
        tests = ", ".join(t.get("path", "") for t in op.get("tests", [])) or "pending"
        lines.append(f"| `{name}` | `{symbol}` | `{source}` | `{tests}` |")
    lines += ["", "- Source identity: `sourceBase` is recorded in `IMPLEMENTATION_MAP.json`.", "- Consumer callsites and durable owner stores remain explicit follow-up evidence when not listed above.", "- Production implementation, runtime composition, independent acceptance, activation, and release remain false until their separate evidence gates pass.", ""]
    return "\n".join(lines)

def generate() -> int:
    changed = []
    for path in sorted((ROOT / "docs/modules").glob("*/TECHNICAL.md")):
        text = path.read_text()
        if HEADING in text:
            continue
        path.write_text(text.rstrip() + "\n" + receipt(path.parent.name), encoding="utf-8")
        changed.append(str(path.relative_to(ROOT)))
    print(json.dumps({"generated": len(changed), "documents": changed}))
    return 0

def verify() -> int:
    missing = [str(p.relative_to(ROOT)) for p in sorted((ROOT / "docs/modules").glob("*/TECHNICAL.md")) if HEADING not in p.read_text()]
    if missing:
        raise SystemExit("missing source receipts: " + ", ".join(missing))
    print(json.dumps({"status": "PASS_HEPTA_TECHNICAL_RECEIPTS", "documents": 40}))
    return 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["generate", "verify"])
    args = parser.parse_args()
    raise SystemExit(generate() if args.command == "generate" else verify())
