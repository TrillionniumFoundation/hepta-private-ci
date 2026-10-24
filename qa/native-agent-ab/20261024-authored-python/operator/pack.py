"""Trusted preparation and pure scoring; never imports a submitted candidate.

`requests` is used only after a model turn is frozen. Launch the public adapter
in an externally admitted sandbox, then give its JSONL observations to `judge`.
That observation stream alone is not an isolation or execution attestation.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
MAX_REPLIES_BYTES = 2 * 1024 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_index():
    return json.loads((ROOT / "operator" / "task-index.json").read_bytes())


def task_record(task_id_or_slug):
    matches = [task for task in read_index()["tasks"]
               if task_id_or_slug in (task["task_id"], task["slug"])]
    if len(matches) != 1:
        raise ValueError("unknown or ambiguous task")
    return matches[0]


def load_cases(task):
    raw = (ROOT / "private" / task["slug"] / "cases.json").read_bytes()
    if digest(raw) != task["hidden_cases_sha256"]:
        raise ValueError("hidden case hash mismatch")
    document = json.loads(raw)
    if document["task_id"] != task["task_id"]:
        raise ValueError("case task identity mismatch")
    return document["cases"]


def validate():
    index = read_index()
    identities = set()
    for task in index["tasks"]:
        if task["task_id"] in identities:
            raise ValueError("duplicate task identity")
        identities.add(task["task_id"])
        directory = ROOT / "tasks" / task["slug"]
        expected_names = set(task["agent_visible_files"])
        if {p.name for p in directory.iterdir()} != expected_names:
            raise ValueError("unexpected agent-visible fixture")
        source = (directory / "repair_target.py").read_bytes()
        prompt = (directory / "TASK.md").read_bytes()
        if digest(source) != task["initial_source_sha256"] or digest(prompt) != task["task_text_sha256"]:
            raise ValueError("public fixture hash mismatch")
        public_hash = digest(canonical({"repair_target.py": source.decode(), "TASK.md": prompt.decode()}))
        if public_hash != task["public_bundle_sha256"]:
            raise ValueError("public bundle hash mismatch")
        compile(source, "repair_target.py", "exec")
        reference = (ROOT / "private" / task["slug"] / "reference.py").read_bytes()
        if digest(reference) != task["reference_sha256"]:
            raise ValueError("author reference hash mismatch")
        compile(reference, "reference.py", "exec")
        cases = load_cases(task)
        if len(cases) != task["case_count"] or len({c["case_id"] for c in cases}) != len(cases):
            raise ValueError("case count or uniqueness mismatch")
        for case in cases:
            if digest(canonical(case["input"])) != case["input_sha256"]:
                raise ValueError("test input hash mismatch")
    return {"status": "valid", "tasks": len(identities),
            "families": len({t["family_id"] for t in index["tasks"]}),
            "cases": sum(t["case_count"] for t in index["tasks"])}


def materialize(task, destination):
    validate()
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise ValueError("destination must not exist; never reuse an agent workspace")
    destination.mkdir(parents=True)
    try:
        for name in task["agent_visible_files"]:
            origin = ROOT / "tasks" / task["slug"] / name
            if origin.is_symlink():
                raise ValueError("fixture symlink rejected")
            shutil.copyfile(origin, destination / name)
    except BaseException:
        # A partial workspace is retained for diagnosis and will not be reused.
        raise
    return {"task_id": task["task_id"], "destination": str(destination.resolve()),
            "files": {name: digest((destination / name).read_bytes()) for name in task["agent_visible_files"]},
            "contains_hidden_tests_or_reference": False,
            "os_sandbox_established": False}


def requests_for(task):
    for case in load_cases(task):
        yield {"schema": "hepta.native-ab.case-request.v1", "task_id": task["task_id"],
               "slug": task["slug"], "case_id": case["case_id"],
               "input_sha256": case["input_sha256"], "input": case["input"]}


def judge(task, replies_raw, candidate_sha256):
    """Functional comparison only. Supervisor evidence is evaluated separately."""
    cases = load_cases(task)
    if len(replies_raw) > MAX_REPLIES_BYTES:
        return {"functional_status": "grading_error", "reason": "reply_size_limit", "success": False}
    try:
        replies = [json.loads(line) for line in replies_raw.splitlines()]
        if len(replies) != len(cases):
            raise ValueError("missing or extra response lines")
        results = []
        for case, reply in zip(cases, replies):
            expected_identity = {"schema": "hepta.native-ab.observation.v1",
                                 "task_id": task["task_id"], "slug": task["slug"],
                                 "case_id": case["case_id"], "input_sha256": case["input_sha256"],
                                 "candidate_sha256": candidate_sha256}
            if not isinstance(reply, dict) or set(reply) != set(expected_identity) | {"observed"}:
                raise ValueError("response schema mismatch")
            if any(reply.get(key) != value for key, value in expected_identity.items()):
                raise ValueError("response identity/order mismatch")
            # Canonical byte equality preserves JSON type distinctions: False != 0.
            passed = canonical(reply["observed"]) == canonical(case["expected"])
            results.append({"case_id": case["case_id"], "passed": passed})
        success = all(item["passed"] for item in results)
        return {"schema": "hepta.native-ab.functional-grade.v1", "task_id": task["task_id"],
                "candidate_sha256": candidate_sha256, "hidden_cases_sha256": task["hidden_cases_sha256"],
                "observations_sha256": digest(replies_raw), "functional_status": "pass" if success else "fail",
                "success": success, "passed": sum(item["passed"] for item in results),
                "total": len(results), "cases": results,
                "execution_or_isolation_attested": False,
                "scope": "Finite black-box functional observations only; join independent supervisor receipts before A/B analysis"}
    except (ValueError, TypeError, KeyError) as error:
        return {"schema": "hepta.native-ab.functional-grade.v1", "task_id": task["task_id"],
                "functional_status": "grading_error", "success": False,
                "reason": str(error), "observations_sha256": digest(replies_raw),
                "execution_or_isolation_attested": False}


def print_json(value):
    sys.stdout.buffer.write(canonical(value) + b"\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    sub.add_parser("list")
    material = sub.add_parser("materialize")
    material.add_argument("--task", required=True)
    material.add_argument("--dest", required=True)
    request = sub.add_parser("requests")
    request.add_argument("--task", required=True)
    scoring = sub.add_parser("judge")
    scoring.add_argument("--task", required=True)
    scoring.add_argument("--replies", required=True)
    scoring.add_argument("--candidate-sha256", required=True,
                         help="Digest measured by the trusted supervisor from the immutable submitted source")
    args = parser.parse_args()
    if args.command == "validate":
        print_json(validate())
    elif args.command == "list":
        print_json(read_index())
    elif args.command == "materialize":
        print_json(materialize(task_record(args.task), args.dest))
    elif args.command == "requests":
        for request in requests_for(task_record(args.task)):
            print_json(request)
    else:
        digest_text = args.candidate_sha256
        if len(digest_text) != 64 or any(c not in "0123456789abcdef" for c in digest_text):
            raise ValueError("invalid candidate digest")
        print_json(judge(task_record(args.task), Path(args.replies).read_bytes(), digest_text))


if __name__ == "__main__":
    main()
