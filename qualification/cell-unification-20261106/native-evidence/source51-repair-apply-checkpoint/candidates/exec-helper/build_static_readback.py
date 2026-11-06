#!/usr/bin/env python3
"""Verify fixed inputs and the isolated one-file candidate; no native commands."""

from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent
COMMIT = "1fdd647b0ecb235530e8b88bbea45b3d3762906f"
TREE = "ea48acf562499192a25e05ae28926a32632dee62"
TARGET = "codex-rs/exec-server/tests/common/fake_bwrap.rs"
EXPECTED_BLOBS = {
    "AGENTS.md": "faa57cc0db48123e1011f1eb47692cd3bbbcfc3a",
    "codex-rs/exec-server/tests/capability_discovery.rs": "80484ecfa01dac48189cbcc3324caa4374961ea0",
    "codex-rs/exec-server/tests/file_system_unix.rs": "5051ec2e5bbc625c090e335cc8872044415a85ad",
    TARGET: "cc79362f7a8a3a44b0a93949d18494281511ec7b",
    "codex-rs/exec-server/tests/common/mod.rs": "161728f5127d5a311579603b480bc0351a605880",
    "codex-rs/exec-server/tests/common/exec_server.rs": "ea4f5b166cac271930382ef158edd5ac7db66253",
    "codex-rs/linux-sandbox/src/launcher.rs": "d4e9b521bf93f0861cf497c3153a9efdc6e3c67b",
    "codex-rs/linux-sandbox/src/bundled_bwrap.rs": "61d10547d3b3eb499f8b8a06d6444845c4ff7f93",
    "codex-rs/exec-server/src/fs_sandbox.rs": "ca715ef44ed7c30e4da11149dcc2cf8248c67ab3",
    "codex-rs/exec-server/src/fs_helper_main.rs": "3ca9ecc21e3d9e525a807680f91d8ebe04059a6d",
    "codex-rs/exec-server/src/capability_discovery.rs": "43721630e2e8e7776ed1456db9f7b752164690ca",
    "codex-rs/sandboxing/src/lib.rs": "a756012a272a794ca1302a87327d9eb9ac1c48ae",
    "codex-rs/sandboxing/src/bwrap.rs": "633487136abe00065ee0f30707573ceb67b04e5b",
    "codex-rs/exec-server/Cargo.toml": "455df9eedc14b77ac3779899087cd8391b153b37",
    "codex-rs/exec-server/BUILD.bazel": "73c71a65112db4c7d306f3be215ab17907decfa5",
}
BEFORE = b'    let real_bwrap = codex_utils_cargo_bin::cargo_bin("bwrap")?;\n'
AFTER = (
    b"    // Resolve the real launcher before the shim can enter the child's PATH.\n"
    b"    let real_bwrap = match codex_sandboxing::find_system_bwrap_in_path() {\n"
    b"        Some(path) => path,\n"
    b'        None => codex_utils_cargo_bin::cargo_bin("bwrap")?,\n'
    b"    };\n"
)


def pin(data: bytes) -> dict:
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob": hashlib.sha1(
            b"blob " + str(len(data)).encode("ascii") + b"\0" + data
        ).hexdigest(),
    }


def write_exact(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == data, f"Refusing to overwrite different bytes: {path}"
    else:
        with path.open("xb") as handle:
            handle.write(data)


def emit(name: str, value: dict) -> None:
    write_exact(ROOT / name, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())


def main() -> None:
    source_pins = []
    for path, expected_blob in EXPECTED_BLOBS.items():
        data = (ROOT / "original" / path).read_bytes()
        observed = pin(data)
        assert observed["git_blob"] == expected_blob, (path, observed)
        source_pins.append({
            "path": path,
            **observed,
            "source_url": f"https://github.com/TrillionniumFoundation/hepta-private-ci/blob/{COMMIT}/{path}",
        })
    assert sorted(str(p.relative_to(ROOT / "original")) for p in (ROOT / "original").rglob("*") if p.is_file()) == sorted(EXPECTED_BLOBS)
    before = (ROOT / "original" / TARGET).read_bytes()
    after = (ROOT / "source" / TARGET).read_bytes()
    patch = (ROOT / "repair.patch").read_bytes()
    assert before.count(BEFORE) == 1 and after.count(AFTER) == 1
    assert before.replace(BEFORE, AFTER, 1) == after
    assert after.replace(AFTER, BEFORE, 1) == before
    regenerated = "".join(difflib.unified_diff(
        before.decode().splitlines(keepends=True),
        after.decode().splitlines(keepends=True),
        fromfile=f"a/{TARGET}", tofile=f"b/{TARGET}",
    )).encode()
    assert regenerated == patch
    assert pin(after)["sha256"] == "83d3637f2648b967c70e2368c623fe0b84afe1cdf32860284d897923ad0dc1ca"
    assert pin(patch)["sha256"] == "0f8ee51664c850a9fd450bcba800d3ffb6866633f1924845b058ffadcc7b1ba8"
    assert list(p.relative_to(ROOT / "source").as_posix() for p in (ROOT / "source").rglob("*") if p.is_file()) == [TARGET]
    assert before.split(BEFORE, 1)[0] == after.split(AFTER, 1)[0]
    assert before.split(BEFORE, 1)[1] == after.split(AFTER, 1)[1]

    closed = WORK / "native-validation-results/r24-failure-closed"
    index = json.loads((closed / "INDEX.json").read_bytes())
    assert index["source_tree"] == TREE and index["source_commit"] == COMMIT
    assert index["guidance"] == ["AGENTS.md"]
    for item in index["support_source"][:3]:
        assert pin((ROOT / "original" / item["path"]).read_bytes()) == {
            k: item[k] for k in ("bytes", "sha256", "git_blob")
        }
    failure_refs = []
    for item in index["failures"][:2]:
        data = (closed / item["file"]).read_bytes()
        assert pin(data) == {k: item[k] for k in ("bytes", "sha256", "git_blob")}
        assert b"loopback: Failed RTM_NEWADDR: Operation not permitted" in data
        assert item["end_byte_offset"] - item["byte_offset"] == len(data)
        failure_refs.append(item)
    receipt = json.loads((closed / "native-source50-project-r24-tests-receipt.json").read_bytes())
    raw = json.loads((closed / "native-source50-project-r24-tests-raw-process-result.json").read_bytes())
    guard = json.loads((closed / "native-source50-project-r24-tests-source-post-verification.json").read_bytes())
    terminal = json.loads((closed / "terminal-process-status.json").read_bytes())
    assert receipt["source_tree"] == raw["source_tree"] == guard["actual_tree"] == TREE
    assert receipt["exit_code"] == raw["exit_code"] == guard["gate_exit_code"] == terminal["exit_code"] == 100
    assert receipt["effective_exit_code"] == 100 and not receipt["phase_pass"]
    assert receipt["log_sha256"] == index["log"]["sha256"]
    assert guard["pass"] and guard["changed_file_count"] == 194
    assert not terminal["timed_out"] and not terminal["cancelled"] and terminal["output_durable"]
    assert pin((closed / "native-source50-project-r24-tests-resources.txt").read_bytes())["sha256"] == receipt["resources_sha256"]
    for key, name in (
        ("raw_process_result", "native-source50-project-r24-tests-raw-process-result.json"),
        ("source_postguard", "native-source50-project-r24-tests-source-post-verification.json"),
        ("acceptance_readback", "native-source50-project-r24-tests-result-review.json"),
    ):
        assert pin((closed / name).read_bytes()) == {k: receipt[key][k] for k in ("bytes", "sha256", "git_blob")}

    attachments = []
    names = [
        "INDEX.json", "failure-1.txt", "failure-2.txt", "terminal-process-status.json",
        "native-source50-project-r24-tests-receipt.json",
        "native-source50-project-r24-tests-raw-process-result.json",
        "native-source50-project-r24-tests-resources.txt",
        "native-source50-project-r24-tests-source-post-verification.json",
        "native-source50-project-r24-tests-result-review.json",
    ]
    for name in names:
        data = (closed / name).read_bytes()
        dest = f"evidence/r24/{name}"
        write_exact(ROOT / dest, data)
        attachments.append({"source": f"native-validation-results/r24-failure-closed/{name}", "destination": dest, **pin(data)})
    for name, digest in (
        ("CANDIDATE-STATIC-REVIEW.json", "1570f493d0cb763a1e07a46ddccab0b1a02752de796559decdb83b3ba1c270e4"),
        ("C-SOURCE-AUDIT.json", "9b2edbd109468a7bc207e7d71d1d96b562e52340822e2db36516f16db98e0145"),
    ):
        data = (WORK / "exec-server-bwrap-r24-independent-review" / name).read_bytes()
        assert pin(data)["sha256"] == digest
        dest = f"independent-review/{name}"
        write_exact(ROOT / dest, data)
        attachments.append({"source": f"exec-server-bwrap-r24-independent-review/{name}", "destination": dest, **pin(data)})

    emit("source-input-pins.json", {
        "schema": "hepta.exec-server-bwrap-r24-source-inputs.v1",
        "source_commit": COMMIT, "source_tree": TREE,
        "nearest_guidance": ["AGENTS.md"],
        "files": source_pins,
        "native_confirmed_source_paths": [x["path"] for x in index["support_source"][:3]],
        "independent_c_sources": "independent-review/C-SOURCE-AUDIT.json",
    })
    emit("source-manifest.json", {
        "schema": "hepta.exec-server-bwrap-r24-isolated-candidate.v1",
        "status": "STATIC_CANDIDATE_NATIVE_VALIDATION_PENDING",
        "base_commit": COMMIT, "base_tree": TREE,
        "files": [{"path": TARGET, "before": pin(before), "after": pin(after), "git_mode": "100644"}],
        "patch": {"path": "repair.patch", **pin(patch)},
        "changed_files": 1, "production_files_changed": 0,
        "dependency_manifest_changed": False, "rust_executed": False,
        "native_source_modified": False,
    })
    emit("STATIC-READBACK.json", {
        "schema": "hepta.exec-server-bwrap-r24-static-readback.v1",
        "scope": "Local immutable source, isolated edit, and closed original failure receipts only.",
        "status": "STATIC_CHECKS_PASS_RUNTIME_COMPARISON_SEPARATE",
        "script": {"path": "build_static_readback.py", **pin(Path(__file__).read_bytes())},
        "source_count": len(source_pins),
        "source_blob_checks": "15 expected immutable Git blobs equal computed full-file blobs",
        "native_source_matches": 3,
        "candidate_forward_inverse_exact": True,
        "patch_recreated_exactly": True,
        "full_original_prefix_suffix_and_shell_script_unchanged": True,
        "candidate_source_paths": [TARGET],
        "original_failure_blocks": failure_refs,
        "original_receipt_and_resource_bindings_pass": True,
        "original_gate_exit_code": 100,
        "full_log_not_reparsed_here": True,
        "full_log_pin": index["log"],
        "attachments": attachments,
        "rust_or_probe_executed": False,
        "test_assertions_or_timeouts_modified": False,
        "native_qualification": "PENDING",
    })
    print(json.dumps({
        "status": "PASS",
        "source_inputs": len(source_pins), "candidate": pin(after), "patch": pin(patch),
        "reports": {name: pin((ROOT / name).read_bytes()) for name in (
            "source-input-pins.json", "source-manifest.json", "STATIC-READBACK.json"
        )},
    }, indent=2))


if __name__ == "__main__":
    main()
