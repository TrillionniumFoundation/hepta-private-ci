"""Read the fresh full study only after sources, 18 deliveries and all original seals."""

import argparse
import hashlib
import importlib.util
import math
from pathlib import Path
import re
import stat
import sys
import time
from types import SimpleNamespace
import zipfile

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from operational.parameter_field_recovery07 import common as c  # noqa: E402
from operational.parameter_field_recovery07.queue import LABELS  # noqa: E402

SCHEMA = "hepta.execution07.postseal-review.1"


def nonnegative(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


class Metadata:
    """Track streaming identities before any scientific value decoder is admitted."""

    def __init__(self):
        self.items, self.fingerprints = {}, {}

    def check(self, item):
        path = c.checked(item)
        previous = self.items.setdefault(str(path), item)
        c.need(previous == item, "Conflicting metadata identity")
        info = path.stat()
        identity = tuple(
            getattr(info, k)
            for k in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        )
        c.need(
            self.fingerprints.setdefault(str(path), identity) == identity,
            "Metadata changed",
        )
        return path

    def read(self, item):
        path = self.check(item)
        c.need(item["bytes"] <= 32 * 1024**2, "Metadata exceeds size bound")
        raw = path.read_bytes()
        c.need(
            hashlib.sha256(raw).hexdigest() == item["sha256"],
            "Metadata changed during read",
        )
        return c.strict_json(raw)

    def file(self, path):
        return self.read(c.descriptor(path))

    def stable(self):
        for path, before in self.fingerprints.items():
            now = c.regular(path).stat()
            c.need(
                tuple(
                    getattr(now, k)
                    for k in (
                        "st_dev",
                        "st_ino",
                        "st_size",
                        "st_mtime_ns",
                        "st_ctime_ns",
                    )
                )
                == before,
                "Consumed metadata changed before review closure",
            )


def wait4(metadata, directory, *, config_item=None, argv=None):
    directory = Path(directory)
    closure, waited = (
        metadata.file(directory / "CLOSURE.json"),
        metadata.file(directory / "001.WAIT4.json"),
    )
    c.need(
        closure.get("all_returned_direct_children_reaped") is True
        and closure.get("accounting_complete_for_attempted_direct_workers") is True
        and closure.get("attempt_count") == closure.get("returned_children") == 1
        and len(closure.get("attempts", [])) == len(closure.get("children", [])) == 1
        and closure["children"][0].get("wait4") == waited
        and closure.get("original_exception") is None
        and closure.get("receipt_errors") == []
        and closure.get("cleanup_errors") == []
        and closure.get("construction_wait4_unavailable") is False
        and closure.get("binding", {}).get("execution_episode") == c.EPISODE,
        "Owned process accounting is not complete",
    )
    c.need(
        waited.get("exit_code") == 0
        and type(waited.get("pid")) is int
        and waited["pid"] > 0
        and all(
            nonnegative(waited.get(k))
            for k in (
                "wall_seconds",
                "cpu_seconds",
                "user_cpu_seconds",
                "system_cpu_seconds",
                "peak_rss_bytes",
            )
        )
        and math.isclose(
            waited["cpu_seconds"],
            waited["user_cpu_seconds"] + waited["system_cpu_seconds"],
            abs_tol=1e-9,
        ),
        "Invalid or failed owned wait4",
    )
    if config_item is not None:
        c.need(
            closure["binding"].get("pipeline_config") == config_item,
            "Owned process configuration differs",
        )
    if argv is not None:
        c.need(closure["attempts"][0]["argv"] == argv, "Owned process argv differs")
    return {
        "wait4": c.descriptor(directory / "001.WAIT4.json"),
        "closure": c.descriptor(directory / "CLOSURE.json"),
        "cpu_seconds": waited["cpu_seconds"],
        "wall_seconds": waited["wall_seconds"],
        "peak_rss_bytes": waited["peak_rss_bytes"],
    }


def logical(value):
    path = Path(value)
    c.need(
        type(value) is str
        and value
        and not path.is_absolute()
        and ".." not in path.parts
        and path.as_posix() == value
        and all(part not in ("", ".") for part in path.parts),
        "Unsafe archive logical path",
    )
    return path


def verify_ack(metadata, row, binding, expected_identity=None, *, terminal=False):
    ack_path = metadata.check(row["ack"])
    ack = metadata.read(row["ack"])
    schema = (
        "hepta.github-actions-terminal-ack.v1"
        if terminal
        else "hepta.github-actions-archive-ack.v1"
    )
    c.need(
        ack.get("schema") == schema
        and ack.get("binding") == row.get("binding") == binding
        and "synthetic_only" not in binding,
        "Actual ACK sequence or binding differs",
    )
    identity = ack["identity"]
    c.need(
        set(identity) == {"repository", "run_id", "run_attempt", "head_sha", "job"}
        and identity["repository"] == "TrillionniumFoundation/hepta-private-ci"
        and re.fullmatch(r"[0-9a-f]{40}", identity["head_sha"] or "")
        and all(
            isinstance(identity[k], str)
            and identity[k].isdigit()
            and int(identity[k]) > 0
            for k in ("run_id", "run_attempt")
        )
        and isinstance(identity["job"], str)
        and identity["job"],
        "ACK lacks actual Actions identity",
    )
    c.need(
        expected_identity is None or identity == expected_identity,
        "ACK producer changed",
    )
    for key in ("manifest", "logical_files", "items_verified", "cost", "artifact"):
        c.need(ack.get(key) == row.get(key), "ACK return does not bind " + key)
    manifest = metadata.read(ack["manifest"])
    files = ack["logical_files"]
    c.need(
        manifest.get("schema") == "hepta.github-actions-archive-manifest.v1"
        and manifest.get("binding") == binding
        and manifest.get("identity") == identity
        and manifest.get("files") == files
        and manifest.get("file_count") == ack["items_verified"] == len(files)
        and 0 < len(files) <= 20000
        and len({r["path"] for r in files}) == len(files)
        and manifest.get("payload_bytes") == sum(r["bytes"] for r in files),
        "Archive manifest population differs",
    )
    artifact = ack["artifact"]
    c.need(
        type(artifact.get("id")) is int
        and artifact["id"] > 0
        and artifact.get("name")
        == "hepta-r07-"
        + identity["run_id"]
        + "-"
        + identity["run_attempt"]
        + "-"
        + binding["label"]
        and type(artifact.get("bytes")) is int
        and artifact["bytes"] > 0
        and re.fullmatch(r"[0-9a-f]{64}", artifact.get("sha256", "")),
        "Immutable provider artifact is missing",
    )
    returned = ack["readback"]
    archive = returned["raw_archive"]
    c.need(
        returned.get("all_sha256_and_bytes_match") is True
        and archive["sha256"] == artifact["sha256"]
        and archive["bytes"] == artifact["bytes"]
        and returned["client"].get("id") == artifact["id"]
        and returned["client"].get("expected_sha256") == artifact["sha256"]
        and returned["client"].get("digest_mismatch") is False
        and returned["client"].get("raw_archive") is True,
        "Provider raw readback differs",
    )
    archive_path = metadata.check(archive)
    directory = ack_path.parent
    c.need(
        Path(ack["manifest"]["path"]) == directory / "upload/MANIFEST.json"
        and archive_path.parent == directory / "download_raw",
        "Archive files escape their stage",
    )
    proofs = returned["independent_device_inodes"]
    c.need(
        len(proofs) == len(files)
        and {x["path"] for x in proofs} == {x["path"] for x in files},
        "Readback proof population differs",
    )
    proofs = {x["path"]: x for x in proofs}
    with zipfile.ZipFile(archive_path) as saved:
        expected = {"MANIFEST.json"} | {"payload/" + r["path"] for r in files}
        members = saved.infolist()
        names = [i.filename for i in members if not i.is_dir()]
        c.need(
            len(names) == len(set(names)) and set(names) == expected,
            "Downloaded ZIP file population differs",
        )
        c.need(
            sum(v.file_size for v in members) <= 2 * 1024**3 + 2 * 1024**2,
            "Downloaded archive exceeds the registered transport bound",
        )
        for member in members:
            logical(member.filename.rstrip("/"))
            c.need(
                stat.S_IFMT(member.external_attr >> 16)
                in (0, stat.S_IFREG, stat.S_IFDIR)
                and not member.flag_bits & 1
                and (
                    not member.is_dir()
                    or any(k.startswith(member.filename) for k in expected)
                ),
                "Archive contains a link, encrypted member or unrelated directory",
            )
        c.need(
            saved.read("MANIFEST.json") == Path(ack["manifest"]["path"]).read_bytes(),
            "Downloaded manifest bytes differ",
        )
        for item in files:
            relative = logical(item["path"])
            c.need(
                type(item["bytes"]) is int
                and item["bytes"] >= 0
                and re.fullmatch(r"[0-9a-f]{64}", item["sha256"] or ""),
                "Malformed archived file identity",
            )
            key = "payload/" + item["path"]
            c.need(
                saved.getinfo(key).file_size == item["bytes"],
                "ZIP payload size differs",
            )
            with saved.open(key) as stream:
                c.need(
                    hashlib.file_digest(stream, "sha256").hexdigest() == item["sha256"],
                    "ZIP payload hash differs",
                )
            proof = proofs[item["path"]]
            identities = []
            for part, field in (
                ("upload", "staged_device_inode"),
                ("readback", "readback_device_inode"),
            ):
                path = directory / part / "payload" / relative
                metadata.check({**item, "path": str(path)})
                info = path.stat()
                actual = [info.st_dev, info.st_ino]
                c.need(
                    proof.get(field) == actual,
                    "Independent readback inode identity differs",
                )
                identities.append(tuple(actual))
            source_inode = proof.get("source_device_inode")
            c.need(
                type(source_inode) is list
                and len(source_inode) == 2
                and all(type(v) is int and v >= 0 for v in source_inode)
                and len({*identities, tuple(source_inode)}) == 3,
                "Readback was not an independent copy",
            )
    cost = ack["cost"]
    waits = cost["wait4"]
    c.need(
        len(waits) == 2
        and [v.get("operation") for v in waits] == ["upload", "download"],
        "Transport cost population differs",
    )
    for value in waits:
        c.need(
            value == metadata.file(directory / (value["operation"] + ".wait4.json"))
            and value.get("measurement") == "os.wait4 direct owned child"
            and value.get("exit_code") == 0
            and value.get("timed_out") is False
            and value.get("interruption_type") is None
            and value.get("pid") == value.get("waited_pid")
            and type(value.get("pid")) is int
            and value["pid"] > 0
            and all(
                nonnegative(value.get(k))
                for k in (
                    "wall_seconds",
                    "user_cpu_seconds",
                    "system_cpu_seconds",
                    "peak_rss_bytes",
                )
            ),
            "Transport child cost was not closed successfully",
        )
    child_cpu = sum(v["user_cpu_seconds"] + v["system_cpu_seconds"] for v in waits)
    c.need(
        all(
            nonnegative(cost.get(k))
            for k in (
                "wall_seconds",
                "cpu_seconds",
                "transport_child_cpu_seconds",
                "parent_self_cpu_delta_seconds",
            )
        )
        and math.isclose(cost["transport_child_cpu_seconds"], child_cpu, abs_tol=1e-9)
        and math.isclose(
            cost["cpu_seconds"],
            child_cpu + cost["parent_self_cpu_delta_seconds"],
            abs_tol=1e-9,
        ),
        "Transport CPU attribution differs",
    )
    return ack


def operational_gate(config, config_item, terminal_item, metadata):
    """Metadata/streamed bytes only. No model, endpoint, bank or outcome decoder."""
    ops, raw, source = (
        Path(config[k]) for k in ("ops_root", "raw_root", "source_root")
    )
    metadata.check(config_item)
    c.need(
        not (ops / "FAILED.json").exists(),
        "Failed primary episode cannot be reviewed as complete",
    )
    frozen = metadata.read(config["descriptors"]["controller_freeze"])
    c.need(
        frozen["source_files"] == config["source_files"],
        "Full initial source closure differs",
    )
    for name, sha in config["source_files"].items():
        item = c.descriptor(source / name)
        c.need(item["sha256"] == sha, "Registered operational source changed")
        metadata.check(item)
    plan = metadata.read(config["descriptors"]["prospective_plan"])
    c.need(
        plan.get("execution07_source_closure") == config["source_files"]
        and plan.get("registered_source_commit") == config["source_commit"]
        and plan.get("execution_episode") == c.EPISODE
        and plan.get("imported_jobs") == [],
        "Prospective source closure differs",
    )
    runtime = metadata.read(config["descriptors"]["runtime_receipt"])
    contract = metadata.file(c.OWN / "INPUT_CONTRACT.json")
    asset_receipt = metadata.read(config["descriptors"]["assets_receipt"])
    expected_assets = [
        {**row, "path": str(Path(config["assets_root"]) / row["path"])}
        for row in contract["assets"]
    ]
    c.need(
        len(expected_assets) == 9
        and asset_receipt.get("files") == expected_assets
        and asset_receipt.get("decoded") is False,
        "Original nine-input byte population differs",
    )
    for item in expected_assets:
        metadata.check(item)
        c.need(
            frozen["artifacts"].get(item["path"]) == item["sha256"],
            "Controller freeze omitted a direct scientific asset pin",
        )
    for phase in ("a_freeze", "c_freeze"):
        source_freeze = metadata.read(config["descriptors"][phase])
        c.need(
            all(
                source_freeze["artifacts"].get(item["path"]) == item["sha256"]
                for item in expected_assets
            ),
            "Scientific freeze omitted a direct input asset pin",
        )
    c.need(
        runtime.get("schema") == "hepta.execution07.destination-runtime.1"
        and runtime.get("execution_episode") == c.EPISODE
        and runtime.get("source_commit") == config["source_commit"]
        and runtime.get("old_host_receipt_reused") is False
        and runtime.get("science_started") is False
        and runtime["runtime"].get("exact_match") is True
        and runtime["runtime"].get("runtime_sha256")
        == contract["runtime_expected"]["runtime_sha256"]
        and len(runtime["capacity_samples"]) == 3
        and all(
            v["capacity"].get("original_joint_pass") is True
            and v["cgroup_root"].get("finite_limit") == 8 * 1024**3
            for v in runtime["capacity_samples"]
        ),
        "Actual destination runtime/resource gate is absent",
    )
    complete_item = c.descriptor(ops / "COMPLETE.json")
    complete = metadata.read(complete_item)
    c.need(
        complete.get("schema") == "hepta.fullstudy.pipeline-completion.4"
        and complete.get("complete") is True
        and complete.get("execution_episode") == c.EPISODE
        and complete.get("pipeline_config") == config_item
        and complete.get("jobs")
        == complete.get("scientific_jobs_executed_here")
        == list(c.ORDER)
        and complete.get("jobs_imported") == 0
        and complete.get("imported_jobs") == []
        and complete.get("jobs_executed_here") == 14
        and complete.get("required_finalizer_seals_verified") == 30,
        "Primary completion is not the full fresh fourteen-job episode",
    )
    stages = complete["durable_stages"]
    c.need(len(stages) == 17, "All seventeen primary ACKs are required")
    identity, ids, coverage = config["actions_identity"], set(), {}
    for index, row in enumerate(stages):
        binding = {
            "execution_episode": c.EPISODE,
            "sequence": index + 1,
            "label": LABELS[index],
            "pipeline_config": config_item,
            "completed_jobs": list(c.ORDER[: min(index + 1, 14)]),
            "previous_ack": None if index == 0 else stages[index - 1]["ack"],
        }
        ack = verify_ack(metadata, row, binding, identity)
        identity = ack["identity"]
        c.need(
            identity["head_sha"] == config["source_commit"]
            and ack["artifact"]["id"] not in ids,
            "Provider source commit differs or immutable artifact was reused",
        )
        ids.add(ack["artifact"]["id"])
        for item in ack["logical_files"]:
            if item["path"].startswith("raw/"):
                coverage[item["path"][4:]] = {k: item[k] for k in ("bytes", "sha256")}
    artifacts = complete["artifacts"]
    c.need(
        set(artifacts)
        == {"verified", "manifest", "aggregate_results", "finalizer_freeze"},
        "Original public artifact interface differs",
    )
    manifest = metadata.read(artifacts["manifest"])
    finalizer = metadata.read(artifacts["finalizer_freeze"])
    c.need(
        all(
            finalizer["source_files"].get(k) == v
            for k, v in config["source_files"].items()
        ),
        "Finalizer dropped operational source pins",
    )
    for name, item in manifest["logical_paths"].items():
        logical(name)
        expected = {k: item[k] for k in ("bytes", "sha256")}
        c.need(
            coverage.get(name) == expected,
            "External archive does not cover final raw bytes: " + name,
        )
        metadata.check({"path": str(raw / name), **expected})
    # All direct children are complete; nested measurements describe attribution, not extra cost.
    population = (
        set(c.ORDER)
        | {"register_" + s for s in ("followups", "endpoints", "analysis", "finalizer")}
        | {"analysis", "finalizer"}
    )
    workers = ops / "owned_workers"
    c.need(
        {p.name for p in workers.iterdir()} == population,
        "Direct child measurement population differs",
    )
    costs = {
        name: wait4(metadata, workers / name, config_item=config_item)
        for name in sorted(population)
    }
    wrapper_population = set(c.ORDER) | {
        "ANALYSIS_PARENT",
        "ANALYSIS_CHILD",
        "FINALIZER",
    }
    wrappers = ops / "wrapper_runs"
    c.need(
        {p.name for p in wrappers.iterdir()} == wrapper_population,
        "Seventeen original worker wrapper scopes are required",
    )
    for name in wrapper_population:
        directory = wrappers / name
        c.need(not (directory / "FAILED.json").exists(), "A worker wrapper failed")
        start, result = (
            metadata.file(directory / "START.json"),
            metadata.file(directory / "COMPLETE.json"),
        )
        c.need(
            start.get("execution_episode")
            == result.get("execution_episode")
            == c.EPISODE
            and start.get("pipeline_config")
            == result.get("pipeline_config")
            == config_item
            and result.get("complete") is True
            and result.get("original_entrypoint_returned_successfully") is True,
            "Actual worker wrapper completion or source differs",
        )
    nested = wait4(
        metadata, wrappers / "ANALYSIS_PARENT/owned_children", config_item=config_item
    )
    initial_plan = metadata.read(config["initialization_intent"])
    c.need(
        initial_plan.get("execution_episode") == c.EPISODE
        and initial_plan.get("source_commit") == config["source_commit"]
        and initial_plan.get("program") == c.descriptor(c.OWN / "initialize.py")
        and initial_plan.get("python") == config["python"]
        and initial_plan.get("base_argv")
        == ["--source-commit", config["source_commit"]],
        "Actual initialization plan identity differs",
    )
    initial_argv = [
        config["python"],
        "-B",
        initial_plan["program"]["path"],
        *initial_plan["base_argv"],
        "--initialization-intent",
        config["initialization_intent"]["path"],
        "--initialization-intent-sha256",
        config["initialization_intent"]["sha256"],
    ]
    initialization = wait4(
        metadata,
        Path(config["initialization_intent"]["path"]).parent / "children",
        argv=initial_argv,
    )
    semantic_item = c.descriptor(ops / "registrations/initial/SEMANTIC_PREFLIGHT.json")
    semantic = metadata.read(semantic_item)
    c.need(
        semantic.get("schema") == "hepta.execution07.initial-semantic-preflight.1"
        and semantic.get("complete") is True
        and semantic.get("execution_episode") == c.EPISODE
        and semantic.get("pipeline_config") == config_item
        and semantic.get("source_commit") == config["source_commit"]
        and [row.get("id") for row in semantic.get("initial_jobs", [])]
        == list(c.ORDER[:4])
        and all(
            row.get("validator_returned_without_model_or_data_loader") is True
            and row.get("source_freeze")
            == config["descriptors"]["c_freeze" if row["id"] == "C" else "a_freeze"]
            for row in semantic["initial_jobs"]
        )
        and semantic.get("controller_freeze")
        == config["descriptors"]["controller_freeze"]
        and all(
            semantic.get(key) is True
            for key in (
                "original_resource_registration_validator_passed",
                "original_controller_queue_job_and_phase_validators_passed",
                "loaded_repository_source_closure_verified",
                "raw_and_cas_untouched",
            )
        )
        and semantic.get("scientific_workers_started")
        == semantic.get("scheduled_gradient_microsteps")
        == 0
        and semantic.get("model_created") is False
        and semantic.get("scientific_inputs_opened") is False,
        "Original C2 metadata validators were not completed before first science",
    )
    semantic_argv = [
        config["python"],
        "-B",
        str(c.OWN / "semantic_preflight.py"),
        "--config",
        config_item["path"],
        "--expected-config-sha256",
        config_item["sha256"],
    ]
    semantic_cost = wait4(
        metadata,
        ops / "registrations/initial/semantic_measurement",
        config_item=config_item,
        argv=semantic_argv,
    )
    supervisor_argv = [
        config["python"],
        "-B",
        str(c.OWN / "supervisor.py"),
        "--config",
        config_item["path"],
        "--expected-config-sha256",
        config_item["sha256"],
    ]
    supervisor = wait4(
        metadata, ops / "outer_wait4", config_item=config_item, argv=supervisor_argv
    )
    closure = metadata.read(terminal_item)
    c.need(
        closure.get("schema") == "hepta.execution07.terminal-closure.1"
        and closure.get("complete") is True
        and closure.get("execution_episode") == c.EPISODE
        and closure.get("pipeline_config") == config_item
        and closure.get("this_closure_in_its_referenced_terminal_archive") is False,
        "Separate terminal closure is missing",
    )
    publication = metadata.read(closure["publication"])
    c.need(
        publication.get("schema") == "hepta.execution07.terminal-publication.1"
        and publication.get("execution_episode") == c.EPISODE
        and publication.get("pipeline_config") == config_item
        and publication.get("primary_completion") == complete_item
        and publication["terminal_archive"]["ack"] == closure["terminal_ack"],
        "Terminal publication binding differs",
    )
    binding = {
        "execution_episode": c.EPISODE,
        "sequence": 18,
        "label": "terminal_metadata",
        "pipeline_config": config_item,
        "completed_jobs": list(c.ORDER),
        "previous_ack": stages[-1]["ack"],
    }
    terminal = verify_ack(
        metadata, publication["terminal_archive"], binding, identity, terminal=True
    )
    c.need(
        terminal["artifact"]["id"] not in ids,
        "Terminal artifact reused a primary immutable ID",
    )
    terminal_files = {
        r["path"]: {k: r[k] for k in ("bytes", "sha256")}
        for r in terminal["logical_files"]
    }
    required = {
        "ops/COMPLETE.json": complete_item,
        "metadata/PIPELINE_CONFIG.json": config_item,
        "ops/" + Path(stages[-1]["ack"]["path"]).relative_to(ops).as_posix(): stages[
            -1
        ]["ack"],
    }
    for name, measurement in (
        ("ops/outer_wait4", supervisor),
        ("initialization_measurement/children", initialization),
    ):
        for key, filename in (("wait4", "001.WAIT4.json"), ("closure", "CLOSURE.json")):
            required[name + "/" + filename] = measurement[key]
    c.need(
        all(
            terminal_files.get(k)
            == {field: item[field] for field in ("bytes", "sha256")}
            for k, item in required.items()
        ),
        "Terminal archive lacks primary completion or actual owner costs",
    )
    publication_argv = [
        config["python"],
        "-B",
        str(c.OWN / "terminal.py"),
        "publish-child",
        "--config",
        config_item["path"],
        "--expected-config-sha256",
        config_item["sha256"],
    ]
    publication_cost = wait4(
        metadata,
        ops / "terminal_publication_measurement",
        config_item=config_item,
        argv=publication_argv,
    )
    c.need(
        closure["publication_measurement"]
        == {k: publication_cost[k] for k in ("wait4", "closure")},
        "Terminal owner wait4 binding differs",
    )
    return complete, {
        "status": "SOURCE_COST_17_PRIMARY_AND_TERMINAL_DELIVERY_VERIFIED",
        "execution_episode": c.EPISODE,
        "primary_barriers": 17,
        "terminal_barriers": 1,
        "actual_transport_children": 36,
        "github_identity": identity,
        "provider_artifact_ids": sorted([*ids, terminal["artifact"]["id"]]),
        "final_raw_files_stream_hash_verified": len(manifest["logical_paths"]),
        "direct_child_attribution": costs,
        "closed_inclusive_intervals": {
            "initialization": initialization,
            "original_semantic_preflight": semantic_cost,
            "supervisor": supervisor,
            "terminal_publication": publication_cost,
        },
        "wrapper_completions": 17,
        "analysis_nested_child_attribution": nested,
        "direct_child_and_transport_costs_already_inside_inclusive_intervals": True,
        "environment_preparation_cpu": "unknown; use actual workflow wall durations separately",
        "postseal_and_pipeline_owner_wait4": "Pending their actual process exits; retained by bootstrap separately, not fabricated here",
        "terminal_closure_is_not_claimed_inside_its_own_archive": True,
        "historical_costs_complete": False,
        "scientific_payloads_decoded": False,
    }


def original_supplement(config):
    path = (
        c.SOURCE
        / "supplements/parameter_field_fullstudy_20261030/postseal_supplement.py"
    )
    c.need(
        c.descriptor(path)["sha256"]
        == config["source_files"][path.relative_to(c.SOURCE).as_posix()],
        "Original supplement source changed",
    )
    spec = importlib.util.spec_from_file_location("execution07_original_postseal", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.EPISODE = c.EPISODE
    return module


def science_gate_args(config, complete):
    result = {
        "raw_root": config["raw_root"],
        "source_root": config["source_root"],
        "plan": config["descriptors"]["prospective_plan"]["path"],
        "expected_plan_sha256": config["descriptors"]["prospective_plan"]["sha256"],
    }
    item = c.descriptor(Path(config["ops_root"]) / "COMPLETE.json")
    result.update(
        pipeline_complete=item["path"], expected_pipeline_sha256=item["sha256"]
    )
    for name in ("verified", "manifest", "finalizer_freeze"):
        result[name], result["expected_" + name + "_sha256"] = (
            complete["artifacts"][name]["path"],
            complete["artifacts"][name]["sha256"],
        )
    return SimpleNamespace(**result)


def review(config, config_item, terminal_item, output):
    output = Path(output).absolute()
    c.need(
        output == Path(config["ops_root"]).parent / "postseal" and not output.exists(),
        "Fresh canonical postseal destination required",
    )
    started, cpu = time.monotonic(), time.process_time()
    metadata = Metadata()
    complete, operations = operational_gate(
        config, config_item, terminal_item, metadata
    )
    original = original_supplement(config)
    inputs = original.Inputs()
    plan, store, protocol, gate = original.gate(
        science_gate_args(config, complete), inputs, output
    )
    # No diagnostic value decoder or numeric package is imported until both gates returned.
    output.mkdir(parents=True, exist_ok=False)
    import numpy as np
    from operational.parameter_field_five_questions_20261031 import (
        postseal_analysis_coverage as coverage,
    )
    from supplements.parameter_field_execution_20261031 import p0_actions, run_review
    from operational.parameter_field_five_questions_20261031.finite_head_guard import (
        make_guarded_choose,
    )

    choose = original.frozen_choose(c.SOURCE, inputs, np)
    banks, summaries, details, differences, issue_rows = original.bank_analysis(
        store, np
    )
    calibration, calibration_rows = original.calibration_analysis(
        store, banks, np, make_guarded_choose(choose)
    )
    witness, witness_issues = original.witness_analysis(store, banks)
    issue_rows.extend(witness_issues)
    issues = {
        "issue_count": len(issue_rows),
        "issues": issue_rows,
        "primary_results_not_rewritten": True,
        "any_issue_precludes_unqualified_interpretation": True,
    }
    outputs = {}
    for name, rows in (
        ("SUCCESSOR_DIFFERENCES.jsonl", differences),
        ("GATED_CALIBRATION_ROWS.jsonl", calibration_rows),
        ("EQUAL_DYNAMICS_GROUPS.jsonl", details),
    ):
        original.write_jsonl(output / name, rows)
        outputs[name] = c.descriptor(output / name)
    diagnostics = {
        "BANK_SUMMARY.json": {"models": summaries},
        "GATED_CALIBRATION.json": {
            "models_and_modes": calibration,
            "new_independent_samples": 0,
            "calibration_parents_are_dependent": True,
            "certificate": False,
            "original_chooser_finite_head_guard": "Read-only diagnostic wrapper; no live guard installation is claimed",
        },
        "W_SHARED_ACTION_REGRET.json": {
            "records": witness,
            "reachable_policy_occupancy_established": False,
        },
        "INTEGRITY_ISSUES.json": issues,
        "GATE.json": gate,
        "OPERATIONAL_GATE.json": operations,
    }
    for name, value in diagnostics.items():
        outputs[name] = c.write_new(output / name, value)
    context = {
        "gate": gate,
        "inputs": inputs,
        "store": store,
        "plan": plan,
        "outputs": outputs,
        "issues": issues,
    }
    aggregate_item = complete["artifacts"]["aggregate_results"]
    aggregate = inputs.descriptor_json(aggregate_item, "admitted_original_aggregate")
    history = metadata.file(c.OWN / "HISTORICAL_COSTS.json")
    historical_gate = history["original_integrity"]["historical_exact_regression_gate"]
    c.need(
        aggregate.get("historical_exact_regression_gate") == historical_gate
        and aggregate.get("integrity") == history["original_integrity"],
        "Original historical integrity disposition changed",
    )
    audit = coverage.aggregate_checks(aggregate)
    p0 = p0_actions.analyze(context)
    unified = run_review.assemble(aggregate, {"integrity_issues": issues}, audit, p0)
    unified["historical_integrity"] = history["original_integrity"]
    # Original thresholds and science outputs stay in the original aggregate; no refit/bootstrap occurs here.
    outputs["UNIFIED_REVIEW.json"] = c.write_new(
        output / "UNIFIED_REVIEW.json", unified
    )
    inputs.unchanged()
    metadata.stable()
    c.committed_sources(c.SOURCE, config["source_commit"], config["source_files"])
    outputs["INPUTS.json"] = c.write_new(
        output / "INPUTS.json",
        {
            "operational": sorted(metadata.items.values(), key=lambda x: x["path"]),
            "scientific": list(inputs.rows.values()),
            "all_consumed_input_bytes_verified": True,
            "scientific_inputs_modified": False,
        },
    )
    result = {
        "schema": SCHEMA,
        "complete": True,
        "execution_episode": c.EPISODE,
        "pipeline_config": config_item,
        "terminal_closure": terminal_item,
        "status": unified["status"],
        "outputs": outputs,
        "original_statistical_gates": unified["original_statistical_gates"],
        "integrity_issues": issues,
        "historical_integrity": history["original_integrity"],
        "operational_gate": operations,
        "primary_scientific_gate": gate,
        "original_scientific_analysis_changed": False,
        "new_bootstrap_training_scoring_refitting": False,
        "new_independent_samples": 0,
        "certificate": False,
        "adoption": "not_assessed",
        "cpu_seconds_before_final_receipt": time.process_time() - cpu,
        "wall_seconds_before_final_receipt": time.monotonic() - started,
        "timing_scope": "In-process review before final serialization; external owned wait4 is authoritative and closes after exit.",
        "preparation_installation_cpu_total_known": False,
        "historical_campaign_cost_complete": False,
        "delivery_scope": "These review outputs and terminal closure require the workflow final operations artifact; no self-referential archive claim.",
    }
    c.write_new(output / "COMPLETE.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "config",
        "expected-config-sha256",
        "terminal-closure",
        "expected-terminal-closure-sha256",
        "output",
    ):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--execute-post-seal", action="store_true")
    args = parser.parse_args(argv)
    try:
        c.need(args.execute_post_seal, "Explicit postseal invocation required")
        config, item = c.load_config(args.config, args.expected_config_sha256)
        terminal = c.descriptor(args.terminal_closure)
        c.need(
            terminal["sha256"] == args.expected_terminal_closure_sha256
            and Path(terminal["path"])
            == Path(config["ops_root"]) / "TERMINAL_CLOSURE.json",
            "Actual terminal closure pin differs",
        )
        result = review(config, item, terminal, args.output)
        print(
            c.encode(
                {
                    "schema": SCHEMA,
                    "complete": True,
                    "status": result["status"],
                    "completion": c.descriptor(Path(args.output) / "COMPLETE.json"),
                }
            ).decode(),
            end="",
        )
        # A negative or incomplete scientific/cost finding is a completed review, never a manufactured efficacy pass.
        return 0
    except (
        ValueError,
        KeyError,
        TypeError,
        OSError,
        ImportError,
        OverflowError,
        FloatingPointError,
        zipfile.BadZipFile,
    ) as error:
        print(
            c.encode(
                {
                    "schema": SCHEMA,
                    "complete": False,
                    "status": "BLOCKED_OR_FAILED_REVIEW",
                    "reason": str(error),
                    "scientific_completion_claim": False,
                    "partial_output_preserved": True,
                }
            ).decode(),
            file=sys.stderr,
            end="",
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
