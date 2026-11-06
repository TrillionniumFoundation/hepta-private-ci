#!/usr/bin/env python3
"""Build the one-file r16 fixture candidate and audit exact inverse transforms."""
from pathlib import Path
import difflib
import hashlib
import json
import re
import shutil

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
NATIVE = WORKSPACE / "native-validation-results/r16-blockers"
SOURCE_COMMIT = "96dc9232535fedf735e3099ef1391b69477270d4"
SOURCE_TREE = "3ebd193f213d640e5330a1be4b983bcc4b06617a"
TARGET = "codex-rs/core/tests/suite/turn_input_submission.rs"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def write_json(name, value):
    p = ROOT / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


native_manifest = json.loads((NATIVE / "original-input/source-manifest.json").read_bytes())
native_pins = {e["path"]: e for e in native_manifest["related_source_pins"]}
assert native_manifest["source_tree"] == SOURCE_TREE
assert native_manifest["source_commit"] == SOURCE_COMMIT
support = [
    (TARGET, NATIVE / "original-input/source" / TARGET),
    ("codex-rs/core/src/session/turn_input.rs", WORKSPACE / "core-mcp-recovery-r14-audit/original/codex-rs/core/src/session/turn_input.rs"),
    ("codex-rs/core/src/codex_thread.rs", WORKSPACE / "core-recovery-epoch-r14-fixture/original/codex-rs/core/src/codex_thread.rs"),
]
pins = []
for name, path in support:
    data = path.read_bytes()
    expected = native_pins[name]
    assert (len(data), sha(data), blob(data)) == (expected["bytes"], expected["sha256"], expected["git_blob"])
    dest = ROOT / "original" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    pins.append({**expected, "native_source_manifest_match": True, "read_from": str(path.relative_to(WORKSPACE)), "immutable_url": f"https://github.com/TrillionniumFoundation/hepta-private-ci/blob/{SOURCE_COMMIT}/{name}"})

github_pins = json.loads((ROOT / "github-read-pins.json").read_bytes())
for pin in github_pins["files"]:
    data = (ROOT / "original" / pin["path"]).read_bytes()
    assert (len(data), sha(data), blob(data)) == (pin["bytes"], pin["sha256"], pin["git_blob"])
    pins.append(pin)

guidance = (NATIVE / "original-input/source/AGENTS.md").read_bytes()
base_map = json.loads((WORKSPACE / "native-validation-results/checkpoint-r14/INDEPENDENT-SOURCE-TREE-INPUT.json").read_bytes())
base_agent = next(e for e in base_map["base_entries"] if e["path"] == "AGENTS.md")
assert blob(guidance) == base_agent["sha"]
(ROOT / "original/AGENTS.md").write_bytes(guidance)
pins.append({"path": "AGENTS.md", "bytes": len(guidance), "sha256": sha(guidance), "git_blob": blob(guidance), "native_nearest_guidance": native_manifest["nearest_guidance_paths"], "original_base_blob_match": True})

before = (ROOT / "original" / TARGET).read_text()
start = before.index("#[tokio::test]\nasync fn recover_turn_if_idle_preserves_id_and_resumes_plan_mode()")
end = before.index("/// Concurrent submissions must start exactly one turn", start)
old_test = before[start:end]
edits = [
    (
        '''    let initial_submission = submit_user_message(&test.codex, "recoverable user input")
        .await
        .expect("initial turn should start");''',
        '''    let plan_mode = CollaborationMode {
        mode: ModeKind::Plan,
        settings: Settings {
            model: test.session_configured.model.clone(),
            reasoning_effort: None,
            developer_instructions: None,
        },
    };
    // Recovery resumes the interrupted settings; select Plan on the original user turn.
    let initial_submission = test
        .codex
        .start_or_steer_turn(user_message_request("recoverable user input").with_thread_settings(
            ThreadSettingsOverrides {
                collaboration_mode: Some(plan_mode.clone()),
                ..Default::default()
            },
        ))
        .await
        .expect("initial turn should start");''',
    ),
    (
        '''        panic!("initial recovery fixture turn must start: {initial_submission:?}");
    };
    timeout(Duration::from_secs(5), server.wait_for_request_count(1))''',
        '''        panic!("initial recovery fixture turn must start: {initial_submission:?}");
    };
    assert_eq!(
        test.codex.config_snapshot().await.collaboration_mode,
        plan_mode,
        "the original user turn must enter Plan mode before interruption"
    );
    timeout(Duration::from_secs(5), server.wait_for_request_count(1))''',
    ),
    (
        '''            thread_settings: ThreadSettingsOverrides {
                collaboration_mode: Some(CollaborationMode {
                    mode: ModeKind::Plan,
                    settings: Settings {
                        model: test.session_configured.model.clone(),
                        reasoning_effort: None,
                        developer_instructions: None,
                    },
                }),
                ..Default::default()
            },''',
        '''            thread_settings: ThreadSettingsOverrides::default(),''',
    ),
    (
        '''    let started = wait_for_event(&test.codex, |event| {
        matches!(event, EventMsg::TurnStarted(_))''',
        '''    assert_eq!(
        test.codex.config_snapshot().await.collaboration_mode,
        plan_mode,
        "recovery must preserve the original Plan mode and its settings"
    );

    let started = wait_for_event(&test.codex, |event| {
        matches!(event, EventMsg::TurnStarted(_))''',
    ),
]
new_test = old_test
for old, new in edits:
    assert new_test.count(old) == 1
    new_test = new_test.replace(old, new, 1)
after = before[:start] + new_test + before[end:]
inverse = new_test
for old, new in reversed(edits):
    assert inverse.count(new) == 1
    inverse = inverse.replace(new, old, 1)
assert before[:start] + inverse + before[end:] == before
assert after[:start] == before[:start] and after[start + len(new_test):] == before[end:]

# Every pre-existing assertion remains byte-for-byte in the one changed test.
assertions = re.findall(r"    assert(?:_eq|_ne)?!\([^\n]*\);|    assert(?:_eq|_ne)?!\([\s\S]*?\n    \);", old_test)
assert len(assertions) == 7, len(assertions)
assert all(item in new_test for item in assertions)
assert re.findall(r"(?:Duration::from_(?:secs|millis)\(\d+\)|expected_epoch|turn_id: turn_id.clone\(\))", new_test) == re.findall(r"(?:Duration::from_(?:secs|millis)\(\d+\)|expected_epoch|turn_id: turn_id.clone\(\))", old_test)
assert new_test.count('"recoverable user input"') == old_test.count('"recoverable user input"')
assert new_test.count("ModeKind::Plan") == old_test.count("ModeKind::Plan") == 1
assert len(re.findall(r"^#\[tokio::test", after, re.M)) == len(re.findall(r"^#\[tokio::test", before, re.M))

candidate = ROOT / "source" / TARGET
candidate.parent.mkdir(parents=True, exist_ok=True)
candidate.write_text(after)
patch = "".join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True), fromfile="a/" + TARGET, tofile="b/" + TARGET))
(ROOT / "repair.patch").write_text(patch)
before_bytes = before.encode()
after_bytes = after.encode()
manifest = {"schema": "hepta.r16-recovery-settings-fixture-source.v1", "source_base_commit": SOURCE_COMMIT, "source_base_tree": SOURCE_TREE, "files": [{"path": TARGET, "before": {"bytes": len(before_bytes), "sha256": sha(before_bytes), "git_blob": blob(before_bytes)}, "after": {"bytes": len(after_bytes), "sha256": sha(after_bytes), "git_blob": blob(after_bytes)}, "mode": "100644"}], "patch": {"path": "repair.patch", "bytes": len(patch.encode()), "sha256": sha(patch.encode())}, "exact_inverse_sha256": sha((before[:start] + inverse + before[end:]).encode()), "exact_inverse_equals_original": True}
write_json("source-manifest.json", manifest)
write_json("source-input-pins.json", {"schema": "hepta.r16-recovery-settings-fixture-input.v1", "source_commit": SOURCE_COMMIT, "source_tree": SOURCE_TREE, "files": pins, "native_source_manifest": {"path": "support/native-source-input-manifest.json", "bytes": (NATIVE / "original-input/source-manifest.json").stat().st_size, "sha256": sha((NATIVE / "original-input/source-manifest.json").read_bytes())}})
(ROOT / "support").mkdir(exist_ok=True)
for src, dest in [(NATIVE / "original-input/source-manifest.json", ROOT / "support/native-source-input-manifest.json"), (NATIVE / "failure-source-pins.json", ROOT / "support/native-failure-source-pins.json"), (NATIVE / "native-core-mcp-r16-result-review.json", ROOT / "support/native-core-mcp-r16-result-review.json")]:
    shutil.copyfile(src, dest)
write_json("mechanical-readback.json", {"schema": "hepta.r16-recovery-settings-fixture-mechanical.v1", "exact_inverse_equals_original": True, "outside_one_test_unchanged": True, "preexisting_assertions_count": len(assertions), "all_preexisting_assertions_preserved_exactly": True, "new_configuration_readback_assertions": 2, "duration_epoch_id_token_sequence_unchanged": True, "same_test_declarations": True, "source45_header_gate_unchanged": True, "original_input_string_occurrences_unchanged": True, "patch_files": 1, "rust_or_test_commands_executed": False, "native_source_modified": False})
print(json.dumps(manifest, indent=2))
