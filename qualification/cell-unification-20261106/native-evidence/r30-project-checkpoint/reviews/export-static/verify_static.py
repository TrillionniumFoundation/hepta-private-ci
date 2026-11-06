"""AST/byte checks only; does not import or execute the reviewed exporter."""
from pathlib import Path
import ast
import difflib
import hashlib
import json

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent
PREP = ROOT / "r30-export-preparation"


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def parse(path):
    raw = (ROOT / path).read_bytes()
    text = raw.decode()
    tree = ast.parse(text)
    funcs = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    return raw, text, tree, funcs, {"path": path, **pin(raw)}


def snippet(text, node):
    return ast.get_source_segment(text, node)


def constants(tree):
    out = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            try:
                out[n.targets[0].id] = ast.literal_eval(n.value)
            except (ValueError, TypeError):
                pass
    return out


def accessed(function, variable):
    return sorted({n.slice.value for n in ast.walk(function)
                   if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name)
                   and n.value.id == variable and isinstance(n.slice, ast.Constant)
                   and isinstance(n.slice.value, str)})


def schema_dict(function, schema):
    found = []
    for n in ast.walk(function):
        if not isinstance(n, ast.Dict):
            continue
        fields = {k.value: v for k, v in zip(n.keys, n.values) if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        value = fields.get("schema")
        if isinstance(value, ast.Constant) and value.value == schema:
            found.append((n, fields))
    assert len(found) == 1, (schema, len(found))
    return found[0]


def main():
    handoff_raw = (PREP / "HANDOFF-MANIFEST.json").read_bytes()
    handoff = json.loads(handoff_raw)
    assert handoff["state"] == "FROZEN_TEMPLATE_INERT_CLOSURE_MAPS_NONE"
    assert len(handoff["files"]) == handoff["file_count"] == 12
    for row in handoff["files"]:
        path = Path(row["path"])
        assert not path.is_absolute() and ".." not in path.parts
        target = PREP / path
        assert target.is_file() and not target.is_symlink()
        assert pin(target.read_bytes()) == {k: row[k] for k in ("bytes", "sha256", "git_blob")}
    assert sum(row["bytes"] for row in handoff["files"]) == handoff["total_bytes"]
    current = parse("r30-export-preparation/export-r30-closed-template.py")
    previous = parse("r28-export-preparation/export-r28-closed-template-v2.py")
    producer = parse("source53-native-gates-preparation/native-run-r30-template-v2.py")
    raw, text, tree, funcs, current_pin = current
    assert len(raw) == 44373 and current_pin["sha256"] == "45e64afcdffd597de793c12158f90f605bb2274667b2774ad39d431a4af3700a"
    c = constants(tree)
    unknowns = sorted(name for name, value in c.items() if value is None)
    assert unknowns == ["CLOSED_ORIGINAL_PINS", "CONTROLLER_ORIGINAL_PINS", "TERMINAL_PIN"]
    assert c["FROZEN"] is False
    assert c["COMMIT"] == "f74be175de66a4b351cd239d39d98cd34fe9cc1b"
    assert c["TREE"] == "440d4a8e09af4009e4d9ea067388826308da8803"
    assert c["JOB_ID"] == "1a1b25b399f-fc05-7daa"
    assert c["PACKAGES"] == ["codex-app-server"] and c["BASELINE_COUNT"] == 1345
    assert c["COMMANDS"] == {
        "strict": ["just", "clippy", "--locked", "-p", "codex-app-server", "--", "-D", "warnings"],
        "tests": ["just", "test", "--locked", "--retries", "0", "-p", "codex-app-server"],
    }
    old_helpers = ["require", "sha", "data_pin", "safe_relative", "check_pin", "stable_read", "git", "natural_terminal"]
    for name in old_helpers:
        assert snippet(text, funcs[name]) == snippet(previous[1], previous[3][name])
    for name in ("clean_lines", "review_tests"):
        assert snippet(text, funcs[name]) == snippet(producer[1], producer[3][name])

    # No exporter or runner function is executed: these are syntax-level access checks.
    actual_root = ROOT / "native-validation-results/r30-start-closed"
    env_raw = (actual_root / "evidence/native-source53-project-r30-environment.json").read_bytes()
    pre_raw = (actual_root / "evidence/native-source53-project-r30-preconditions.json").read_bytes()
    launch_raw = (actual_root / "controller/source53R30LaunchRaw.json").read_bytes()
    env, pre, launch = json.loads(env_raw), json.loads(pre_raw), json.loads(launch_raw)
    for value in (env, pre):
        assert value["source_commit"] == c["COMMIT"] and value["source_tree"] == c["TREE"]
        assert value["diagnostic_only"] is True and value["behavior_repair_claimed"] is False
    field_readback = []
    for variable, value in (("env", env), ("pre", pre)):
        keys = accessed(funcs["export_closed"], variable)
        assert set(keys) <= set(value), (variable, set(keys) - set(value))
        field_readback.append({"variable": variable, "accessed_keys": keys, "actual_keys": sorted(value), "missing": []})
    assert set(env["approved_prerequisite_env_pin"]) == {"bytes", "sha256", "git_blob"}
    assert "add('input/environment/agentd-prerequisite-env.json', E / 'agentd-prerequisite-env.json', env['approved_prerequisite_env_pin'])" in text
    job = launch["job"]
    assert job["id"] == c["JOB_ID"] and job["idempotency_key"] == c["JOB_KEY"]
    assert job["args"] == ["/home/alex/work/hepta-cell-unified-20261106-a/" + c["RUNNER_NAME"]]
    assert job["executable"] == "/usr/bin/python3" and job["cwd"] == "/home/alex/work/hepta-cell-unified-20261106-a"
    assert job["host"] == "pocket4" and job["env_keys"] == []
    assert launch["reused"] is False and launch["launch"]["ok"] is True
    producer_fields = []
    review = funcs["review_closed_originals"]
    for variable, function, schema in (
        ("raw", "run_phase", "hepta.native-raw-process-result.v1"),
        ("rec", "run_phase", "hepta.native-gate-receipt.v2"),
        ("complete", "run_frozen", "hepta.source53-project-gates-complete.v1"),
        ("error_record", "main", "hepta.source53-project-orchestration-error.v1"),
    ):
        node, fields = schema_dict(producer[3][function], schema)
        keys = accessed(review, variable)
        assert set(keys) <= set(fields), (variable, set(keys) - set(fields))
        producer_fields.append({"consumer_variable": variable, "producer_function": function,
                                "producer_schema": schema, "producer_line": node.lineno,
                                "accessed_keys": keys, "producer_keys": sorted(fields), "missing": []})
    incomplete_dicts = []
    for n in ast.walk(producer[3]["run_frozen"]):
        if isinstance(n, ast.Dict):
            fields = {k.value: v for k, v in zip(n.keys, n.values) if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            if "failed_phase" in fields:
                incomplete_dicts.append(fields)
    assert len(incomplete_dicts) == 1
    assert set(accessed(review, "incomplete")) <= set(incomplete_dicts[0])
    # Producer intentionally has no schema key for its incomplete JSON; consumer does not invent one.
    assert "schema" not in incomplete_dicts[0] and "schema" not in accessed(review, "incomplete")

    subprocess_calls = [(n.lineno, snippet(text, n)) for n in ast.walk(tree)
                        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and isinstance(n.func.value, ast.Name) and n.func.value.id == "subprocess"]
    assert len(subprocess_calls) == 1 and "['git','--no-optional-locks',*args]" in subprocess_calls[0][1]
    assert "{'write-tree','rev-parse','diff','ls-files','ls-tree'}" in snippet(text, funcs["git"])
    main_text = snippet(text, funcs["main"])
    assert main_text.index("check_bindings()") < main_text.index("export_closed()")
    assert "require(__debug__" in snippet(text, funcs["check_bindings"])
    assert "require(FROZEN is True" in snippet(text, funcs["check_bindings"])
    export_text = snippet(text, funcs["export_closed"])
    assert "actual_names == set(CLOSED_ORIGINAL_PINS)" in export_text
    assert "contents['INDEX.json']" in export_text and "with OUT.open('xb')" in export_text
    assert "tf.extractfile(member).read() == contents[member.name]" in export_text
    assert "counts': None if review is None" in export_text
    assert "archive_export_success_is_not_a_gate_pass': True" in export_text
    assert "source_guard(source)" in export_text and "final_source == initial_source" in export_text
    assert "data_pin(raw) == value['raw'] and mode == value['mode']" in export_text
    review_text = snippet(text, review)
    assert "set(closed) == {PREFIX + s for s in SUCCESS_SUFFIXES}" in review_text
    assert "original_exit': raw.get('exit_code')" in review_text
    assert "effective_exit': rec.get('effective_exit_code')" in review_text
    assert "terminal['exit_code'] == 0 and complete is not None" in review_text
    assert "original incomplete/error absent; actual existing originals retained" in review_text

    result = {
        "schema": "hepta.r30-export-independent-static-mechanical.v1",
        "classification": "STATIC_ONLY_NO_EXPORTER_EXECUTION",
        "template": current_pin,
        "author_handoff": {"path": "r30-export-preparation/HANDOFF-MANIFEST.json", **pin(handoff_raw)},
        "handoff_listed_files_rehashed": 12,
        "references": [previous[4], producer[4]],
        "FROZEN": False, "unknown_bindings": unknowns,
        "eight_old_helpers_byte_identical": old_helpers,
        "two_actual_r30_parser_functions_byte_identical": ["clean_lines", "review_tests"],
        "actual_closed_start_inputs": {
            "launch": {"path": "native-validation-results/r30-start-closed/controller/source53R30LaunchRaw.json", **pin(launch_raw)},
            "environment": {"path": "native-validation-results/r30-start-closed/evidence/native-source53-project-r30-environment.json", **pin(env_raw)},
            "preconditions": {"path": "native-validation-results/r30-start-closed/evidence/native-source53-project-r30-preconditions.json", **pin(pre_raw)},
        },
        "direct_file_launch_matches_actual_original": True,
        "actual_precondition_environment_key_checks": field_readback,
        "actual_environment_pin_has_no_path_and_fixed_original_path_used": True,
        "producer_consumer_fields": producer_fields,
        "incomplete_original_has_no_schema_and_consumer_accepts_actual_keys": True,
        "only_subprocess_site": subprocess_calls,
        "successful_closure_requires_exact_original_19": True,
        "unsuccessful_closure_requires_only_actual_original_set_and_records_missing_fields": True,
        "raw_effective_outer_results_kept_separate": True,
        "no_complete_summary_means_counts_null": True,
        "source_before_after_and_all_copied_originals_reread": True,
        "archive_verified_byte_for_byte_after_create_only_write": True,
        "native_rust_metadata_exporter_or_git_execution": False,
        "future_closure_claimed": False,
        "execution_authorized": False,
    }
    out = (json.dumps(result, indent=2) + "\n").encode()
    with (OUT / "MECHANICAL-READBACK.json").open("xb") as f:
        f.write(out)
    print(json.dumps({"path": "MECHANICAL-READBACK.json", **pin(out)}))


if __name__ == "__main__":
    main()
