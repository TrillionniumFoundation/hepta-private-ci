"""Fetch only already-public pinned inputs. Never execute the submitted cloud payload."""
import ast
import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import time
import urllib.request
import zipfile

from static_support import sha, write_bytes, write_json

HERE = Path(__file__).resolve().parent


def fetch(item):
    repo = "TrillionniumFoundation/hepta-private-ci"
    url = "https://raw.githubusercontent.com/" + repo + "/" + item["commit"] + "/" + item["path"]
    request = urllib.request.Request(url, headers={"User-Agent": "hepta-public-sender40-research"})
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.geturl() != url:
            raise ValueError("input redirect is outside the frozen public URL")
        raw = response.read(item["bytes"] + 1)
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if len(raw) != item["bytes"] or sha(raw) != item["sha256"] or blob != item["git_blob"]:
        raise ValueError("public input bytes do not match all commitments")
    return raw


def members(raw, expected):
    archive = zipfile.ZipFile(io.BytesIO(raw))
    names = archive.namelist()
    if len(names) != len(set(names)) or set(names) != set(expected):
        raise ValueError("ZIP directory differs from its complete allowlist")
    for item in archive.infolist():
        path = Path(item.filename)
        if path.is_absolute() or ".." in path.parts or item.is_dir() or item.file_size > 262144:
            raise ValueError("unsafe bounded archive member")
    return archive


def main():
    start = time.monotonic()
    destination = Path(sys.argv[1]).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((HERE / "public_inputs.json").read_text())
    public = {}
    receipts = []
    for item in manifest["inputs"]:
        spec = dict(item, commit=manifest["source_commit"])
        raw = fetch(spec)
        public[Path(item["path"]).name] = raw
        receipts.append(dict(path=item["path"], bytes=len(raw), sha256=sha(raw), git_blob=item["git_blob"]))
    contract = fetch(manifest["data_contract"])
    erratum = json.loads(contract)["source_integrity_erratum"]
    if (erratum["excluded_actor_emotion"] != [[7, 3]] or
            erratum["expected_queries"] != dict(train=80, dev=32, retain=28, test=48)):
        raise ValueError("public acquisition erratum is outside the frozen quality scope")
    write_bytes(destination / "data_contract.json", contract)
    receipts.append(dict(manifest["data_contract"], source_integrity_verified=True))
    outer = members(public["t4_payload.zip"], {"t4_submitted.py"})
    submitted = outer.read("t4_submitted.py")
    if sha(submitted) != manifest["payload_script"]["sha256"]:
        raise ValueError("submitted script identity")
    constants = [n.value for n in ast.walk(ast.parse(submitted)) if isinstance(n, ast.Constant) and isinstance(n.value, bytes)]
    if len(constants) != 1:
        raise ValueError("exactly one static bytes payload required")
    inner = base64.b64decode(constants[0], validate=True)
    if sha(inner) != manifest["inner_zip_sha256"]:
        raise ValueError("inner payload identity")
    listing = {item["path"]: item for item in manifest["payload_members"]}
    archive = members(inner, listing)
    source = destination / "source"
    for name, item in listing.items():
        if name == "data/test.npz":
            continue
        raw = archive.read(name)
        if len(raw) != item["bytes"] or sha(raw) != item["sha256"]:
            raise ValueError("payload member identity: " + name)
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        write_bytes(target, raw)
    checkpoint = manifest["checkpoint"]
    with zipfile.ZipFile(io.BytesIO(public["selected_checkpoints.zip"])) as saved:
        if len(saved.namelist()) != len(set(saved.namelist())):
            raise ValueError("duplicate checkpoint archive member")
        raw = saved.read(checkpoint["archive_member"])
        seal = saved.read(checkpoint["seal_member"])
    if len(raw) != checkpoint["bytes"] or sha(raw) != checkpoint["sha256"] or sha(seal) != checkpoint["seal_sha256"]:
        raise ValueError("checkpoint/seal identity")
    if json.loads(seal)["centered_47"] != sha(raw):
        raise ValueError("original selected checkpoint seal")
    write_bytes(destination / "parent.pt", raw)
    history = json.loads(public["lowlevel_results.json"])
    fit = next(row for row in history["rows"] if row["mode"] == "fit" and row["arm"] == "centered" and row["seed"] == 47)
    evaluation = next(row for row in history["rows"] if row["mode"] == "eval" and row["arm"] == "centered" and row["seed"] == 47)
    if fit["checkpoint"] != checkpoint["sha256"]:
        raise ValueError("historical parent identity")
    write_json(destination / "golden_retain.json", evaluation["retain"])
    golden = (destination / "golden_retain.json").read_bytes()
    if sha(golden) != manifest["golden_retain_export"]["sha256"] or len(golden) != manifest["golden_retain_export"]["bytes"]:
        raise ValueError("deterministic historical retained witness identity")
    write_json(destination / "PREPARED.json", dict(schema="hepta.sender40-public-prepared.v1",
               input_manifest_sha256=sha((HERE / "public_inputs.json").read_bytes()), inputs=receipts,
               golden_retain_sha256=sha(golden),
               parent_sha256=sha(raw), historical_test_fields_used=False, test_npz_extracted=False,
               submitted_script_executed=False, model_calls=0, seconds=time.monotonic() - start))


if __name__ == "__main__":
    report = Path(sys.argv[2])
    try:
        main()
    except BaseException as error:
        write_json(report, dict(status="ABORTED_BEFORE_MODEL", error=repr(error),
                   model_calls=0, candidate_fits=0, retries=0, partial_inputs_may_exist=True))
        raise
    else:
        write_json(report, dict(status="PREPARED", model_calls=0, candidate_fits=0, retries=0))
