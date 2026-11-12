"""Prepare the three-file Root formatter request; Root alone may dispatch."""
import ast
import base64
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import re


OUT = Path(__file__).resolve().parent
WORKSPACE = OUT.parent
SOURCE = "a96d1b821d10ed3d9e99dd06c5141f9f242ae318"
TREE = "f96bebefbc1e7d8187efadb62f88d524cdd18451"
RECORDS = "/home/qian-qi/hepta-learn-037c-evidence/format-root-progress-postread-v3"
KEY = "learn-037c-format-root-progress-postread-v3"
ROOT12 = WORKSPACE / "root-evaluated-candidate-formatted-v1"
PROGRESS = WORKSPACE / "root-evaluated-candidate-progress-v3"
POSTREAD = WORKSPACE / "candidate-root-postread-batch-a96-v1"
PREFIX = "codex-rs/hepta-agentd/src/"


def meta(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def normalized_meta(value):
    return {"bytes": value["bytes"], "sha256": value["sha256"],
            "blob": value.get("blob", value.get("git_blob"))}


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def write(name, data):
    path = OUT / name
    if path.exists():
        assert path.read_bytes() == data, "refuse overwrite differing canonical: " + name
    else:
        path.write_bytes(data)


root_manifest_bytes = (ROOT12 / "manifest.json").read_bytes()
assert meta(root_manifest_bytes)["sha256"] == "cbe3f63d93e14d2cc835dd8fb38e4f63e923822fed36af98f7d93e40fc82f972"
root_manifest = json.loads(root_manifest_bytes)
assert root_manifest["returncode"] == 0 and root_manifest["error"] is None
root_rows = {row["path"]: row for row in root_manifest["files"]}
progress_manifest_bytes = (PROGRESS / "MANIFEST.json").read_bytes()
progress_manifest = json.loads(progress_manifest_bytes)
postread_manifest_bytes = (POSTREAD / "MANIFEST.json").read_bytes()
postread_manifest = json.loads(postread_manifest_bytes)
postread_rows = {row["path"]: row for row in postread_manifest["product_files"]}
selection = PREFIX + "cell_q24_candidate_stage_retention_selection.rs"
retention = PREFIX + "cell_q24_candidate_stage_retention.rs"
evaluation = PREFIX + "cell_q24_candidate_stage_evaluation.rs"
assert progress_manifest["path"] == selection
assert progress_manifest["before_format"]["sha256"] == "6c97b28cd0a495d41dbd808bb3feb76f49c316a3fba6aeb12b77e418917d40a7"
assert set(postread_rows) == {evaluation, retention}

rows = []
for path in sorted([selection, retention, evaluation]):
    if path == selection:
        base = (PROGRESS / "base" / path).read_bytes()
        before = (PROGRESS / "work" / path).read_bytes()
        assert meta(base) == normalized_meta(progress_manifest["base"])
        assert meta(before) == normalized_meta(progress_manifest["before_format"])
        original_manifest = meta(progress_manifest_bytes)
        original_manifest_path = str(PROGRESS / "MANIFEST.json")
    else:
        base = (POSTREAD / "base" / path).read_bytes()
        before = (POSTREAD / "postimages-prefmt-v1" / path).read_bytes()
        assert meta(base) == normalized_meta(postread_rows[path]["base"])
        assert meta(before) == normalized_meta(postread_rows[path]["after"])
        original_manifest = meta(postread_manifest_bytes)
        original_manifest_path = str(POSTREAD / "MANIFEST.json")
    if path in {selection, retention}:
        assert base == (ROOT12 / "postimages" / path).read_bytes()
        assert meta(base) == root_rows[path]["after"]
        base_kind = "actual Root12 formatted postimage; not a bare a96 path"
        base_proof = {"actual_root12_manifest": meta(root_manifest_bytes),
                      "actual_root12_after": root_rows[path]["after"]}
    else:
        original = WORKSPACE / "root-evaluated-candidate-a96-v1/base" / path
        assert base == original.read_bytes()
        assert meta(base)["blob"] == "089a57d500eda46aa92bfe110722b9a4183732d3"
        base_kind = "exact a96 original evaluation source"
        base_proof = {"commit": SOURCE, "tree": TREE,
                      "git_blob": "089a57d500eda46aa92bfe110722b9a4183732d3"}
    rows.append({
        "path": path, "base_exists": True,
        "base": meta(base), "before": meta(before),
        "base_utf8": base.decode(), "before_utf8": before.decode(),
        "origin": {"base_kind": base_kind, "base_proof": base_proof,
                   "input_manifest_path": original_manifest_path,
                   "input_manifest": original_manifest},
    })

paths = sorted(row["path"] for row in rows)
assert len(paths) == len(set(paths)) == 3
source_binding = {
    "commit": SOURCE, "tree": TREE,
    "description": (
        "Only the Root progress selection increment and Candidate postread batching "
        "two-file increment. Selection and retention bases are verified actual "
        "Root12 formatted postimages; evaluation is exact a96. This is an isolated "
        "three-file formatter, not a full tree, compilation or execution."
    ),
    "actual_root12_manifest": meta(root_manifest_bytes),
    "progress_manifest": meta(progress_manifest_bytes),
    "postread_manifest": meta(postread_manifest_bytes),
    "per_file_base": [{"path": row["path"], "base": row["base"],
                       "origin": row["origin"]} for row in rows],
    "excluded": ["already-formatted Root caller V2 binding postimage", "Version V4 product files"],
    "dependency_not_executed": "Version V4 evaluated-only publication_progress API",
}
input_manifest = {
    "state": "NOT_SUBMITTED", "source_binding": source_binding,
    "files": [{key: value for key, value in row.items() if key not in {"base_utf8", "before_utf8"}} for row in rows],
    "counts": {"files": 3, "production": 3, "tests": 0},
    "first_start_owner": "/root", "native": "UNRUN", "ordinary_qualification": 0,
}
template_path = WORKSPACE / "profile-evaluated-version-format-v3-argv-v1/format-driver.py"
template = template_path.read_bytes()
assert meta(template)["sha256"] == "c9896a4dd81550b0670b4fb0d86182dbcb37905038c6397293e129936531a7ca"
provenance = {
    "original_driver_path": str(template_path), "original_driver": meta(template),
    "allowed_changes": ["records and artifact/qualification labels", "three exact paths and count", "payload hashes and per-file source binding"],
    "unchanged": ["single argv-chunk launch", "create-only record directory", "Rust 1.96 and fixed Rustfmt SHA", "edition 2024/imports_granularity=Item/skip_children=true", "no checkout/target/Cargo/native"],
    "first_start_owner": "/root", "state": "NOT_SUBMITTED",
}
payload = {"source_commit": SOURCE, "source_tree": TREE,
           "source_binding": source_binding, "files": rows,
           "input_manifest": input_manifest, "format_method_provenance": provenance}
payload_bytes = json_bytes(payload)
compressed = gzip.compress(payload_bytes, mtime=0)
encoded = base64.b64encode(compressed).decode()
driver = template.decode()
for old, new in {
    "format-evaluated-version-v3": "format-root-progress-postread-v3",
    "evaluated-version-v3-prefmt.patch": "root-progress-postread-v3-prefmt.patch",
    "combined-evaluated-version-v3.patch": "combined-root-progress-postread-v3.patch",
    "isolated evaluated Version V3 formatting only; no native or ordinary qualification": "isolated Root progress/postread V3 formatting only; no native or ordinary qualification",
    'assert len(payload["files"]) == 40': 'assert len(payload["files"]) == 3',
}.items():
    assert old in driver
    driver = driver.replace(old, new)
for assignment, value in [("INPUT_GZIP_SHA256", meta(compressed)["sha256"]),
                          ("INPUT_JSON_SHA256", meta(payload_bytes)["sha256"])]:
    driver, count = re.subn("^" + assignment + r" = .*?$", assignment + " = " + repr(value), driver, count=1, flags=re.M)
    assert count == 1
expected_paths = "EXPECTED_PATHS = {\n" + "".join("    " + repr(path) + ",\n" for path in paths) + "}"
driver, count = re.subn(r"^EXPECTED_PATHS = \{.*?^\}", expected_paths, driver, count=1, flags=re.M | re.S)
assert count == 1


def normalized_ast(source):
    class Normalize(ast.NodeTransformer):
        def visit_Assign(self, node):
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name in {"INPUT_GZIP_SHA256", "INPUT_JSON_SHA256", "RECORDS", "EXPECTED_PATHS"}:
                    node.value = ast.Constant("PER_REQUEST:" + name)
            return self.generic_visit(node)

        def visit_Assert(self, node):
            if ast.unparse(node.test) in {"len(payload['files']) == 40", "len(payload['files']) == 3"}:
                node.test = ast.Constant("EXACT_REQUEST_FILE_COUNT")
            return self.generic_visit(node)

        def visit_Constant(self, node):
            aliases = {
                "evaluated-version-v3-prefmt.patch": "PREFMT_PATCH",
                "root-progress-postread-v3-prefmt.patch": "PREFMT_PATCH",
                "combined-evaluated-version-v3.patch": "COMBINED_PATCH",
                "combined-root-progress-postread-v3.patch": "COMBINED_PATCH",
                "isolated evaluated Version V3 formatting only; no native or ordinary qualification": "FORMAT_ONLY_QUALIFICATION",
                "isolated Root progress/postread V3 formatting only; no native or ordinary qualification": "FORMAT_ONLY_QUALIFICATION",
            }
            if isinstance(node.value, str) and node.value in aliases:
                node.value = aliases[node.value]
            return node
    return ast.dump(Normalize().visit(copy.deepcopy(ast.parse(source))), include_attributes=False)


normalized = normalized_ast(driver)
assert normalized == normalized_ast(template.decode())
chunks = [encoded[offset:offset + 32768] for offset in range(0, len(encoded), 32768)]
request = {"host": "desktop", "executable": "/usr/bin/python3",
           "args": ["-u", "-c", driver, *chunks],
           "cwd": "/home/qian-qi/hepta-learn-037c-evidence", "idempotency_key": KEY}
assert gzip.decompress(base64.b64decode("".join(request["args"][3:]), validate=True)) == payload_bytes
sizes = [len(request["executable"].encode()), *[len(value.encode()) for value in request["args"]]]
assert max(sizes) <= 32768
total = sum(size + 1 for size in sizes)
arg_max = os.sysconf("SC_ARG_MAX")
assert total + 65536 < arg_max
request_bytes = json_bytes(request)
review = {
    "state": "NOT_SUBMITTED", "first_start_owner": "/root",
    "records": RECORDS, "stable_key": KEY,
    "request": meta(request_bytes), "driver": meta(driver.encode()),
    "payload": meta(payload_bytes), "compressed": meta(compressed),
    "source_binding": source_binding, "files": 3,
    "normalized_ast_equal_to_approved_actual_v3_driver": True,
    "normalized_ast_sha256": hashlib.sha256(normalized.encode()).hexdigest(),
    "argument_sizes": sizes, "argument_total_bytes_with_nuls": total,
    "local_SC_ARG_MAX": arg_max, "reserved_environment_and_pointer_bytes": 65536,
    "remote_ARG_MAX": "not probed", "create_only_records": True,
    "checkout_access": False, "target_access": False,
    "cargo_or_native_tests": False, "ordinary_qualification": 0,
}
for name, data in {
    "format-driver.py": driver.encode(), "input-payload.json": payload_bytes,
    "input-payload.json.gz": compressed, "input-manifest.json": json_bytes(input_manifest),
    "format-method-provenance.json": json_bytes(provenance),
    "h-pty-start-request.json": request_bytes, "REQUEST_REVIEW.json": json_bytes(review),
}.items():
    write(name, data)
print(json.dumps({key: review[key] for key in ["state", "records", "stable_key", "request", "driver", "payload", "compressed", "files", "argument_sizes", "argument_total_bytes_with_nuls", "normalized_ast_equal_to_approved_actual_v3_driver"]}, indent=2))
