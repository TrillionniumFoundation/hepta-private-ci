"""Fixed paths and byte admission for the existing A-only experiment materials."""

import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
OLD_CODE = Path("/home/qian-qi/work/hepta-e1-matched-info-20261118-2e9b/source")
PREVIOUS = Path("/home/qian-qi/work/hepta-e2-current-credit-20261118-2e9b")
COLLECTION = Path("/home/qian-qi/work/hepta-upstream-current-policy-20261118-2e9b")
ARTIFACT = Path("/dev/shm/hepta-cell-experiments-v3-20261116-0c078a")
WORK = Path(
    "/home/qian-qi/work/hepta-upstream-layout-learning-20261118-2e9b-expandable"
)
FIT_ROOT = ARTIFACT / "research-upstream-layout-learning-20261118-2e9b-expandable"
PYTHON = "/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a/venv/bin/python"
PROJECTS = (
    "python-attrs/attrs",
    "Textualize/rich",
    "tox-dev/platformdirs",
    "python-humanize/humanize",
)
PARENT_PATH = PREVIOUS / "retained/PARENT_MODEL.json"
PARENT_FILE_SHA = "4a9c82ab237a5d902db378d1987170c1608bdef40c5603731718f4202fff6c5d"
NATIVE_SHA = "49cced4d3eb61ee86b1f55a11ca097be7618a0fc9b59e515f1b1d7676bec671c"
POLICY_SHA = "68546d87c57c152c3f82fe058821907b479cb2d78ce7725818d28fff09642a4e"
TASKS_SHA = "b30229f6fe886a0d23151b3e761592e3e11eeb333bdaf7e79c606eb6f85a08de"
PROTOCOL_SHA = "56071aea433cbf5e3b3c479e01ad39e3b025533030e6d4c57c68357163bdfc50"
sys.path.insert(0, str(OLD_CODE / "scripts"))
sys.path.insert(0, str(HERE))
data = importlib.import_module("cell_experiments.data")


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data.canonical(value) + b"\n")


def load(name, path, expected):
    if sha(path) != expected:
        raise ValueError("fixed source changed: " + str(path))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def originals():
    for path, expected in (
        (PARENT_PATH, PARENT_FILE_SHA),
        (COLLECTION / "prepared/TASKS.json", TASKS_SHA),
        (COLLECTION / "prepared/PROTOCOL.json", PROTOCOL_SHA),
    ):
        if sha(path) != expected:
            raise ValueError("original artifact changed: " + str(path))
    native = load(
        "native_sandbox", COLLECTION / "execution-code/native_sandbox.py", NATIVE_SHA
    )
    sys.modules["native_sandbox"] = native
    return (
        native,
        read(PARENT_PATH),
        read(COLLECTION / "prepared/TASKS.json"),
        read(COLLECTION / "prepared/PROTOCOL.json"),
    )
