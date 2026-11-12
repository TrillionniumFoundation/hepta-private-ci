"""Prepare, but never submit, the five-file isolated formatter request."""
import ast
import base64
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TASK = ROOT.parents[1]
DEEP = TASK / "native-deep-readback-split-4ab-v1"
C = TASK / "candidate-c-withdrawal-diagnostic-4ab-v1"
STACK = TASK / "stack-fix-v2"
SOURCE = "4ab34bbd3ca803213b6eecbaba81af719630f5d0"
TREE = "f947d38de96534b3882fba023e51ecd0476c809d"
RECORDS = "/home/qian-qi/hepta-learn-037c-evidence/format-native-diagnostic-five-v3"
KEY = "learn-037c-format-native-diagnostic-five-v3"
RUSTFMT = "342c3d56e8958da0b108108a39e37ceac64ebdd42e6eefafa237d219e5b7eb0c"
AGENT = "codex-rs/hepta-agentd/src/"


def metadata(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def write(name, data):
    path = ROOT / name
    if path.exists():
        assert path.read_bytes() == data, "refuse overwrite different canonical artifact: " + name
    else:
        path.write_bytes(data)


def write_json(name, data):
    write(name, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode())


old_driver_bytes = (DEEP / "format-request/format-driver.py").read_bytes()
old_driver = old_driver_bytes.decode()
old_review = json.loads((DEEP / "format-request/REQUEST_REVIEW.json").read_text())
assert metadata(old_driver_bytes) == old_review["driver"]
assert old_review["actual_rustfmt_run"] is False
assert old_review["source_commit"] == SOURCE and old_review["source_tree"] == TREE
old_request = json.loads((DEEP / "format-request/h-pty-start-request.json").read_text())
old_payload = json.loads((DEEP / "format-request/input-payload.json").read_text())
assert len(old_payload["files"]) == 1
assert metadata((DEEP / "format-request/input-payload.json").read_bytes()) == old_review["payload"]
assert old_request["args"][-1] == old_driver

originals = {}
deep_row = old_payload["files"][0]
originals[deep_row["path"]] = (DEEP, deep_row["base"], deep_row["before"], deep_row["origin"])
c_manifest = json.loads((C / "MANIFEST.json").read_text())
assert c_manifest["source_commit"] == SOURCE and c_manifest["source_tree"] == TREE
assert len(c_manifest["files"]) == 3
for row in c_manifest["files"]:
    originals[row["path"]] = (C, row["base"], row["postimage"],
        "exact4ab C withdrawal diagnostic markers; original non-test product tokens unchanged")
stack_path = AGENT + "circuit_original_evaluation_panel_tests.rs"
stack_source = json.loads((STACK / "source.original.json").read_text())["structuredContent"]
assert stack_source["display_url"].endswith("/blob/" + SOURCE + "/" + stack_path)
stack_base = (STACK / "base" / stack_path).read_bytes()
assert stack_base == stack_source["content"].encode()
assert metadata(stack_base)["blob"] == stack_source["sha"]
originals[stack_path] = (STACK, metadata(stack_base), metadata((STACK / "work" / stack_path).read_bytes()),
    "exact4ab Panel shared future heap cut from reviewed actual poll-stack evidence; native validation pending")
assert len(originals) == 5
assert set(originals) == {
    AGENT + "circuit_deep_training_readback_tests.rs",
    AGENT + "circuit_next_use_command_evidence.rs",
    AGENT + "circuit_next_use_command_owner_tests.rs",
    AGENT + "circuit_next_use_command_support_tests.rs",
    stack_path,
}

rows = []
for path, (directory, expected_base, expected_before, origin) in sorted(originals.items()):
    original = (directory / "base" / path).read_bytes()
    before = (directory / "work" / path).read_bytes()
    assert metadata(original) == expected_base, path
    assert metadata(before) == expected_before, path
    rows.append({"path": path, "origin": origin, "base": expected_base, "before": expected_before,
                 "base_base64": base64.b64encode(original).decode(),
                 "before_base64": base64.b64encode(before).decode()})
manifest = {"source_commit": SOURCE, "source_tree": TREE,
    "status": "NOT_SUBMITTED", "files": [{k: v for k, v in row.items() if not k.endswith("_base64")} for row in rows],
    "scope": "five reviewed diagnostic source files, isolated formatting only",
    "old_deep_single_file_request": "NOT_SUBMITTED_AND_NOT_REUSED",
    "checkout_access": False, "target_access": False, "cargo_access": False,
    "native_tests_run": False, "ordinary_qualification": 0}
provenance = copy.deepcopy(old_payload["format_method_provenance"])
provenance.update({
    "reviewed_deep_driver": str(DEEP / "format-request/format-driver.py"),
    "reviewed_deep_driver_metadata": metadata(old_driver_bytes),
    "changes": "only five exact payload paths/count/hashes, create-only records, labels, and base64 argv chunk transport",
    "source_commit": SOURCE, "source_tree": TREE,
    "old_deep_single_file_request": "NOT_SUBMITTED; new five-file intent has a new key",
})
payload = {"source_commit": SOURCE, "source_tree": TREE, "files": rows,
           "input_manifest": manifest, "format_method_provenance": provenance}
payload_bytes = (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
compressed = gzip.compress(payload_bytes, mtime=0)
encoded = base64.b64encode(compressed).decode()
chunks = [encoded[index:index + 32_768] for index in range(0, len(encoded), 32_768)]
assert "".join(chunks) == encoded and all(len(chunk.encode()) <= 32_768 for chunk in chunks)
assert gzip.decompress(base64.b64decode("".join(chunks), validate=True)) == payload_bytes

tree = ast.parse(old_driver)
driver = old_driver
edits = []
lines = old_driver.splitlines(keepends=True)
offsets = [0]
for line in lines:
    offsets.append(offsets[-1] + len(line))
assignments = {
    "INPUT_GZIP_BASE64": "''.join(sys.argv[1:])",
    "INPUT_GZIP_SHA256": repr(metadata(compressed)["sha256"]),
    "INPUT_JSON_SHA256": repr(metadata(payload_bytes)["sha256"]),
    "RECORDS": "pathlib.Path(" + repr(RECORDS) + ")",
    "EXPECTED_PATHS": repr(set(originals)),
}
for node in tree.body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        name = node.targets[0].id
        if name in assignments:
            start = offsets[node.lineno - 1] + node.col_offset
            end = offsets[node.end_lineno - 1] + node.end_col_offset
            edits.append((start, end, name + " = " + assignments[name]))
assert len(edits) == len(assignments)
for start, end, replacement in sorted(edits, reverse=True):
    driver = driver[:start] + replacement + driver[end:]
driver = "import sys\n" + driver
assert driver.count('assert len(payload["files"]) == 1') == 1
driver = driver.replace('assert len(payload["files"]) == 1', 'assert len(payload["files"]) == 5')
driver = driver.replace("deep-readback-split-prefmt.patch", "native-diagnostic-five-prefmt.patch")
driver = driver.replace("deep-readback-split-formatted.patch", "native-diagnostic-five-formatted.patch")
driver = driver.replace("isolated Deep hot/cold test split formatting only; no native or ordinary qualification",
                        "isolated five-file native diagnostic formatting only; no native or ordinary qualification")
compile(driver, "format-driver.py", "exec")


class Normalize(ast.NodeTransformer):
    def visit_Import(self, node):
        return None if len(node.names) == 1 and node.names[0].name == "sys" else node

    def visit_Assign(self, node):
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in assignments:
            return ast.Assign(targets=node.targets, value=ast.Constant("<approved input/records substitution>"))
        return self.generic_visit(node)

    def visit_Assert(self, node):
        if ast.unparse(node.test) in ("len(payload['files']) == 1", "len(payload['files']) == 5"):
            return ast.Assert(test=ast.Constant("<approved five-file count>"))
        return self.generic_visit(node)

    def visit_Constant(self, node):
        values = {
            "deep-readback-split-prefmt.patch": "<prefmt patch label>",
            "native-diagnostic-five-prefmt.patch": "<prefmt patch label>",
            "deep-readback-split-formatted.patch": "<formatted patch label>",
            "native-diagnostic-five-formatted.patch": "<formatted patch label>",
            "isolated Deep hot/cold test split formatting only; no native or ordinary qualification": "<scope label>",
            "isolated five-file native diagnostic formatting only; no native or ordinary qualification": "<scope label>",
        }
        if isinstance(node.value, str) and node.value in values:
            return ast.Constant(values[node.value])
        return node


old_ast = ast.dump(Normalize().visit(ast.parse(old_driver)), include_attributes=False)
new_ast = ast.dump(Normalize().visit(ast.parse(driver)), include_attributes=False)
assert old_ast == new_ast, "unapproved formatter driver logic difference"
assert "raise SystemExit(returncode if returncode is not None and error is None else 1)" in driver
assert RUSTFMT in driver and '"imports_granularity=Item,skip_children=true"' in driver
request = copy.deepcopy(old_request)
request["args"] = [*old_request["args"][:-1], driver, *chunks]
request["idempotency_key"] = KEY
assert request["executable"] == "/usr/bin/python3"
assert request["host"] == "desktop"
assert request["args"][-len(chunks)-1] == driver
assert all(len(arg.encode()) <= 32_768 for arg in request["args"])
arg_bytes = sum(len(arg.encode()) + 1 for arg in [request["executable"], *request["args"]])
local_arg_max = os.sysconf("SC_ARG_MAX")
assert arg_bytes + 65_536 < local_arg_max
canonical = (json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
review = {
    "status": "NOT_SUBMITTED", "first_start_owner": "/root",
    "idempotency_key": KEY, "create_only_records": RECORDS,
    "source_commit": SOURCE, "source_tree": TREE,
    "canonical": metadata(canonical), "driver": metadata(driver.encode()),
    "payload": metadata(payload_bytes), "payload_gzip": metadata(compressed),
    "path_count": 5, "paths": sorted(originals),
    "base_and_before_full_bytes_sha_gitblob_checked": True,
    "driver_ast_equal_after_only_approved_substitutions": True,
    "normalized_driver_ast_sha256": hashlib.sha256(old_ast.encode()).hexdigest(),
    "argv_count": len(request["args"]), "base64_chunks": len(chunks),
    "argument_lengths_bytes": [len(arg.encode()) for arg in request["args"]],
    "argument_total_bytes_with_nul": arg_bytes, "local_SC_ARG_MAX": local_arg_max,
    "environment_reserve_bytes": 65_536, "remote_ARG_MAX_not_probed": True,
    "old_deep_request_preserved": True, "old_deep_request_not_submitted": True,
    "checkout_access": False, "target_access": False, "cargo_access": False,
    "native_tests_run": False, "actual_rustfmt_run": False,
}
write("format-driver.py", driver.encode())
write("input-payload.json", payload_bytes)
write("input-payload.json.gz", compressed)
write_json("input-manifest.json", manifest)
write_json("format-method-provenance.json", provenance)
write("h-pty-start-request.json", canonical)
write_json("REQUEST_REVIEW.json", review)
print(json.dumps(review, indent=2))
