"""Register all fourteen fresh jobs after committed-source, asset and destination guards."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
import sys
import time

SOURCE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOURCE))
from operational.parameter_field_recovery07 import common as c  # noqa: E402


def actions_identity(commit):
    value = {
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
        value["repository"] == "TrillionniumFoundation/hepta-private-ci"
        and value["head_sha"] == commit
        and all(
            isinstance(value[k], str) and value[k].isdigit() and int(value[k]) > 0
            for k in ("run_id", "run_attempt")
        )
        and isinstance(value["job"], str)
        and value["job"]
        and bool(os.environ.get("ACTIONS_RUNTIME_TOKEN"))
        and bool(os.environ.get("ACTIONS_RESULTS_URL")),
        "Actual registered Actions producer and transport environment are required before science",
    )
    return value


def committed_closure(commit, contract):
    pins = dict(contract["source_files"])
    for key in ("protocol", "original_resource_amendment", "runtime_contract"):
        item = contract[key]
        pins[item["path"]] = item["sha256"]
    for item in contract["scientific_parents"].values():
        pins[item["path"]] = item["sha256"]
    tree = c.committed_sources(SOURCE, commit, pins)
    prefixes = (
        "operational/parameter_field_recovery07/",
        "tools/parameter_field_executor/",
        "operational/parameter_field_five_questions_20261031/",
        "supplements/parameter_field_execution_20261031/",
        "supplements/parameter_field_fullstudy_20261030/",
        ".github/actions/parameter-field-science/",
        ".github/workflows/parameter-field-",
    )
    for name in tree:
        if name.startswith(prefixes):
            pins[name] = c.descriptor(SOURCE / name)["sha256"]
    needed = (
        "initialize.py",
        "registration.py",
        "analysis_worker.py",
        "supervisor.py",
        "controller.py",
        "worker.py",
        "semantic_preflight.py",
        "bootstrap.py",
        "postseal/review.py",
    )
    for name in needed:
        c.need(
            "operational/parameter_field_recovery07/" + name in pins,
            "Missing committed operational component: " + name,
        )
    c.committed_sources(SOURCE, commit, pins)
    return pins


def verify_assets(contract):
    root = Path(contract["assets_root"])
    c.need(root.is_dir(), "Original input directory is missing")
    result = []
    c.need(
        len(contract["assets"]) == 9
        and len({row["path"] for row in contract["assets"]}) == 9,
        "The nine-input population changed",
    )
    for row in contract["assets"]:
        item = {**row, "path": str(root / row["path"])}
        c.checked(item)
        result.append(item)
    return result


def verify_amendment(contract):
    actual = c.descriptor(c.OWN / "OPS_EXECUTION07.json")
    value = c.bound(actual)
    original = c.read(SOURCE / contract["original_resource_amendment"]["path"])
    c.need(
        value["execution_episode"] == c.EPISODE
        and value["raw_root"] == contract["raw_root"]
        and value["content_addressed_store"] == contract["cas_root"],
        "Wrong new operational roots",
    )
    c.need(
        value["concurrency"] == original["concurrency"],
        "Original concurrency limits changed",
    )
    for key, amount in original["proposed_resource_contract"].items():
        if type(amount) in (int, float, bool):
            c.need(
                value["proposed_resource_contract"][key] == amount,
                "Original numerical resource contract changed: " + key,
            )
    c.need(
        value["durable_execution"]["canonical_job_order"] == list(c.ORDER)
        and value["durable_execution"]["imported_jobs"] == []
        and value["durable_execution"]["automatic_scientific_retry"] is False,
        "Fresh single-episode operation plan changed",
    )
    return actual


def destination_runtime(contract, probe_directory, commit):
    """Measure this interpreter and cgroup now; an inherited host receipt is not accepted."""
    c.need(
        str(Path(sys.executable).absolute()) == contract["python"]
        and sys.version == contract["runtime_expected"]["descriptor"]["python"],
        "Wrong destination Python build",
    )
    python_files = []
    for row in contract["public_python_files"]:
        relative = Path(row["name"]).relative_to("python")
        path = Path(contract["python_base"]) / relative
        item = {"path": str(path), "bytes": row["size"], "sha256": row["sha256"]}
        c.checked(item)
        python_files.append(item)
    c.need(
        Path(sys.executable).resolve() == Path(python_files[0]["path"]),
        "Venv interpreter does not resolve to the fixed public binary",
    )
    path = SOURCE / "tools/parameter_field_executor/diagnose.py"
    spec = importlib.util.spec_from_file_location("execution07_runtime_probe", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    initial = module.capacity(probe_directory)
    c.need(
        initial["original_joint_pass"],
        "Original resource admission failed before runtime import",
    )
    runtime = module.runtime_probe(contract["runtime_expected"])
    matches = (
        runtime.get("exact_match") is True
        and runtime.get("runtime_sha256")
        == contract["runtime_expected"]["runtime_sha256"]
        and runtime.get("model_created") is False
        and runtime.get("scientific_inputs_opened") is False
    )
    if not matches:
        c.write_new(
            probe_directory / "REJECTED_RUNTIME.json",
            {
                "source_commit": commit,
                "expected_runtime_sha256": contract["runtime_expected"][
                    "runtime_sha256"
                ],
                "observed": runtime,
                "science_started": False,
            },
        )
    c.need(
        matches,
        "Actual destination runtime differs from the original descriptor",
    )
    samples = []
    for index in range(3):
        sample = module.capacity(probe_directory)
        c.need(
            sample["original_joint_pass"], "Original destination resource gate failed"
        )
        leaf = module.memory_node(Path("/sys/fs/cgroup"))
        c.need(
            leaf.get("finite_limit") == contract["docker_memory_max_bytes"],
            "Expected the actual finite 8GiB Docker cgroup",
        )
        samples.append({"capacity": sample, "cgroup_root": leaf})
        if index < 2:
            time.sleep(10)
    process, filesystem = (
        module.process_probe(),
        module.filesystem_probe(probe_directory),
    )
    c.need(
        process.get("supported") is True
        and all(
            filesystem.get(name) is True
            for name in ("fsync", "atomic_rename", "flock", "xattr", "byte_readback")
        ),
        "Destination wait4 or filesystem probe failed",
    )
    return {
        "schema": "hepta.execution07.destination-runtime.1",
        "execution_episode": c.EPISODE,
        "source_commit": commit,
        "python": contract["python"],
        "python_files": python_files,
        "runtime": runtime,
        "capacity_samples": samples,
        "sample_interval_seconds": 10,
        "process": process,
        "filesystem": filesystem,
        "measured_in_initializer_process": True,
        "cgroup_membership": Path("/proc/self/cgroup").read_text(),
        "science_started": False,
        "old_host_receipt_reused": False,
    }


def original_parent(phase, contract):
    item = contract["scientific_parents"][phase]
    path = SOURCE / item["path"]
    value = c.read(path)
    return {
        "path": str(path),
        "sha256": item["sha256"],
        "registered_commit": value["registered_commit"],
        "protocol_sha256": c.PROTOCOL_SHA,
        "source_root": str(SOURCE),
    }


def freeze(commit, closure, amendment, artifacts, phase, contract):
    value = {
        "schema": "hepta.fullstudy.source-freeze.1",
        "registered_commit": commit,
        "allowed_phases": [phase],
        "attempt_id": "attempt02",
        "execution_episode": c.EPISODE,
        "execution_kind": "controller" if phase == "OPS" else "training",
        "protocol_sha256": c.PROTOCOL_SHA,
        "operational_amendment_sha256": amendment["sha256"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_files": closure,
        "artifacts": {item["path"]: item["sha256"] for item in artifacts},
        "source_git_root": str(SOURCE),
        "source_registration_scope": "COMMITTED_SOURCE_BEFORE_FRESH_EXECUTION",
        "scope": "All prescribed jobs are fresh execution07 producers; original scientific bytes and thresholds are unchanged.",
    }
    if phase in ("A", "C"):
        value["scientific_parent"] = original_parent(phase, contract)
    return value


def initial_queue(a, cc, amendment, contract):
    old = c.read(SOURCE / c.PREFIX / "registrations/QUEUE_ATTEMPT02_DISK_INITIAL.json")
    c.need(
        [r["id"] for r in old["jobs"]] == list(c.ORDER[:4]),
        "Original initial job grid differs",
    )
    queue = deepcopy(old)
    queue.update(
        execution_episode=c.EPISODE,
        source_registration_scope="COMMITTED_SOURCE_BEFORE_FRESH_EXECUTION",
        note="All jobs execute fresh; later fixed prefixes require actual completion seals and external ACKs.",
    )
    common = {
        "--root": contract["raw_root"],
        "--assets": contract["assets_root"],
        "--amendment": amendment["path"],
        "--amendment-sha256": amendment["sha256"],
        "--protocol": str(SOURCE / c.PREFIX / "PROTOCOL.json"),
        "--reference-root": str(SOURCE),
    }
    for index, job in enumerate(queue["jobs"]):
        selected = cc if job["phase"] == "C" else a
        for flag, value in {**common, "--freeze": selected["path"]}.items():
            if flag in job["argv"]:
                job["argv"][job["argv"].index(flag) + 1] = value
        job.update(
            freeze_sha256=selected["sha256"],
            requires=[] if index == 0 else [c.ORDER[index - 1]],
        )
    return queue


def initialize(commit, initialization_intent, initialization_intent_sha256):
    contract = c.read(c.OWN / "INPUT_CONTRACT.json")
    c.need(
        str(SOURCE) == contract["source_root"],
        "Initialize only the registered destination checkout",
    )
    producer = actions_identity(commit)
    intent_item = c.descriptor(initialization_intent)
    c.need(
        intent_item["sha256"] == initialization_intent_sha256,
        "Initialization plan pin differs",
    )
    intent = c.bound(intent_item)
    c.need(
        intent.get("schema") == "hepta.execution07.initialization-plan.1"
        and intent.get("execution_episode") == c.EPISODE
        and intent.get("source_commit") == commit
        and intent.get("program") == c.descriptor(Path(__file__).resolve())
        and intent.get("python") == contract["python"]
        and intent.get("base_argv") == ["--source-commit", commit]
        and intent.get("generated_config_path")
        == str(
            Path(contract["ops_root"]) / "registrations/initial/PIPELINE_CONFIG.json"
        ),
        "Initialization intent does not bind this actual source and destination",
    )
    closure = committed_closure(commit, contract)
    amendment = verify_amendment(contract)
    assets = verify_assets(contract)
    ops, raw, cas = (Path(contract[k]) for k in ("ops_root", "raw_root", "cas_root"))
    c.need(
        not any(p.exists() for p in (ops, raw, cas)),
        "Fresh execution roots must not already exist",
    )
    c.need(
        all(
            not p.is_relative_to(SOURCE) and not SOURCE.is_relative_to(p)
            for p in (ops, raw, cas)
        ),
        "Destination overlaps source",
    )
    ops.parent.mkdir(parents=True, exist_ok=True)
    probe = ops.parent / "initial_runtime_probe"
    probe.mkdir(exist_ok=False)
    runtime = destination_runtime(contract, probe, commit)
    c.committed_sources(SOURCE, commit, closure)
    c.need(
        verify_assets(contract) == assets, "Original assets changed during preflight"
    )
    initial = ops / "registrations/initial"
    initial.mkdir(parents=True, exist_ok=False)
    for p in (raw, cas, ops / "empty_cwd"):
        p.mkdir(exist_ok=False)
    runtime_item = c.write_new(initial / "RUNTIME.json", runtime)
    assets_item = c.write_new(
        initial / "ASSETS.json",
        {
            "schema": "hepta.execution07.asset-verification.1",
            "public_source_commit": contract["public_assets_commit"],
            "files": assets,
            "decoded": False,
        },
    )
    artifacts = [
        amendment,
        runtime_item,
        assets_item,
        c.descriptor(c.OWN / "INPUT_CONTRACT.json"),
        *assets,
    ]
    a = c.write_new(
        initial / "A_SOURCE_FREEZE.json",
        freeze(commit, closure, amendment, artifacts, "A", contract),
    )
    cc = c.write_new(
        initial / "C_SOURCE_FREEZE.json",
        freeze(commit, closure, amendment, artifacts, "C", contract),
    )
    queue = c.write_new(
        initial / "QUEUE_INITIAL.json", initial_queue(a, cc, amendment, contract)
    )
    controller = c.write_new(
        initial / "OPS_SOURCE_FREEZE.json",
        freeze(commit, closure, amendment, [*artifacts, a, cc, queue], "OPS", contract),
    )
    parent_plan = c.descriptor(
        SOURCE / "supplements/parameter_field_fullstudy_20261030/PRE_ENDPOINT_PLAN.json"
    )
    plan = c.bound(parent_plan)
    plan.update(
        execution_episode=c.EPISODE,
        registered_source_commit=commit,
        original_plan=parent_plan,
        declared_at=datetime.now(timezone.utc).isoformat(),
        execution_context={
            "operations_root": str(ops),
            "raw_root": str(raw),
            "source_root": str(SOURCE),
        },
        pipeline_interface={
            **plan["pipeline_interface"],
            "execution_episode": c.EPISODE,
        },
        execution07_source_closure=closure,
        imported_jobs=[],
        preparation_state="METADATA_ONLY_NO_SCIENCE",
    )
    prospective = c.write_new(initial / "PRE_ENDPOINT_PLAN07.json", plan)
    descriptors = {
        "amendment": amendment,
        "initial_queue": queue,
        "controller_freeze": controller,
        "runtime_receipt": runtime_item,
        "assets_receipt": assets_item,
        "a_freeze": a,
        "c_freeze": cc,
        "prospective_plan": prospective,
        "registration_driver": c.descriptor(c.OWN / "registration.py"),
    }
    config = {
        "schema": c.SCHEMA,
        "execution_episode": c.EPISODE,
        "source_commit": commit,
        "actions_identity": producer,
        **{
            k: contract[k]
            for k in (
                "source_root",
                "ops_root",
                "raw_root",
                "cas_root",
                "assets_root",
                "python",
            )
        },
        "empty_cwd": str(ops / "empty_cwd"),
        "active_queue": str(ops / "ACTIVE_QUEUE.json"),
        "analysis_id": "analysis07",
        "evidence_id": "verification07",
        "job_order": list(c.ORDER),
        "imported_jobs": [],
        "new_scientific_jobs": list(c.ORDER),
        "source_files": closure,
        "descriptors": descriptors,
        "initialization_intent": intent_item,
    }
    config_item = c.write_new(initial / "PIPELINE_CONFIG.json", config)
    c.write_new(
        initial / "INITIALIZATION.json",
        {
            "schema": "hepta.execution07.initialization.1",
            "pipeline_config": config_item,
            "source_commit": commit,
            "source_files": len(closure),
            "original_source_files": len(contract["source_files"]),
            "fresh_jobs": list(c.ORDER),
            "imported_jobs": [],
            "workers_started": 0,
            "model_data_decoded": False,
            "source_commit_verified": True,
            "first_scientific_worker_not_started": True,
            "first_worker_requires_original_semantic_preflight": True,
            "first_job_ack_pending": True,
        },
    )
    return config_item


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--initialization-intent", required=True)
    parser.add_argument("--initialization-intent-sha256", required=True)
    args = parser.parse_args()
    print(
        c.encode(
            {
                "pipeline_config": initialize(
                    args.source_commit,
                    args.initialization_intent,
                    args.initialization_intent_sha256,
                ),
                "workers_started": 0,
            }
        ).decode()
    )


if __name__ == "__main__":
    main()
