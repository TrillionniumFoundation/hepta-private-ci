"""Bind a pure Python Windows API observation to two immutable checkouts."""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback

REFERENCE_SHA = "ba4e1e42b6a8cbab724e1755bddfb9b5b8f298a1"
REFERENCE_TREE = "d2f261084bad25c230b95835e9a589fe7b866be1"
PROBE_SHA = "c4030cf9a8e7638ef16d5781ee47d54313a4917bfafbc0cc85f5d098c55b23e9"


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def fingerprint(path):
    before = path.stat()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    after = path.stat()
    if before != after:
        raise ValueError(f"file changed while hashing: {path}")
    return {"size": after.st_size, "sha256": digest}


def source(root):
    def git(*args):
        return subprocess.check_output(
            ["git", "--no-replace-objects", *args], cwd=root, text=True
        ).strip()

    return {
        "head": git("rev-parse", "HEAD"),
        "tree": git("rev-parse", "HEAD^{tree}"),
        "changes": git("status", "--porcelain=v1", "--untracked-files=all"),
        "cargoLock": fingerprint(root / "codex-rs/Cargo.lock"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--expected-observer-head", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    observer = Path(__file__).resolve().parents[2]
    reference = args.reference_root.resolve(strict=True)
    output = args.output.resolve()
    if any(output.is_relative_to(root) for root in (observer, reference)):
        raise ValueError("records must be outside both read-only checkouts")
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    receipt = {
        "schema": "hepta.windows.directory-flush-observer.v1",
        "status": "INCOMPLETE",
        "original_scope": "not_run",
        "native_tests_run": False,
        "observation_only": True,
        "science_pass": False,
        "product_qualified": False,
        "power_loss_or_namespace_durability_qualified": False,
        "full_cost": None,
        "tested_production_sha": None,
        "reference_source_sha": REFERENCE_SHA,
        "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "host": {"platform": platform.platform(), "python": sys.version},
        "github": {key: os.environ.get(key) for key in (
            "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_SHA", "RUNNER_OS",
            "ImageOS", "ImageVersion",
        )},
    }
    write(output / "attempt.json", receipt)
    exit_code = 1
    before = None
    try:
        if sys.platform != "win32":
            raise RuntimeError("actual Windows is required")
        before = {"observer": source(observer), "reference": source(reference)}
        write(output / "source-before.json", before)
        if (before["observer"]["head"] != args.expected_observer_head
                or before["reference"]["head"] != REFERENCE_SHA
                or before["reference"]["tree"] != REFERENCE_TREE
                or any(item["changes"] for item in before.values())):
            raise RuntimeError("checkout identity or clean-source check failed")
        probe = observer / ".github/scripts/windows_directory_flush_probe.py"
        probe_before = fingerprint(probe)
        receipt["probe"] = {"path": str(probe), **probe_before}
        if probe_before["sha256"] != PROBE_SHA:
            raise RuntimeError("reviewed probe bytes do not match")
        command = [sys.executable, str(probe), "--records", str(output / "probe")]
        write(output / "command.json", {"argv": command, "cwd": str(observer)})
        with (output / "stdout.log").open("xb") as stdout:
            with (output / "stderr.log").open("xb") as stderr:
                completed = subprocess.run(command, cwd=observer, stdout=stdout, stderr=stderr)
        receipt["probe_exit_code"] = completed.returncode
        result_path = output / "probe/RESULT.json"
        if result_path.stat().st_size > 65536:
            raise RuntimeError("probe result exceeds the observation bound")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        receipt["result"] = result
        if (completed.returncode != 0 or fingerprint(probe) != probe_before
                or result.get("script_sha256") != PROBE_SHA
                or result.get("status") != "OBSERVATIONS_RECORDED"
                or result.get("product_qualified") is not False
                or result.get("power_loss_or_namespace_durability_qualified") is not False
                or result.get("original_file_bytes_unchanged") is not True
                or len(result.get("cases", [])) != 6):
            raise RuntimeError("observation capture or control failed")
        receipt["status"] = "OBSERVATIONS_RECORDED"
        exit_code = 0
    except Exception:
        receipt["error"] = traceback.format_exc()
    finally:
        try:
            after = {"observer": source(observer), "reference": source(reference)}
            write(output / "source-after.json", after)
            receipt["source_unchanged"] = before is not None and before == after
        except Exception:
            receipt["source_unchanged"] = False
            receipt["source_after_error"] = traceback.format_exc()
        if not receipt["source_unchanged"]:
            exit_code = 1
            receipt["status"] = "INCOMPLETE"
        receipt["wall_seconds_not_full_cost"] = time.monotonic() - started
        receipt["exit_code"] = exit_code
        write(output / "RECEIPT.json", receipt)
        write(output / "MANIFEST.json", {
            "members": {str(path.relative_to(output)): fingerprint(path)
                        for path in sorted(output.rglob("*")) if path.is_file()}
        })
    print(json.dumps({"status": receipt["status"], "exit_code": exit_code,
                      "observation_only": True, "product_qualified": False}))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
