"""Construct the isolated B2 panel from pinned, licensed public source bytes."""

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
SPECS = [
    {
        "origin": "django", "function": "is_same_domain",
        "archive": "django_http.py.txt", "family": "domain-pattern",
        "pairs": [
            (("api.example.org", ".example.org"), True),
            (("example.org", ".example.org"), True),
            (("badexample.org", ".example.org"), False),
            (("api.example.org", "example.org"), False),
            (("example.org", ""), False),
            (("example.org", "EXAMPLE.ORG"), True),
        ],
        "controls": [True, False],
    },
    {
        "origin": "django", "function": "escape_leading_slashes",
        "archive": "django_http.py.txt", "family": "redirect-path",
        "pairs": [
            (("//example.org/a",), "/%2Fexample.org/a"),
            (("/local",), "/local"),
            (("///path",), "/%2F/path"),
            (("https://example.org",), "https://example.org"),
        ],
        "controls": ["/local", "//example.org/a"],
    },
    {
        "origin": "pydantic", "function": "to_pascal",
        "archive": "pydantic_alias_generators.py.txt", "family": "pascal-alias",
        "pairs": [
            (("user_name",), "UserName"),
            (("__private_value",), "__PrivateValue"),
            (("version_2_id",), "Version2Id"),
            (("",), ""),
        ],
        "controls": ["UserName", ""],
    },
    {
        "origin": "pydantic", "function": "to_snake",
        "archive": "pydantic_alias_generators.py.txt", "family": "snake-alias",
        "pairs": [
            (("HTTPServer",), "http_server"),
            (("userID",), "user_id"),
            (("release2Tag",), "release_2_tag"),
            (("mixed-value",), "mixed_value"),
        ],
        "controls": ["http_server", ""],
    },
    {
        "origin": "more-itertools", "function": "first_true",
        "archive": "more_itertools_recipes.py.txt", "family": "first-truthy",
        "pairs": [
            (([0, False, None, "yes", "later"],), "yes"),
            (([0, False, None], "missing"), "missing"),
            (([],), None),
            (([0, 3, 4],), 3),
        ],
        "controls": [None, "yes"],
    },
    {
        "origin": "more-itertools", "function": "quantify",
        "archive": "more_itertools_recipes.py.txt", "family": "truthy-count",
        "pairs": [
            (([0, 1, 2, "", False, None, []],), 2),
            (([],), 0),
            (([False, False, False],), 0),
            ((["x", "y", True],), 3),
        ],
        "controls": [0, 1],
    },
]


def main():
    output = HERE / "prepared"
    output.mkdir(exist_ok=False)
    retrieved = data._parse((HERE / "SOURCE_RETRIEVAL.json").read_bytes())
    pins = {item["file"]: item for item in retrieved["sources"]}
    for pin in pins.values():
        raw = (HERE / "sources" / pin["file"]).read_bytes()
        assert len(raw) == pin["size"]
        assert hashlib.sha256(raw).hexdigest() == pin["sha256"]
        assert hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == pin["git_blob"]
    fixtures, records, checks = [], [], []
    for spec in SPECS:
        pin = pins[spec["archive"]]
        raw = (HERE / "sources" / pin["file"]).read_bytes()
        nodes = [node for node in ast.parse(raw).body if isinstance(node, ast.FunctionDef) and node.name == spec["function"]]
        assert len(nodes) == 1 and not nodes[0].decorator_list
        node = nodes[0]
        subject = "".join(raw.decode().splitlines(keepends=True)[node.lineno - 1:node.end_lineno]).rstrip("\n") + "\n"
        source = {key: pin[key] for key in ("repository", "revision", "path", "sha256", "git_blob", "url")}
        source["archive_name"] = pin["file"]
        name = "blind-b2-" + spec["origin"] + "-" + spec["function"].replace("_", "-")
        fixture = {
            "fixture_id": name, "nodes": [spec["function"]],
            "subject_source": subject, "source": source,
            "function": spec["function"], "entry": "direct", "globals": {},
            "controls": [{"id": f"constant-{i}", "kind": "constant", "value": value} for i, value in enumerate(spec["controls"])],
        }
        assert name not in repo_execution._CATALOG
        repo_execution._CATALOG[name] = fixture
        fixtures.append(fixture)
        assertions = [
            "    assert subject(" + ", ".join(repr(arg) for arg in args) + ") == " + repr(expected)
            for args, expected in spec["pairs"]
        ]
        answer = data.canonical({"edits": [{"path": "test_contract.py", "old": "    pass", "new": "\n".join(assertions)}]}).decode()
        prompt = (
            "Write meaningful assertions for the pinned repository function below, exposed as subject. "
            "Cover distinct behaviors, including optional literal arguments and boundaries where present. "
            "Use literal arguments only; do not import, define helpers or call the original function name. "
            "Callable predicate arguments are outside this literal-input task; retain their default. "
            "The assertions must pass the original and detect wrong output controls.\nSource: "
            + pin["repository"] + ":" + pin["path"] + "@" + pin["revision"] + "\n" + subject
        )
        now = time.time_ns() // 1_000_000_000
        record = {
            "schema": data.SCHEMA, "record_id": name,
            "task_id": "test-completion:" + name,
            "lineage_id": pin["repository"] + ":" + pin["path"] + ":" + spec["function"],
            "family_id": spec["origin"] + ":" + spec["family"],
            "project_id": pin["repository"],
            "source_id": pin["repository"] + ":" + pin["path"],
            "source": {key: source[key] for key in ("repository", "revision", "path", "sha256")},
            "split": "confirmation", "origin_kind": "curated_development",
            "exposure": "development", "observed_at": now, "available_at": now,
            "authorization": {
                "training_allowed": False, "evaluation_allowed": True,
                "rights_basis": pin["license"] + " public source; complete pinned license retained; user requested E1-E6 experiments; assertions newly authored.",
                "scope": "New held-out function-contract tasks from public projects; blinded to the A-only training constructor until both weights freeze; no authenticated users or independent legal custody.",
            },
            "task": {"input": prompt, "domain": "python-contract-test", "verifier": {"name": "repo_patch", "version": "1", "parameters": {"fixture_id": name, "fixture_sha256": data.digest(fixture)}}},
            "task_domain": "python-contract-test", "teacher_id": None,
            "final_answer": answer, "trajectory": [],
        }
        record = verify_reference(prepare_record(record))
        args = spec["pairs"][0][0]
        call = "subject(" + ", ".join(repr(arg) for arg in args) + ")"
        tautology = data.canonical({"edits": [{"path": "test_contract.py", "old": "    pass", "new": f"    assert {call} == {call}"}]}).decode()
        negative = data.verify_answer(record, tautology)
        assert not negative["success"]
        assert negative["result"]["result"]["original_passed"] is True
        assert negative["result"]["controls_rejected"] == 0
        checks.append({"task_id": record["task_id"], "reference": record["protocol_reference_receipt"], "tautology": negative, "tautology_answer": tautology})
        records.append(record)
    data.validate_records(records)
    (HERE / "CATALOG.json").write_bytes(data.canonical({"schema": "hepta.repo-function-fixtures.v1", "fixtures": fixtures}) + b"\n")
    (output / "records.jsonl").write_bytes(b"".join(data.canonical(record) + b"\n" for record in records))
    (output / "REFERENCE_CHECKS.json").write_bytes(data.canonical(checks) + b"\n")
    summary = {
        "schema": "hepta.blind-evaluation-panel-b2.v1", "created_at_ns": time.time_ns(),
        "tasks": len(records), "repositories": sorted({r["project_id"] for r in records}),
        "maintainer_groups": ["django", "more-itertools", "pydantic"],
        "source_file_groups": 3, "independent_users": 0, "independent_evaluator": False,
        "external_teacher_calls": 0, "model_calls": 0, "training_allowed": False,
        "task_demand": "newly authored literal-input function-test requirements on genuine upstream source",
        "blinding": "Separate author and directory; only commitment hashes are disclosed to training constructor before both weight manifests freeze. Shared workspace is not an access-control or independent-custody claim.",
        "pretraining_overlap_known": False, "old_A_B_task_reuse": False,
        "previous_panel_repositories_reused": False,
        "reference_successes": len(records), "tautology_rejections": len(checks),
        "reference_verifier_calls": len(records), "tautology_verifier_calls": len(checks),
        "catalog_sha256": hashlib.sha256((HERE / "CATALOG.json").read_bytes()).hexdigest(),
        "records_sha256": hashlib.sha256((output / "records.jsonl").read_bytes()).hexdigest(),
        "source_retrieval_sha256": hashlib.sha256((HERE / "SOURCE_RETRIEVAL.json").read_bytes()).hexdigest(),
        "verifier_source_sha256": hashlib.sha256(Path(repo_execution.__file__).read_bytes()).hexdigest(),
    }
    (HERE / "PANEL.json").write_bytes(data.canonical(summary) + b"\n")
    print(json.dumps({key: summary[key] for key in ("tasks", "model_calls", "reference_successes", "tautology_rejections", "catalog_sha256", "records_sha256", "source_retrieval_sha256")}, indent=2))


if __name__ == "__main__":
    main()
