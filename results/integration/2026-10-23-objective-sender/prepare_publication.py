#!/usr/bin/env python3
"""Freeze exact candidate source and preserve successful and failed evidence."""
import datetime
import difflib
import hashlib
import json
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET

import owner_overlay

ROOT = Path(__file__).resolve().parent.parent
VALIDATION = ROOT / "validation"
PUBLICATION = ROOT / "publication"
EVIDENCE_PATH = "results/integration/2026-10-23-objective-sender"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def git_tree(rows):
    root = {}
    for row in rows:
        cursor = root
        parts = row["path"].split("/")
        for name in parts[:-1]:
            cursor = cursor.setdefault(name, {})
        cursor[parts[-1]] = (row["mode"], row["sha"])

    def digest(tree):
        data = bytearray()
        for name in sorted(tree, key=lambda name: name + ("/" if isinstance(tree[name], dict) else "")):
            value = tree[name]
            mode, object_id = ("40000", digest(value)) if isinstance(value, dict) else value
            data.extend(mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(object_id))
        return hashlib.sha1(b"tree " + str(len(data)).encode() + b"\0" + data).hexdigest()

    return digest(root)


def receipt(name):
    return json.loads((VALIDATION / (name + ".json")).read_text())


def main():
    assert not (PUBLICATION / "manifest.json").exists(), "Never overwrite a frozen publication."
    changes = owner_overlay.changes()
    assert len(changes) == 19
    identity = json.loads((VALIDATION / "overlay-identity.json").read_text())
    assert changes == identity["changes"]
    final = receipt("memory-all-final")
    assert final["exit_code"] == 0 and final["controlled_stop_reason"] is None
    assert final["overlay_changes"] == changes
    assert final["Cargo_lock_sha256_before"] == final["Cargo_lock_sha256_after"]
    assert final["source_verification_after"]["unrecorded_differences"] == []
    formatting = receipt("memory-final-fmt-check")
    assert formatting["exit_code"] == 0 and not formatting["rewrites"]
    assert formatting["after_changes"] == changes
    assert formatting["source_verification_error"] is None
    junit = ET.parse(VALIDATION / "memory-all-final.junit.xml").getroot()
    assert junit.attrib["tests"] == "317"
    assert junit.attrib["failures"] == junit.attrib["errors"] == "0"
    cases = [case.attrib["name"] for case in junit.iter("testcase")]
    sender = [name for name in cases if "objective_sender::" in name]
    recovery = [name for name in cases if name.startswith("cognitive_store::recovery::tests::")]
    assert len(sender) == 16 and len(recovery) == 14
    assert all(not path["path"].endswith(("Cargo.toml", "Cargo.lock", "MODULE.bazel.lock")) for path in changes)
    base = owner_overlay.BASELINE
    assert git_tree(base["blobs"]) == base["tree"]
    candidate_blobs = {row["path"]: row.copy() for row in base["blobs"]}
    for row in changes:
        candidate_blobs[row["path"]] = {"path": row["path"], "sha": row["candidate_git_blob"], "mode": row["mode"]}
    candidate_tree = git_tree(candidate_blobs.values())
    PUBLICATION.mkdir(parents=True, exist_ok=True)
    patch = []
    additions = deletions = 0
    for row in changes:
        path = row["path"]
        before = (ROOT / "base" / path).read_text() if row["preimage_git_blob"] else ""
        after = (ROOT / "change" / path).read_text()
        patch.append(f"diff --git a/{path} b/{path}\n")
        if row["preimage_git_blob"] is None:
            patch.append(f"new file mode {row['mode']}\n")
            patch.append(f"index 0000000..{row['candidate_git_blob']}\n")
        else:
            patch.append(f"index {row['preimage_git_blob']}..{row['candidate_git_blob']} {row['mode']}\n")
        diff = list(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True), fromfile=f"a/{path}" if before else "/dev/null", tofile=f"b/{path}"))
        additions += sum(line.startswith("+") and not line.startswith("+++") for line in diff)
        deletions += sum(line.startswith("-") and not line.startswith("---") for line in diff)
        patch.extend(diff)
    patch_path = PUBLICATION / "objective-sender.patch"
    patch_path.write_text("".join(patch))
    reports = [
        "memory-sender-schema-recovery-01", "memory-sender-schema-recovery-02",
        "memory-sender-schema-recovery-03-recovered-receipt", "memory-sender-schema-recovery-03",
        "memory-sender-schema-recovery-04", "memory-all-01", "memory-all-final",
        "memory-clippy-fix-01", "memory-clippy-fix-02", "memory-final-fmt", "memory-final-fmt-check",
        "schema-oracle", "crash-diagnostic-01", "clippy-metadata-cleanup",
        "overlay-identity", "format-baseline-identity", "candidate-test-binary-space",
    ]
    evidence = []
    destination = PUBLICATION / EVIDENCE_PATH
    destination.mkdir(parents=True, exist_ok=True)
    for name in reports:
        for extension in ["json", "stdout", "stderr", "junit.xml"]:
            source = VALIDATION / f"{name}.{extension}"
            if source.is_file():
                target = destination / source.name
                shutil.copyfile(source, target)
                data = target.read_bytes()
                evidence.append({"path": f"{EVIDENCE_PATH}/{target.name}", "source_path": str(target), "bytes": len(data), "sha256": sha256(data)})
    for name in ["owner_overlay.py", "run_owner_candidate.py", "run_owner_quality.py", "prepare_publication.py"]:
        source = VALIDATION / name
        target = destination / name
        shutil.copyfile(source, target)
        data = target.read_bytes()
        evidence.append({"path": f"{EVIDENCE_PATH}/{name}", "source_path": str(target), "bytes": len(data), "sha256": sha256(data)})
    test_summary = {
        "original_owning_package": "codex-hepta-memory",
        "original_entry_point": final["command"],
        "executed": 317, "passed": 317, "failed": 0,
        "not_executed_reported_by_nextest": 8,
        "junit_execution_seconds": float(junit.attrib["time"]),
        "new_sender_tests_passed": sender,
        "original_recovery_tests_passed": recovery,
        "original_schema_and_migration_tests_passed": [name for name in cases if "schema" in name or "migrat" in name],
        "all_executed_test_names": cases,
        "Agentd_bridge_tests": {"authored": 3, "executed": 0, "status": "Not executed; original Agentd package build remains separately unqualified."},
        "Clippy": {"attempted": True, "passed": False, "final_attempt_exit_code": 130, "reason": "Controlled stop below the coordinated 256 MiB shared-memory boundary, before owning-package lint analysis."},
        "format": {"original_just_fmt_exit_code": 0, "original_just_fmt_check_exit_code": 0},
        "production_checkpoint_provider": "Required interface implemented by embedding host; no production provider in this slice.",
        "old_schema_production_upgrade": "Explicitly fails closed; an authorized upgrade with a new independently authenticated current cut is not implemented.",
        "legacy_fresh_initialization": "Original recovery rejects observed legacy fresh WAL/SHM mode 0644; production crash tests first enter original open_with_recovery. No permission or recovery gate was relaxed.",
    }
    summary_path = destination / "execution-summary.json"
    summary_path.write_text(json.dumps(test_summary, indent=2) + "\n")
    data = summary_path.read_bytes()
    evidence.append({"path": f"{EVIDENCE_PATH}/{summary_path.name}", "source_path": str(summary_path), "bytes": len(data), "sha256": sha256(data)})
    readme = destination / "README.md"
    readme.write_text(f"""# Original Objective sender: execution record

The final candidate extends the original Hepta CognitiveStore and
ProductionDurableWriter. It retains the exact Objective request and complete
origin in the original database, occupies one durable sending opportunity,
requires an independent current-cut acknowledgement, and preserves unknown,
observation and local cancellation state without regranting send after restart.

Base: `{base['head']}` / tree `{base['tree']}`.
Source-only candidate tree: `{candidate_tree}`. The publication manifest binds
all 19 changed paths to original Git preimages and final SHA-256 values.
All 9,111 original source blobs and file modes were checked before and after
the final run; the candidate overlay was explicit. No Cargo manifest,
Cargo.lock or Bazel dependency lock changed. Existing `BUILD.bazel` includes
the new migration through its original `migrations/**` compile-data glob.

## Executed verification

| Original gate | Actual result | Qualification |
| --- | --- | --- |
| `just test --locked --cargo-profile dev-small --build-jobs 1 --test-threads 1 -p codex-hepta-memory --lib` | 317 executed / 317 passed / 0 failed; nextest separately reports 8 skipped | Final formatted candidate, Rust 1.95.0, {junit.attrib['time']} seconds of test execution; not an Agentd or native guest qualification. |
| Focused original sender/schema/recovery entry | 42 / 42 passed before final formatting; all included in final full run | 16 new sender tests, 14 original recovery tests, original schema and related regressions. |
| Original `just fmt` then `just fmt --check` | Both exit 0 | Final source byte identities are in the receipts. |
| Original scoped `just fix -p codex-hepta-memory --locked --profile dev-small --lib` | Incomplete; final attempt controlled exit 130 | Additional check metadata crossed the agreed 256 MiB shared-memory boundary, before the owning-package lint analysis. No source rewrite occurred. This is not a Clippy pass. |
| Original Agentd bridge tests | Three authored, zero executed | Installed same-owner capability, uninstalled refusal, and actual AuthBus body cross-package digest compatibility remain separate package gates. |

The final package run includes actual second-process uniqueness and three child
process exits immediately after committed request, observation and local-cancel
cuts. The children exit without Rust destructors. Original exact-cut recovery
then refuses to return another send permission. Test-only checkpoint probes do
not authenticate a production current-cut service.

The original recovery regressions cover current/predecessor witnesses, exact
current-cut writable activation, cold read-only recovery, pending WAL refusal,
physical FTS corruption, hostile file identities, bounded rows and unknown
tables, exclusive owner fencing, graceful close, and post-rename unknown state.
`execution-summary.json` contains every executed test name and the exact 14
original recovery names.

## Earlier failures were retained and resolved

- The first focused attempt stopped at the storage guard before the candidate
  compiled. A later attempt reached an actual test-only `SqlSafeStr` compile
  failure; the test now uses the original static trigger DDL.
- The first executing focused run had 39 passes and three failures. Fixes kept
  the production gates intact: a new lease epoch receives a distinct original
  fencing token; the tamper fixture uses separate static statements in the
  original transaction; the crash fixture enters original production recovery
  before its crash boundary. The wrapper initially rejected the generated
  nextest JUnit file. Its recovered receipt preserves that reporting failure
  without inventing a lost subprocess exit code.
- The first full run had 316 passes and one stale migration assertion: actual
  compiled migrations were 1 through 17 while the old test expected 1 through
  16. Only that expected original migration chain changed. The final full run
  above re-executed the complete library successfully.
- The first Clippy invocation was rejected because the restored source had no
  discoverable Git checkout. Validation then fetched and verified the exact
  original commit into external local Git metadata. The next original Clippy
  attempt ran but hit the resource boundary. Its 43,350,215 bytes of newly
  produced check-only metadata were SHA-recorded before removal; the original
  linked test graph, source, cache and locks remained intact.

## Legacy fresh initialization remains a separate boundary

An actual diagnostic of a legacy fresh `CognitiveStore::open` crash observed a
0600 main database but 0644 WAL/SHM sidecars under the inherited umask. Original
production recovery correctly rejects those identities. The patch does not
chmod an existing source, weaken recovery, or add a fallback to legacy open.
The positive crash tests explicitly establish test genesis, close it, enter
the original `open_with_recovery`, and only then exercise production commits
and process death. This is not a new production first-provisioning service.

## Remaining production work

1. A real independent checkpoint host must authenticate and fence publishers,
   durably ACK the exact full original cut, and handle cancellation without
   late publication. This slice requires that capability and supplies no
   production default or echo implementation.
2. Old-schema production anchors intentionally fail the new schema oracle.
   An authorized upgrade and a new independently authenticated current cut are
   still required; legacy open cannot repair a rejected production source.
3. The original Agentd package must execute the three bridge regressions, and
   Clippy must complete on a runner with adequate space. Memory passing does
   not substitute for either gate.
4. Trusted Session adapter composition and original journal ACK publication
   must remain bound to real owners. A CognitiveStore cut is not an Objective
   history anchor; a local cancel is not RunCancel; a retained unknown is not
   permission to resend. Other original writer domains still need their own
   checkpoint publication integration.

No native guest, QEMU, hardware, model turn or actual Objective dispatch ran as
part of this candidate's memory qualification. No remote write was performed
by the implementation agent. Source publication and merge remain the parent
reviewer's actions.
""")
    data = readme.read_bytes()
    evidence.append({"path": f"{EVIDENCE_PATH}/{readme.name}", "source_path": str(readme), "bytes": len(data), "sha256": sha256(data)})
    manifest = {
        "repository": "TrillionniumFoundation/hepta-private-ci",
        "base_head": base["head"], "base_tree": base["tree"],
        "source_only_candidate_tree": candidate_tree,
        "candidate_stage": "Final source, Rust 1.95 original memory package 317/317 passed; Agentd bridge and Clippy remain unqualified.",
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "files": [{**row, "source_path": str(ROOT / "change" / row["path"])} for row in changes],
        "diff_lines": {"added": additions, "removed": deletions},
        "patch_path": str(patch_path), "patch_sha256": sha256(patch_path.read_bytes()),
        "evidence": evidence,
        "final_test_receipt": f"{EVIDENCE_PATH}/memory-all-final.json",
        "execution_summary": f"{EVIDENCE_PATH}/execution-summary.json",
        "Cargo_lock_sha256": final["Cargo_lock_sha256_after"],
        "schema_oracle_sha256": "55a697816bedf97c5fa3ef36a4d9d39d98f6f572d825a38541afe62e19203773",
        "supersedes": str(ROOT / "patches/draft-source-manifest.json"),
    }
    (PUBLICATION / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"manifest": str(PUBLICATION / "manifest.json"), "source_files": len(changes), "source_tree": candidate_tree, "evidence_files": len(evidence), "patch_sha256": manifest["patch_sha256"], "source_bytes": sum(row["bytes"] for row in changes), "evidence_bytes": sum(row["bytes"] for row in evidence), "diff_lines": manifest["diff_lines"]}, indent=2))


if __name__ == "__main__":
    main()
