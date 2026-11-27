"""Restore pinned failing sources and expose only task inputs to the solver."""

import inspect
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

from edit_protocol import canonical, sha
from solver_common import file_identity, save


REPO = Path(__file__).resolve().parents[2]
EVALUATION = REPO / "scripts/memory_cell_evaluation"
sys.path.insert(0, str(EVALUATION))
sys.path.insert(0, str(REPO / "scripts/memory_cell_budget"))


def task_contract(task):
    if task == "ruff":
        from ruff_executor import CONTRACT_SHA256, contract

        return contract(), CONTRACT_SHA256
    if task == "codec":
        from task_contract_v2 import CODEC_SHA256, codec_contract

        return codec_contract(), CODEC_SHA256
    raise ValueError("unregistered task")


def restore(repo, task, output):
    spec, contract_sha = task_contract(task)
    commit = spec.get("failing_commit", spec.get("source_commit"))
    if not commit:
        raise ValueError("task must name its original failing commit")
    output = Path(output)
    output.mkdir(exist_ok=False)
    for name, expected in spec["files"].items():
        raw = subprocess.check_output(["git", "show", f"{commit}:{name}"], cwd=repo)
        if {"bytes": len(raw), "sha256": sha(raw)} != expected:
            raise ValueError("historical source pin mismatch: " + name)
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return {"commit": commit, "contract_sha256": contract_sha, "files": spec["files"]}


def runtime_profile(task, tools, output):
    spec, contract_sha = task_contract(task)
    selected = {name: str(Path(tools[name]).resolve()) for name in spec["tools"]}
    value = {
        "schema": "hepta.memory-cell.runtime-profile.v1",
        "task_contract_sha256": contract_sha,
        "tools": {name: file_identity(path) for name, path in selected.items()},
    }
    save(output, value)
    return {
        "path": str(output),
        "sha256": file_identity(output)["sha256"],
        "tools": selected,
    }


def describe(task, fixture):
    spec, contract_sha = task_contract(task)
    allowed = [spec["target"]] if task == "ruff" else spec["allowed_paths"]
    files = {
        p: (Path(fixture) / p).read_text() if (Path(fixture) / p).exists() else None
        for p in allowed
    }
    if task == "ruff":
        instruction = (
            "Repair the original F401 unused-import and E731 lambda-assignment "
            "diagnostics in the admitted implementation. Keep all 76 original "
            "semantic tests passing; no lint suppressions or test edits."
        )
    else:
        instruction = (
            "The original workflow reports success when ffmpeg or ffprobe is "
            "missing and all 21 media tests are skipped. Make its selected test "
            "entrypoint fail when required tools or actual test outcomes are "
            "missing, and pass all 21 original tests when tools are present. "
            "Only the selected run line may change in the workflow. It may "
            "invoke the explicitly allowed new Python runner. The runner must "
            "discover the original test_*media*.py modules in "
            "qualification/ndu-dmgp-shadow and preserve failure/skip status."
        )
    return {
        "id": task,
        "source_commit": spec.get("failing_commit", spec.get("source_commit")),
        "contract_sha256": contract_sha,
        "instruction": instruction,
        "allowed_paths": allowed,
        "original_test_count": len(spec["test_ids"]),
        "original_command": spec.get("original_command"),
        "runner_command": spec.get("runner_command"),
        "input_is_exposed_development_case": True,
    }, files


def evaluate(task, fixture, candidate, output, profile):
    options = {
        "runtime_profile": profile["path"],
        "runtime_profile_sha256": profile["sha256"],
    }
    if task == "ruff":
        from ruff_executor import evaluate as gate
    else:
        from codec_executor_v2 import evaluate as gate
    return gate(fixture, candidate, output, **profile["tools"], **options)


def feedback(result, gate_directory):
    """Bounded actual diagnostic summaries; never cut serialized JSON in half."""
    directory = Path(gate_directory)
    value = {
        "accepted": result.get("accepted"),
        "status": result.get("status"),
        "summary_policy": "at most6 lint diagnostics,3 failure/missing IDs; stderr excerpts explicit",
        "error": str(result.get("error") or "")[:240],
    }

    def semantic(report, required):
        report = report or {}
        outcomes = report.get("outcomes", [])
        failed = [row for row in outcomes if row.get("status") != "success"]
        missing = sorted(set(required) - set(report.get("completed", [])))
        return {
            "tests_run": report.get("tests_run"),
            "required_count": len(required),
            "missing_ids": [name[:160] for name in missing[:3]],
            "missing_count": len(missing),
            "failure_count": len(failed),
            "failure_ids_omitted": max(0, len(failed) - 3),
            "failures": [
                {"id": str(row.get("id"))[:160], "status": row.get("status")}
                for row in failed[:3]
            ],
        }

    def stderr(path):
        if not path.is_file() or path.is_symlink():
            return {"available": False}
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - 300))
            raw = stream.read(300)
        return {
            "tail": raw.decode(errors="replace"),
            "excerpt": path.stat().st_size > len(raw),
        }

    if result.get("profiles"):
        required = task_contract("codec")[0]["test_ids"]
        value["profiles"] = {
            name: {
                "passed": row.get("passed"),
                **semantic(row.get("semantic"), required),
                "stderr": stderr(directory / name / "execution/stderr"),
            }
            for name, row in result["profiles"].items()
        }
    else:
        path = directory / "candidate-lint/stdout"
        if path.is_file() and not path.is_symlink():
            try:
                with path.open("rb") as stream:
                    raw = stream.read(262145)
                if len(raw) > 262144:
                    raise ValueError("diagnostics exceed feedback read cap")
                diagnostics = json.loads(raw)
                value["candidate_lint"] = [
                    {
                        "code": row.get("code"),
                        "message": str(row.get("message"))[:220],
                        "location": row.get("location"),
                    }
                    for row in diagnostics[:6]
                ]
                value["lint_diagnostics_omitted"] = max(0, len(diagnostics) - 6)
            except (ValueError, TypeError) as error:
                value["candidate_lint_read_error"] = str(error)[:200]
        value["semantic"] = semantic(
            result.get("semantic"), task_contract("ruff")[0]["test_ids"]
        )
        value["stderr"] = stderr(
            directory
            / (
                "semantic-process/stderr"
                if result.get("semantic")
                else "candidate-lint/stderr"
            )
        )
    # Valid bounded JSON remains useful even for abnormal very long test IDs.
    encoded = canonical(value).decode()
    if len(encoded.encode()) > 6000:
        for row in value.get("profiles", {}).values():
            row.pop("stderr", None)
            row["missing_ids"] = []
            row["failures"] = []
            row["details_omitted_for_total_byte_cap"] = True
        value.pop("stderr", None)
        value["details_omitted_for_total_byte_cap"] = True
        encoded = canonical(value).decode()
    if len(encoded.encode()) > 6000:
        return canonical(
            {
                "accepted": result.get("accepted"),
                "status": result.get("status"),
                "feedback_error": "abnormal diagnostic structure exceeds fixed byte cap",
            }
        ).decode()
    return encoded


def retrieval_corpus(output):
    """Use earlier teaching observations and general Python implementation text."""
    source = REPO / "qa/memory-development-20261025/protocol.json"
    old = json.loads(source.read_text())
    documents = []
    for i, fact in enumerate(old["facts"]):
        text = canonical(
            {k: fact[k] for k in ("entity", "relation", "value", "source_digest")}
        ).decode()
        documents.append(
            {
                "doc_id": f"observed-ruff-{i}",
                "group_id": "prior-ruff-teaching",
                "path": "teaching/ruff-diagnostic",
                "text": text,
                "origin": str(source.relative_to(REPO)),
                "available_at": "2026-10-25T10:29:22Z",
                "source_sha256": sha(text.encode()),
            }
        )
    targets = [
        unittest.TestResult.wasSuccessful,
        unittest.TestResult.addSkip,
        unittest.TestResult.startTest,
        unittest.TestLoader.discover,
        shutil.which,
    ]
    pins = []
    for target in targets:
        text = inspect.getsource(target)
        path = Path(inspect.getsourcefile(target)).resolve()
        name = target.__module__ + "." + target.__qualname__
        documents.append(
            {
                "doc_id": name,
                "group_id": "python-stdlib",
                "path": name.replace(".", "/"),
                "text": text,
                "origin": "installed-standard-library:" + name,
                "available_at": "2026-10-25T00:00:00Z",
                "source_sha256": sha(text.encode()),
            }
        )
        pins.append(
            {
                "name": name,
                "source_file": str(path),
                "file": file_identity(path),
                "selected_text_sha256": sha(text.encode()),
            }
        )
    save(
        output,
        {
            "documents": documents,
            "stdlib_sources": pins,
            "prior_teaching_protocol": file_identity(source),
            "known_task_repair_code_included": False,
            "availability_note": "Already exposed development inputs; dates are corpus cut labels, not prospective evidence.",
        },
    )
    return documents
