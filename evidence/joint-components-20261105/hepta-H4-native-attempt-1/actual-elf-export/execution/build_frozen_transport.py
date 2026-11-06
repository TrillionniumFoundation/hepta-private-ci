"""Construct cloud-only exact compressed stdin from an already frozen H4 plan.

This builder never calls any remote tool or launches the resulting request.
"""
import argparse
import ast
import base64
import hashlib
import json
from pathlib import Path
import zlib
from transport_payload import decode_exact

ROOT = Path(__file__).resolve().parent
CODE = ROOT.parent / "h4-content-reference-draft/archive_reference.py"
CODE_SHA = "ce96de09dc981311753d37312c1b254751cce3b40c4f950f603303a523508425"
DECODER_SHA = "6160a7dc42e570ae51b49ae8c5f44fc59c4eba60b1333577a1c51c0ce4063b84"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def write_fresh(name, raw):
    path = ROOT / name
    with path.open("xb") as stream:
        stream.write(raw)
    return dict(path=str(path), bytes=len(raw), sha256=digest(raw))


def build(plan_path, expected_plan_sha256):
    code, plan_raw = CODE.read_bytes(), Path(plan_path).read_bytes()
    if digest(code) != CODE_SHA or digest(plan_raw) != expected_plan_sha256 or len(plan_raw) > 2 * 1024 * 1024:
        raise ValueError("exact approved code and bounded frozen plan required")
    plan = json.loads(plan_raw)
    if plan["phase"] != "H4" or plan["transport_budget_seconds"] != 900 or plan["native_reexecution"] is not False:
        raise ValueError("exact storage-only H4 plan required")
    files = [dict(name=name, bytes=len(raw), sha256=digest(raw), data_base64=base64.b64encode(raw).decode())
             for name, raw in [("archive_reference.py", code), ("H4-reference-export-plan.json", plan_raw)]]
    bundle = json.dumps(dict(files=files), sort_keys=True, separators=(",", ":")).encode()
    compressed = zlib.compress(bundle, level=6)
    payload = base64.b64encode(compressed).decode()
    parameters = (payload, len(compressed), digest(compressed), len(bundle), digest(bundle))
    if decode_exact(*parameters) != bundle:
        raise ValueError("actual complete compressed input roundtrip differs")
    decoder = (ROOT / "transport_payload.py").read_bytes()
    if digest(decoder) != DECODER_SHA:
        raise ValueError("reviewed bounded transport decoder changed")
    expected = {row["name"]: dict(bytes=row["bytes"], sha256=row["sha256"]) for row in files}
    script = decoder.decode() + "\nimport json,os,stat\nfrom pathlib import Path\n"
    script += "FROZEN_TRANSPORT = " + repr(parameters) + "\n"
    script += "EXPECTED = " + repr(expected) + "\n"
    script += '''bundle = decode_exact(*FROZEN_TRANSPORT)
document = json.loads(bundle)
if set(document) != {"files"} or len(document["files"]) != 2:
    raise ValueError("exact two-file transport bundle required")
verified = {}
for row in document["files"]:
    if set(row) != {"name","bytes","sha256","data_base64"} or row["name"] not in EXPECTED or row["name"] in verified:
        raise ValueError("unexpected or duplicate frozen input")
    if {key:row[key] for key in ("bytes","sha256")} != EXPECTED[row["name"]]:
        raise ValueError("frozen input metadata differs")
    raw = base64.b64decode(row["data_base64"], validate=True)
    if len(raw) != row["bytes"] or hashlib.sha256(raw).hexdigest() != row["sha256"]:
        raise ValueError("frozen input bytes differ after bounded decode")
    verified[row["name"]] = raw
if set(verified) != set(EXPECTED):
    raise ValueError("missing frozen input")
stage = Path("/home/qian-qi/work/hepta-h4-reference-export-inputs-20261105-93bfc-01")
if stage.parent.resolve(strict=True) != stage.parent:
    raise ValueError("canonical existing input parent required")
stage.mkdir(mode=0o700)
for name,raw in verified.items():
    path = stage / name
    with path.open("xb") as stream:
        if stream.write(raw) != len(raw):
            raise ValueError("short frozen input write")
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != len(raw):
            raise ValueError("regular exact frozen input required")
        actual = stream.read(len(raw)+1)
    if actual != raw or hashlib.sha256(actual).hexdigest() != EXPECTED[name]["sha256"]:
        raise ValueError("actual written frozen input changed")
for directory in (stage, stage.parent):
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
os.execv("/usr/bin/python3", ["/usr/bin/python3", "-B", str(stage / "archive_reference.py"), "export",
    "--plan", str(stage / "H4-reference-export-plan.json"),
    "--expected-plan-sha256", EXPECTED["H4-reference-export-plan.json"]["sha256"],
    "--expected-exporter-sha256", EXPECTED["archive_reference.py"]["sha256"]])
'''
    ast.parse(script)
    bootstrap = write_fresh("H4-reference-export-bootstrap.py", script.encode())
    request = dict(host="desktop", executable="/usr/bin/python3", args=["-B", "-"],
        cwd="/home/qian-qi/work", env={"PYTHONDONTWRITEBYTECODE":"1"}, stdin=script,
        timeout_seconds=900, idempotency_key="93bfc-hepta-h4-actual-reference-images-export-01")
    launch = write_fresh("H4-reference-export-frozen-launch-request.json", encoded(request))
    manifest = dict(schema="H4-exact-compressed-transport-inputs-v1", remote_dispatched=False,
        files=[dict(name=row["name"], bytes=row["bytes"], sha256=row["sha256"]) for row in files],
        decoded_bundle_bytes=len(bundle), decoded_bundle_sha256=digest(bundle),
        compressed_transport_bytes=len(compressed), compressed_transport_sha256=digest(compressed),
        encoding="base64 of one zlib stream; raw decoded bundle is exact JSON containing exact original input base64",
        decoder_max_raw_bytes=4*1024*1024, decoder_max_compressed_bytes=4*1024*1024,
        exact_roundtrip_verified=True, appended_or_truncated_or_second_stream_rejected=True,
        code_source_unchanged=True, original_plan_bytes_unchanged=True, bootstrap=bootstrap, launch=launch,
        original_native_budget_changed=False, postrun_transport_seconds=900,
        root_and_independent_actual_input_review_required=True)
    record = write_fresh("H4-reference-export-transport-manifest.json", encoded(manifest))
    print(json.dumps(record, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-sha256", required=True)
    args = parser.parse_args()
    build(args.plan, args.expected_plan_sha256)
