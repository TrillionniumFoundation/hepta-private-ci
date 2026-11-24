#!/usr/bin/env python3
"""Record source/lock bindings and reject a zero-test or partial native pass."""
import argparse
import hashlib
import json
import platform
import re
import subprocess
import tomllib
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--test-exit", type=int, required=True)
    args = parser.parse_args()
    location = Path(__file__).resolve().parent
    root = location.parents[2]
    vendor = root / "codex-rs/third_party/libsqlite3-sys-0.39.1"
    source_files = [
        root / ".github/workflows/hepta-windows-durable-fixtures.yml",
        vendor / "Cargo.toml", vendor / "build.rs",
        vendor / "sqlite3/sqlite3.c", vendor / "sqlite3/sqlite3.h",
        vendor / "sqlite3/hepta_owner_vfs.c",
        vendor / "sqlite3/bindgen_bundled_version.rs",
        *sorted((vendor / "src").glob("hepta_owner*.rs")),
        vendor / "src/lib.rs",
        location / "native-probe/Cargo.toml", location / "native-probe/Cargo.lock",
        location / "native-probe/probe.rs", location / "native-probe/nextest.toml",
    ]
    workspace_config = tomllib.loads((root / "codex-rs/.config/nextest.toml").read_text())
    probe_config = tomllib.loads((location / "native-probe/nextest.toml").read_text())
    defaults_match = all(workspace_config["profile"]["default"][key]
                         == probe_config["profile"]["default"][key]
                         for key in ["slow-timeout", "retries"])
    log_path = args.evidence / "native-owner-vfs.log"
    text = log_path.read_text(encoding="utf-8-sig", errors="replace")
    text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)
    summaries = re.findall(r"\b(\d+) tests run: (\d+) passed", text)
    observed = tuple(map(int, summaries[-1])) if summaries else None
    source_clean = subprocess.run(["git", "diff", "--quiet", "HEAD"], cwd=root).returncode == 0
    qualified = (platform.system() == "Windows" and args.test_exit == 0
                 and observed == (8, 8) and defaults_match and source_clean)
    receipt = {
        "schema": "hepta.windows-sqlite-owner-native.v1",
        "source_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "platform": platform.platform(), "test_exit": args.test_exit,
        "expected_tests": 8, "observed_run_and_pass": observed,
        "source_clean": source_clean, "workspace_timeout_and_retry_defaults_match": defaults_match,
        "native_vfs_qualified": qualified,
        "scope": "actual bundled Windows C VFS and eight native tests in an isolated locked dependency graph",
        "sqlx_consumer_graph_qualified": False,
        "different_account_impersonation_qualified": False,
        "ancestor_confinement_or_current_cut_fence_qualified": False,
        "source_sha256": {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in source_files},
        "native_log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
    }
    args.evidence.mkdir(parents=True, exist_ok=True)
    (args.evidence / "native-owner-vfs-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({key: receipt[key] for key in ["source_head", "test_exit", "observed_run_and_pass", "native_vfs_qualified"]}))
    if args.test_exit == 0 and not qualified:
        raise SystemExit("native qualification requires Windows, all eight tests, unchanged source and original timeout/retry defaults")


if __name__ == "__main__":
    main()
