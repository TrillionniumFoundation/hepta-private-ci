#!/usr/bin/env python3
"""Read-only original protected-row diagnostic; never a full caller/gate proof."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
SOURCE_COMMIT = "e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd"
SOURCE_TREE = "b607ff5f50812c5e0f932d7dae18d4c74f1269cb"
MANIFEST_SHA256 = "529c421f3580b87f3eedbea2b53f93fa2f39e45ea478dcbbb69b69e91a95723d"
ORIGINAL_INPUTS = {
    "CALLERS.toml": "103904d43ead801b3752c5ab861b8cccf11bcd064c575bf720153efcd74161b6",
    "scripts/verify_hepta_callers.py": "16015483d2319a2dbf2f6ab13e4c3c5e5f3a5318ac85f70557004b7fcb450e3f",
    "scripts/hepta_typed_callers.py": "3740bc9c17796686f1d6b282675d275d1b07c70a4b22c67945072c7b61a40d38",
}


def git(root, *args):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    return subprocess.check_output(
        ["git", "-C", str(root), *args], env=env, timeout=30
    )


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    root, manifest = args.root.resolve(), args.manifest.resolve()
    report = {
        "format": "hepta-original-protected-row-diagnostic-v1",
        "scope": "Only original _verify_protected_files; not source-closure unittest, privileged inventory, full caller proof, or Rust tests.",
        "source_commit": SOURCE_COMMIT,
        "source_tree": SOURCE_TREE,
        "manifest_sha256": MANIFEST_SHA256,
        "status": "rejected_before_execution",
        "full_gate_status": "not_run",
        "rows": [],
    }
    inputs = {}
    started = False
    try:
        if manifest == root or root in manifest.parents:
            raise RuntimeError("Diagnostic manifest must remain outside the frozen source tree")
        if git(root, "rev-parse", "HEAD").decode().strip() != SOURCE_COMMIT:
            raise RuntimeError("Unexpected source commit")
        if git(root, "rev-parse", "HEAD^{tree}").decode().strip() != SOURCE_TREE:
            raise RuntimeError("Unexpected source tree")
        if digest(manifest) != MANIFEST_SHA256:
            raise RuntimeError("Unexpected prepared manifest bytes")
        for relative, expected in ORIGINAL_INPUTS.items():
            if digest(root / relative) != expected:
                raise RuntimeError("Unexpected original input: " + relative)
        sys.path.insert(0, str(root / "scripts"))
        spec = importlib.util.spec_from_file_location(
            "hepta_original_protected_diagnostic", root / "scripts/verify_hepta_callers.py"
        )
        verifier = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = verifier
        spec.loader.exec_module(verifier)
        before = verifier._load_manifest(root / "CALLERS.toml")
        prepared = verifier._load_manifest(manifest)
        if len(before["boundary"]) != 522 or len(before["protected_file"]) != 381:
            raise RuntimeError("Unexpected source boundary/protected-row counts")
        for index, leaf in ((233, 13), (235, 8)):
            row = before["protected_file"][index]
            if row["path"] != "codex-rs/hepta-agentd/src/cell_q24_training_model_lane.rs":
                raise RuntimeError("Unexpected target row")
            if row["required_order"][0][leaf] != "if owners":
                raise RuntimeError("Unexpected original marker")
            row["required_order"][0][leaf] = "&& owners"
        if before != prepared:
            raise RuntimeError("Prepared manifest contains changes beyond two reviewed leaves")
        tree = {}
        for entry in git(root, "ls-tree", "-r", "-z", SOURCE_COMMIT).split(b"\0"):
            if entry:
                header, relative = entry.split(b"\t", 1)
                mode, kind, object_id = header.decode().split()
                tree[relative.decode()] = (mode, kind, object_id)
        paths = sorted({r["path"] for r in prepared["protected_file"]} | set(ORIGINAL_INPUTS))
        for relative in paths:
            path = root / relative
            if path.is_symlink() or not path.is_file():
                raise RuntimeError("Missing or symlinked original source: " + relative)
            data = path.read_bytes()
            blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            mode, kind, expected_blob = tree[relative]
            if kind != "blob" or blob != expected_blob:
                raise RuntimeError("Source differs from exact e8b6 object: " + relative)
            inputs[relative] = {"mode": mode, "git_blob": blob, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        report["source_inputs"] = inputs
        started = True
        for index, row in enumerate(prepared["protected_file"]):
            result = {"index": index, "path": row["path"]}
            try:
                verifier._verify_protected_files(root, {"protected_file": [row]})
                result["status"] = "passed"
            except verifier.VerificationFailure as error:
                result.update(status="failed", error=str(error))
            report["rows"].append(result)
        if any(digest(root / relative) != value["sha256"] for relative, value in inputs.items()):
            raise RuntimeError("Source changed during diagnostic")
        if digest(manifest) != MANIFEST_SHA256:
            raise RuntimeError("Prepared manifest changed during diagnostic")
        report["passed_rows"] = sum(row["status"] == "passed" for row in report["rows"])
        report["failed_rows"] = sum(row["status"] == "failed" for row in report["rows"])
        report["status"] = "failed" if report["failed_rows"] else "passed_scoped_diagnostic"
        report["source_inputs_unchanged"] = True
    except Exception as error:
        report["status"] = "unknown_after_execution_started" if started else "rejected_before_execution"
        report["error"] = f"{type(error).__name__}: {error}"
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "passed_scoped_diagnostic" else 1


if __name__ == "__main__":
    raise SystemExit(main())
