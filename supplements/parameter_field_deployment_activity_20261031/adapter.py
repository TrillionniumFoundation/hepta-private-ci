"""One measured portable replay of a fully closed, externally pinned study.

No original study, archive or postseal file is rewritten. Fresh provider
downloads are measured independently. Scientific payload decoding begins only
after the portable operational adaptation, original full science gate and
original postseal/lifecycle closure have all succeeded.
"""

import argparse
from contextlib import contextmanager
import gzip
import importlib
import os
from pathlib import Path
import re
import resource
import sys
import time

ADDON = Path(__file__).resolve().parents[2]
if str(ADDON) not in sys.path:
    sys.path.insert(0, str(ADDON))
from supplements.parameter_field_deployment_activity_20261031 import (  # noqa: E402
    activity,
    archives,
    portable_common as c,
    portable_gate,
)


@contextmanager
def timed(book, label):
    started, cpu = time.monotonic(), time.process_time()
    try:
        yield
    finally:
        book[label] = {
            "wall_seconds": time.monotonic() - started,
            "self_cpu_seconds": time.process_time() - cpu,
        }


def prepare_imports(binding):
    c.original_source(binding)
    # Both complete checkouts contain the same namespace packages. A preexisting
    # later SOURCE entry must still move ahead of the additive checkout.
    sys.path[:] = [
        str(c.SOURCE),
        *(value for value in sys.path if value != str(c.SOURCE)),
    ]
    process = importlib.import_module("operational.parameter_field_recovery07.process")
    c.need(
        Path(process.__file__).resolve()
        == c.SOURCE / "operational/parameter_field_recovery07/process.py",
        "Owned-child implementation imported from another source",
    )
    return process


def owned(process, name, argv, output, binding_item, deadline, oom, extra_env=None):
    log = output / "logs" / (name + ".log")
    log.parent.mkdir(exist_ok=True)
    log.touch(exist_ok=False)
    empty = output / "empty_cwd"
    empty.mkdir(exist_ok=True)
    result = process.run_owned(
        argv,
        directory=output / "measurements" / name,
        cwd=str(empty),
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join((str(c.SOURCE), str(ADDON))),
            "PYTHONDONTWRITEBYTECODE": "1",
            **(extra_env or {}),
        },
        log=log,
        health=lambda: c.health(deadline, oom),
        binding={
            "execution_episode": c.EPISODE,
            "component_schema_is_implementation_version_not_execution_episode": True,
            "original_child_owner_source_commit": c.git(c.SOURCE, "rev-parse", "HEAD")
            .decode()
            .strip(),
            "replay_binding": binding_item,
            "phase": name,
        },
    )
    c.need(
        result["exit_code"] == 0, name + " failed; no retry or later payload admission"
    )
    return result


def compressed_json(store, relative):
    c.need(
        store.admitted is True, "Compressed scientific trace blocked before admission"
    )
    item = store.descriptor(relative)
    with store.inputs.opened(
        item["path"], item["sha256"], item["bytes"], "deployment_trace"
    ) as source:
        with gzip.GzipFile(fileobj=source, mode="rb") as compressed:
            raw = compressed.read(32 * 1024**2 + 1)
    c.need(len(raw) <= 32 * 1024**2, "Scientific trace exceeds decompressed bound")
    return c.strict_json(raw)


def joined_c_paths(store):
    complete = store.read_json("stage_C/COMPLETE.json")
    c.need(
        complete["schema"] == "hepta.fullstudy.C.complete-seal.1"
        and complete["complete"] is True
        and complete["training_complete"] is True
        and len(complete["paths"]) == 32,
        "C deployment completion population differs",
    )
    inventory = complete["artifacts"]
    c.need(
        len({item["path"] for item in inventory}) == len(inventory),
        "Duplicate C artifact identity",
    )
    artifacts = {item["path"]: item for item in inventory}
    result, selected = [], set()
    required = {
        "seed",
        "mode",
        "policy",
        "checkpoint",
        "state_sha256",
        "overrides",
        "accepted_overrides",
        "first_legal_divergence_decision",
        "first_legal_divergence_clock",
    }
    for item in complete["paths"]:
        c.need(set(item) == required, "C completion inventory schema differs")
        checkpoint = item["checkpoint"]
        expected = (
            f"endpoints/{item['mode']}-seed-{item['seed']}-{item['policy']}.pt.gz"
        )
        c.need(
            checkpoint["path"] == expected and expected not in selected,
            "C endpoint selection differs or duplicates",
        )
        selected.add(expected)
        c.need(
            artifacts.get(expected) == checkpoint,
            "C checkpoint is not in the original artifact inventory",
        )
        trace_name = expected.removesuffix(".pt.gz") + ".trace.json.gz"
        for name in (expected, trace_name):
            declared = artifacts[name]
            actual = store.descriptor("stage_C/" + name)
            c.need(
                all(declared[k] == actual[k] for k in ("bytes", "sha256")),
                "C original inventory and final literal manifest differ",
            )
        trace = compressed_json(store, "stage_C/" + trace_name)
        additions = {"first_legal_divergence_decision", "first_legal_divergence_clock"}
        c.need(
            set(item) - additions <= set(trace)
            and not additions & set(trace)
            and all(trace[key] == item[key] for key in set(item) - additions),
            "C trace and completion inventory conflict",
        )
        result.append({**trace, **item})
    return result


def decode_and_reduce(context):
    store, inputs = context["store"], context["inputs"]
    c.need(
        context["receipt"]["complete"] is True and store.admitted is True,
        "Deployment payloads require actual complete admission",
    )
    b_paths = []
    for seed in activity.B_SEEDS:
        prefix = f"stage_B/seed-{seed}/paths/"
        value = store.read_json(prefix + "PATHS.json")
        c.need(
            value["complete"] is True
            and value["training_complete"] is True
            and value["phase"] == "B"
            and value["seed"] == seed
            and len(value["paths"]) == 80,
            "B fixed completed inventory differs",
        )
        for row in value["paths"]:
            c.need(
                row["seed"] == seed and row["path"] == row["id"] + ".state",
                "B literal terminal selection differs",
            )
            terminal = store.descriptor(prefix + row["path"])
            c.need(
                all(terminal[k] == row[k] for k in ("bytes", "sha256")),
                "B terminal identity is outside original manifest",
            )
        b_paths.extend(value["paths"])
    b_result = activity.audit_b(b_paths)
    c_paths = joined_c_paths(store)
    state = importlib.import_module(
        "experiments.parameter_field_fullstudy_20261029.architecture_state"
    )
    c.need(
        Path(state.__file__).resolve()
        == c.SOURCE
        / "experiments/parameter_field_fullstudy_20261029/architecture_state.py",
        "C safe decoder loaded from another source",
    )
    components = {}
    for path in c_paths:
        item = store.descriptor("stage_C/" + path["checkpoint"]["path"])
        with inputs.opened(
            item["path"], item["sha256"], item["bytes"], "deployment_terminal_tensor"
        ):
            record = state.read_checkpoint(item["path"])
            components[(path["mode"], path["seed"], path["policy"])] = (
                activity.terminal_components(record, path, state.digest)
            )
            del record
    return {"B": b_result, "C": activity.audit_c(c_paths, components)}


def validate_literal_reconstruction(context):
    """Compare complete downloaded RAW/CAS bytes; never assert old hardlinks survive."""
    store = context["store"]
    actual = {
        str(path.relative_to(store.root))
        for path in store.root.rglob("*")
        if path.is_file()
    }
    evidence = {
        "evidence_v2/verification07/" + name
        for name in ("START.json", "MANIFEST.json", "VERIFIED.json")
    }
    c.need(
        actual == set(store.entries) | evidence,
        "Reconstructed RAW has unregistered extra or missing paths",
    )
    for name, row in store.entries.items():
        if row["storage"] == "cas":
            item = {
                "path": str(c.RUN / "raw_cas" / row["blob"]),
                "bytes": row["bytes"],
                "sha256": row["sha256"],
            }
            context["metadata"].check(item)
    for path in (c.RUN / "raw_cas").iterdir():
        item = c.descriptor(path)
        c.need(
            path.name == item["sha256"], "CAS member name does not bind literal bytes"
        )
    return {
        "logical_raw_files": len(store.entries),
        "raw_and_cas_bytes_checked": True,
        "original_hardlink_or_inode_layout_reproduced": False,
    }


def child(args):
    binding, binding_item = c.load_binding(args.binding, args.expected_binding_sha256)
    process = prepare_imports(binding)
    output = Path(args.output)
    plan = c.read(c.descriptor(output / "PLAN.json"))
    c.need(
        plan["binding"] == binding_item and plan["execution_episode"] == c.EPISODE,
        "Replay owner plan differs",
    )
    deadline, oom = plan["deadline_monotonic"], plan["oom_baseline"]
    timings, measurements = {}, {}
    runtime_path = output / "runtime/RUNTIME.json"
    measurements["runtime"] = owned(
        process,
        "runtime",
        [
            sys.executable,
            "-B",
            str(c.SOURCE / "tools/parameter_field_executor/diagnose.py"),
            "--output",
            str(runtime_path),
        ],
        output,
        binding_item,
        deadline,
        oom,
    )
    runtime = c.read(c.descriptor(runtime_path))
    c.need(
        runtime["runtime"]["exact_match"] is True
        and runtime["three_original_joint_passes"] is True,
        "Fresh diagnostic runtime failed; provider payloads not admitted",
    )
    measurements["original_public_inputs"] = owned(
        process,
        "original_public_inputs",
        [
            sys.executable,
            "-B",
            str(c.SOURCE / "tools/parameter_field_executor/prepare_inputs.py"),
        ],
        output,
        binding_item,
        deadline,
        oom,
    )
    request = c.write(output / "PROVIDER_REQUEST.json", binding["provider"])
    measurements["provider"] = owned(
        process,
        "provider",
        [
            sys.executable,
            "-B",
            str(c.OWN / "provider.py"),
            "--request",
            request["path"],
            "--expected-request-sha256",
            request["sha256"],
            "--output",
            str(output / "provider"),
        ],
        output,
        binding_item,
        deadline,
        oom,
    )
    provider_item = c.descriptor(output / "provider/RECEIPT.json")
    receipt = c.read(provider_item)
    copy_item = c.descriptor(output / "provider/REQUEST.json")
    c.need(
        all(copy_item[k] == request[k] for k in ("bytes", "sha256")),
        "Provider copied another request",
    )
    with timed(timings, "new_archive_bytes_and_reconstruction"):
        downloads = portable_gate.download_map(receipt, binding, copy_item)
        coverage = archives.reconstruct(
            downloads["final_scientific"]["download"],
            downloads["final_operations"]["download"],
        )
        c.write(output / "RECONSTRUCTED_FILES.json", coverage)
    with timed(
        timings, "portable_operational_and_original_scientific_and_postseal_gates"
    ):
        context = portable_gate.admit(
            binding,
            downloads,
            runtime,
            output,
            replay_identity=plan["current_replay_identity"],
        )
        literal = validate_literal_reconstruction(context)
        context["receipt"]["new_literal_reconstruction"] = literal
        admission_item = c.write(output / "ADMISSION.json", context["receipt"])
    c.health(deadline, oom)
    with timed(timings, "admitted_deployment_traces_and_terminal_components"):
        result = decode_and_reduce(context)
    with timed(timings, "input_and_source_stability"):
        context["inputs"].unchanged()
        context["metadata"].stable()
        c.load_binding(args.binding, args.expected_binding_sha256)
        c.original_source(binding)
        c.checked(provider_item)
    result.update(
        schema="hepta.parameter-field.deployment-activity.1",
        execution_episode=c.EPISODE,
        admission=admission_item,
        replay_binding=binding_item,
        original_postseal_disposition=context["receipt"][
            "full_original_postseal_and_lifecycle"
        ]["original_postseal_disposition"],
        original_integrity_issues=context["receipt"][
            "full_original_postseal_and_lifecycle"
        ]["original_integrity_issues"],
        scientific_admission_performed_here=True,
        original_outputs_modified=False,
        new_scientific_rollouts=0,
        new_independent_samples=0,
        adoption="not_assessed",
        certificate=False,
    )
    result_item = c.write(output / "DEPLOYMENT_ACTIVITY.json", result)
    inputs_item = c.write(
        output / "CONSUMED_INPUTS.json",
        {
            "scientific": list(context["inputs"].rows.values()),
            "metadata": list(context["metadata"].items.values()),
            "provider_receipt": provider_item,
            "source_binding": binding_item,
            "all_consumed_bytes_verified": True,
        },
    )
    c.health(deadline, oom)
    return c.write(
        output / "CHILD_COMPLETE.json",
        {
            "schema": "hepta.parameter-field.deployment-replay-child.1",
            "complete": True,
            "execution_episode": c.EPISODE,
            "binding": binding_item,
            "admission": admission_item,
            "result": result_item,
            "inputs": inputs_item,
            "closed_phase_wait4": measurements,
            "self_cpu_timing_components": timings,
            "cost_scope": "Real closed runtime/input/provider children plus this process work are included in the outer owned wait4. Nested intervals are attribution, never added to the inclusive total.",
            "this_child_outer_wait4_pending": True,
            "no_new_training_scoring_refitting": True,
            "original_scientific_gates_changed": False,
            "historical_cost_total_known": False,
        },
    )


def run(args):
    started, cpu = time.monotonic(), time.process_time()
    reaped_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    binding, item = c.load_binding(args.binding, args.expected_binding_sha256)
    c.need(
        Path(args.output) == c.OUTPUT and not c.OUTPUT.exists() and not c.RUN.exists(),
        "Replay needs fresh canonical output and original-data destinations",
    )
    process = prepare_imports(binding)
    replay_identity = {
        key: os.environ.get(name)
        for key, name in (
            ("repository", "GITHUB_REPOSITORY"),
            ("run_id", "GITHUB_RUN_ID"),
            ("run_attempt", "GITHUB_RUN_ATTEMPT"),
            ("head_sha", "GITHUB_SHA"),
            ("job", "GITHUB_JOB"),
        )
    }
    c.need(
        replay_identity["repository"] == binding["provider"]["repository"]
        and all(
            type(replay_identity[key]) is str
            and replay_identity[key].isdigit()
            and int(replay_identity[key]) > 0
            for key in ("run_id", "run_attempt")
        )
        and replay_identity["run_id"] != str(binding["provider"]["run_id"])
        and replay_identity["head_sha"]
        == c.git(ADDON, "rev-parse", "HEAD").decode().strip()
        and re.fullmatch("[0-9a-f]{40}", replay_identity["head_sha"] or "")
        and type(replay_identity["job"]) is str
        and replay_identity["job"],
        "A distinct actual diagnostic Actions producer is required",
    )
    c.OUTPUT.mkdir(parents=True, exist_ok=False)
    events = dict(
        line.split()
        for line in Path("/sys/fs/cgroup/memory.events").read_text().splitlines()
    )
    oom = {key: int(events[key]) for key in ("oom", "oom_kill")}
    deadline = time.monotonic() + 5400
    c.health(deadline, oom)
    c.write(
        c.OUTPUT / "PLAN.json",
        {
            "schema": "hepta.parameter-field.deployment-replay-owner-plan.1",
            "execution_episode": c.EPISODE,
            "binding": item,
            "deadline_monotonic": deadline,
            "operational_deadline_seconds": 5400,
            "current_replay_identity": replay_identity,
            "oom_baseline": oom,
            "source_commit": binding["provider"]["head_sha"],
            "addon": binding["addon"],
            "original_scientific_deadlines_and_thresholds_changed": False,
        },
    )
    argv = [
        sys.executable,
        "-B",
        str(Path(__file__).resolve()),
        "--binding",
        item["path"],
        "--expected-binding-sha256",
        item["sha256"],
        "--output",
        str(c.OUTPUT),
        "--child",
    ]
    result = owned(process, "inclusive_replay", argv, c.OUTPUT, item, deadline, oom)
    child_item = c.descriptor(c.OUTPUT / "CHILD_COMPLETE.json")
    completed = c.read(child_item)
    c.need(
        completed["complete"] is True
        and completed["binding"] == item
        and completed["execution_episode"] == c.EPISODE,
        "Replay child did not seal the same inputs",
    )
    c.load_binding(args.binding, args.expected_binding_sha256)
    c.health(deadline, oom)
    reaped_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    return c.write(
        c.OUTPUT / "COMPLETE.json",
        {
            "schema": "hepta.parameter-field.deployment-replay-completion.1",
            "complete": True,
            "execution_episode": c.EPISODE,
            "binding": item,
            "child_completion": child_item,
            "current_replay_identity": replay_identity,
            "inclusive_real_wait4": result,
            "launcher_self_cpu_seconds_before_final_serialization": time.process_time()
            - cpu,
            "launcher_wall_seconds_before_final_serialization": time.monotonic()
            - started,
            "launcher_all_reaped_child_user_cpu_seconds": reaped_after.ru_utime
            - reaped_before.ru_utime,
            "launcher_all_reaped_child_system_cpu_seconds": reaped_after.ru_stime
            - reaped_before.ru_stime,
            "launcher_child_cpu_scope": "All reaped children since run() entry, including the inclusive replay child and source-verification Git children; this overlaps the child wait4 and must not be added to it. Startup/imports/argument parsing and final receipt serialization remain outside these counters.",
            "cost_scope": "The inclusive child wait4 includes provider downloads, input preparation, runtime qualification, reconstruction, verification, tensor decode, reducers and child serialization. Launcher CPU and workflow preparation/delivery are separate; never add nested phase costs again.",
            "workflow_environment_preparation_cpu": "unknown; actual workflow wall durations remain separately available",
            "final_output_delivery_and_this_receipt_serialization_outside_inclusive_child": True,
            "scientific_result_is_descriptive_activity_only": True,
            "adoption": "not_assessed",
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binding", required=True)
    parser.add_argument("--expected-binding-sha256", required=True)
    parser.add_argument("--output", default=str(c.OUTPUT))
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        result = child(args) if args.child else run(args)
        print(result["sha256"])
        return 0
    except BaseException as error:
        output = Path(args.output)
        if output == c.OUTPUT and output.is_dir():
            name = "CHILD_FAILED.json" if args.child else "FAILED.json"
            if not (output / name).exists():
                c.write(
                    output / name,
                    {
                        "schema": "hepta.parameter-field.deployment-replay-failure.1",
                        "complete": False,
                        "execution_episode": c.EPISODE,
                        "error_type": type(error).__name__,
                        "message": str(error)[:4096],
                        "automatic_retry": False,
                        "original_evidence_modified": False,
                        "partial_new_evidence_preserved": True,
                    },
                )
        print(type(error).__name__ + ": " + str(error)[:4096], file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
