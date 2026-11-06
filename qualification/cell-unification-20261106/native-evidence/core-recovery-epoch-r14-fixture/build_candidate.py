from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
BASE_COMMIT = "b44d4ca4aa0ef9f894eff29e9975938e066a82f5"
BASE_TREE = "d3d2313b838422818bf9448ce5a1b86d89abdf69"
SOURCE = "codex-rs/core/tests/suite/turn_input_submission.rs"
TEST = "suite::turn_input_submission::recover_turn_if_idle_preserves_id_and_resumes_plan_mode"
PINS = {
    SOURCE: (
        "3e2e4ae457f30315ad0614c81cfac55050d7a7b79d8ebdaf50af972ae7970773",
        "9f1fc48fbafdf48ba7b97774ceaf6b47c06f9a50",
    ),
    "codex-rs/core/src/tasks/mod.rs": (
        "b51df87d911a73b51ac13cf28157f4d3bb3a7192f3aa2621265c849acc157a88",
        "04332800b862436b2e372c78145bae849e596822",
    ),
    "codex-rs/core/src/codex_thread.rs": (
        "a2b7930a96d8a32ee9747fa9da8e1fc9c8c77af19aefda898466b1799347f02f",
        "589f0b9305aeb8cf257cdb3d7a83c22335f17252",
    ),
    "codex-rs/core/src/session/turn.rs": (
        "a0cdb211158e4e3f46a5fe35f61dd778432ad115c710ead77500126066bdacf4",
        "a8e1fca6dd5a97f838262cf8f13087928beb9a20",
    ),
    "codex-rs/core/tests/common/streaming_sse.rs": (
        "ed1e35fa973116adf94c8ddbb39bb7e0d2c4c7773b980277921f859ce40d252b",
        "3766bbd88084f0ba514df52143918450be7d21eb",
    ),
}


def identity(data: bytes) -> dict:
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


support = []
for path, (sha256, git_blob) in PINS.items():
    actual = identity((ROOT / "original" / path).read_bytes())
    assert actual["sha256"] == sha256, path
    assert actual["git_blob"] == git_blob, path
    support.append({"path": path, **actual})

original = (ROOT / "original" / SOURCE).read_bytes()
old = b'''            StreamingSseChunk {
                gate: None,
                body: responses::sse(vec![ev_response_created("resp-interrupted")]),
            },
            StreamingSseChunk {
                gate: Some(first_response_gate),
                body: responses::sse(vec![ev_completed("resp-interrupted")]),
            },'''
new = b'''            StreamingSseChunk {
                // Recovery ends when the first provider event reaches the turn
                // executor, including response.created. Keep that event gated.
                gate: Some(first_response_gate),
                body: responses::sse(vec![ev_response_created("resp-interrupted")]),
            },
            StreamingSseChunk {
                gate: None,
                body: responses::sse(vec![ev_completed("resp-interrupted")]),
            },'''
assert original.count(old) == 1
candidate = original.replace(old, new)
assert candidate.count(new) == 1
assert candidate.replace(new, old) == original
assert old.count(b"Some(first_response_gate)") == new.count(b"Some(first_response_gate)") == 1
assert old.count(b"gate: None") == new.count(b"gate: None") == 1
assert [line for line in old.splitlines() if b"body:" in line] == [
    line for line in new.splitlines() if b"body:" in line
]
unchanged_suffix = original.split(old)[1]
assert candidate.split(new)[1] == unchanged_suffix
assert b"timeout(Duration::from_secs(5)" in unchanged_suffix
assert b"collaboration_mode: Some(CollaborationMode" in unchanged_suffix
assert b"mode: ModeKind::Plan" in unchanged_suffix
assert b"drop(first_response_release);" in unchanged_suffix

destination = ROOT / "source" / SOURCE
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_bytes(candidate)
patch = "".join(
    difflib.unified_diff(
        original.decode().splitlines(keepends=True),
        candidate.decode().splitlines(keepends=True),
        fromfile="a/" + SOURCE,
        tofile="b/" + SOURCE,
    )
).encode()
(ROOT / "repair.patch").write_bytes(patch)
write_json(ROOT / "edit-operations.json", {
    "base_commit": BASE_COMMIT,
    "operations": [{"path": SOURCE, "old": old.decode(), "new": new.decode(), "count": 1}],
})
write_json(ROOT / "source-manifest.json", {
    "base_commit": BASE_COMMIT,
    "base_tree": BASE_TREE,
    "files": [{
        "path": SOURCE,
        "git_mode": "100644",
        "before": identity(original),
        "after": identity(candidate),
        "exact_inverse": True,
    }],
    "patch": identity(patch),
    "support_sources": support,
})

closed_path = WORKSPACE / "native-validation-results/r14-blockers/native-core-r14-result-review.json"
closed_bytes = closed_path.read_bytes()
assert hashlib.sha256(closed_bytes).hexdigest() == "9b5b3a81d4901d8c6769908e2021235e3ef82e3257d5b0c21bf1c086899f0732"
closed = json.loads(closed_bytes)
assert closed["source_tree"] == BASE_TREE
assert closed["source_commit"] == BASE_COMMIT
failures = [block for block in closed["blocks"] if block["name"] == TEST]
assert len(failures) == 1 and failures[0]["status"] == "FAIL"
failure = failures[0]
(ROOT / "original-failure.log").write_text(failure["excerpt"], encoding="utf-8")
write_json(ROOT / "repair-audit.json", {
    "schema": "hepta.fixture-repair-source-audit.v1",
    "status": "FROZEN_SOURCE_REVIEW_ONLY_NATIVE_VALIDATION_PENDING",
    "base_commit": BASE_COMMIT,
    "base_tree": BASE_TREE,
    "test": TEST,
    "kind": "existing_recovery_fixture_pre_output_boundary_alignment",
    "original_failure": {
        "closed_review": str(closed_path.relative_to(WORKSPACE)),
        "closed_review_sha256": identity(closed_bytes)["sha256"],
        "raw_log_sha256": closed["log_sha256"],
        "elapsed": failure["elapsed"],
        "log_byte_range": failure["log_byte_range"],
        "observed_error": "interrupted idle turn should expose its recovery epoch: Elapsed(())",
        "limitations": "The failure proves that the epoch was not observed in the original five-second budget. It does not contain a per-event trace proving when response.created crossed the owner gate.",
    },
    "source_causal_chain": [
        {
            "path": SOURCE,
            "lines": "119-210",
            "fact": "The original fixture releases response.created immediately and gates only response.completed, then interrupts after the first physical request and historical durable Ready assertions.",
        },
        {
            "path": "codex-rs/core/src/session/turn.rs",
            "lines": "2820-2854",
            "fact": "The first successfully received ResponseEvent closes recovery authority before matching the event; ResponseEvent::Created is included.",
        },
        {
            "path": "codex-rs/core/src/tasks/mod.rs",
            "lines": "2079-2114",
            "fact": "The same-owner first-output gate calls ensure_turn_recovery_unready while the exact task and authority are still attached.",
        },
        {
            "path": "codex-rs/core/src/tasks/mod.rs",
            "lines": "1720-1760",
            "fact": "An interrupted recovery seed requires an eligible model turn, durable Ready state, ready atomic, and the recorded replay/fingerprint/generation. An old Ready entry alone is insufficient.",
        },
        {
            "path": "codex-rs/core/tests/common/streaming_sse.rs",
            "lines": "119-150; 257-259",
            "fact": "The server records and notifies the physical request before awaiting any chunk gate. Its bare SSE headers do not contain model or rate-limit event metadata. Dropping the release sender makes the gated chunk return without writing provider event bytes.",
        },
    ],
    "inference": "The original fixture permits response.created to invalidate Ready before its Interrupt, contrary to this test's intended pre-output recovery scenario. Relocating the same gate before the first event eliminates that fixture interleaving without weakening the production recovery boundary.",
    "change": "Move the existing first_response_gate from response.completed to response.created. Keep the event bodies and order, sender, interrupt, sender drop, and every subsequent recovery assertion identical.",
    "retained": [
        "All production recovery authority, ownership, durable state, request fingerprint, generation, cancellation and replay logic.",
        "The original test count and all original assertion/panic/expect expressions, in their original order.",
        "The physical request observation and durable input-before-Ready and TurnContext-before-Ready assertions.",
        "The original five-second budgets, ten-millisecond polling interval, Interrupt, TurnAborted wait and release-sender drop order.",
        "The recovery epoch, original turn ID, Plan collaboration override, TurnStarted/TurnComplete observations, exact two-request and single-original-input assertions.",
        "The same two streaming responses, all response event bodies, the single oneshot receiver and both completion handles.",
    ],
    "mechanical_verification": {
        "all_five_original_source_sha256_and_git_blobs_verified": True,
        "single_unique_replacement": True,
        "exact_inverse_restores_original_bytes": True,
        "event_body_lines_and_order_unchanged": True,
        "gate_count_and_receiver_identity_unchanged": True,
        "entire_test_body_after_response_fixture_unchanged": True,
        "other_tests_and_imports_unchanged": True,
    },
    "validation": {
        "python_source_and_inverse_checks": "PASS",
        "rust_compile": "NOT_RUN",
        "native_original_core_gate": "PENDING",
        "formatting": "NOT_RUN",
        "claim": "A source-reviewed isolated fixture candidate, not a native PASS or proof that all later recovery assertions already pass.",
    },
    "patch": identity(patch),
    "candidate": identity(candidate),
    "wire_digest_authority": "No production API, wire schema, digest, serialized state, permission, deadline, feature flag or runner/filter changes.",
})
print(json.dumps({
    "candidate": identity(candidate),
    "patch": identity(patch),
    "audit": identity((ROOT / "repair-audit.json").read_bytes()),
    "manifest": identity((ROOT / "source-manifest.json").read_bytes()),
}, indent=2))
