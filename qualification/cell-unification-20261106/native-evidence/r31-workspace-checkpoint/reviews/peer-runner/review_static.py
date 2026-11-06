"""Offline AST/byte review only. Never import or execute a prepared runner."""
from pathlib import Path
import ast
import hashlib
import json

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent
INPUTS = {
    "r31": ("source53-r31-preparation/native-run-r31-template.py", 124806, "83aa49f02eca55b409d7685f6719765a46de1ccf3bea84f357cd4d352c06fab6"),
    "r30": ("source53-native-gates-preparation/native-run-r30-template-v2.py", 60715, "a4bb18b0f2d2af63625e7ee6629df9f5a42f47c684bd8e4a72125b62b05d2c0b"),
    "r29": ("source53-r31-preparation/references/native-run-r29-actual.py", 82985, "26bb2c31806895b19410f290e1f20232ee3be2dbe09321e081857dddefac1fa2"),
}


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def write(name, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    path = OUT / name
    with path.open("xb") as handle:
        handle.write(raw)
    return {"path": name, **pin(raw)}


def functions(text):
    return {node.name: ast.get_source_segment(text, node) for node in ast.parse(text).body
            if isinstance(node, ast.FunctionDef)}


def literal_assignments(text):
    values = {}
    for node in ast.parse(text).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        try:
            values[node.targets[0].id] = ast.literal_eval(node.value)
        except (ValueError, TypeError):
            pass
    return values


def main():
    text, pins = {}, {}
    for label, (relative, size, digest) in INPUTS.items():
        path = ROOT / relative
        assert path.is_file() and not path.is_symlink()
        raw = path.read_bytes()
        assert len(raw) == size and hashlib.sha256(raw).hexdigest() == digest
        text[label] = raw.decode("utf-8")
        pins[label] = {"path": relative, **pin(raw)}
    r31, r30, r29 = (functions(text[key]) for key in ("r31", "r30", "r29"))
    common = [name for name in sorted(r31.keys() & r30.keys()) if r31[name] == r30[name]]
    assert len(common) == 27
    assert r31["check_source_bindings"] == r30["check_bindings"].replace("def check_bindings():", "def check_source_bindings():", 1)
    original_parser = r29["review_workspace"].replace("def review_workspace(", "def review_original_workspace(", 1)
    original_parser = original_parser.replace("EXPECTED_TREE", "SOURCE52_TREE").replace("EXPECTED_COMMIT", "SOURCE52_COMMIT")
    assert original_parser == r31["review_original_workspace"]
    values = literal_assignments(text["r31"])
    unknown = [name for name, value in values.items() if value is None]
    assert values["FROZEN"] is False and len(unknown) == 21
    assert values["COMMAND"] == ["just", "test", "--locked", "--retries", "0"]
    assert values["METADATA_COMMAND"] == ["cargo", "metadata", "--locked", "--no-deps", "--format-version", "1"]
    assert values["EXPECTED_WORKSPACE_MEMBER_COUNT"] == 193
    assert values["OUTER_TIMEOUT_SECONDS_CONTRACT"] == 9600
    assert values["R30_PREFIX"] == "native-source53-project-r30"
    assert values["R30_PHASES"] == ("strict", "tests")
    assert values["R29_JOB_ID"] == "1a1b1f83e4b-fc05-7bcd"
    # These are static syntax checks, never a call into the runner.
    assert "require(sys.flags.optimize == 0" in r31["check_source_bindings"]
    assert "check_source_bindings()" in r31["check_bindings"]
    assert r31["main"].index("check_bindings()") < r31["main"].index("run_frozen()")
    assert r31["run_frozen"].index("r30_prerequisite(") < r31["run_frozen"].index("capture_metadata(")
    assert r31["run_frozen"].index("capture_metadata(") < r31["run_frozen"].index("run_workspace(")
    assert r31["run_workspace"].index("raw_pin = write_json(") < r31["run_workspace"].index("log.read_bytes()")
    assert "output.flush()" in r31["write_json"] and "os.fsync(output.fileno())" in r31["write_json"]
    assert "process.wait()" in r31["run_workspace"]
    assert "process.kill(" not in text["r31"] and "process.terminate(" not in text["r31"]
    assert '"terminal_counts": observed_counts if complete else None' in r31["review_workspace"]
    assert 'missing = sorted(baseline - set(current))' in r31["review_workspace"]
    assert 'additional = sorted(set(current) - baseline)' in r31["review_workspace"]
    assert 'and not missing and not additional and not unsuccessful' in r31["review_workspace"]
    assert '"historical_project_pass_substitutes_for_r30": False' in r31["run_frozen"]
    review = {
        "schema": "hepta.source53-r31-independent-static-review.v1",
        "status": "STATIC_CLEAR_INERT_PREPARATION_ONLY",
        "inputs": pins,
        "ast_parse_pass": True,
        "r30_shared_function_count": len(common),
        "r30_shared_functions_byte_exact": common,
        "source_binding_checker_only_renamed": True,
        "original_r29_full_log_parser_only_renamed_and_bound_to_historical_source52": True,
        "unknown_binding_count": len(unknown),
        "unknown_bindings": unknown,
        "frozen": False,
        "manual_semantic_review": {
            "r30_current_prerequisite": "Nineteen original files plus separately pinned natural outer0. Both original app-server commands, raw/receipt timing/rc, resources, pre/post guards, source manifest, environment and complete fields are matched to the actual R30 V2 producer. Full-log exact1345 acceptance is recomputed before any fresh metadata or workspace launch.",
            "history_boundary": "Source52 R28 three-phase/Python/four-package PASS remains historical and is separately verified. It never substitutes for source53 R30. Original R24, R26 and R29 failed100 inputs remain pinned; R29 population remains20227PASS+1FAIL/130reportedskip.",
            "source_and_apply": "The identical27 R30 functions retain full197 source, both new existing leaves, all old195 rows, source53 apply complete/outer0, source50 unchanged-dependency lock inheritance, native HEAD bef and dual-lock guards.",
            "new_workspace_execution": "Fresh cargo metadata on current frozen source must produce193 members/defaults with identical member sets. The only workspace command is original no-p just test --locked --retries0; no added test filter, feature selection, retry, timeout or protection-environment change.",
            "baseline": "Original20228 binary/name IDs are independently parsed from pinned historical R29 complete log and compared only after the full unfiltered new gate. Missing/additional/duplicate/nonPASS IDs fail acceptance; none is passed as a test selector.",
            "failure_accounting": "Original subprocess rc is create-only flush/fsync persisted before log/resource or source postprocessing. Failure never becomes PASS. Compile/incomplete execution retains null terminal counts; natural wait does not kill/retry. Postguard failure retains source and prevents successful complete.",
            "result_boundary": "A genuine source53 project/workspace PASS would qualify only that engineering gate. Diagnostic stage logging is not a behavior repair or proven root cause. No scientific/adoption claim is made.",
        },
        "runner_imported_or_executed": False,
        "rust_cargo_metadata_formatter_native_or_network_probe_executed": False,
        "source_or_frozen_preparation_modified": False,
        "remaining_execution_prerequisites": "Actual source53 successful apply and all same-source original R30 closure bindings plus explicit root authorization remain required. This review grants no execution permission.",
    }
    record = write("INDEPENDENT-REVIEW.json", review)
    self_pin = {"path": Path(__file__).name, **pin(Path(__file__).read_bytes())}
    write("HANDOFF-MANIFEST.json", {"schema": "hepta.source53-r31-independent-review-handoff.v1", "files": [record, self_pin], "native_executed": False})
    print(json.dumps(record))


if __name__ == "__main__":
    main()
