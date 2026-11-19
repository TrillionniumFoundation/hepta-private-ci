"""Synthetic receipt consistency controls; no model or candidate program runs."""

import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from audit import audit


SCRIPTS = Path(__file__).resolve().parents[1]


def raw_identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = encoded(value)
    path.write_bytes(raw)
    return raw_identity(raw)


def put_raw(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw_identity(raw)


def read(path):
    return json.loads(path.read_bytes())


def rebind_protocol(evidence):
    root = evidence / "run"
    pin = raw_identity((root / "protocol.json").read_bytes())
    freeze = read(root / "freeze.json")
    freeze["protocol"] = pin
    put(root / "freeze.json", freeze)
    summary = read(root / "summary.json")
    summary["protocol_sha256"] = pin["sha256"]
    put(root / "summary.json", summary)


def semantics(ids):
    return {
        "tests_run": len(ids),
        "unittest_success": True,
        "discovered": ids,
        "started": ids,
        "completed": ids,
        "outcomes": [{"id": name, "status": "success"} for name in ids],
        "synthetic_metadata_only": True,
    }


def fixture(evidence):
    """Build tiny metadata, preserving original 76/21 IDs and recipe thresholds."""
    source_root = "/synthetic-unavailable/checkout"
    original_run = "/synthetic-unavailable/evidence/run"
    run = evidence / "run"
    recipe_raw = (SCRIPTS / "memory_cell_solver/recipe.json").read_bytes()
    recipe = json.loads(recipe_raw)
    model_raw = (SCRIPTS / "memory_cell_solver/model_manifest.json").read_bytes()
    model = json.loads(model_raw)
    source_files = {
        "scripts/memory_cell_solver/recipe.json": raw_identity(recipe_raw),
        "scripts/memory_cell_solver/model_manifest.json": raw_identity(model_raw),
    }
    eval_sources = {}
    for name in ("test_ruff_executor.py", "test_codec_executor_v2.py"):
        pin = raw_identity(
            ("# synthetic metadata; no execution: " + name + "\n").encode()
        )
        source_files["scripts/memory_cell_evaluation/" + name] = pin
        eval_sources[name] = pin
    contracts, hashes, fixture_bytes = {}, {}, {}
    for task, filename in (
        ("ruff", "ruff_contract.json"),
        ("codec", "codec_contract_v2.json"),
    ):
        spec = read(SCRIPTS / "memory_cell_evaluation" / filename)
        data = {
            path: ("# synthetic unexecuted fixture: " + path + "\n").encode()
            for path in spec["files"]
        }
        target = spec["target"] if task == "ruff" else spec["workflow"]
        data[target] = b"old admitted source\n"
        spec["files"] = {path: raw_identity(raw) for path, raw in data.items()}
        raw = encoded(spec)
        pin = raw_identity(raw)
        source_files["scripts/memory_cell_evaluation/" + filename] = pin
        eval_sources[filename] = pin
        contracts[task], hashes[task], fixture_bytes[task] = spec, pin["sha256"], data
    expected = {
        "head": "1" * 40,
        "tree": "2" * 40,
        "files": source_files,
        "contracts": contracts,
        "contract_hashes": hashes,
        "model": model,
        "recipe_source_utf8": recipe_raw.decode(),
        "source_root": source_root,
        "format_argv": [
            "just",
            "fmt",
            "--base",
            "1823dc1dc82b3c4ad7d980d80863bbc763c36941",
        ],
    }
    evidence.mkdir(parents=True)
    put_raw(
        evidence / "source.txt",
        (expected["head"] + "\n" + expected["tree"] + "\n").encode(),
    )
    put(run / "source-before.json", source_files)
    put(run / "source-after.json", source_files)
    staged_model = put(run / "model-manifest.json", model)
    put(
        evidence / "model-acquisition.json",
        {"identity": model["file"], "model_calls": 0, "training_updates": 0},
    )
    protocol = copy.deepcopy(recipe)
    protocol.update(
        source_head=expected["head"],
        source_files=source_files,
        staged_model_manifest=staged_model,
        tasks={},
    )
    runtime_by_task, input_by_task = {}, {}
    for task in recipe["task_order"]:
        spec = contracts[task]
        directory = run / "tasks" / task
        logical = original_run + "/tasks/" + task
        for name, raw in fixture_bytes[task].items():
            put_raw(directory / "fixture" / name, raw)
        profile = {
            "schema": "hepta.memory-cell.runtime-profile.v1",
            "task_contract_sha256": hashes[task],
            "tools": spec["tools"],
        }
        profile_id = put(directory / "runtime-profile.json", profile)
        tools = {name: "/synthetic-tools/" + name for name in profile["tools"]}
        frozen_profile = {
            "path": logical + "/runtime-profile.json",
            "sha256": profile_id["sha256"],
            "tools": tools,
        }
        runtime = {
            "sha256": profile_id["sha256"],
            "tools": profile["tools"],
            "mode": "controller_supplied",
            "qualification_proven_by_profile_alone": False,
        }
        runtime_by_task[task] = runtime
        qualified = {
            "accepted": True,
            "tests_run": {"ruff": 9, "codec": 6}[task],
            "errors": 0,
            "failures": 0,
            "skips": 0,
        }
        if task == "ruff":
            qualified["runtime_profile_sha256"] = profile_id["sha256"]
        else:
            qualified.update(contract_sha256=hashes[task], runtime=runtime)
        qualification_id = put(
            directory / "qualification/qualification.json", qualified
        )
        harness = (
            "test_ruff_executor.py" if task == "ruff" else "test_codec_executor_v2.py"
        )
        argv = [
            tools["python"],
            "-B",
            source_root + "/scripts/memory_cell_evaluation/" + harness,
        ]
        flags = {
            "--fixture": logical + "/fixture",
            "--output": logical + "/qualification",
            "--runtime-profile": frozen_profile["path"],
            "--runtime-profile-sha256": frozen_profile["sha256"],
            "--known-fix": logical + "/known-fix.json",
            **{"--" + name: path for name, path in tools.items()},
        }
        for key, value in flags.items():
            argv.extend((key, value))
        command_id = put(
            directory / "qualification-command.json",
            {
                "argv": argv,
                "returncode": 0,
                "runtime_profile_sha256": profile_id["sha256"],
            },
        )
        allowed = [spec["target"]] if task == "ruff" else spec["allowed_paths"]
        inputs = {
            "task": {
                "id": task,
                "allowed_paths": allowed,
                "synthetic_metadata_only": True,
            },
            "files": {
                name: fixture_bytes[task][name].decode()
                if name in fixture_bytes[task]
                else None
                for name in allowed
            },
        }
        input_by_task[task] = inputs
        input_id = put(directory / "task-input.json", inputs)
        protocol["tasks"][task] = {
            "fixture": logical + "/fixture",
            "runtime_profile": frozen_profile,
            "qualification": {
                "path": logical + "/qualification/qualification.json",
                **qualification_id,
            },
            "qualification_command": {
                "path": logical + "/qualification-command.json",
                **command_id,
            },
            "input": {"path": logical + "/task-input.json", **input_id},
        }
        for arm in recipe["arms"]:
            put(directory / (arm + "-retrieval.json"), {"documents": []})
    protocol_id = put(run / "protocol.json", protocol)
    put(
        run / "freeze.json",
        {
            "protocol": protocol_id,
            "source_head": expected["head"],
            "model_calls_so_far": 0,
            "training_updates": 0,
        },
    )
    rows = []
    for task in recipe["task_order"]:
        spec = contracts[task]
        target = spec["target"] if task == "ruff" else spec["workflow"]
        original = input_by_task[task]["files"]
        proposed = dict(original)
        proposed[target] = original[target].replace("old", "new", 1)
        candidate = {
            "schema": "hepta.memory-cell.implementation-candidate.v1",
            "files": [{"path": target, "content": proposed[target]}],
        }
        candidate_raw = encoded(candidate)
        for arm in recipe["arms"]:
            name = task + "-" + arm
            trajectory = run / "trajectories" / name
            attempt_root = trajectory / "attempt-01"
            gate_root = attempt_root / "gate"
            generation = trajectory / "generation-01"
            put(generation / "query-start.json", {"synthetic_metadata_only": True})
            put(
                generation / "request.json",
                {
                    "prompt_token_ids": [1],
                    "messages": [
                        {"role": "system", "content": "Synthetic metadata; no model."},
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "task": input_by_task[task]["task"],
                                    "current_files": original,
                                    "retrieved_history": [],
                                }
                            ),
                        },
                    ],
                },
            )
            put(
                generation / "response.json",
                {
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "schema": "hepta.memory-cell.code-edits.v1",
                                        "edits": [
                                            {"path": target, "old": "old", "new": "new"}
                                        ],
                                    }
                                )
                            }
                        }
                    ],
                },
            )
            put_raw(attempt_root / "candidate.json", candidate_raw)
            put_raw(gate_root / "candidate.raw", candidate_raw)
            logical_gate = original_run + "/trajectories/" + name + "/attempt-01/gate"
            request = {
                "fixture": protocol["tasks"][task]["fixture"],
                "candidate": logical_gate.removesuffix("/gate") + "/candidate.json",
                "contract_sha256": hashes[task],
                "runtime": runtime_by_task[task],
                "executor_sources" if task == "ruff" else "source_code": eval_sources,
            }
            put(gate_root / "request.json", request)
            workspace = dict(fixture_bytes[task])
            workspace[target] = proposed[target].encode()
            if task == "ruff":
                judge = {
                    Path(path).name: raw
                    for path, raw in fixture_bytes[task].items()
                    if Path(path).name.startswith("test_")
                }
                roots = {
                    "baseline": fixture_bytes[task],
                    "workspace": workspace,
                    "judge": judge,
                }
            else:
                roots = {
                    profile + "/workspace": workspace for profile in spec["profiles"]
                }
            inventories = {
                source_root + "/scripts/memory_cell_evaluation": eval_sources,
                protocol["tasks"][task]["fixture"]: spec["files"],
            }
            for relative, contents in roots.items():
                for path, raw in contents.items():
                    put_raw(gate_root / relative / path, raw)
                inventories[logical_gate + "/" + relative] = {
                    path: raw_identity(raw) for path, raw in contents.items()
                }
            put(gate_root / "observed-inventories.json", inventories)
            gate = {"accepted": True, "synthetic_metadata_only": True}
            if task == "ruff":
                put(gate_root / "expected-inventories.json", inventories)
                gate["semantic"] = semantics(spec["test_ids"])
                put(
                    gate_root / "candidate-lint/process.json",
                    {"returncode": 0, "timeout": False},
                )
                put(gate_root / "candidate-lint/stdout", [])
            else:
                gate["profiles"] = {
                    "provisioned": {"semantic": semantics(spec["test_ids"])},
                    "missing_ffmpeg": {"missing_tool_refused": True},
                    "missing_ffprobe": {"missing_tool_refused": True},
                }
                for profile in ("missing_ffmpeg", "missing_ffprobe"):
                    put(
                        gate_root / profile / "execution/process.json",
                        {"returncode": 1, "timeout": False},
                    )
            gate_id = put(gate_root / "result.json", gate)
            attempt = {"number": 1, "accepted": True, "gate_result": gate_id}
            put(attempt_root / "attempt.json", attempt)
            local = {
                "accepted": True,
                "execution_valid": True,
                "model_queries_started": 1,
                "model_queries_returned": 1,
                "prompt_tokens": 1,
                "generated_tokens": 1,
                "training_updates": 0,
                "attempts": [attempt],
                "stop_reason": "first_actual_task_success",
                "synthetic_metadata_only": True,
            }
            local_id = put(trajectory / "result.json", local)
            rows.append(
                {
                    "task": task,
                    "arm": arm,
                    "accepted": True,
                    "execution_valid": True,
                    "result": local,
                    "result_file": local_id,
                    "process": {"returncode": 0, "timed_out": False},
                }
            )
    put(
        run / "summary.json",
        {
            "protocol_sha256": protocol_id["sha256"],
            "source_head": expected["head"],
            "source_unchanged": True,
            "rows": rows,
            "unexecuted_trajectories": [],
            "task_success": {
                arm: {"registered_total": 2, "correct": 2} for arm in recipe["arms"]
            },
            "recorded_model_calls_started": 4,
            "recorded_prompt_tokens": 4,
            "recorded_generated_tokens": 4,
            "synthetic_metadata_only": True,
        },
    )
    log_id = put_raw(
        evidence / "final-format.log",
        b"synthetic formatter metadata; no formatter executed\n",
    )
    put_raw(evidence / "post-test-format.patch", b"")
    put_raw(evidence / "final-worktree-status.txt", b"")
    put(
        evidence / "final-format-result.json",
        {
            "schema": "hepta.memory-cell.final-format.v1",
            "argv": expected["format_argv"],
            "command_returncode": 0,
            "log_returncode": 0,
            "log": log_id,
        },
    )
    return expected


def alias_qualification(evidence, expected, kind):
    """Only metadata: do not create or resolve a historical filesystem link."""
    protocol_path = evidence / "run/protocol.json"
    protocol = read(protocol_path)
    alias = "/synthetic-unavailable/venv/bin/python"
    for task in protocol["tasks"]:
        directory = evidence / "run/tasks" / task
        command_path = directory / "qualification-command.json"
        command = read(command_path)
        command["argv"][0] = alias
        pin = put(command_path, command)
        protocol["tasks"][task]["qualification_command"].update(pin)
    binding = {"argv0": alias, "resolved": "/synthetic-tools/python"}
    if kind == "registered-alias":
        expected["qualification_python"] = binding
    elif kind == "wrong-resolved":
        expected["qualification_python"] = {
            **binding,
            "resolved": "/synthetic-tools/different-python",
        }
    elif kind == "evidence-only":
        protocol["qualification_python"] = binding
    elif kind != "unregistered-alias":
        raise ValueError(kind)
    put(protocol_path, protocol)
    rebind_protocol(evidence)


def mismatch(evidence, kind):
    run = evidence / "run"
    if kind in (
        "qualification-bytes",
        "qualification-command",
        "qualification-runtime",
    ):
        task = "codec" if kind == "qualification-runtime" else "ruff"
        directory = run / "tasks" / task
        protocol = read(run / "protocol.json")
        if kind == "qualification-command":
            path = directory / "qualification-command.json"
            value = read(path)
            value["argv"][2] = (
                "/different-checkout/scripts/memory_cell_evaluation/test_ruff_executor.py"
            )
            pin = put(path, value)
            protocol["tasks"][task]["qualification_command"].update(pin)
        else:
            path = directory / "qualification/qualification.json"
            value = read(path)
            if kind == "qualification-runtime":
                value["runtime"]["sha256"] = "f" * 64
            else:
                value["runtime_profile_sha256"] = "f" * 64
            pin = put(path, value)
            if kind == "qualification-runtime":
                protocol["tasks"][task]["qualification"].update(pin)
        put(run / "protocol.json", protocol)
        rebind_protocol(evidence)
    elif kind == "recipe-budget":
        protocol = read(run / "protocol.json")
        protocol["generation"]["maximum_calls"] = 4
        put(run / "protocol.json", protocol)
        rebind_protocol(evidence)
    elif kind == "candidate-raw":
        path = run / "trajectories/ruff-no_history/attempt-01/gate/candidate.raw"
        path.write_bytes(path.read_bytes() + b"\n")
    elif kind in ("workspace-both-records", "codec-workspace"):
        codec = kind == "codec-workspace"
        task = "codec" if codec else "ruff"
        gate = run / ("trajectories/" + task + "-no_history/attempt-01/gate")
        request = read(gate / "request.json")
        logical_gate = request["candidate"].removesuffix("/candidate.json") + "/gate"
        original_contract = read(
            SCRIPTS
            / "memory_cell_evaluation"
            / ("codec_contract_v2.json" if codec else "ruff_contract.json")
        )
        target = original_contract["workflow"] if codec else original_contract["target"]
        relative = "provisioned/workspace" if codec else "workspace"
        pin = put_raw(gate / relative / target, b"a different gate candidate\n")
        for name in (
            ("observed-inventories.json",)
            if codec
            else ("expected-inventories.json", "observed-inventories.json")
        ):
            value = read(gate / name)
            value[logical_gate + "/" + relative][target] = pin
            put(gate / name, value)
    elif kind == "unbound-success":
        trajectory = run / "trajectories/ruff-no_history"
        previous, current = trajectory / "attempt-01", trajectory / "attempt-02"
        shutil.copytree(previous, current)
        gate = current / "gate"
        request = read(gate / "request.json")
        old_gate = request["candidate"].removesuffix("/candidate.json") + "/gate"
        new_gate = old_gate.replace("/attempt-01/", "/attempt-02/")
        request["candidate"] = new_gate.removesuffix("/gate") + "/candidate.json"
        put(gate / "request.json", request)
        for name in ("expected-inventories.json", "observed-inventories.json"):
            value = read(gate / name)
            put(
                gate / name,
                {key.replace(old_gate, new_gate): item for key, item in value.items()},
            )
        attempt = read(current / "attempt.json")
        attempt["number"] = 2
        put(current / "attempt.json", attempt)
        local = read(trajectory / "result.json")
        local["attempts"] = [attempt]
        pin = put(trajectory / "result.json", local)
        summary = read(run / "summary.json")
        row = next(
            item
            for item in summary["rows"]
            if item["task"] == "ruff" and item["arm"] == "no_history"
        )
        row["result"], row["result_file"] = local, pin
        put(run / "summary.json", summary)
    elif kind == "format-missing":
        (evidence / "final-format-result.json").unlink()
    elif kind == "format-exit":
        path = evidence / "final-format-result.json"
        value = read(path)
        value["command_returncode"] = 1
        put(path, value)
    elif kind == "format-log":
        (evidence / "final-format.log").write_bytes(b"changed log\n")
    else:
        raise ValueError(kind)


class ReceiptBindingTests(unittest.TestCase):
    def test_consistent_synthetic_receipts_do_not_claim_model_attestation(self):
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Path(temporary) / "evidence"
            expected = fixture(evidence)
            result = audit(evidence, expected)
            self.assertTrue(result["accepted"], result["checks"])
            self.assertEqual(result["audit_status"], "CONSISTENT")
            self.assertFalse(result["production_accepted"])
            self.assertFalse(result["strong_rag_qualified"])
            self.assertFalse(result["historical_results_recertified"])
            self.assertEqual(result["model_queries_run_by_auditor"], 0)
            self.assertEqual(result["training_updates_by_auditor"], 0)

    def check_mismatches(self, kinds):
        for kind in kinds:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                evidence = Path(temporary) / "evidence"
                expected = fixture(evidence)
                mismatch(evidence, kind)
                result = audit(evidence, expected)
                self.assertFalse(result["accepted"], kind)
                self.assertEqual(
                    result["audit_status"], "HOLD_INCOMPLETE_OR_INCONSISTENT"
                )
                self.assertEqual(result["model_queries_run_by_auditor"], 0)

    def test_frozen_qualification_bytes_command_and_runtime_must_match(self):
        self.check_mismatches(
            ("qualification-bytes", "qualification-command", "qualification-runtime")
        )
        for kind in (
            "registered-alias",
            "unregistered-alias",
            "wrong-resolved",
            "evidence-only",
        ):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                evidence = Path(temporary) / "evidence"
                expected = fixture(evidence)
                alias_qualification(evidence, expected, kind)
                result = audit(evidence, expected)
                self.assertEqual(result["accepted"], kind == "registered-alias")
                self.assertEqual(result["model_queries_run_by_auditor"], 0)

    def test_evidence_cannot_raise_independently_pinned_generation_budget(self):
        self.check_mismatches(("recipe-budget",))
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Path(temporary) / "evidence"
            expected = fixture(evidence)
            del expected["recipe_source_utf8"]
            self.assertFalse(audit(evidence, expected)["accepted"])

    def test_model_candidate_must_match_gate_bytes_and_derived_inventories(self):
        self.check_mismatches(
            (
                "candidate-raw",
                "workspace-both-records",
                "codec-workspace",
                "unbound-success",
            )
        )

    def test_missing_or_failed_formatter_and_changed_log_cannot_pass(self):
        self.check_mismatches(("format-missing", "format-exit", "format-log"))


if __name__ == "__main__":
    unittest.main()
