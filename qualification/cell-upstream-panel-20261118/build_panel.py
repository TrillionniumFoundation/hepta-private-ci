"""Build six evaluation-only requirements from exact public repository bytes."""

import ast
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from cell_experiments import data, repo_execution
from cell_experiments.protocol_v3 import prepare_record, verify_reference

HERE = Path(__file__).resolve().parent
SOURCES = {
    "requests": ("psf/requests", "3c7baaa05ab4aa49cc819ce3a819d260de19c157", "src/requests/utils.py", "requests_utils.py.txt", "Apache-2.0"),
    "werkzeug": ("pallets/werkzeug", "0f43c6ebd426039e4b99ec22535c2c8a2ec2f69f", "src/werkzeug/http.py", "werkzeug_http.py.txt", "BSD-3-Clause"),
    "click": ("pallets/click", "08b803cf32ceb2ae6a772c62d5da42757a897d44", "src/click/parser.py", "click_parser.py.txt", "BSD-3-Clause"),
}


def constant(identifier, value, **extra):
    return {"id": identifier, "kind": "constant", "value": value, **extra}


SPECS = [
    ("requests", "unquote_header_value", "header-unquote", {},
     [(('"alpha"',), "alpha"), (("bare",), "bare")],
     [constant("always-alpha", "alpha"), {"id": "suffix", "kind": "suffix", "value": "wrong"}]),
    ("requests", "unquote_unreserved", "uri-unreserved", {"UNRESERVED_SET": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"},
     [(("%41%2F%7E",), "A%2F~"), (("x%20y",), "x%20y")],
     [constant("decode-reserved", "A/~", when_first_arg="%41%2F%7E"), constant("always-original", "%41%2F%7E")]),
    ("requests", "parse_header_links", "http-links", {},
     [(('<https://example.org/a>; rel="next"',), [{"url": "https://example.org/a", "rel": "next"}]), (("<b>",), [{"url": "b"}])],
     [constant("empty-links", []), constant("relation-lost", [{"url": "https://example.org/a"}], when_first_arg='<https://example.org/a>; rel="next"')]),
    ("werkzeug", "_is_entity_header", "entity-header", {},
     [(("Content-Type",), True), (("x-custom",), False), (("CONTENT-LENGTH",), True)],
     [constant("always-entity", True), constant("case-lost", False, when_first_arg="CONTENT-LENGTH")]),
    ("werkzeug", "_is_byte_range_valid", "byte-range", {},
     [((0, 2, 4), True), ((3, 2, 4), False), ((None, 1, 4), False)],
     [constant("always-valid", True), {"id": "invert", "kind": "toggle"}]),
    ("click", "_split_opt", "option-prefix", {},
     [(("--name",), ("--", "name")), (("-x",), ("-", "x")), (("plain",), ("", "plain"))],
     [constant("always-short", ["-", "x"]), constant("long-tail-corrupt", ["--", "wrong"], when_first_arg="--name")]),
]


def main():
    output = HERE / "prepared"
    output.mkdir(exist_ok=False)
    retrieved = json.loads((HERE / "SOURCE_RETRIEVAL.json").read_text())
    pins = {item["file"]: item for item in retrieved["sources"]}
    fixtures, records, checks = [], [], []
    for origin, function, family, globals_, pairs, controls in SPECS:
        repo, revision, path, archive, license_ = SOURCES[origin]
        raw = (HERE / "sources" / archive).read_bytes()
        pin = pins[archive]
        assert hashlib.sha256(raw).hexdigest() == pin["sha256"]
        assert hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == pin["git_blob"]
        tree = ast.parse(raw)
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == function]
        assert len(nodes) == 1 and not nodes[0].decorator_list
        node = nodes[0]
        subject = "".join(raw.decode().splitlines(keepends=True)[node.lineno - 1:node.end_lineno]).rstrip("\n") + "\n"
        source = {"repository": repo, "revision": revision, "path": path, "archive_name": archive, "sha256": pin["sha256"], "git_blob": pin["git_blob"], "url": pin["url"]}
        name = "upstream-" + origin + "-" + function.lstrip("_").replace("_", "-")
        fixture = {"fixture_id": name, "nodes": [function], "subject_source": subject, "source": source, "function": function, "entry": "direct", "globals": globals_, "controls": controls}
        fixtures.append(fixture)
        assert name not in repo_execution._CATALOG
        repo_execution._CATALOG[name] = fixture
        assertions = []
        for args, expected in pairs:
            call = "subject(" + ", ".join(repr(arg) for arg in args) + ")"
            if isinstance(expected, tuple):
                assertions.extend(f"    assert {call}[{i}] == {value!r}" for i, value in enumerate(expected))
            else:
                assertions.append(f"    assert {call} == {expected!r}")
        answer = data.canonical({"edits": [{"path": "test_contract.py", "old": "    pass", "new": "\n".join(assertions)}]}).decode()
        prompt = ("Write meaningful assertions for the pinned repository function below, exposed as subject. Cover distinct behaviors, including optional arguments and boundaries where present. Use literal arguments only; do not import, define helpers or call the original function name. The assertions must pass the original and detect wrong output controls.\nSource: " + repo + ":" + path + "@" + revision + "\n" + ("Bound globals: " + data.canonical(globals_).decode() + "\n" if globals_ else "") + subject)
        now = time.time_ns() // 1000000000
        record = {"schema": data.SCHEMA, "record_id": name, "task_id": "test-completion:" + name, "lineage_id": repo + ":" + path + ":" + function, "family_id": origin + ":" + family, "project_id": repo, "source_id": repo + ":" + path, "source": {k: source[k] for k in ("repository", "revision", "path", "sha256")}, "split": "selection", "origin_kind": "curated_development", "exposure": "development", "observed_at": now, "available_at": now, "authorization": {"training_allowed": False, "evaluation_allowed": True, "rights_basis": license_ + " public source with complete pinned license retained; user requested E1-E6 experiments; assertions newly authored.", "scope": "Isolated external-source function-contract evaluation; not user traffic or independent evaluator custody."}, "task": {"input": prompt, "domain": "python-contract-test", "verifier": {"name": "repo_patch", "version": "1", "parameters": {"fixture_id": name, "fixture_sha256": data.digest(fixture)}}}, "task_domain": "python-contract-test", "teacher_id": None, "final_answer": answer, "trajectory": []}
        record = verify_reference(prepare_record(record))
        args = pairs[0][0]
        call = "subject(" + ", ".join(repr(arg) for arg in args) + ")"
        invalid = data.canonical({"edits": [{"path": "test_contract.py", "old": "    pass", "new": f"    assert {call} == {call}"}]}).decode()
        negative = data.verify_answer(record, invalid)
        assert negative["success"] is False and negative["result"]["result"]["original_passed"] is True and negative["result"]["controls_rejected"] == 0
        checks.append({"task_id": record["task_id"], "reference": record["protocol_reference_receipt"], "tautology": negative, "tautology_answer": invalid})
        records.append(record)
    data.validate_records(records)
    (HERE / "CATALOG.json").write_bytes(data.canonical({"schema": "hepta.repo-function-fixtures.v1", "fixtures": fixtures}) + b"\n")
    (output / "records.jsonl").write_bytes(b"".join(data.canonical(record) + b"\n" for record in records))
    (output / "REFERENCE_CHECKS.json").write_bytes(data.canonical(checks) + b"\n")
    summary = {"schema": "hepta.upstream-evaluation-panel.v1", "tasks": len(records), "repositories": sorted({r["project_id"] for r in records}), "maintainer_groups": ["psf", "pallets"], "source_file_groups": 3, "independent_users": 0, "independent_evaluator": False, "external_teacher_calls": 0, "training_allowed": False, "task_demand": "newly authored function-test requirements on genuine upstream source", "pretraining_overlap_known": False, "old_A_B_task_reuse": False, "reference_successes": len(records), "tautology_rejections": len(checks), "catalog_sha256": hashlib.sha256((HERE / "CATALOG.json").read_bytes()).hexdigest(), "records_sha256": hashlib.sha256((output / "records.jsonl").read_bytes()).hexdigest(), "source_retrieval_sha256": hashlib.sha256((HERE / "SOURCE_RETRIEVAL.json").read_bytes()).hexdigest()}
    (HERE / "PANEL.json").write_bytes(data.canonical(summary) + b"\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
