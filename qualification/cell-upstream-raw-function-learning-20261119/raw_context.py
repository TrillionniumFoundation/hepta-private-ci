"""Bind the completed A diagnostic and unchanged, previously qualified trainer."""

import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
WORK = Path("/home/qian-qi/work/hepta-upstream-raw-function-learning-20261119-2e9b")
COLLECTION = Path(
    "/home/qian-qi/work/hepta-upstream-replacement-interface-20261119-2e9b"
)
LEGACY_WORK = Path(
    "/home/qian-qi/work/hepta-upstream-layout-learning-20261118-2e9b-checkpoint2"
)
LEGACY_SOURCE = (
    LEGACY_WORK / "source/qualification/cell-upstream-layout-learning-20261118"
)
OLD_CODE = Path("/home/qian-qi/work/hepta-e1-matched-info-20261118-2e9b/source")
ARTIFACT = Path("/dev/shm/hepta-cell-experiments-v3-20261116-0c078a")
FIT_ROOT = ARTIFACT / "research-upstream-raw-function-20261119-2e9b"
PARENT_PATH = Path(
    "/home/qian-qi/work/hepta-e2-current-credit-20261118-2e9b/retained/PARENT_MODEL.json"
)
PARENT_SHA = "4a9c82ab237a5d902db378d1987170c1608bdef40c5603731718f4202fff6c5d"
PYTHON = "/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a/venv/bin/python"
PROJECTS = (
    "python-attrs/attrs",
    "Textualize/rich",
    "tox-dev/platformdirs",
    "python-humanize/humanize",
)
FIXED = {
    "DEPLOYMENT.json": "bb22610ab20d26073206a6d37e3e6a3464cb38f2037bc7b9dcf52231445cec21",
    "prepared/PROTOCOL.json": "b195b818806bf1047589ef9d8b07057c63cc2f0f66de340a06a9c21a1fe7ac0b",
    "prepared/TASKS.json": "01a5591f223c5f1cc7a55735a04ccc4adadffc65c93dd54d32c82651b4623226",
    "prepared/BINDINGS.json": "e31e0b541cf37be504c4a045e3c0c46ad8052feebd0f0e1c908b1de5b3ea3266",
    "cpu-attempt-1/prepared/REFERENCES.json": "11cfb762522f3e50e2894ddf3aa49fba9c5360f5a01d0e829507527a871411eb",
    "cpu-attempt-1/cpu-controls-1/RESULT.json": "60c11251d7e7337d15f1a0c4d7ffa473fa50e0d0ec17293c3ccecd344bd36eb0",
    "analysis-1/READOUT.json": "a6d6ada131e98314f01a07b4929b99a70bcf1f65166043fce5d23ae7248a5fe0",
    "mechanism-1/MECHANISM.json": "5556d212c3729ac97525c40194613201257b5bd2b0300f26856177e08ed3c0d1",
}


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")


def require(value, message):
    if not value:
        raise ValueError(message)


def load(name, path, expected):
    path = Path(path)
    require(sha(path) == expected, "frozen source changed: " + str(path))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def originals():
    for relative, expected in FIXED.items():
        require(
            sha(COLLECTION / relative) == expected,
            "original A material changed: " + relative,
        )
    require(sha(PARENT_PATH) == PARENT_SHA, "actual parent manifest changed")
    deployment = read(COLLECTION / "DEPLOYMENT.json")
    for relative, expected in deployment["candidate_files"].items():
        require(
            sha(COLLECTION / "execution-source-2" / relative) == expected,
            "original interface source changed",
        )
    for path, expected in deployment["external_source_files"].items():
        require(sha(path) == expected, "original dependency source changed")
    codec = load(
        "raw_function_original_codec",
        COLLECTION / "execution-source-2/replacement_codec.py",
        deployment["candidate_files"]["replacement_codec.py"],
    )
    return (
        codec,
        read(PARENT_PATH),
        read(COLLECTION / "prepared/TASKS.json"),
        read(COLLECTION / "prepared/PROTOCOL.json"),
    )


def legacy():
    originals()
    sys.path.insert(0, str(OLD_CODE / "scripts"))
    sys.path.insert(0, str(LEGACY_SOURCE))
    module = importlib.import_module("layout_sft")
    require(
        Path(module.__file__).resolve() == (LEGACY_SOURCE / "layout_sft.py").resolve(),
        "wrong ancestral trainer imported",
    )
    require(
        sha(module.__file__)
        == "a3331738cf460f3e484d4d75c28fc78427b523bd27cbe5a2cbddfe792b282005",
        "ancestral numerical helper changed",
    )
    return module


def previous_engine_qualification():
    legacy()
    qualification = importlib.import_module("freeze_training")
    require(
        Path(qualification.__file__).resolve()
        == (LEGACY_SOURCE / "freeze_training.py").resolve(),
        "wrong prior engine qualification imported",
    )
    require(
        sha(qualification.__file__)
        == "d807fa70a2758b99157c7d98a50ee9be0d3b7d065f4c8fcb9e69fc6624a696d9",
        "prior engine qualification source changed",
    )
    return qualification.verify_admission()


def admitted():
    freeze = read(HERE / "prepared/PROTOCOL.json")
    for name, expected in freeze["candidate_files"].items():
        require(sha(HERE / name) == expected, "new candidate changed: " + name)
    for path, expected in freeze["original_input_files"].items():
        require(sha(path) == expected, "precommitted original input changed: " + path)
    require(
        previous_engine_qualification()
        == freeze["previous_engine_qualification_sha256"],
        "prior full 3584 engine evidence changed",
    )
    require(
        freeze["primary_arm"] == "native_feedback"
        and freeze["train_record_count"] == 4,
        "fixed scientific scope changed",
    )
    return freeze
