"""Freeze one independent Colab entry after its source/native receipts are final."""

import argparse
import ast
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import zipfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--expected-bundle-sha256", required=True)
    parser.add_argument("--native-qualification", type=Path, required=True)
    parser.add_argument("--native-budget", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; preserve prior prepared entries")
    bundle = json.loads(args.bundle.read_bytes())
    raw = base64.b64decode(bundle["archive_b64"], validate=True)
    if sha(raw) != bundle["sha256"] or bundle["sha256"] != args.expected_bundle_sha256:
        raise RuntimeError("bundle differs from the explicitly frozen source")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = [entry.filename for entry in archive.infolist()]
        if len(names) != len(set(names)) or set(names) != set(bundle["manifest"]):
            raise RuntimeError("archive member set mismatch")
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or str(path) != name:
                raise RuntimeError("noncanonical source path")
            if sha(archive.read(name)) != bundle["manifest"][name]:
                raise RuntimeError("source file digest mismatch: " + name)
        budget_spec = json.loads(archive.read("qualification/hcsn_differentiable/error_budget.json"))
    qraw, braw = args.native_qualification.read_bytes(), args.native_budget.read_bytes()
    qualification, budget = json.loads(qraw), json.loads(braw)
    if (qualification.get("status") != "passed" or qualification.get("tests_run") != 71
            or len(qualification.get("tests", [])) != 71 or budget.get("status") != "passed"
            or len(budget.get("fixtures", [])) != 4 or budget.get("budget") != budget_spec):
        raise RuntimeError("native receipts do not match the declared 71-test / 4-fixture baseline")
    for report in (qualification, budget):
        if report["source_before"] != report["source_after"] or report.get("source_unchanged") is not True:
            raise RuntimeError("native source changed during execution")
        for name, value in report["source_before"].items():
            digest = value["sha256"] if isinstance(value, dict) else value
            if bundle["manifest"].get("qualification/hcsn_differentiable/" + name) != digest:
                raise RuntimeError("native receipt is from a different snapshot: " + name)
    config = dict(bundle, qualification_sources=qualification["source_before"], budget_sources=budget["source_before"],
                  test_inventory=[row["test"] for row in qualification["tests"]], fixture_count=4,
                  budget_spec=budget_spec, native_qualification_sha256=sha(qraw), native_budget_sha256=sha(braw))
    encoded = base64.b64encode(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).decode()
    header = "import base64, json\nCONFIG = json.loads(base64.b64decode(" + repr(encoded) + "))\n"
    text = header + Path(__file__).with_name("worker_template.py").read_text()
    ast.parse(text)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(text)
    print(json.dumps({"prepared_only": True, "source_archive_sha256": bundle["sha256"],
                      "worker_sha256": sha(text.encode()), "worker_bytes": len(text.encode()),
                      "output": str(args.output), "submitted": False}))


if __name__ == "__main__":
    main()
