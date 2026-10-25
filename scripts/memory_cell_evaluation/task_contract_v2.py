"""Pinned source admission and cost declarations shared by local task drivers."""

import hashlib
import json
from pathlib import Path

from bounded_process import digest, save
from ruff_executor import inventory, unique_object
from runtime_profile import load_runtime

HERE = Path(__file__).resolve().parent
CODEC_SHA256 = "12077c2c7559b4ba9b8000b0bf437e420a33f283fc66eea4deacbf1023dba30a"


def codec_contract():
    raw = (HERE / "codec_contract_v2.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != CODEC_SHA256:
        raise ValueError("codec contract drift")
    return json.loads(raw)


def source_bytes(spec, fixture):
    if inventory(fixture) != spec["files"]:
        raise ValueError("original source inventory drift")
    source = {name: (fixture / name).read_bytes() for name in spec["files"]}
    if any(
        {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        != spec["files"][name]
        for name, data in source.items()
    ):
        raise ValueError("source changed while reading")
    return source


def replacements(raw, spec):
    if len(raw) > spec["limits"]["candidate_bytes"]:
        raise ValueError("candidate request limit; only bounded prefix retained")
    value = json.loads(raw, object_pairs_hook=unique_object)
    if (
        set(value) != {"schema", "files"}
        or value["schema"] != "hepta.memory-cell.implementation-candidate.v1"
        or not isinstance(value["files"], list)
    ):
        raise ValueError("candidate schema")
    result = {}
    for row in value["files"]:
        if (
            set(row) != {"path", "content"}
            or row["path"] not in spec["allowed_paths"]
            or row["path"] in result
            or not isinstance(row["content"], str)
        ):
            raise ValueError("candidate file outside allowed implementation scope")
        data = row["content"].encode("utf-8")
        if len(data) > spec["limits"]["content_bytes"] or b"\0" in data:
            raise ValueError("candidate content limit")
        result[row["path"]] = data
    return result


def materialize(destination, files):
    destination.mkdir()
    for name, data in files.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)


def export_inputs(fixture, output, runtime_profile=None, runtime_profile_sha256=None):
    spec = codec_contract()
    runtime = load_runtime(spec, CODEC_SHA256, runtime_profile, runtime_profile_sha256)
    source = source_bytes(spec, Path(fixture))
    output = Path(output)
    if output.resolve().is_relative_to(Path(fixture).resolve()) or Path(
        fixture
    ).resolve().is_relative_to(output.resolve()):
        raise ValueError("input export overlaps original fixture")
    output.mkdir(exist_ok=False)
    materialize(output / "source", source)
    save(
        output / "task.json",
        {
            "contract": spec,
            "contract_sha256": CODEC_SHA256,
            "runtime": runtime,
            "scope": "failing source only; no resolution, runner fix or gold",
            "source_snapshot": inventory(output / "source"),
        },
    )
    return {
        "task": spec["task_id"],
        "files": len(source),
        "bytes": sum(map(len, source.values())),
        "task_json": digest(output / "task.json"),
    }
