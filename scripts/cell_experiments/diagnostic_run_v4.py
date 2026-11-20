"""Fixed-graph new-task diagnostics; retained provider runs in a separate process."""

import argparse
from dataclasses import asdict
import hashlib
import os
from pathlib import Path
import select
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cell_experiments import data, repo_execution
from cell_experiments.coding_sft import write_new
from cell_experiments.online_v4.circuit_contract import Budget, CellSpec, Graph
from cell_experiments.online_v4.circuit_runtime import run_graph

LIMIT = 262144


def file_hash(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            value.update(block)
    return value.hexdigest()


class ProviderProcess:
    """Bounded Linux pipe protocol; only this owned child can be terminated."""

    def __init__(self, command, directory, timeout=300):
        self.directory, self.timeout = Path(directory), timeout
        self.stderr = (self.directory / "PROVIDER_STDERR.log").open("xb")
        self.stdout_raw = (self.directory / "PROVIDER_STDOUT.bin").open("xb")
        self.wire = (self.directory / "PROVIDER_PROTOCOL.jsonl").open("xb")
        self.buffer, self.sequence, self.outputs, self.dispatched = b"", 0, [], 0
        self.started = time.perf_counter()
        self.child = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr,
            bufsize=0,
        )

    def record(self, direction, value):
        self.wire.write(
            data.canonical({"direction": direction, "value": value}) + b"\n"
        )
        self.wire.flush()
        os.fsync(self.wire.fileno())

    def read(self):
        deadline = time.monotonic() + self.timeout
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            if (
                remaining <= 0
                or not select.select([self.child.stdout], [], [], remaining)[0]
            ):
                raise TimeoutError("owned provider response deadline exceeded")
            raw = os.read(
                self.child.stdout.fileno(), min(65536, LIMIT + 1 - len(self.buffer))
            )
            if not raw:
                raise ValueError("provider exited before a complete response")
            self.retain_stdout(raw)
            self.buffer += raw
            if len(self.buffer) > LIMIT and b"\n" not in self.buffer:
                raise ValueError("provider response exceeds bound")
        raw, self.buffer = self.buffer.split(b"\n", 1)
        if len(raw) + 1 > LIMIT:
            raise ValueError("provider response exceeds bound")
        value = data._parse(raw)
        self.record("received", value)
        if not isinstance(value, dict):
            raise ValueError("provider response must be an object")
        return value

    def retain_stdout(self, raw):
        self.stdout_raw.write(raw)
        self.stdout_raw.flush()
        os.fsync(self.stdout_raw.fileno())

    def require_eof(self):
        if self.child.poll() is None:
            raise ValueError("provider must exit before checking trailing stdout")
        raw = self.child.stdout.read(LIMIT + 1)
        if raw:
            self.retain_stdout(raw)
        if self.buffer or raw:
            raise ValueError("provider emitted data after close")

    def call(self, operation, **fields):
        self.sequence += 1
        message = {"op": operation, "id": self.sequence, **fields}
        raw = data.canonical(message) + b"\n"
        if len(raw) > LIMIT:
            raise ValueError("provider request exceeds bound")
        self.record("sent", message)
        pending = memoryview(raw)
        while pending:
            written = self.child.stdin.write(pending)
            if not written:
                raise BrokenPipeError("provider stdin closed during request")
            pending = pending[written:]
        self.child.stdin.flush()
        self.dispatched += operation == "generate"
        result = self.read()
        expected = "OUTPUT" if operation == "generate" else "CLOSED"
        if result.get("id") != self.sequence or result.get("status") != expected:
            raise ValueError("provider returned wrong sequence/status: " + str(result))
        if operation == "generate":
            self.outputs.append(result["output"])
            return result["output"]
        return result

    def finish(self):
        if hasattr(self, "exit_receipt"):
            return self.exit_receipt
        terminated = self.child.poll() is None
        killed = False
        if terminated:
            self.child.terminate()
            try:
                self.child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.child.kill()
                killed = True
        code = self.child.wait(timeout=20)
        receipt = {
            "pid": self.child.pid,
            "returncode": code,
            "wait_source": "subprocess.Popen.wait",
            "termination_requested": terminated,
            "kill_requested": killed,
            "wall_seconds": time.perf_counter() - self.started,
            "generation_requests_dispatched": self.dispatched,
            "complete_outputs_retained": len(self.outputs),
        }
        write_new(self.directory / "PROVIDER_EXIT.json", receipt)
        for stream in (
            self.child.stdin,
            self.child.stdout,
            self.stderr,
            self.stdout_raw,
            self.wire,
        ):
            stream.close()
        self.exit_receipt = receipt
        return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "provider-python",
        "provider-script",
        "artifact-root",
        "module-root",
        "output",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument(
        "--study", choices=("fixed_graphs", "repair_retrieval"), default="fixed_graphs"
    )
    parser.add_argument(
        "--panel", choices=("diagnostic", "upstream"), default="diagnostic"
    )
    parser.add_argument("--matched-training-source", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    command = [
        str(args.provider_python.absolute()),
        "-I",
        "-B",
        str(args.provider_script.resolve(strict=True)),
        "--artifact-root",
        str(args.artifact_root.resolve(strict=True)),
        "--module-root",
        str(args.module_root.resolve(strict=True)),
        "--run-dir",
        str(directory),
    ]
    if args.matched_training_source is not None:
        if args.panel != "upstream":
            raise ValueError("matched adapters require the explicit upstream study")
        command.extend(
            [
                "--matched-training-source",
                str(args.matched_training_source.resolve(strict=True)),
            ]
        )
    source = lambda: {
        str(p.relative_to(root)): file_hash(p)
        for p in sorted((root / "scripts/cell_experiments").rglob("*.py"))
    }
    inventory = source()
    if args.panel == "upstream":
        if args.study != "repair_retrieval":
            raise ValueError(
                "upstream requires the preregistered repair/retrieval study"
            )
        from cell_experiments.upstream_panel_v4 import load_panel

        materials = root / "qualification/cell-upstream-panel-20261118"
        panels = {"upstream": load_panel(materials)}
        catalog = data._parse((materials / "CATALOG.json").read_bytes())
    else:
        catalog = repo_execution.load_catalog("diagnostic")
        materials = root / "qualification/cell-diagnostic-panel-20261118"
        panels = {
            name: data.load_records(materials / name / "prepared-records.jsonl")
            for name in ("c", "d")
        }
    records = [(panel, record) for panel, rows in panels.items() for record in rows]
    if (
        len({row["task_id"] for _, row in records})
        != (6 if args.panel == "upstream" else 4)
        or (
            args.panel == "diagnostic"
            and any(len(rows) != 2 for rows in panels.values())
        )
        or any(row["authorization"]["training_allowed"] for _, row in records)
    ):
        raise ValueError("complete frozen evaluation-only panel required")
    arms = [
        ("FF", Graph("FF", ("F", "F")), {}),
        ("TT", Graph("TT", ("T", "T")), {}),
        ("CC", Graph("CC", ("C", "C")), {}),
        ("TF", Graph("TF", ("T", "F")), {}),
        ("CF", Graph("CF", ("C", "F")), {}),
        ("TF_no_answer", Graph("TF_no_answer", ("T", "F")), {"drop_edge": "answer"}),
        (
            "TF_no_feedback",
            Graph("TF_no_feedback", ("T", "F")),
            {"drop_edge": "feedback"},
        ),
        ("F_one_call", Graph("F_one_call", ("F", "T")), {"drop_cell": "T"}),
    ]
    study, augmented = None, {}
    if args.study == "repair_retrieval":
        from cell_experiments.circuit_repair_study_v4 import prepare

        arms, augmented, study = prepare(records, root)
        if args.panel == "upstream":
            arms = [arm for arm in arms if arm[0].startswith("native_")]
            for cell, removed in (("F", "T"), ("T", "F")):
                name = "native_" + cell + "_one_call"
                arms.append(
                    (
                        name,
                        Graph(name, (cell, removed)),
                        {"message_style": "native_turn_v1", "drop_cell": removed},
                    )
                )
            study["evaluation_scope"] = (
                "Six fixed public-source tasks already accessed by E1. "
                "Development transfer and interaction diagnostics, not a new confirmation."
            )
            study["single_call_control"] = (
                "F or T in slot zero; the other Cell removed before any dispatch"
            )
        write_new(directory / "RETRIEVAL.json", study)
    budget = Budget(max_output_tokens_per_call=384, max_relay_bytes=2048)
    launch = {
        "command": command,
        "provider_sha256": file_hash(args.provider_script),
        "provider_python_sha256": file_hash(args.provider_python),
        "source_inventory": inventory,
        "started_at_ns": time.time_ns(),
        "automatic_retry": False,
        "planned_model_calls": len(records)
        * sum(
            sum(cell != intervention.get("drop_cell") for cell in graph.path)
            for _, graph, intervention in arms
        ),
    }
    write_new(directory / "LAUNCH.json", launch)
    client, outcomes, started = None, [], time.perf_counter()
    try:
        client = ProviderProcess(command, directory)
        ready = client.read()
        if (
            ready.get("status") != "READY"
            or ready.get("schema") != "hepta.diagnostic-provider.v1"
            or ready.get("pid") != client.child.pid
        ):
            raise ValueError("provider startup identity differs")
        if (
            ready.get("script_sha256") != launch["provider_sha256"]
            or ready.get("interpreter_sha256") != launch["provider_python_sha256"]
            or ready.get("source_gates_unchanged") is not True
            or ready.get("evidence_scope") != "actual_shared_adapter_pool"
        ):
            raise ValueError("provider executable or admission differs")
        cells = {cell: CellSpec(**value) for cell, value in ready["cells"].items()}
        if set(cells) != {"F", "T", "C"}:
            raise ValueError("exactly the original three adapters required")
        freeze = {
            "schema": "hepta.fixed-diagnostic-freeze.v1",
            "launch": launch,
            "provider": ready,
            "record_digests": {
                panel: [data.digest(row) for row in rows]
                for panel, rows in panels.items()
            },
            "catalog_digest": data.digest(catalog),
            "budget": asdict(budget),
            "arms": [
                {"name": name, "graph": asdict(graph), "intervention": intervention}
                for name, graph, intervention in arms
            ],
            "order": (
                "upstream records in frozen order, then declared arm order"
                if args.panel == "upstream"
                else "c then d; declared task order then declared arm order"
            ),
            "learned_routing_tested": False,
            "single_call_definition": (
                "F or T in slot 0; other Cell in slot 1 removed before dispatch"
                if args.panel == "upstream"
                else "F in slot 0; slot 1 T removed before dispatch"
            ),
            "posthoc_selection": False,
            "scientific_confirmation_qualified": False,
            "native_owner_adoption": False,
        }
        if study is not None:
            freeze["study_extension"] = {
                "name": args.study,
                "receipt_digest": data.digest(study),
            }
        write_new(directory / "FREEZE.json", freeze)

        def generate(cell, request, call_dir):
            return client.call(
                "generate", cell=cell, request=request, call_dir=str(call_dir)
            )

        for panel, record in records:
            for name, graph, intervention in arms:
                location = directory / panel / record["record_id"] / name
                result = run_graph(
                    augmented[(panel, record["record_id"])]
                    if name.endswith("_retrieval")
                    else record,
                    graph,
                    cells,
                    budget,
                    generate,
                    data.verify_answer,
                    location,
                    **intervention,
                )
                complete = [
                    node for node in result["nodes"] if node["status"] == "COMPLETE"
                ]
                outcomes.append(
                    {
                        "panel": panel,
                        "task_id": record["task_id"],
                        "arm": name,
                        "result_digest": data.digest(result),
                        "path": str(location.relative_to(directory)),
                        "success": result["success"],
                        "first_success": result["first_success"],
                        "last_success": complete[-1]["business"]["business_success"],
                        "selected_slot": result["final_slot"],
                        "cost": result["cost"],
                    }
                )
        closed = client.call("close")
        if (
            client.child.wait(timeout=30) != 0
            or closed.get("pid") != client.child.pid
            or closed.get("source_inventory_unchanged") is not True
            or source() != inventory
        ):
            raise ValueError("provider close or frozen source validation failed")
        client.require_eof()
        exited = client.finish()
        keys = (
            "model_calls",
            "verifier_calls",
            "input_tokens",
            "output_tokens",
            "business_executions",
            "format_rejections",
        )
        report = {
            "schema": "hepta.fixed-diagnostic-result.v1",
            "status": "COMPLETE",
            "freeze_digest": data.digest(freeze),
            "outcomes": outcomes,
            "cost": {key: sum(row["cost"][key] for row in outcomes) for key in keys},
            "pool_initialization_cost": ready["pool"]["initialization_cost"],
            "provider_close": closed,
            "provider_exit": exited,
            "wall_seconds": time.perf_counter() - started,
            "full_system_cost_known": False,
            "matched_actual_cost_claim": False,
            "learned_routing_tested": False,
            "scientific_confirmation_qualified": False,
            "native_owner_adoption": False,
            "independent_sample_increment": 0,
            "external_teacher_count_added": 0,
            "new_users": 0,
        }
        if study is not None:
            report["study_extension"] = {
                "name": args.study,
                "receipt_digest": data.digest(study),
                "additional_reference_verifier_calls": study[
                    "reference_verifier_calls"
                ],
                "reference_preparation_wall_seconds": study["wall_seconds"],
                "reference_preparation_parent_cpu_seconds": study["parent_cpu_seconds"],
            }
        write_new(directory / "RESULT.json", report)
        print(
            data.canonical(
                {
                    "status": "COMPLETE",
                    "cost": report["cost"],
                    "result_digest": data.digest(report),
                }
            ).decode()
        )
    except BaseException as error:
        write_new(
            directory / "FAILED.json",
            {
                "status": "FAILED_PRESERVED",
                "error_type": type(error).__name__,
                "error": str(error),
                "completed_outcomes": outcomes,
                "automatic_retry": False,
                "generation_requests_dispatched": client.dispatched if client else 0,
                "complete_outputs_retained": len(client.outputs) if client else 0,
                "cost_complete": False,
                "wall_seconds": time.perf_counter() - started,
            },
        )
        raise
    finally:
        if client is not None:
            client.finish()


if __name__ == "__main__":
    main()
