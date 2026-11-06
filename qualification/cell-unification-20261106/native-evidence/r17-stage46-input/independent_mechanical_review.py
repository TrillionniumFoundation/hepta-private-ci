#!/usr/bin/env python3
"""Independent strict unified-diff application; no author edit scripts are executed."""
from pathlib import Path
from collections import Counter
import hashlib
import json
import re

OUT = Path(__file__).resolve().parent
ROOT = OUT.parent
NATIVE = ROOT / "native-validation-results/checkpoint-r16"
SOURCE_COMMIT = "96dc9232535fedf735e3099ef1391b69477270d4"
SOURCE_TREE = "3ebd193f213d640e5330a1be4b983bcc4b06617a"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def balanced_end(text, start, opener="(", closer=")"):
    assert text[start] == opener
    depth = 0
    index = start
    while index < len(text):
        if text[index:index + 2] == "//":
            index = text.index("\n", index)
            continue
        raw = re.match(r'r(#+)?"', text[index:])
        if raw:
            closing = '"' + (raw[1] or "")
            index = text.index(closing, index + len(raw[0])) + len(closing)
            continue
        if text[index] == '"':
            index += 1
            while True:
                if text[index] == "\\":
                    index += 2
                elif text[index] == '"':
                    index += 1
                    break
                else:
                    index += 1
            continue
        if text[index] == opener:
            depth += 1
        elif text[index] == closer:
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    raise AssertionError("unbalanced macro or struct")


def assertion_macros(text):
    result = []
    for match in re.finditer(r"\bassert(?:_eq|_ne)?!\(", text):
        end = balanced_end(text, match.end() - 1)
        assert text[end] == ";"
        result.append(text[match.start():end + 1])
    return result


def parse_patch(raw, expected_path):
    lines = raw.decode().splitlines(keepends=True)
    assert lines[:2] == ["--- a/" + expected_path + "\n", "+++ b/" + expected_path + "\n"]
    hunks = []
    index = 2
    while index < len(lines):
        match = re.fullmatch(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@[^\n]*\n", lines[index])
        assert match, (index, lines[index])
        old_start, old_count, new_start, new_count = [int(v) if v is not None else 1 for v in match.groups()]
        index += 1
        records = []
        while index < len(lines) and not lines[index].startswith("@@"):
            assert lines[index][0] in " +-", "unsupported diff record"
            records.append((lines[index][0], lines[index][1:]))
            index += 1
        assert sum(sign in " -" for sign, _ in records) == old_count
        assert sum(sign in " +" for sign, _ in records) == new_count
        hunks.append((old_start, old_count, new_start, new_count, records))
    return hunks


def apply_hunks(text, hunks, reverse=False):
    source_lines = text.splitlines(keepends=True)
    result = []
    cursor = 0
    for old_start, old_count, new_start, new_count, records in hunks:
        start = (new_start if reverse else old_start) - 1
        assert start >= cursor
        result.extend(source_lines[cursor:start])
        cursor = start
        if reverse:
            records = [({"+": "-", "-": "+", " ": " "}[sign], line) for sign, line in records]
        for sign, line in records:
            if sign in " -":
                assert source_lines[cursor] == line, (cursor, source_lines[cursor], line)
                cursor += 1
            if sign in " +":
                result.append(line)
    result.extend(source_lines[cursor:])
    return "".join(result)


native_manifest_raw = (NATIVE / "evidence/native-candidate-r16-source.json").read_bytes()
native_manifest = json.loads(native_manifest_raw)
assert native_manifest["source_tree"] == SOURCE_TREE
assert native_manifest["source_commit"] == SOURCE_COMMIT
native_files = {r["path"]: r for r in native_manifest["changed_files"]}
reviews = []
for group, path in [
    ("core-recovery-settings-r16-fixture", "codex-rs/core/tests/suite/turn_input_submission.rs"),
    ("core-cold-root-r16-repair", "codex-rs/core/tests/suite/multi_agent_resume.rs"),
]:
    directory = ROOT / group
    before = (directory / "original" / path).read_bytes()
    after = (directory / "source" / path).read_bytes()
    patch = (directory / "repair.patch").read_bytes()
    author = json.loads((directory / "source-manifest.json").read_bytes())
    declared = author["files"][0]
    actual_native = (NATIVE / "source" / path).read_bytes()
    assert before == actual_native
    pin = native_files[path]
    assert (len(before), sha(before), blob(before)) == (pin["bytes"], pin["sha256"], pin["git_blob"])
    assert (len(before), sha(before), blob(before)) == (declared["before"]["bytes"], declared["before"]["sha256"], declared["before"]["git_blob"])
    assert (len(after), sha(after), blob(after)) == (declared["after"]["bytes"], declared["after"]["sha256"], declared["after"]["git_blob"])
    assert len(patch) == author["patch"]["bytes"] and sha(patch) == author["patch"]["sha256"]
    hunks = parse_patch(patch, path)
    before_text, after_text = before.decode(), after.decode()
    assert apply_hunks(before_text, hunks).encode() == after
    assert apply_hunks(after_text, hunks, reverse=True).encode() == before
    assertions_before = assertion_macros(before_text)
    assertions_after = assertion_macros(after_text)
    before_counts, after_counts = Counter(assertions_before), Counter(assertions_after)
    assert before_counts <= after_counts
    timing_pattern = r"Duration::from_\w+\([^)]*\)"
    assert re.findall(timing_pattern, before_text) == re.findall(timing_pattern, after_text)
    assert re.findall(r"^#\[tokio::test[^\n]*", before_text, re.M) == re.findall(r"^#\[tokio::test[^\n]*", after_text, re.M)
    specifics = {}
    if group == "core-cold-root-r16-repair":
        assert before_counts == after_counts and len(assertions_before) == 17
        assert before_text.count(".flush_rollout()") == after_text.count(".flush_rollout()") == 3
        assert before_text.count(".shutdown_and_wait()") == after_text.count(".shutdown_and_wait()") == 3
        normalized = after_text
        for receiver in ["worker_thread", "sibling_thread", "initial.codex"]:
            pattern = re.escape("    " + receiver) + r'\n        \.flush_rollout\(\)\n        \.await\n        \.with_context\(\|\| \{\n            format!\(\n                "cold-root [^\n]*"\n            \)\n        \}\)\?;'
            normalized, count = re.subn(pattern, "    " + receiver + ".flush_rollout().await?;", normalized)
            assert count == 1
        comments = "    // The sibling can evict this worker: the configured limit reserves one slot for root.\n    // Flush while this handle still owns a live recorder, before that admission.\n"
        assert normalized.count(comments) == 1
        normalized = normalized.replace(comments, "", 1)
        moved = "    worker_thread.flush_rollout().await?;\n\n"
        assert normalized.count(moved) == 1
        normalized = normalized.replace(moved, "", 1)
        anchor = "    sibling_thread.flush_rollout().await?;\n    initial.codex.flush_rollout().await?;"
        assert normalized.count(anchor) == 1
        normalized = normalized.replace(anchor, "    sibling_thread.flush_rollout().await?;\n    worker_thread.flush_rollout().await?;\n    initial.codex.flush_rollout().await?;", 1)
        assert normalized == before_text
        worker_flush = after_text.index("    worker_thread\n        .flush_rollout()")
        role_assert = after_text.index("    assert_eq!(\n        initial_worker_role_config,")
        role_assert_end = balanced_end(after_text, after_text.index("(", role_assert))
        assert role_assert_end < worker_flush < after_text.index("    let sibling_spawn_args") < after_text.index("initial.submit_turn(SIBLING_PROMPT)")
        specifics = {"all_17_original_assertions_identical": True, "flush_and_shutdown_counts": {"flush": 3, "shutdown": 3}, "worker_flush_after_role_assertions_before_sibling_admission": True, "other_operations_relative_order_unchanged_after_removing_three_context_wrappers_and_reversing_one_move": True, "capacity_configuration_unchanged": True, "contexts_only_enrich_existing_errors": True, "runtime_worker_eviction_identity_independently_observed": False, "causal_boundary": "This review verifies fixture lifecycle ordering and the exact source delta; the author's/root's separate lifecycle-source audit owns the production eviction chain. No particular runtime victim is asserted from the bare old error."}
    else:
        added = list((after_counts - before_counts).elements())
        assert len(added) == 2 and all("config_snapshot().await.collaboration_mode" in a and "plan_mode" in a for a in added)
        old_name = "async fn recover_turn_if_idle_preserves_id_and_resumes_plan_mode()"
        before_start = before_text.index(old_name)
        after_start = after_text.index(old_name)
        before_end = before_text.index("/// Concurrent submissions", before_start)
        after_end = after_text.index("/// Concurrent submissions", after_start)
        assert before_text[:before_start] == after_text[:after_start] and before_text[before_end:] == after_text[after_end:]
        old_test, new_test = before_text[before_start:before_end], after_text[after_start:after_end]
        assert len(assertion_macros(old_test)) == 7 and len(assertion_macros(new_test)) == 9
        old_mode_start = old_test.index("CollaborationMode {")
        old_brace = old_test.index("{", old_mode_start)
        old_mode_end = balanced_end(old_test, old_brace, "{", "}")
        new_mode_start = new_test.index("CollaborationMode {")
        new_brace = new_test.index("{", new_mode_start)
        new_mode_end = balanced_end(new_test, new_brace, "{", "}")
        assert re.sub(r"\s+", "", old_test[old_mode_start:old_mode_end]) == re.sub(r"\s+", "", new_test[new_mode_start:new_mode_end])
        recovery_call = new_test[new_test.index(".recover_turn_if_idle("):]
        assert "thread_settings: ThreadSettingsOverrides::default()," in recovery_call
        assert "with_thread_settings" not in recovery_call and "collaboration_mode: Some(" not in recovery_call
        before_recovery = new_test[:new_test.index(".recover_turn_if_idle(")]
        assert "collaboration_mode: Some(plan_mode.clone())," in before_recovery
        specifics = {"original_7_test_assertions_exact": True, "new_complete_plan_readback_assertions": 2, "original_plan_value_exact_after_whitespace_normalization": True, "plan_supplied_to_initial_user_request": True, "recovery_overrides_default_only": True, "outside_target_test_identical": True, "reviewer_authorship_disclosure": "Reviewer authored this recovery fixture; the independent step here is a separate strict unified-patch parser and native45 byte comparison, not a claim of separate-author semantic review. Root supplies semantic peer review."}
    reviews.append({"group": group, "path": path, "before": {"bytes": len(before), "sha256": sha(before), "git_blob": blob(before)}, "after": {"bytes": len(after), "sha256": sha(after), "git_blob": blob(after)}, "patch": {"bytes": len(patch), "sha256": sha(patch), "hunks": len(hunks)}, "native45_original_bytes_equal": True, "strict_patch_forward_exact": True, "strict_patch_inverse_exact": True, "original_assertions_preserved": len(assertions_before), "new_assertions": len(assertions_after) - len(assertions_before), "duration_tokens_identical": True, "same_test_declarations": True, "specifics": specifics})

report = {"schema": "hepta.stage46-independent-mechanical-review.v1", "status": "PASS_STATIC_MECHANICAL_REVIEW", "source_base_commit": SOURCE_COMMIT, "source_base_tree": SOURCE_TREE, "proposed_stage": 46, "new_native_validation": "PENDING", "reviewer": "/root/differentiation_study", "method": "Independently parse actual unified diff hunks, enforce source context/line counts and apply forward/reverse to actual native45 exported files; recompute SHA256 and Git blobs; inspect all assertion macro bytes and timing/test declarations. Author edit scripts and inverse claims are not used as the patch engine.", "native_source_manifest_sha256": sha(native_manifest_raw), "files": reviews, "source_or_native_modified": False, "rust_commands_run": False, "discrepancies": [], "limitations": ["This is a static delta audit, not an executed candidate test result.", "The Cold Root patch has a real intentional lifecycle order change: worker flush precedes possible unloading at sibling admission. That move is disclosed and all original product assertions remain.", "Recovery semantics retain the production no-override invariant; the test now starts the interrupted turn with Plan and reads it back twice."]}
(OUT / "INDEPENDENT-REVIEW.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
data = (OUT / "INDEPENDENT-REVIEW.json").read_bytes()
print(json.dumps({"status": report["status"], "files": len(reviews), "report_bytes": len(data), "report_sha256": sha(data)}))
