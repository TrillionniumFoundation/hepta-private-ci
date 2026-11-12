"""Build only the immutable V4 formatter request; do not dispatch it."""

import ast
import base64
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent
V3_FORMAT = ROOT / "profile-evaluated-version-format-v3-argv-v1"
ACTUAL_V3 = ROOT / "profile-evaluated-version-formatted-v3"
V4 = ROOT / "profile-evaluated-version-a96-v4"
SOURCE = "a96d1b821d10ed3d9e99dd06c5141f9f242ae318"
TREE = "f96bebefbc1e7d8187efadb62f88d524cdd18451"
RECORDS = "/home/qian-qi/hepta-learn-037c-evidence/format-evaluated-version-v4"
KEY = "learn-037c-format-evaluated-version-v4"


def meta(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def write(name, data):
    path = OUT / name
    if path.exists():
        assert path.read_bytes() == data, "refuse to overwrite differing canonical: " + name
    else:
        path.write_bytes(data)


actual_manifest_bytes = (ACTUAL_V3 / "manifest.json").read_bytes()
assert meta(actual_manifest_bytes)["sha256"] == (
    "0fa8571788642ae6a6f3e2cec81788a8a014915a920b79c2f2ad75fa647823d2"
)
actual_manifest = json.loads(actual_manifest_bytes)
assert actual_manifest["returncode"] == 0 and actual_manifest["error"] is None
actual_rows = {row["path"]: row for row in actual_manifest["files"]}
assert len(actual_rows) == 40
replay_bytes = (V4 / "V4_FROM_ACTUAL_V3.json").read_bytes()
replay = json.loads(replay_bytes)
assert replay["status"] == "FROZEN_PREFMT_V4_ON_VERIFIED_ACTUAL_V3"
assert replay["source_commit"] == SOURCE and replay["source_tree"] == TREE
assert len(replay["files"]) == 12
assert all(row["exit_code"] == 0 for row in replay["strict_replay"])

rows = []
for entry in sorted(replay["files"], key=lambda row: row["path"]):
    path = entry["path"]
    before = (V4 / "work" / path).read_bytes()
    assert meta(before) == entry["postimage"]
    base_exists = entry["base_exists"]
    if base_exists:
        base = (V4 / "base-actual-v3" / path).read_bytes()
        assert base == (ACTUAL_V3 / "postimages" / path).read_bytes()
        assert meta(base) == actual_rows[path]["after"]
    else:
        assert path not in actual_rows
        assert path == "codex-rs/hepta-agentd/src/circuit_evaluated_version_progress_support_tests.rs"
        base = b""
    assert meta(base) == entry["base"]
    rows.append({
        "path": path,
        "base_exists": base_exists,
        "base": meta(base),
        "before": meta(before),
        "base_utf8": base.decode(),
        "before_utf8": before.decode(),
        "origin": {
            "ancestor_source_commit": SOURCE,
            "ancestor_source_tree": TREE,
            "base_kind": "verified actual V3 formatted postimage" if base_exists else "new V4 test helper",
            "base_actual_v3_manifest": meta(actual_manifest_bytes),
            "base_postimage_blob": meta(base)["blob"] if base_exists else None,
            "v4_replay_manifest": meta(replay_bytes),
        },
    })

paths = sorted(row["path"] for row in rows)
assert len(set(paths)) == len(paths) == 12
assert {p.as_posix() for p in Path(".").glob("THIS_PATH_MUST_NOT_EXIST")} == set()
input_manifest = {
    "state": "PREPARED_ONLY_NOT_SUBMITTED",
    "source_commit": SOURCE,
    "source_tree": TREE,
    "base_actual_v3_manifest": meta(actual_manifest_bytes),
    "prefmt_v4_replay_manifest": meta(replay_bytes),
    "files": [{key: value for key, value in row.items() if key not in {"base_utf8", "before_utf8"}}
              for row in rows],
    "counts": {
        "files": len(rows),
        "production": sum(not row["path"].endswith("_tests.rs") for row in rows),
        "fixtures": sum(row["path"].endswith("_tests.rs") for row in rows),
    },
    "claims": {
        "v3_actual_rustfmt": "exit 0, all 40 postimages independently verified",
        "v4_exact_base_patch_replay": "strict check and apply exit 0, all 12 postimages verified",
        "v4_rustfmt": "NOT_SUBMITTED",
        "native": "UNRUN",
        "ordinary_qualification": 0,
    },
}
source_binding = {
    "commit": SOURCE,
    "tree": TREE,
    "description": (
        "Exact a96 ancestor plus verified actual Version V3 40-file formatted overlay; "
        "this request formats only the V4 12-file dependency increment. The 11 existing "
        "base files are actual V3 postimages, not blobs claimed to exist in bare a96. "
        "No full materialized Git tree, compilation, or ordinary execution is claimed."
    ),
    "actual_v3_manifest": meta(actual_manifest_bytes),
    "actual_v3_postimage_gzip": meta((ACTUAL_V3 / "complete-postimages.json.gz").read_bytes()),
    "independent_v3_replay": meta((ROOT / "profile-evaluated-version-formatted-v3-audit/INDEPENDENT_VERIFICATION.json").read_bytes()),
    "v4_replay_manifest": meta(replay_bytes),
    "v4_dependency_patch": meta((V4 / "V4_FROM_ACTUAL_V3.patch").read_bytes()),
    "dependency_blocks_not_executed": [
        "candidate C14 actual formatted remote-read block",
        "candidate S12 actual formatted command block",
        "candidate C11 actual formatted command block",
        "Root actual Candidate block plus independent publication-progress consumer",
    ],
}
template_bytes = (V3_FORMAT / "format-driver.py").read_bytes()
assert meta(template_bytes)["sha256"] == "c9896a4dd81550b0670b4fb0d86182dbcb37905038c6397293e129936531a7ca"
provenance = {
    "original_driver_path": str(V3_FORMAT / "format-driver.py"),
    "original_driver": meta(template_bytes),
    "original_actual_manifest": meta(actual_manifest_bytes),
    "allowed_changes": [
        "records directory and artifact qualification labels",
        "exact 12 paths and file count",
        "exact payload hashes and input/source-binding data",
    ],
    "unchanged": [
        "single argv-chunk input transport and create-only record directory",
        "Rust 1.96 toolchain and exact Rustfmt binary SHA",
        "edition 2024, imports_granularity=Item, skip_children=true",
        "no checkout, Cargo, target, or native-test operations",
        "source ancestor commit and tree",
    ],
    "first_start_owner": "/root",
    "state": "NOT_SUBMITTED",
}
payload = {
    "source_commit": SOURCE,
    "source_tree": TREE,
    "source_binding": source_binding,
    "files": rows,
    "input_manifest": input_manifest,
    "format_method_provenance": provenance,
}
payload_bytes = json_bytes(payload)
compressed = gzip.compress(payload_bytes, mtime=0)
encoded = base64.b64encode(compressed).decode()
driver = template_bytes.decode()
replacements = {
    "format-evaluated-version-v3": "format-evaluated-version-v4",
    "evaluated-version-v3-prefmt.patch": "evaluated-version-v4-prefmt.patch",
    "combined-evaluated-version-v3.patch": "combined-evaluated-version-v4.patch",
    "isolated evaluated Version V3 formatting only; no native or ordinary qualification":
        "isolated evaluated Version V4 increment formatting only; no native or ordinary qualification",
    'assert len(payload["files"]) == 40': 'assert len(payload["files"]) == 12',
}
for old, new in replacements.items():
    assert old in driver, old
    driver = driver.replace(old, new)
driver, count = re.subn(r"^INPUT_GZIP_SHA256 = .*?$", "INPUT_GZIP_SHA256 = " + repr(meta(compressed)["sha256"]), driver, count=1, flags=re.M)
assert count == 1
driver, count = re.subn(r"^INPUT_JSON_SHA256 = .*?$", "INPUT_JSON_SHA256 = " + repr(meta(payload_bytes)["sha256"]), driver, count=1, flags=re.M)
assert count == 1
path_assignment = "EXPECTED_PATHS = {\n" + "".join("    " + repr(path) + ",\n" for path in paths) + "}"
driver, count = re.subn(r"^EXPECTED_PATHS = \{.*?^\}", path_assignment, driver, count=1, flags=re.M | re.S)
assert count == 1


def normalized_ast(source):
    parsed = ast.parse(source)

    class Normalize(ast.NodeTransformer):
        def visit_Assign(self, node):
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name in {"INPUT_GZIP_SHA256", "INPUT_JSON_SHA256", "RECORDS", "EXPECTED_PATHS"}:
                    node.value = ast.Constant(value="PER_REQUEST:" + name)
            return self.generic_visit(node)

        def visit_Assert(self, node):
            if ast.unparse(node.test) in {"len(payload['files']) == 40", "len(payload['files']) == 12"}:
                node.test = ast.Constant(value="EXACT_REQUEST_FILE_COUNT")
            return self.generic_visit(node)

        def visit_Constant(self, node):
            names = {
                "evaluated-version-v3-prefmt.patch": "PREFMT_PATCH",
                "evaluated-version-v4-prefmt.patch": "PREFMT_PATCH",
                "combined-evaluated-version-v3.patch": "COMBINED_PATCH",
                "combined-evaluated-version-v4.patch": "COMBINED_PATCH",
                "isolated evaluated Version V3 formatting only; no native or ordinary qualification": "FORMAT_ONLY_QUALIFICATION",
                "isolated evaluated Version V4 increment formatting only; no native or ordinary qualification": "FORMAT_ONLY_QUALIFICATION",
            }
            if isinstance(node.value, str) and node.value in names:
                node.value = names[node.value]
            return node

    return ast.dump(Normalize().visit(copy.deepcopy(parsed)), include_attributes=False)


original_ast = normalized_ast(template_bytes.decode())
current_ast = normalized_ast(driver)
assert current_ast == original_ast, "driver method changed outside exact allowed per-request fields"
chunks = [encoded[offset:offset + 32768] for offset in range(0, len(encoded), 32768)]
request = {
    "host": "desktop",
    "executable": "/usr/bin/python3",
    "args": ["-u", "-c", driver, *chunks],
    "cwd": "/home/qian-qi/hepta-learn-037c-evidence",
    "idempotency_key": KEY,
}
assert "".join(request["args"][3:]) == encoded
assert gzip.decompress(base64.b64decode("".join(request["args"][3:]), validate=True)) == payload_bytes
assert all(len(value.encode()) <= 32768 for value in request["args"])
argument_sizes = [len(request["executable"].encode()), *[len(value.encode()) for value in request["args"]]]
arg_bytes = sum(size + 1 for size in argument_sizes)
arg_max = os.sysconf("SC_ARG_MAX")
assert arg_bytes + 65536 < arg_max
request_bytes = json_bytes(request)
review = {
    "state": "NOT_SUBMITTED",
    "first_start_owner": "/root",
    "source_binding": source_binding,
    "records": RECORDS,
    "stable_key": KEY,
    "request": meta(request_bytes),
    "driver": meta(driver.encode()),
    "payload": meta(payload_bytes),
    "compressed": meta(compressed),
    "files": len(rows),
    "production": input_manifest["counts"]["production"],
    "fixtures": input_manifest["counts"]["fixtures"],
    "normalized_ast_equal_to_approved_actual_v3_driver": True,
    "normalized_ast_sha256": hashlib.sha256(current_ast.encode()).hexdigest(),
    "argument_sizes": argument_sizes,
    "argument_total_bytes_with_nuls": arg_bytes,
    "local_SC_ARG_MAX": arg_max,
    "reserved_environment_and_pointer_bytes": 65536,
    "remote_ARG_MAX": "not probed",
    "exact_base_after_payload_checked": True,
    "base64_join_exact": True,
    "create_only_records": True,
    "checkout_access": False,
    "target_access": False,
    "cargo_or_native_tests": False,
    "ordinary_qualification": 0,
}
for name, data in {
    "format-driver.py": driver.encode(),
    "input-payload.json": payload_bytes,
    "input-payload.json.gz": compressed,
    "input-manifest.json": json_bytes(input_manifest),
    "format-method-provenance.json": json_bytes(provenance),
    "h-pty-start-request.json": request_bytes,
    "REQUEST_REVIEW.json": json_bytes(review),
}.items():
    write(name, data)
print(json.dumps({key: review[key] for key in ["state", "records", "stable_key", "request", "driver", "payload", "compressed", "files", "production", "fixtures", "normalized_ast_equal_to_approved_actual_v3_driver", "argument_sizes", "argument_total_bytes_with_nuls"]}, indent=2))
