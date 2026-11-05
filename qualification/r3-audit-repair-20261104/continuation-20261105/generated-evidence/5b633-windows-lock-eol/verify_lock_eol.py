#!/usr/bin/env python3
"""Read existing exact-source artifacts; reproduce Windows lock input hashes."""
from pathlib import Path
import hashlib
import json
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
WATCH = HERE.parent


def identity(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }


def run():
    business_path = WATCH / "snapshot-0017/windows-business-extracted/ordinary-consumers/source.json"
    retained_path = WATCH / "retained-extracted/source.json"
    business = json.loads(business_path.read_bytes())
    retained = json.loads(retained_path.read_bytes())
    assert business["head"] == "9063c52a063b6f26c48e9418f6d8dbd14e9e06ff"
    assert business["tree"] == retained["source_tree"] == "b26598d0d97d8d51e723bb5582137315f2174d35"
    assert retained["source_head"] == "5b6331250ff459033bd44d1a95daec70131277cc"
    assert business["parents"] == ["63652be658ebed8d3052eb789b951793384fd5e4", retained["source_head"]]
    envelope = json.loads((HERE / "source-api-envelopes.json").read_bytes())
    by_label = {r["label"]: r for r in envelope["records"]}
    root_tree = json.loads(by_label["tree"]["response"]["structuredContent"]["content"])
    rust_tree = json.loads(by_label["codex-rs-tree"]["response"]["structuredContent"]["content"])
    root_entries = {r["path"]: r for r in root_tree["tree"]}
    rust_entries = {r["path"]: r for r in rust_tree["tree"]}
    assert root_tree["sha"] == business["tree"]
    assert root_entries["codex-rs"]["sha"] == rust_tree["sha"]
    specs = [
        ("codex-rs/Cargo.lock", HERE / "Cargo.lock.source.txt", rust_entries["Cargo.lock"],
         "4a7a5535cf045089458468411e126b5f59bc6bbf34fc0deead9b0c1b8d84000a"),
        ("MODULE.bazel.lock", ROOT / "research-audit/published-0e139-ci-20261105/terminal/ui-run-41975255764/artifact-13393945289/members/MODULE.bazel.lock", root_entries["MODULE.bazel.lock"],
         "11f8a421224b9b05f32c4c14054e8868083d989fc497310c8d51e1156f189ca3"),
    ]
    rows = []
    for logical, local, leaf, native_sha in specs:
        original = local.read_bytes()
        original_id = identity(original)
        assert original_id["git_blob"] == leaf["sha"]
        assert original_id["bytes"] == leaf["size"]
        assert original_id["sha256"] == native_sha
        assert original.count(b"\r") == 0
        windows = original.replace(b"\n", b"\r\n")
        win_id = identity(windows)
        assert windows.replace(b"\r\n", b"\n") == original
        assert win_id["sha256"] == business["inputs"][logical] == retained["inputs"][logical]
        rows.append({
            "logical_path": logical,
            "local_original_path": str(local.relative_to(ROOT)),
            "fixed_git_leaf": leaf,
            "stored_lf": original_id,
            "stored_cr_count": original.count(b"\r"),
            "stored_lf_count": original.count(b"\n"),
            "reconstructed_crlf": win_id,
            "business_artifact_reported_sha256": business["inputs"][logical],
            "retained_artifact_reported_sha256": retained["inputs"][logical],
            "both_exact_sha256_matches": True,
            "inverse_crlf_to_lf_is_byte_equal": True,
        })
    attrs = (HERE / "gitattributes.source.txt").read_bytes()
    assert identity(attrs)["git_blob"] == root_entries[".gitattributes"]["sha"]
    receipt = {
        "schema": "hepta.windows-lock-checkout-eol.v1",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "verdict": "EXACT_CRLF_RECONSTRUCTION_MATCHES_BOTH_WINDOWS_INPUT_RECEIPTS",
        "product_head": retained["source_head"],
        "product_tree": retained["source_tree"],
        "business_merge": business["head"],
        "business_merge_parents": business["parents"],
        "business_run_id": business["run_id"],
        "business_job_id": 127149582006,
        "retained_run_id": retained["run_id"],
        "retained_job_id": 127149547694,
        "run_attempt": 1,
        "rows": rows,
        "gitattributes": {"identity": identity(attrs), "text": attrs.decode(),
            "lock_file_eol_override_present": False},
        "original_input_receipts": [
            {"path": str(p.relative_to(ROOT)), **identity(p.read_bytes())}
            for p in [business_path, retained_path]
        ],
        "scope": [
            "The actual b265 Git root and codex-rs subtree were fetched and the two stored leaf identities verified independently.",
            "Cargo original text was read from its fixed Git blob. MODULE original text was reused from an already verified original UI artifact and matched the current leaf exactly.",
            "Changing every LF to CRLF, with no other byte changes, reproduces each reported Windows SHA256 exactly in both independent job source receipts.",
            "The Windows ZIPs contain the input hashes, not the full working-tree lock files. The CRLF bodies here are reconstructed candidates verified by cryptographic hash equality, not separately downloaded Windows lock bodies.",
            "This proves the recorded difference is fully accounted for by line endings. It does not imply the source Git blobs and Windows working-tree byte sequences are identical.",
            "No new native build, test, checkout, repository source change, index change or ref update was performed. No new qualification is inferred.",
        ],
        "reproduce": "python research-audit/published-5b633-ci-20261105/windows-checkout-locks/verify_lock_eol.py",
    }
    (HERE / "lock-eol-review.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"verdict": receipt["verdict"], "rows": len(rows), "output": str(HERE / "lock-eol-review.json")}))


if __name__ == "__main__":
    run()
