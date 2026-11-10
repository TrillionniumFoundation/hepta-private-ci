"""Reconstruct one pinned native publication input; never invoke GitHub."""

import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys


ROOT = Path("/Users/qianqi/hepta-hcsn-math-closure-20261108-v1/publication-v2")
ARCHIVE = Path("/Users/qianqi/hepta-hcsn-math-closure-20261108-v1/evidence/localization-v2-interface-001/interface-001-evidence.zip")
ARCHIVE_SHA = "f32b15255a0a5cfa083d2db3b020b60d3945aeed3ca851da6f4fe8c0b4077fd0"
ARCHIVE_BYTES = 4103593


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def create_or_verify(path, raw):
    if path.is_symlink():
        raise RuntimeError("refuse a symlink output")
    if path.exists():
        if not path.is_file() or path.read_bytes() != raw:
            raise RuntimeError("existing native input differs: " + path.name)
        return "existing_identical"
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return "created"


if len(sys.argv) != 3 or any(re.fullmatch("[0-9a-f]{64}", value) is None for value in sys.argv[1:]):
    raise RuntimeError("requires the reviewed transport-file SHA and complete-plan SHA")
expected_transport, expected_plan = sys.argv[1:]
raw_transport = sys.stdin.buffer.read(1048577)
if len(raw_transport) > 1048576 or sha(raw_transport) != expected_transport:
    raise RuntimeError("stdin differs from the reviewed bounded transport file")
transport = json.loads(raw_transport)
compressed = base64.b64decode(transport["gzip_base64"], validate=True)
if len(compressed) != transport["bytes"] or sha(compressed) != transport["sha256"]:
    raise RuntimeError("compressed transport identity mismatch")
with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
    envelope_bytes = stream.read(24 * 1024 * 1024 + 1)
if len(envelope_bytes) > 24 * 1024 * 1024:
    raise RuntimeError("transport expands beyond the declared reconstruction limit")
envelope = json.loads(envelope_bytes)
if (envelope["schema"] != "hcsn-native-followup-transport-v1"
        or envelope["native_root"] != str(ROOT) or envelope["plan_sha256"] != expected_plan):
    raise RuntimeError("unreviewed native destination or plan")
external = envelope["external_files"]
if (len(external) != 1 or external[0]["native_file"] != str(ARCHIVE)
        or external[0]["bytes"] != ARCHIVE_BYTES or external[0]["sha256"] != ARCHIVE_SHA
        or external[0]["path"] != "qualification/hcsn_differentiable/evidence/localization-v2-20261108/interfaces/interface-001-evidence.zip"):
    raise RuntimeError("unreviewed external file")
if ARCHIVE.is_symlink() or not ARCHIVE.is_file():
    raise RuntimeError("external archive must be the expected native regular file")
archive = ARCHIVE.read_bytes()
if len(archive) != ARCHIVE_BYTES or sha(archive) != ARCHIVE_SHA:
    raise RuntimeError("already transferred native archive changed")

plan = envelope["plan_without_external_base64"]
filled = 0
for stage in plan["stages"]:
    for item in stage["files"]:
        if item["path"] == external[0]["path"]:
            if "base64" in item or item["sha256"] != ARCHIVE_SHA:
                raise RuntimeError("external plan member is not the reviewed placeholder")
            item["base64"] = base64.b64encode(archive).decode()
            filled += 1
if filled != 1:
    raise RuntimeError("external archive must fill exactly one plan member")
raw_plan = encoded(plan)
if sha(raw_plan) != expected_plan:
    raise RuntimeError("complete native plan bytes differ from the reviewed local plan")
helper = base64.b64decode(envelope["helper_base64"], validate=True)
wrapper = base64.b64decode(envelope["wrapper_base64"], validate=True)
if sha(helper) != envelope["helper_sha256"] or sha(wrapper) != envelope["wrapper_sha256"]:
    raise RuntimeError("helper or wrapper identity mismatch")
if helper.count(('EXPECTED_PLAN_SHA256 = "' + expected_plan + '"').encode()) != 1:
    raise RuntimeError("helper does not pin the reviewed complete plan")

if ROOT.is_symlink():
    raise RuntimeError("native destination cannot be a symlink")
ROOT.mkdir(exist_ok=True)
outputs = {"plan.json": raw_plan, "native_publish_inline_tree.py": helper,
           "retry_native_transport_inline_tree.py": wrapper}
for name, raw in outputs.items():
    create_or_verify(ROOT / name, raw)
receipt = {"schema": "hcsn-native-followup-reconstruction-v1", "status": "verified_inputs_only",
           "transport_file_sha256": expected_transport, "complete_plan_sha256": expected_plan,
           "files": {name: {"sha256": sha(raw), "bytes": len(raw)} for name, raw in outputs.items()},
           "external_archive": {"path": str(ARCHIVE), "bytes": len(archive), "sha256": sha(archive)},
           "github_calls": 0, "existing_inputs_overwritten": False}
create_or_verify(ROOT / "transport-reconstruction.json", encoded(receipt))
directory_fd = os.open(str(ROOT), os.O_RDONLY)
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
print(json.dumps(receipt, sort_keys=True), flush=True)
