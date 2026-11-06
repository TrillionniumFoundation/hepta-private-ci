#!/usr/bin/env python3
"""Losslessly package the fixed B21 v3 evidence; never execute product code."""
import argparse
import base64
import hashlib
import json
import shutil
import zipfile
from pathlib import Path, PurePosixPath


def identity(data):
    return {"bytes": len(data), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
            "sha256": hashlib.sha256(data).hexdigest()}


def file_identity(path):
    size = path.stat().st_size
    git = hashlib.sha1(b"blob " + str(size).encode() + b"\0")
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1048576):
            git.update(chunk)
            sha.update(chunk)
    return {"bytes": size, "git_blob": git.hexdigest(), "sha256": sha.hexdigest()}


def main(author, packet):
    raw_freeze = (author / "freeze-manifest.json").read_bytes()
    assert identity(raw_freeze)["git_blob"] == "b94ccbf22bdeca017e740fcaed20e14f3e06113f"
    freeze = json.loads(raw_freeze)
    assert freeze["members"] == len(freeze["files"]) == 42
    assert freeze["total_bytes"] == sum(row["bytes"] for row in freeze["files"]) == 83441944
    assert freeze["product_blocker_transition"] == "NONE; B21/B15 OPEN"
    members = sorted(freeze["files"] + [{"path": "freeze-manifest.json", **identity(raw_freeze)}], key=lambda row: row["path"])
    assert len({row["path"] for row in members}) == 43
    archive = packet / "evidence.original.zip"
    assert not archive.exists()
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for row in members:
            relative = PurePosixPath(row["path"])
            assert not relative.is_absolute() and all(x not in ("", ".", "..") for x in relative.parts)
            source = author.joinpath(*relative.parts)
            assert not source.is_symlink() and source.is_file()
            assert file_identity(source) == {k: row[k] for k in ("bytes", "git_blob", "sha256")}
            item = zipfile.ZipInfo(row["path"], (2026, 11, 6, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o100644 << 16
            item._compresslevel = 9
            with source.open("rb") as src, z.open(item, "w") as dst:
                shutil.copyfileobj(src, dst, 1048576)
    parts = []
    with archive.open("rb") as handle:
        while raw := handle.read(300000):
            body = base64.b64encode(raw)
            assert len(body) <= 400000
            name = f"evidence.zip.part-{len(parts) + 1:04d}.b64"
            (packet / name).write_bytes(body)
            parts.append({"path": name, **identity(body)})
    original_result = json.loads((author / "verification.stdout.json").read_bytes())
    assert original_result["retention"]["original_complete_flag"] is False
    assert original_result["retention"]["original_errors"] == [{"kind": "original_bazel_exit_mismatch"}]
    qualifications = {
        "original_workflow_conclusion": "failure",
        "actual_run": original_result["actual_run"],
        "source": original_result["source"],
        "retention": original_result["retention"],
        "exit_phase_observation": original_result["exit_phase_observation"],
        "failed_targets": original_result["failed_targets"],
        "core_original_attempts": original_result["core_original_attempts"],
        "core_retry_compact_digest_limits": original_result["core_retry_compact_digest_limits"],
        "BEP_representation": "credential-sanitized / opaque-payload-omitted derived BEP, not raw original bytes",
        "product_blocker_statuses": {"B21": "OPEN", "B15": "OPEN"},
        "ledger_transition": "NONE",
        "independent_review": "Separate subsequent immutable receipt; frozen input is not rewritten",
        "product_or_native_execution_by_packager": False,
        "refs_PRs_or_CI_changed_by_packager": False,
        "limits": original_result["limits"],
    }
    manifest = {
        "schema": "hepta-b21-collector-v3-native-portable-packet-v1",
        "archive": {"path": archive.name, **file_identity(archive)},
        "parts": parts,
        "members": members,
        "original_freeze": identity(raw_freeze),
        "expected_verifier_stdout": identity((author / "verification.stdout.json").read_bytes()),
        "qualification": qualifications,
        "only_manifest_selected_originals_included": True,
        "excluded_expanded_ZIP_duplicates_and_pycache": True,
    }
    (packet / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    for src, dst in (("README.zh-CN.md", "ASSESSMENT.zh-CN.md"), ("freeze-manifest.json", "input-freeze.original.json"),
                     ("verification.stdout.json", "root-verification.stdout.original.json")):
        shutil.copyfile(author / src, packet / dst)
    (packet / "qualification.json").write_text(json.dumps(qualifications, ensure_ascii=False, indent=2) + "\n")
    (packet / "README.md").write_text("""# B21 collector v3: original Intel full-context failure evidence

The [original assessment](ASSESSMENT.zh-CN.md) is byte-for-byte the frozen input README. The official artifact ZIP, full job log, source archive, API/publication evidence, derived BEP, every retained attempt log/XML, compact log, fixed primary sources, and read-only verifier remain intact in the portable archive. The 42 original files plus their original freeze manifest are restored as 43 outer members. Expanded ZIP duplicates and Python cache directories are excluded exactly as the original freeze specifies.

Keep every base64 part, manifest.json and restore_packet.py in one directory, then run:

```sh
python3 restore_packet.py --output /new/empty/b21-v3-evidence --replay
```

The restorer requires Python and zstd, refuses an existing output directory, verifies every part/archive/member and the original freeze, and invokes only the read-only original evidence verifier. No product, Rust test, OS mechanism experiment, CI, ref or PR is executed or changed. Its stdout must exactly equal the original 16,908-byte root verification stdout.

Run 42164663819 / job 127718214088 failed. Actual checkout 84cc73453eb926d6f2c5b0372c0287b0ab86ed53 is the collector-only branch with the original 10,582 product leaves; it is not the PTY optimization candidate. Original collector complete=false remains unchanged: process exit 38 and test-stage BEP exit 3 differ following a recorded BES upload failure. All 501 produced attempts and 1,002 attempt log/XML files are retained; 438 target summaries, attempt totals, and Rust cases are distinct denominators. Four targets failed, including 28P/3F original PTY cases; original Core failed and timed-out attempts remain alongside their retries.

BEP is a credential-sanitized / opaque-payload-omitted derived representation, not the raw original BEP. Two successful Core retry XML files are not claimed bound to their compact XML-output digests. See qualification.json and the full assessment for these limits. B21 and B15 remain OPEN; there is no ledger transition. The input freeze remains unchanged; subsequent independent review is a separate receipt.
""")
    print(json.dumps({"members": len(members), "archive": manifest["archive"], "parts": len(parts),
                      "freeze": manifest["original_freeze"], "original_data_bytes": freeze["total_bytes"]}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--packet", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    main(args.source.resolve(), args.packet.resolve())
