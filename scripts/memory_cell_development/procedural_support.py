"""Pinned historical fixtures and a shared, restricted procedural executor."""

import hashlib
import io
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import tarfile
import time


SCOPE = "ruff-procedural-development-20261025"
TARGET = "experiments/multimodal_output_portfolio/v4/counterfactual_audit.py"
OPERATIONS = {
    "ruff check --fix": ["--fix"],
    "ruff check --fix --unsafe-fixes": ["--fix", "--unsafe-fixes"],
}
TEMPLATES = [
    "For failure {entity}, return the recorded {relation}.",
    "Which {relation} was recorded for failure {entity}?",
    "Recall the {relation} for this failure: {entity}",
    "Failure: {entity}. Give its stored {relation}.",
]
FINAL = "According to incident memory, what repair command resolves failure {}?"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    data = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    with Path(path).open("xb") as stream:
        stream.write(data)
    return sha(data)


def command(argv, cwd, output, stdin=None, pythonpath=None):
    output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", RAYON_NUM_THREADS="1")
    if pythonpath is not None:
        env["PYTHONPATH"] = str(pythonpath)
    start, usage = time.perf_counter(), resource.getrusage(resource.RUSAGE_CHILDREN)
    with (
        (output / "stdout.log").open("wb") as out,
        (output / "stderr.log").open("wb") as err,
    ):
        proc = subprocess.Popen(
            argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=out, stderr=err
        )
        proc.communicate(stdin)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = dict(
        argv=argv,
        cwd=str(cwd),
        pid=proc.pid,
        returncode=proc.returncode,
        wall_seconds=time.perf_counter() - start,
        cpu_seconds=after.ru_utime + after.ru_stime - usage.ru_utime - usage.ru_stime,
        stdout_sha256=sha((output / "stdout.log").read_bytes()),
        stderr_sha256=sha((output / "stderr.log").read_bytes()),
    )
    save(output / "receipt.json", result)
    return result


def extract_fixture(repo, output, ruff):
    original = repo / "qa/memory-budget-20261024"
    manifest = json.loads((original / "evidence-manifest.json").read_text())
    parts = []
    for entry in manifest["archive"]["parts"]:
        data = (original / entry["path"]).read_bytes()
        assert len(data) == entry["bytes"] and sha(data) == entry["sha256"]
        parts.append(data)
    archive = b"".join(parts)
    assert sha(archive) == manifest["archive"]["sha256"]
    prefix = "memory-budget-evidence-20261024/"
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        protocol = json.load(tar.extractfile(prefix + "prepared-001/protocol.json"))
        assert (
            sha(ruff.read_bytes())
            == protocol["task_fixture_files"]["ruff-runtime/bin/ruff"]
        )
        files = {}
        for member in tar:
            start = prefix + "task-fixtures/lint-original/"
            if not member.name.startswith(start) or not member.isfile():
                continue
            relative = Path(member.name.removeprefix(start))
            assert not relative.is_absolute() and ".." not in relative.parts
            data = tar.extractfile(member).read()
            expected = protocol["task_fixture_files"][
                "task-fixtures/lint-original/" + str(relative)
            ]
            assert sha(data) == expected
            dest = output / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            files[str(relative)] = dict(bytes=len(data), sha256=expected)
    assert len(files) == 17
    return dict(
        archive_sha256=sha(archive),
        original_fixture_files=files,
        ruff_sha256=sha(ruff.read_bytes()),
        original_semantic_tests=76,
    )


def diagnostic(ruff, workspace, target, output):
    receipt = command(
        [str(ruff), "check", "--no-cache", "--output-format=json", target],
        workspace,
        output,
    )
    values = json.loads((output / "stdout.log").read_text())
    return receipt, sorted({row["code"] for row in values})


def execute(ruff, python, original, root, prediction):
    workspace = root / "workspace"
    shutil.copytree(original, workspace)
    check = [str(ruff), "check", "--no-cache", TARGET]
    before = command(check, workspace, root / "before")
    log = (root / "before/stdout.log").read_text()
    assert before["returncode"] != 0 and "F401" in log and "E731" in log
    operation = prediction.strip() if isinstance(prediction, str) else None
    action = None
    if operation in OPERATIONS:
        action = command(
            [str(ruff), "check", "--no-cache", *OPERATIONS[operation], TARGET],
            workspace,
            root / "action",
        )
    after = command(check, workspace, root / "after")
    semantic = None
    if after["returncode"] == 0:
        semantic = command(
            [
                str(python),
                "-B",
                "-m",
                "unittest",
                "discover",
                "-s",
                str(Path(TARGET).parent),
                "-v",
            ],
            workspace,
            root / "semantic",
        )
    passed = bool(
        action
        and action["returncode"] == 0
        and after["returncode"] == 0
        and semantic
        and semantic["returncode"] == 0
        and "Ran 76 tests" in (root / "semantic/stderr.log").read_text()
    )
    changed = {
        str(p.relative_to(workspace)): sha(p.read_bytes())
        for p in workspace.rglob("*.py")
        if p.read_bytes() != (original / p.relative_to(workspace)).read_bytes()
    }
    assert set(changed) <= {TARGET}
    result = dict(
        raw_prediction=prediction,
        admitted=action is not None,
        before=before,
        action=action,
        after=after,
        semantic=semantic,
        success=passed,
        changed_files=changed,
        independent_task_groups=1,
    )
    save(root / "result.json", result)
    return result
