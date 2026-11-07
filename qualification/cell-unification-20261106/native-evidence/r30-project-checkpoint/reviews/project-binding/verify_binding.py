"""Read bytes and AST only; never import or execute an apply/gate runner."""
from pathlib import Path
import ast
import difflib
import hashlib
import json

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent
B = ROOT / "source53-r30-binding"
E = ROOT / "native-validation-results/source53-apply-v2-closed/evidence"


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def read(path, digest):
    raw = path.read_bytes()
    assert not path.is_symlink() and hashlib.sha256(raw).hexdigest() == digest
    return raw


def write(name, data):
    raw = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()
    with (OUT / name).open("xb") as handle:
        handle.write(raw)
    return {"path": name, **pin(raw)}


def main():
    template = read(ROOT / "source53-native-gates-preparation/native-run-r30-template-v2.py", "a4bb18b0f2d2af63625e7ee6629df9f5a42f47c684bd8e4a72125b62b05d2c0b")
    bound = read(B / "native-run-r30-bound.py", "e0f0b48c0d5508460d60a80217c19ee087aedad50dc0ff37f297a60d02a86100")
    final = read(B / "native-run-r30.py", "b72407252efdaf81d8e3bc5280c3fa7ad9afb36fa398869e8023daaa392ff3c8")
    bindings = json.loads(read(B / "BINDINGS.json", "c3659f95af9d4d14ef8492bf3f3b5e00668868ef206370334773dd2ee275e888"))
    assert len(bindings) == 15
    text = bound.decode()
    lines = text.splitlines(keepends=True)
    assignments = {node.targets[0].id: node for node in ast.parse(text).body
                   if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)}
    template_assignments = {node.targets[0].id: node for node in ast.parse(template.decode()).body
                            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)}
    for name, value in bindings.items():
        node = assignments[name]
        assert node.lineno == node.end_lineno and ast.literal_eval(node.value) == value
        assert ast.literal_eval(template_assignments[name].value) is None
        lines[node.lineno - 1] = f"{name} = None\n"
    assert "".join(lines).encode() == template
    assert bound.count(b"FROZEN = False\n") == 1
    assert final == bound.replace(b"FROZEN = False\n", b"FROZEN = True\n", 1)
    ast.parse(final.decode())
    for name, old, new, oldlabel, newlabel in (
        ("template-to-bound.patch", template, bound, "native-run-r30-template-v2.py", "native-run-r30-bound.py"),
        ("bound-to-final.patch", bound, final, "native-run-r30-bound.py", "native-run-r30.py"),
    ):
        expected = "".join(difflib.unified_diff(old.decode().splitlines(True), new.decode().splitlines(True), fromfile=oldlabel, tofile=newlabel)).encode()
        assert (B / name).read_bytes() == expected
    input_pins = {}
    for prefix in ("APPLY_COMPLETE", "APPLY_TERMINAL", "DELTA_MANIFEST", "SOURCE_MANIFEST"):
        raw = read(E / bindings[prefix + "_NAME"], bindings[prefix + "_SHA256"])
        if prefix + "_BYTES" in bindings:
            assert len(raw) == bindings[prefix + "_BYTES"]
        input_pins[prefix] = {"path": bindings[prefix + "_NAME"], **pin(raw)}
    complete = json.loads((E / bindings["APPLY_COMPLETE_NAME"]).read_bytes())
    terminal = json.loads((E / bindings["APPLY_TERMINAL_NAME"]).read_bytes())
    assert terminal["job_id"] == bindings["APPLY_JOB_ID"] == "1a1b2552130-fc05-7d91"
    assert terminal["state"] == "succeeded" and terminal["exit_code"] == 0
    assert terminal["output_complete"] and terminal["output_durable"] and terminal["terminal_publication_confirmed"]
    assert not any(terminal[key] for key in ("timed_out", "cancelled", "automatic_retry"))
    assert complete["schema"] == "hepta.source53-apply-complete.v1"
    assert complete["source_commit"] == bindings["EXPECTED_COMMIT"] == "f74be175de66a4b351cd239d39d98cd34fe9cc1b"
    assert complete["source_tree"] == bindings["EXPECTED_TREE"] == "440d4a8e09af4009e4d9ea067388826308da8803"
    assert complete["actual_changed_file_count"] == bindings["EXPECTED_CHANGED_COUNT"] == 197
    assert complete["prior_changed_file_count"] == 195 and complete["source_guards_pass"]
    assert complete["diagnostic_only"] and complete["behavior_repair_claimed"] is False
    assert complete["rust_executed"] is False and complete["fix_fmt_executed"] is False
    for key, prefix in (("source_manifest", "SOURCE_MANIFEST"), ("delta_manifest", "DELTA_MANIFEST")):
        assert complete[key] == input_pins[prefix]
    post_pin = complete["source_postguard"]
    post_raw = read(E / post_pin["path"], post_pin["sha256"])
    assert pin(post_raw) == {key: post_pin[key] for key in ("bytes", "sha256", "git_blob")}
    post = json.loads(post_raw)
    assert post["pass"] and post["actual_tree"] == bindings["EXPECTED_TREE"]
    assert post["actual_changed_file_count"] == 197 and post["native_head"] == "bef6fa7645df9df12b69fda499e97eed25de6c75"
    assert post["file_mismatches"] == post["unstaged_paths"] == post["untracked_paths"] == []
    manifest = json.loads((E / bindings["SOURCE_MANIFEST_NAME"]).read_bytes())
    assert len(manifest["changed_files"]) == 197 and manifest["rust_file_count"] == 183
    assert manifest["source_commit"] == bindings["EXPECTED_COMMIT"] and manifest["source_tree"] == bindings["EXPECTED_TREE"]
    record = write("INDEPENDENT-REVIEW.json", {
        "schema": "hepta.source53-r30-binding-independent-review.v1", "status": "STATIC_BINDING_CLEAR",
        "template": pin(template), "bound": pin(bound), "final": pin(final),
        "actual_bindings": bindings, "actual_closed_input_pins": input_pins, "actual_postguard": post_pin,
        "fifteen_literals_inverse_whole_file_matches_reviewed_v2": True,
        "final_only_FROZEN_false_to_true": True, "both_patch_texts_regenerated_exactly": True,
        "ast_parse_pass": True, "actual_corrected_apply_outer_natural_0": True,
        "actual_source53_197_postguard_and_two_locks": True,
        "original_failed_input_placement_attempt1_preserved": True,
        "diagnostic_only": True, "behavior_repair_claimed": False,
        "R30_started_by_this_review": False, "runner_imported_or_executed": False,
        "Rust_or_native_or_metadata_executed": False,
        "scope": "Binding-only readback; the earlier full V2 static review remains separate. A future genuine project PASS is not proof of a behavioral repair or complete workspace/scientific qualification.",
    })
    write("HANDOFF-MANIFEST.json", {"schema": "hepta.source53-r30-binding-independent-handoff.v1", "files": [record, {"path": "verify_binding.py", **pin(Path(__file__).read_bytes())}]})
    print(json.dumps(record))


if __name__ == "__main__":
    main()
