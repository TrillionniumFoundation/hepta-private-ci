#!/usr/bin/env python3
"""Derive an inert source53 apply-only template; never execute that template."""
import ast
import difflib
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
DEST = Path(__file__).resolve().parent
OLD = ROOT / "source52-apply-preparation/native-source52-apply-template.py"
BASE_MANIFEST = ROOT / "source52-preparation/native-candidate-r28-source.json"
FAILED = ROOT / "native-validation-results/r29-closed-input/evidence"
CANDIDATE = ROOT / "app-server-bedrock-r29-diagnostic-preparation"
PATHS = (
    "codex-rs/app-server/src/request_processors/account_processor/bedrock_setup.rs",
    "codex-rs/app-server/tests/suite/v2/bedrock_setup.rs",
)


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def need(value, message):
    if not value:
        raise ValueError(message)


def put(name, raw):
    p = DEST / name
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        need(p.read_bytes() == raw, "refuse overwrite: " + name)
    else:
        with p.open("xb") as stream:
            stream.write(raw)
    return pin(raw)


def jb(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def replace_assignment(text, name, value):
    tree = ast.parse(text)
    matches = [n for n in tree.body if isinstance(n, ast.Assign)
               and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
               and n.targets[0].id == name]
    need(len(matches) == 1, "assignment missing/duplicate: " + name)
    node = matches[0]
    lines = text.splitlines(keepends=True)
    replacement = name + " = " + repr(value) + "\n"
    return "".join(lines[:node.lineno - 1]) + replacement + "".join(lines[node.end_lineno:])


def replace_function(text, name, replacement):
    tree = ast.parse(text)
    matches = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
    need(len(matches) == 1, "function missing/duplicate: " + name)
    node = matches[0]
    lines = text.splitlines(keepends=True)
    return "".join(lines[:node.lineno - 1]) + replacement.rstrip() + "\n" + "".join(lines[node.end_lineno:])


CHECK_BINDINGS = '''def check_bindings():
    require(FROZEN is True, "INERT PREPARATION: apply is not authorized")
    require(sys.flags.optimize == 0 and os.environ.get("PYTHONOPTIMIZE") in (None, "", "0"), "optimized Python is not an approved executor")
    require(digest(EXPECTED_COMMIT, 40) and digest(EXPECTED_TREE, 40), "source53 identity unbound")
    require(EXPECTED_COMMIT != SOURCE52_COMMIT and EXPECTED_TREE != SOURCE52_TREE, "no new source identity")
    require(type(EXPECTED_CHANGED_COUNT) is int and EXPECTED_CHANGED_COUNT == SOURCE52_COUNT + len(ALLOWED_PATHS), "source53 count must be prior195 plus exactly two existing repository leaves")
    require(type(INPUT_BYTES) is int and INPUT_BYTES > 0 and digest(INPUT_SHA256, 64), "input archive unbound")
    for expected in (SOURCE52_MANIFEST_PIN, R29_TERMINAL_PIN, SOURCE53_MANIFEST_PIN, DELTA_MANIFEST_PIN):
        validate_pin(expected)
    require(set(EXISTING_BASELINE_LEAF_PINS) == set(ALLOWED_PATHS) and len(ALLOWED_PATHS) == 2, "two independently reviewed existing leaves required")
    for expected in EXISTING_BASELINE_LEAF_PINS.values():
        validate_pin(expected)
    require(isinstance(CANDIDATE_PINS, dict) and set(CANDIDATE_PINS) == set(ALLOWED_PATHS), "two reviewed existing repository leaf bindings required")
    for path, row in CANDIDATE_PINS.items():
        safe_relative(path)
        require(path.endswith(".rs") and Path(path).name != "build.rs", "dependency/build input prohibited")
        require(set(row) == {"before", "after"}, "candidate binding shape")
        for side in ("before", "after"):
            require(isinstance(row[side], dict) and set(row[side]) == {"mode", "bytes", "sha256", "git_blob"}, "candidate pin shape")
            validate_pin({key: row[side][key] for key in ("bytes", "sha256", "git_blob")})
            require(row[side]["mode"] == "100644", "candidate mode change prohibited")
        require(row["before"] != row["after"], "candidate must be an actual change")
    for expected in R29_FAILURE_PINS.values():
        validate_pin(expected)
    require(set(R29_FAILURE_PINS) == {
        R29_TERMINAL_NAME, R29_PREFIX + "-tests-raw-process-result.json",
        R29_PREFIX + "-tests-receipt.json", R29_PREFIX + "-source-post-test-verification.json",
    }, "four actual failed r29 originals are required")
    for name in (INPUT_NAME, SOURCE52_MANIFEST_NAME, SOURCE53_MANIFEST_OUTPUT_NAME, *R29_FAILURE_PINS):
        safe_relative(name)
'''

LEAF_GUARD = '''def existing_baseline_leaves_guard():
    leaves = []
    for path in ALLOWED_PATHS:
        expected = EXISTING_BASELINE_LEAF_PINS[path]
        record = git("ls-tree", "-z", SOURCE52_TREE, "--", path)
        require(record.endswith(b"\\0") and record.count(b"\\0") == 1, "existing baseline Git leaf absent or ambiguous")
        header, name = record[:-1].split(b"\\t", 1)
        mode, kind, blob = header.decode().split()
        require(name.decode() == path and kind == "blob" and mode == "100644"
                and blob == expected["git_blob"], "existing source52 leaf Git identity differs")
        committed = git("cat-file", "blob", blob)
        require(pin(committed) == expected, "existing baseline Git blob bytes differ")
        raw, actual_mode = source_raw(path)
        require(actual_mode == mode and pin(raw) == expected, "existing baseline leaf working bytes/mode differ")
        require(CANDIDATE_PINS[path]["before"] == {"mode": mode, **expected},
                "candidate before pin is not the independently reviewed existing leaf")
        leaves.append({"path": path, "mode": mode, **pin(raw), "source_tree": SOURCE52_TREE,
                       "actual_working_bytes_equal_existing_Git_leaf": True})
    return {"before_existing_repo_leaves_not_in_prior_changed_manifest": True, "leaves": leaves}
'''

FAILED_PREREQUISITE = '''def r29_failed_prerequisite():
    originals = {}
    pins = []
    for name, expected in R29_FAILURE_PINS.items():
        raw = (E / safe_relative(name)).read_bytes()
        require(pin(raw) == expected, "original failed r29 pin differs: " + name)
        originals[name] = raw
        pins.append({"path": name, **pin(raw)})
    terminal = json.loads(originals[R29_TERMINAL_NAME])
    require(terminal["job_id"] == R29_JOB_ID and terminal["state"] == "failed"
            and terminal["exit_code"] == 100, "r29 did not naturally close at its original workspace failure")
    for field in ("timed_out", "cancelled", "automatic_retry"):
        require(terminal[field] is False, "invalid r29 termination flag: " + field)
    for field in ("audit_recorded", "output_complete", "output_durable", "terminal_publication_confirmed"):
        require(terminal[field] is True, "r29 durable closure missing: " + field)
    raw_name = R29_PREFIX + "-tests-raw-process-result.json"
    receipt_name = R29_PREFIX + "-tests-receipt.json"
    post_name = R29_PREFIX + "-source-post-test-verification.json"
    result, receipt, post = (json.loads(originals[name]) for name in (raw_name, receipt_name, post_name))
    require(result["schema"] == "hepta.native-raw-process-result.v1"
            and receipt["schema"] == "hepta.native-workspace-gate-receipt.v2", "r29 original schemas differ")
    for value in (result, receipt):
        require(value["phase"] == "workspace-tests" and value["source_tree"] == SOURCE52_TREE
                and value["source_commit"] == SOURCE52_COMMIT and value["exit_code"] == 100
                and value["command"] == ["just", "test", "--locked", "--retries", "0"]
                and value["cwd"] == str(S / "codex-rs"), "r29 original failed gate identity differs")
    for key in ("phase", "source_tree", "source_commit", "command", "cwd", "start_unix", "end_unix", "exit_code"):
        require(result[key] == receipt[key], "r29 raw/receipt mismatch: " + key)
    require(receipt["end_unix"] >= receipt["start_unix"]
            and abs(receipt["elapsed_seconds"] - (receipt["end_unix"] - receipt["start_unix"])) < 1e-6,
            "r29 original time accounting mismatch")
    require(receipt["effective_exit_code"] == 100 and receipt["phase_pass"] is False
            and receipt["test_scope"] == "original_default_workspace" and receipt["packages_argument"] is None
            and receipt["workspace_member_count"] == receipt["workspace_default_member_count"] == 193
            and receipt["retries"] == 0 and receipt["filters"] == "no_additions"
            and receipt["features"] == "unchanged_defaults" and receipt["fix_fmt_executed"] is False,
            "r29 failure or original no-p193 selection was relabeled")
    require(receipt["source_manifest"] == SOURCE52_MANIFEST_NAME
            and receipt["source_manifest_sha256"] == SOURCE52_MANIFEST_PIN["sha256"],
            "r29 receipt does not bind original source52 manifest")
    require(receipt["raw_process_result"] == {"path": raw_name, **pin(originals[raw_name])}
            and receipt["source_postguard"] == {"path": post_name, **pin(originals[post_name])},
            "r29 original receipt pointers differ")
    require(receipt["source_guards_pass"] is True and post["pass"] is True
            and post["actual_tree"] == post["expected_tree"] == SOURCE52_TREE
            and post["source_commit"] == SOURCE52_COMMIT
            and post["changed_file_count"] == SOURCE52_COUNT and post["gate_exit_code"] == 100
            and post["phase"] == "workspace-tests" and post["native_head"] == FRAMEWORK_PARENT,
            "r29 failed gate did not preserve the exact baseline source")
    require(post["changed_path_set_matches"] is True
            and post["unstaged_paths"] == post["untracked_paths"] == post["file_mismatches"] == []
            and post["cargo_lock_sha256"] == CARGO_LOCK_SHA256
            and post["bazel_lock_sha256"] == BAZEL_LOCK_SHA256, "r29 baseline guard or dual-lock mismatch")
    require(terminal["at_unix_ms"] / 1000 >= receipt["end_unix"], "r29 terminal precedes test end")
    return pins
'''

ROW_SLICES = '''def manifest_row_slices(raw):
    text = raw.decode("utf-8")
    matches = list(re.finditer(r'"changed_files"\\s*:\\s*\\[', text))
    require(len(matches) == 1, "one changed_files array required")
    position = matches[0].end()
    decoder = json.JSONDecoder()
    rows = {}
    while True:
        while position < len(text) and text[position].isspace():
            position += 1
        require(position < len(text), "truncated changed_files array")
        if text[position] == "]":
            return rows
        value, end = decoder.raw_decode(text, position)
        require(isinstance(value, dict) and value["path"] not in rows, "invalid or duplicate raw source row")
        rows[value["path"]] = text[position:end].encode("utf-8")
        position = end
        while position < len(text) and text[position].isspace():
            position += 1
        require(position < len(text) and text[position] in ",]", "invalid source array separator")
        if text[position] == ",":
            position += 1
'''

LOAD_INPUTS = '''def load_inputs():
    old_raw = (E / SOURCE52_MANIFEST_NAME).read_bytes()
    require(pin(old_raw) == SOURCE52_MANIFEST_PIN, "source52 manifest bytes changed")
    old = json.loads(old_raw)
    require(old["source_tree"] == SOURCE52_TREE and old["source_commit"] == SOURCE52_COMMIT, "source52 identity")
    old_files = normalized_files(old["changed_files"])
    require(len(old_files) == SOURCE52_COUNT and set(ALLOWED_PATHS).isdisjoint(old_files),
            "both new changed leaves must be outside the prior195 changed manifest")
    r29_pins = r29_failed_prerequisite()
    archive_raw = (T / INPUT_NAME).read_bytes()
    require(len(archive_raw) == INPUT_BYTES and pin(archive_raw)["sha256"] == INPUT_SHA256, "source53 archive pin")
    members = {}
    expected_members = {"delta-manifest.json", "source53-manifest.json", "candidate.patch"}
    expected_members |= {side + "/" + path for side in ("before", "after") for path in ALLOWED_PATHS}
    with tarfile.open(fileobj=io.BytesIO(archive_raw), mode="r:gz") as archive:
        for member in archive.getmembers():
            safe_relative(member.name)
            require(member.isfile() and not member.issym() and not member.islnk(), "archive links/nonregular member")
            require(member.name in expected_members and member.name not in members, "unexpected/duplicate archive member")
            stream = archive.extractfile(member)
            require(stream is not None, "archive read missing")
            data = stream.read()
            require(len(data) == member.size, "archive member truncated")
            members[member.name] = data
    require(set(members) == expected_members and len(members) == 7, "exact seven two-leaf input members required")
    require(pin(members["source53-manifest.json"]) == SOURCE53_MANIFEST_PIN
            and pin(members["delta-manifest.json"]) == DELTA_MANIFEST_PIN, "new manifest pins")
    source = json.loads(members["source53-manifest.json"])
    require(source["source_tree"] == EXPECTED_TREE and source["source_commit"] == EXPECTED_COMMIT,
            "root source53 identity")
    require(source["source_parent_commit"] == SOURCE52_COMMIT, "source53 parent must be source52")
    require(source["diagnostic_only"] is True and source["behavior_repair_claimed"] is False,
            "diagnostic source must not be relabeled as a behavior repair")
    files = normalized_files(source["changed_files"])
    require(len(files) == EXPECTED_CHANGED_COUNT == SOURCE52_COUNT + len(ALLOWED_PATHS)
            and set(files) == set(old_files) | set(ALLOWED_PATHS),
            "full source53 manifest must be exactly unchanged195 plus the two existing Bedrock leaves")
    for obj in (old, source):
        require(obj["cargo_lock_sha256"] == CARGO_LOCK_SHA256
                and obj["bazel_lock_sha256"] == BAZEL_LOCK_SHA256, "manifest dual-lock identity")
    delta = json.loads(members["delta-manifest.json"])
    require(delta["schema"] == "hepta.source53-apply-delta.v1", "delta schema")
    require(delta["diagnostic_only"] is True and delta["behavior_repair_claimed"] is False,
            "diagnostic delta must not be relabeled as a behavior repair")
    for key, value in {
        "source_before_tree": SOURCE52_TREE, "source_before_commit": SOURCE52_COMMIT,
        "source_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT,
    }.items():
        require(delta[key] == value, "delta identity " + key)
    require(delta["patch"] == {"path": "candidate.patch", **pin(members["candidate.patch"])}, "patch pin")
    require(isinstance(delta["files"], list) and len(delta["files"]) == len(ALLOWED_PATHS), "delta must have exactly two files")
    delta_rows = {}
    for row in delta["files"]:
        require(set(row) == {"path", "before", "after"} and row["path"] not in delta_rows, "delta row schema/duplicate")
        delta_rows[row["path"]] = {"before": row["before"], "after": row["after"]}
    require(delta_rows == CANDIDATE_PINS, "delta differs from independently bound two-leaf pins")
    before, after = {}, {}
    for path, pair in CANDIDATE_PINS.items():
        for side, destination in (("before", before), ("after", after)):
            raw = members[side + "/" + path]
            raw.decode("utf-8")
            require({"mode": "100644", **pin(raw)} == pair[side], "candidate member pin")
            destination[path] = raw
        require(pair["before"] == {"mode": "100644", **EXISTING_BASELINE_LEAF_PINS[path]},
                "candidate before is not the independently pinned existing source52 leaf")
        require(files[path] == {"path": path, **pair["after"]}, "candidate after/full source53 mismatch")
    old_rows = {row["path"]: row for row in old["changed_files"]}
    new_rows = {row["path"]: row for row in source["changed_files"]}
    old_slices = manifest_row_slices(old_raw)
    new_slices = manifest_row_slices(members["source53-manifest.json"])
    for path in old_files:
        require(old_files[path] == files[path] and old_rows[path] == new_rows[path]
                and old_slices[path] == new_slices[path], "any prior195 manifest row bytes or values changed: " + path)
    require(replay_patch(members["candidate.patch"], before) == after, "forward patch not exact")
    require(replay_patch(members["candidate.patch"], after, reverse=True) == before, "inverse patch not exact")
    leaves = existing_baseline_leaves_guard()
    return old_files, files, members, {
        "input_archive": {"path": INPUT_NAME, **pin(archive_raw)},
        "source52_manifest": {"path": SOURCE52_MANIFEST_NAME, **pin(old_raw)},
        "r29_original_failed_100_closure": r29_pins,
        "patch_forward_inverse_exact": True, "declared_paths": list(ALLOWED_PATHS),
        "prior_changed_file_count": SOURCE52_COUNT, "actual_changed_file_count": len(files),
        "before_existing_repo_leaves_not_in_prior_changed_manifest": True,
        "source52_original_changed_manifest_rows_unchanged": True,
        "source52_original_manifest_row_json_slices_byte_identical": True,
        "existing_baseline_leaves": leaves,
        "diagnostic_only": True, "behavior_repair_claimed": False,
    }
'''


def main():
    old_raw = OLD.read_bytes()
    old_handoff = json.loads((OLD.parent / "HANDOFF-MANIFEST.json").read_bytes())
    row = next(r for r in old_handoff["files"] if r["path"] == OLD.name)
    need(all(row[k] == pin(old_raw)[k] for k in ("bytes", "sha256", "git_blob")), "reference template changed")
    put("references/native-source52-apply-template.py", old_raw)
    base_raw = BASE_MANIFEST.read_bytes()
    need(pin(base_raw)["sha256"] == "3ff99b41bab572666b424fdbf9a508b33be13e6487d9effa7dd6a0e14b4ec898", "source52 manifest changed")
    put("references/source52-actual-manifest.json", base_raw)
    candidate_raw = (CANDIDATE / "source-manifest.json").read_bytes()
    need(pin(candidate_raw)["sha256"] == "35e8d23122dc0a706af7168607cf1ba937bc23d91b3004e12964b728c4026205", "candidate manifest changed")
    candidate = json.loads(candidate_raw)
    put("references/diagnostic-source-manifest.json", candidate_raw)
    failure_names = ["native-workspace-r29-" + suffix for suffix in (
        "terminal-process-status.json", "tests-raw-process-result.json", "tests-receipt.json", "source-post-test-verification.json")]
    failure_pins = {}
    for name in failure_names:
        raw = (FAILED / name).read_bytes()
        put("references/r29/" + name, raw)
        failure_pins[name] = pin(raw)
    rootproof = ROOT / "native-validation-results/r29-archive-closed/ROOT-ARCHIVE-READBACK.json"
    proof_raw = rootproof.read_bytes()
    need(pin(proof_raw)["sha256"] == "dd154b6b2a11c8e593f487860a6baedb58d58b78b87b0c523b45dbe1540da245", "root original archive closure differs")
    put("references/r29/ROOT-ARCHIVE-READBACK.json", proof_raw)
    before_pins = {r["path"]: r["before"] for r in candidate["files"]}
    need(set(before_pins) == set(PATHS), "two exact before pins required")
    text = old_raw.decode()
    substitutions = {"source51": "source52", "source52": "source53", "SOURCE51": "SOURCE52", "SOURCE52": "SOURCE53", "r26": "r29", "R26": "R29"}
    text = re.sub(r"source51|source52|SOURCE51|SOURCE52|r26|R26", lambda m: substitutions[m[0]], text)
    text = text.replace("existing_baseline_leaf_guard", "existing_baseline_leaves_guard")
    text = text.replace("EXISTING_BASELINE_LEAF_PIN", "EXISTING_BASELINE_LEAF_PINS")
    text = text.replace("existing_repo_leaf_outside_prior_changed_manifest", "existing_repo_leaves_outside_prior_changed_manifest")
    text = text.replace("before_existing_repo_leaf_not_in_prior_changed_manifest", "before_existing_repo_leaves_not_in_prior_changed_manifest")
    values = {
        "SOURCE53_MANIFEST_OUTPUT_NAME": "native-candidate-r30-source.json",
        "SOURCE52_COMMIT": "1e0910becc37383e6d17ecf861ea844fd07d8862",
        "SOURCE52_TREE": "211f15baff19095e8c98bcea2b0ed99ca2270ade",
        "SOURCE52_COUNT": 195,
        "SOURCE52_MANIFEST_NAME": "native-candidate-r28-source.json",
        "SOURCE52_MANIFEST_PIN": pin(base_raw),
        "R29_TERMINAL_NAME": failure_names[0],
        "R29_TERMINAL_PIN": failure_pins[failure_names[0]],
        "R29_JOB_ID": "1a1b1f83e4b-fc05-7bcd",
        "R29_PREFIX": "native-workspace-r29",
        "R29_FAILURE_PINS": failure_pins,
        "ALLOWED_PATHS": PATHS,
        "EXISTING_BASELINE_LEAF_PINS": before_pins,
    }
    for name, value in values.items():
        text = replace_assignment(text, name, value)
    for name, replacement in (("check_bindings", CHECK_BINDINGS), ("existing_baseline_leaves_guard", LEAF_GUARD),
                              ("r29_failed_prerequisite", FAILED_PREREQUISITE), ("load_inputs", LOAD_INPUTS)):
        text = replace_function(text, name, replacement)
    text = text.replace("def load_inputs():", ROW_SLICES.rstrip() + "\n\n\ndef load_inputs():", 1)
    text = text.replace("patch does not cover exactly the single reviewed existing Rust leaf", "patch does not cover exactly the two reviewed existing Rust leaves")
    text = text.replace('post["source52_original_changed_manifest_rows_unchanged"] = True',
                        'post["source52_original_changed_manifest_rows_unchanged"] = True\n        post["diagnostic_only"] = True\n        post["behavior_repair_claimed"] = False')
    text = text.replace('"source52_original_changed_manifest_rows_unchanged": True,\n            "actual_changed_file_count"',
                        '"source52_original_changed_manifest_rows_unchanged": True,\n            "diagnostic_only": True, "behavior_repair_claimed": False,\n            "actual_changed_file_count"')
    text = text.replace("through source52 and source53", "through source51, source52 and source53")
    text = text.replace("there is no automatic reset.\n", "there is no automatic reset.\nThis source adds diagnostic stage records; it does not claim a behavior repair.\n", 1)
    tree = ast.parse(text)
    assignments = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                   and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
                   and isinstance(n.value, ast.Constant)}
    need(assignments["FROZEN"] is False, "inert flag differs")
    unbound = ["EXPECTED_COMMIT", "EXPECTED_TREE", "EXPECTED_CHANGED_COUNT", "INPUT_BYTES", "INPUT_SHA256",
               "SOURCE53_MANIFEST_PIN", "DELTA_MANIFEST_PIN", "CANDIDATE_PINS"]
    need(all(assignments[n] is None for n in unbound), "future bindings must remain None")
    need('"before_existing_repo_leaf_not_in_prior_changed_manifest"' not in text, "singular interface remained")
    need("R26" not in text and "r26" not in text and "SOURCE51_" not in text, "stale runner identity")
    raw = text.encode()
    result_pin = put("native-source53-apply-template.py", raw)
    patch = "".join(difflib.unified_diff(old_raw.decode().splitlines(keepends=True), text.splitlines(keepends=True),
                                       fromfile="a/native-source52-apply-template.py", tofile="b/native-source53-apply-template.py")).encode()
    put("source52-to-source53-template.patch", patch)
    report = {"schema": "hepta.source53-inert-apply-build.v1", "template": result_pin,
              "reference_template": pin(old_raw), "reference_candidate": pin(candidate_raw),
              "r29_original_four_pins": failure_pins,
              "root_full_archive_closure_prior_review": {"path": str(rootproof.relative_to(ROOT)), **pin(proof_raw),
                  "local_provenance_only": True, "remote_root_readback_not_fabricated": True},
              "AST_parsed": True, "runner_imported_or_executed": False,
              "FROZEN": False, "unbound_literal_count": len(unbound), "unbound_names": unbound,
              "candidate_classification": "DIAGNOSTIC_ONLY_NOT_BEHAVIOR_REPAIR",
              "allowed_paths": list(PATHS), "prior_count": 195, "planned_after_count": 197,
              "complete_plural_key": "before_existing_repo_leaves_not_in_prior_changed_manifest",
              "runtime_precondition": "Exact original R29 workspace failed100 raw/receipt/postguard/outer, followed by live source52 full195 and both before-leaf verification.",
              "native_mutation_performed": False, "Rust_executed": False}
    put("BUILD-READBACK.json", jb(report))
    print(json.dumps({"template": result_pin, "patch": pin(patch), "AST": "PASS", "FROZEN": False, "None_count": 8}, indent=2))


if __name__ == "__main__":
    main()
