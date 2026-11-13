#!/usr/bin/env python3
"""Prepare the isolated source packet; no Rust/toolchain/native execution."""
from pathlib import Path
import datetime
import difflib
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parent
BASE = "cc57c7198db6293ccca562253c42fffbe2a04633"
TREE = "b7b357c07b5539769a068c6b9b009629f5612d1e"
SHARED = "92a1567ac32c886d9d7386fb80915071475528bf"
LOCAL_S = "90f0623289c99ecce60d68d9dad348d27e0bd7fa"
IDENTITY = "version-owned-evaluated-next-use-seam-v1"

def pin(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}

def write_json(name, value):
    data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    (ROOT / name).write_bytes(data)
    return pin(data)

def main():
    changes = []
    patch = []
    for path in sorted((ROOT / "after").rglob("*.rs")):
        relative = path.relative_to(ROOT / "after").as_posix()
        before_path = ROOT / "before" / relative
        before = before_path.read_bytes() if before_path.is_file() else None
        after = path.read_bytes()
        row = {"path": relative, "mode": "100644", "before": pin(before) if before is not None else None,
               "after": pin(after), "after_text": after.decode()}
        if before is not None:
            row["before_text"] = before.decode()
        changes.append(row)
        patch.extend(difflib.unified_diff(
            before.decode().splitlines(keepends=True) if before is not None else [],
            after.decode().splitlines(keepends=True),
            fromfile="a/" + relative if before is not None else "/dev/null", tofile="b/" + relative,
        ))
    assert len(changes) == 6
    assert sum(row["before"] is None for row in changes) == 4
    by_name = {Path(row["path"]).name: row for row in changes}
    host = by_name["circuit_retained_version_host.rs"]
    assert host["before"]["git_blob"] == "c949e2a64657bc2ec209253d149b09256f49b42e"
    mount = '\n#[path = "circuit_retained_version_next_use_readback.rs"]\nmod next_use_readback;\n'
    assert host["after_text"].count(mount) == 1
    assert host["after_text"].replace(mount, "", 1) == host["before_text"]
    read = by_name["circuit_learning_read_service.rs"]
    assert read["before"]["git_blob"] == "a2b190518040968eba90448016908974e69d6e40"
    text = read["after_text"]
    start = text.index("    /// The same prebound original channel, attenuated to the evaluated S cut.")
    stop = text.index("    pub(super) fn response(", start)
    restored = text[:start] + text[stop:]
    assert restored.count("use std::time::Instant;\n") == 1
    restored = restored.replace("use std::time::Instant;\n", "", 1)
    fixture_mount = '\n#[cfg(test)]\n#[path = "circuit_evaluated_next_use_read_channel_support_tests.rs"]\nmod evaluated_next_use_fixture;\n'
    assert restored.count(fixture_mount) == 1
    restored = restored.replace(fixture_mount, "", 1)
    assert restored == read["before_text"]
    new = by_name["circuit_retained_version_next_use_readback.rs"]["after_text"]
    for needed in ["self.bind_original_predecessor(&mut state)", "self.read_original_recovery(&mut state)",
                   "self.read_original(&state)", "original_context.snapshot() != evaluated.snapshot()",
                   "original_context.receipt_context_binding() != evaluated.receipt_context_binding()",
                   "for_original_next_use(selection.clone())", "original.cell.clone()",
                   "original.source.as_ref().clone()", "original.identity.clone()",
                   "selection.original_receipt_predecessors", "PublicationAccess::Readback",
                   "lifetime.min(remaining)", "try_acquire_owned()"]:
        assert needed in new, needed
    assert new.count("RetainedVersionFinalUseOutcomeV1::Published") == 2
    assert new.count("original_owner_command_channel_v1(") == 1
    assert "from_original_stream(" not in new
    assert "tokio::try_join!" not in new
    loop = text[start:stop]
    assert loop.count("for request_id in 1..=128") == 1
    assert loop.count("Instant::now() >= end") == 2
    assert loop.index("Instant::now() >= end") < loop.index("let bytes = response(self, bytes, request_id)?;")
    assert loop.rindex("Instant::now() >= end") > loop.index("let bytes = response(self, bytes, request_id)?;")
    assert "HostIssuerTransportError::InvalidRequest" in loop
    assert "Self::response" in loop and "Self::readiness_response" in loop
    tests = by_name["circuit_evaluated_version_next_use_readback_tests.rs"]["after_text"]
    names = re.findall(r'#\[tokio::test\([^\n]*\)\]\nasync fn ([a-z_]+)', tests)
    assert len(names) == 6
    assert "OriginalCircuitSelectionCommandOwnerV1::read_original_evaluated_receipt" in tests
    assert "into_evaluated_shared_command_owner" in tests
    assert "Version::share_original_evaluated_readbacks" in tests
    assert all(Path(row["path"]).name.endswith("_tests.rs")
               for row in changes if "fixture" in row["after_text"] and row["before"] is None
               and Path(row["path"]).name != "circuit_retained_version_next_use_readback.rs")
    references = []
    source_map = json.loads(Path("/tmp/hepta-36fa-provider-combined-preparation-v1/SOURCE_BASE_TREE.json").read_text())["files"]
    for path in sorted((ROOT / "reference").glob("*.rs")):
        relative = "codex-rs/hepta-agentd/src/" + path.name
        identity = pin(path.read_bytes())
        assert identity["git_blob"] == source_map[relative]
        references.append({"path": relative, **identity})
    packet = {"format": "hepta-source-proposal-v1", "identity": IDENTITY,
              "base_commit": BASE, "base_tree": TREE,
              "dependencies": [SHARED, LOCAL_S, "04fb77b4afb11c55ddbee1f0d4a631b4c1cf14ea",
                               "bfc96752df8c76fe59676696b6a1f77cef038aab"],
              "status": "isolated_preparation_not_formatted_compiled_or_run", "changes": changes}
    packet_pin = write_json("SOURCE_PACKET.json", packet)
    (ROOT / "SOURCE_DELTA.patch").write_text("".join(patch))
    mounting = {
        "status": "explicit_integration_hunk_for_ordinary_path_sole_writer_not_applied",
        "target": "codex-rs/hepta-agentd/src/circuit_evaluated_version_recovery_support_tests.rs",
        "baseline_after_test_packet": "a47922b80b3bd9ae0d1168efefdcfbde3f3a98b5",
        "append": '\n#[path = "circuit_evaluated_version_next_use_readback_tests.rs"]\nmod next_use_readback_tests;\n',
        "preserve": ["tests", "final_use_tests", "shared_readback_tests", "shared_export_tests"],
        "methods": names,
        "registration": "Child of the existing model_selection_owner test subtree; original focused filter preserved."
    }
    write_json("TEST_MOUNT.json", mounting)
    review = {
        "format": "hepta-version-next-use-source-review-v1", "identity": IDENTITY,
        "at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "verdict": "STATIC_SOURCE_AND_BYTE_CHECKS_COMPLETE_RUNTIME_UNVERIFIED",
        "source_packet": packet_pin, "source_paths": 6, "new_paths": 4, "modified_paths": 2,
        "inverse_full_bytes": {"Version_host": True, "read_service": True},
        "unchanged_contracts_and_old_serving": True,
        "actual_checks": [
            "Whole host restored by removal of the one new module mount.",
            "Whole original read_service restored by removal of new import, new methods and test module mount.",
            "Every reference file matched its exact canonical cc57 Git blob; no live branch fetched.",
            "One shared 128-request loop for the two new typed NextUse purposes; original loops untouched.",
            "Both pre-handler and post-handler absolute-end checks are in the actual exchange closure.",
            "Version original four-permit pool, 500ms exchange and at-most-300s transport bounds retained.",
            "Same Version lock covers live original admission, original C reader construction, full second read and final freshness.",
            "Exact original four-cut context plus full T/E/S signature authentication precedes reader return.",
            "The tests obtain opaque S through the new same-original-command-owner readonly API and compare all original bytes.",
            "All new test helpers use *_tests.rs; no collector ignore, thresholds, permissions or source policy changed."
        ],
        "semantic_scope": {
            "admission": "actual Published, original Material/D/T/E/Artifact/CURRENT/C with full original signature equality and final S authentication",
            "per_response": "unchanged original C/Source/profile and full T/E/S signature checks; absolute Version end before and after response generation",
            "live_T_E": "original same shared clients at Version admission, and existing NextUse Sources before/after actual C reads; no extra channel or queue",
            "idle": "original HAP relative lifetime/peer checks remain; not a claim of exact HAP end equality or instantaneous idle close at Version end",
            "cancel": "blocking readonly work may outlive a dropped await until its actual bound; no automatic retry or delivery claim",
            "missing_pending": "original readiness only; not NoUpdate, NoEffect, or permission to execute C"
        },
        "test_methods_prepared": names,
        "test_scope": "actual original A/T/B/S and published C in existing cold same-process fixture; not Fresh Root/public UID/real utility proof",
        "deadline_probe": "unchanged actual readiness response is formed, then yielded within a 250ms narrowed deadline inside the original 500ms envelope; no fabricated wire or changed clock",
        "pending": [
            "ordinary_path applies the single separate recovery-parent test mount without overwriting existing mounts",
            "Root registers new production boundaries/scopes after actual formatting",
            "Rust compile/type/privacy validation and all six real fixture executions remain unperformed",
            "Public cross-UID transport and Fresh ten-owner orchestration remain separate unverified integration work",
            "Normal startup must serialize admissions by successful original probes; shared client contention retains Unavailable without queuing",
            "An authentic foreign-operation S test constructs two real fixture operations; it must retain the unchanged native 60s budget"
        ],
        "executions": {"H": False, "Cargo": False, "rustfmt": False, "Rust_tests": False,
                       "gate": False, "source_activation": False, "ref_updates": False},
        "references": references,
    }
    write_json("STATIC_REVIEW.json", review)
    registration = {
        "status": "registration_plan_only_original_verifier_and_CALLERS_not_modified",
        "new_module": "codex-rs/hepta-agentd/src/circuit_retained_version_next_use_readback.rs",
        "public_entrypoints": ["OriginalCircuitRetainedVersionHostV1::serve_original_evaluated_next_use_readback",
                               "OriginalCircuitRetainedVersionHostV1::serve_original_evaluated_completion_readiness"],
        "private_scopes": ["serve_original_evaluated_next_use", "serve_original_evaluated_next_use_channel",
                           "build_original_evaluated_next_use_reader"],
        "read_service_new_scopes": ["serve_original_evaluated_next_use_channel",
                                    "serve_original_evaluated_next_use_readiness_channel",
                                    "serve_original_evaluated_next_use_profile"],
        "concrete_calls": ["original_owner_command_channel_v1", "OriginalCircuitEvaluatedLearningReadContextV1::for_original_next_use",
                           "OriginalCircuitLearningReadOwnerV1::from_original_evaluated_owners",
                           "OriginalCircuitLearningReadOwnerV1::serve_original_evaluated_next_use_channel",
                           "OriginalCircuitLearningReadOwnerV1::serve_original_evaluated_next_use_readiness_channel"],
        "permissions": "No owner getter, creator, writer, RunStart, signer, extra T/E connection, queue, renewal, or fallback authorization."
    }
    write_json("REGISTRATION_PLAN.json", registration)
    artifacts = []
    for path in [ROOT / name for name in ("SOURCE_PACKET.json", "SOURCE_DELTA.patch", "STATIC_REVIEW.json",
                                        "TEST_MOUNT.json", "REGISTRATION_PLAN.json", "build_package.py", "README.md")]:
        artifacts.append({"name": path.name, **pin(path.read_bytes())})
    manifest = {"format": "hepta-isolated-source-manifest-v1", "identity": IDENTITY,
                "status": "PREPARATION_HOLD_NOT_COMPILED_OR_RUN", "base_commit": BASE,
                "source_packet": packet_pin, "dependencies": packet["dependencies"],
                "changes": [{k:v for k,v in row.items() if k not in ("before_text", "after_text")} for row in changes],
                "artifacts": artifacts,
                "paths_relative_to": "qa/evidence/utility-evaluation-20261112-36fa/",
                "test_parent_mount_pending_sole_writer": True,
                "actual_git_publication": "Recorded separately after actual create and full GET; these hashes alone are computed."}
    write_json("MANIFEST.json", manifest)
    print(json.dumps({"packet": packet_pin, "manifest": pin((ROOT/"MANIFEST.json").read_bytes()),
                      "source_paths": 6, "test_methods": names}, indent=2))

if __name__ == "__main__":
    main()
