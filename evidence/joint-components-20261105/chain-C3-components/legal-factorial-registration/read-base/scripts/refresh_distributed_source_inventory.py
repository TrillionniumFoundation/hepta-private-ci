#!/usr/bin/env python3
"""Refresh only the embedded native runner inventory; never scan host/private files."""
from pathlib import Path
import argparse
import subprocess
import os
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "trillionnium/crates/trnm-pon-node/examples/support/distributed_source_inventory.rs"

def render():
    if shutil.which("rg"):
        args = ["rg", "--files", "trillionnium/crates", "config", "-g", "*.rs", "-g", "Cargo.toml", "-g", "*.json"]
        paths = set(subprocess.check_output(args, cwd=ROOT, text=True).splitlines())
    else:
        # Hosted runners need not install ripgrep. Git applies the repository's
        # ignore rules and also includes new development sources before commit.
        raw = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others",
                                       "--exclude-standard", "--", "trillionnium/crates", "config"], cwd=ROOT)
        paths = {path for item in raw.split(b"\0") if item
                 for path in [item.decode("utf-8")]
                 if Path(path).suffix in {".rs", ".json"} or Path(path).name == "Cargo.toml"}
    paths.update(("trillionnium/Cargo.toml", "trillionnium/Cargo.lock", str(OUTPUT.relative_to(ROOT))))
    rows = ["// Embedded exact bytes. Regenerate inventory when adding native source files.", "pub const FILES: &[(&str, &[u8])] = &["]
    for path in sorted(paths):
        item = ROOT / path
        if item.is_symlink() or not item.is_file():
            raise ValueError(f"not a regular source file: {path}")
        rows.extend(("    (", f'        "{path}",', "        include_bytes!(concat!(", '            env!("CARGO_MANIFEST_DIR"),', f'            "/../../../{path}"', "        )),", "    ),"))
    rows.append("];")
    return "\n".join(rows) + "\n"

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = render()
    if args.check:
        if OUTPUT.read_text() != content:
            raise SystemExit("distributed native source inventory differs; refresh before freezing source")
    else:
        # Compilation must never observe a half-written include file.
        with tempfile.NamedTemporaryFile("w", dir=OUTPUT.parent, prefix=".distributed-inventory-", delete=False) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            pending = Path(temporary.name)
        try:
            pending.chmod(0o644)
            os.replace(pending, OUTPUT)
        finally:
            pending.unlink(missing_ok=True)
    print("distributed source inventory: PASS")
