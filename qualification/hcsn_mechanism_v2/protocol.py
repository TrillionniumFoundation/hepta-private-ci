"""Source-bound one-use phases for independent mechanism confirmation.

An explicit published source closure replaces Git-worktree assumptions. The
registry and output markers use exclusive creation; failures remain consumed.
Only JSON records are read during reporting. No final outcome selects a model.
"""

import hashlib
import importlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import sys
import time

try:
    import resource
except ImportError:
    resource = None


STAGES = ("representation", "control", "clock", "readout", "profiled")
ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def object_sha(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def save(path, value):
    with Path(path).open("x", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")


def validate_source(source, root=ROOT):
    if (
        source.get("publication_status") != "published"
        or re.fullmatch(r"[0-9a-f]{40}", source.get("source_commit", "")) is None
        or re.fullmatch(r"[0-9a-f]{40}", source.get("source_tree", "")) is None
        or not isinstance(source.get("files"), list)
    ):
        raise ValueError(
            "formal source must name a published commit/tree and complete file closure"
        )
    paths = set()
    root = Path(root).resolve()
    for entry in source["files"]:
        path = Path(entry["path"])
        if path.is_absolute() or ".." in path.parts or entry["path"] in paths:
            raise ValueError("duplicate or escaping source path")
        resolved = (root / path).resolve()
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise ValueError("source closure member missing or outside source root")
        raw = resolved.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if (
            len(raw) != entry["size"]
            or hashlib.sha256(raw).hexdigest() != entry["sha256"]
            or blob != entry["git_blob"]
            or entry["mode"] != "100644"
        ):
            raise ValueError(f"source byte identity changed: {path}")
        paths.add(entry["path"])
    for path in (root / "qualification/hcsn_mechanism_v2").glob("*.py"):
        if str(path.relative_to(root)) not in paths:
            raise ValueError("unregistered mechanism source")
    return sorted(paths)


def runtime():
    import torch

    return {
        "python": platform.python_version(),
        "executable": sys.executable,
        "resolved_executable": str(Path(sys.executable).resolve()),
        "executable_sha256": sha(Path(sys.executable).resolve()),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "packages": {
            name: importlib.metadata.version(name) for name in ("numpy", "torch")
        },
        "torch_module": torch.__file__,
        "torch_module_sha256": sha(torch.__file__),
        "actual_default_tensor_device": str(torch.empty(0).device),
        "torch_threads": torch.get_num_threads(),
        "torch_interop_threads": torch.get_num_interop_threads(),
        "cuda_build_version": torch.version.cuda,
        "execution_scope": "CPU FP64 dense; shared host, not an exclusive CPU measurement",
    }


def validate_plan(plan):
    if (
        plan.get("schema") != "hepta.hcsn-mechanism.v2"
        or not plan.get("namespace", "").startswith("hcsn-mechanism-v2/")
        or len(plan["namespace"]) < 45
        or plan.get("stages") != list(STAGES)
        or len(plan.get("seeds", [])) != 5
        or len(set(plan["seeds"])) != 5
        or any(type(seed) is not int or seed < 0 for seed in plan["seeds"])
        or set(plan["seeds"]) & {1907341, 4812467, 8629119}
    ):
        raise ValueError(
            "fresh registered mechanism plan with five independent seeds required"
        )
    if (
        plan["representation"]["tasks"] != plan["tasks"]
        or plan["readout"]["tasks"] != plan["tasks"]
        or not set(plan["profiled"]["tasks"]).issubset(plan["tasks"])
    ):
        raise ValueError("case grid disagrees with declared task families")


def freeze(plan_path, source_path, manifest_path, registry):
    plan, source = (
        json.loads(Path(plan_path).read_text()),
        json.loads(Path(source_path).read_text()),
    )
    validate_plan(plan)
    validate_source(source)
    directory = Path(registry)
    directory.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(plan["namespace"].encode()).hexdigest()
    allocation = directory / f"{key}.allocation.json"
    manifest = {
        "plan": plan,
        "plan_sha256": sha(plan_path),
        "source": source,
        "source_manifest_sha256": sha(source_path),
        "runtime": runtime(),
        "plan_object_sha256": object_sha(plan),
        "source_object_sha256": object_sha(source),
        "source_root": str(ROOT),
        "registry": str(directory.resolve()),
        "allocation_key": key,
        "frozen_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    save(
        allocation,
        {
            "namespace": plan["namespace"],
            "plan_sha256": sha(plan_path),
            "source_manifest_sha256": sha(source_path),
            "source_commit": source["source_commit"],
            "plan_object_sha256": object_sha(plan),
            "source_object_sha256": object_sha(source),
        },
    )
    save(manifest_path, manifest)
    return {"manifest_sha256": sha(manifest_path), "allocation": str(allocation)}


def verify(manifest_path):
    manifest = json.loads(Path(manifest_path).read_text())
    validate_plan(manifest["plan"])
    validate_source(manifest["source"])
    if manifest["source_root"] != str(ROOT) or manifest["runtime"] != runtime():
        raise ValueError("runtime or source deployment differs from frozen identity")
    allocation = json.loads(
        (
            Path(manifest["registry"]) / f"{manifest['allocation_key']}.allocation.json"
        ).read_text()
    )
    if (
        allocation["namespace"] != manifest["plan"]["namespace"]
        or allocation["source_manifest_sha256"] != manifest["source_manifest_sha256"]
        or allocation["plan_sha256"] != manifest["plan_sha256"]
        or allocation["plan_object_sha256"] != object_sha(manifest["plan"])
        or allocation["source_object_sha256"] != object_sha(manifest["source"])
        or manifest["plan_object_sha256"] != allocation["plan_object_sha256"]
        or manifest["source_object_sha256"] != allocation["source_object_sha256"]
        or allocation["source_commit"] != manifest["source"]["source_commit"]
        or manifest["allocation_key"]
        != hashlib.sha256(manifest["plan"]["namespace"].encode()).hexdigest()
    ):
        raise ValueError("allocation binding changed")
    return manifest


def cases(plan, stage):
    tasks = ("review_control",) if stage == "control" else plan[stage]["tasks"]
    return [(task, seed) for task in tasks for seed in plan["seeds"]]


def record_failures(value, prefix="record"):
    if isinstance(value, dict):
        found = (
            [prefix] if value.get("status") in ("failed", "error", "invalid") else []
        )
        for key, item in value.items():
            found.extend(record_failures(item, f"{prefix}.{key}"))
        return found
    if isinstance(value, list):
        return [
            failure
            for index, item in enumerate(value)
            for failure in record_failures(item, f"{prefix}[{index}]")
        ]
    return []


def claim_phase(manifest_path, output, phase, selection_sha=None):
    manifest = verify(manifest_path)
    if phase not in ("fit", "final"):
        raise ValueError("declared phase required")
    output = Path(output)
    if phase == "fit":
        output.mkdir(parents=True, exist_ok=False)
    else:
        selected = output / "selection.json"
        if not selection_sha or sha(selected) != selection_sha:
            raise ValueError(
                "exact external selection digest required before final access"
            )
        previous = json.loads(selected.read_text())
        if (
            previous["manifest_sha256"] != sha(manifest_path)
            or previous.get("phase") != "fit"
        ):
            raise ValueError("selection belongs to a different frozen manifest")
        expected = {
            (stage, task, seed, f"fit/{stage}/{task}-{seed}.json")
            for stage in STAGES
            for task, seed in cases(manifest["plan"], stage)
        }
        actual = [
            (entry["stage"], entry["task"], entry["seed"], entry["path"])
            for entry in previous["cases"]
        ]
        if len(actual) != len(expected) or set(actual) != expected:
            raise ValueError(
                "selection must bind every expected fitted case exactly once"
            )
        for entry in previous["cases"]:
            if sha(output / entry["path"]) != entry["sha256"]:
                raise ValueError("fitted case changed after selection was sealed")
    marker = (
        Path(manifest["registry"])
        / f"{manifest['allocation_key']}.{phase}.consumed.json"
    )
    save(
        marker,
        {
            "manifest_sha256": sha(manifest_path),
            "phase": phase,
            "selection_sha256": selection_sha,
            "output": str(output.resolve()),
        },
    )
    save(output / f"{phase.upper()}_CONSUMED.json", json.loads(marker.read_text()))
    return manifest


def execute(manifest_path, output, phase, selection_sha=None):
    started, cpu_started = time.perf_counter(), time.process_time()
    manifest = claim_phase(manifest_path, output, phase, selection_sha)
    plan, output = manifest["plan"], Path(output)
    summary = {
        "manifest_sha256": sha(manifest_path),
        "phase": phase,
        "cases": [],
        "warmup": None,
    }
    # Shared cold startup is retained, not charged selectively to the first arm.
    if phase == "fit":
        from .readout import warmup

        summary["warmup"] = warmup(plan["readout"])
    for stage in STAGES:
        module = importlib.import_module(f"qualification.hcsn_mechanism_v2.{stage}_run")
        directory = output / phase / stage
        directory.mkdir(parents=True, exist_ok=False)
        cfg = {**plan, **plan[stage], "namespace": plan["namespace"] + "/" + stage}
        for task, seed in cases(plan, stage):
            if time.perf_counter() - started >= plan["phase_wall_seconds"]:
                raise TimeoutError(
                    "complete phase budget exhausted; namespace remains consumed"
                )
            begin, cpu_begin = time.perf_counter(), time.process_time()
            destination = directory / f"{task}-{seed}.json"
            try:
                if phase == "fit":
                    record = (
                        module.fit_case(seed, cfg)
                        if stage == "control"
                        else module.fit_case(task, seed, cfg)
                    )
                else:
                    saved = json.loads(
                        (output / "fit" / stage / destination.name).read_text()
                    )
                    record = (
                        module.final_case(saved["record"], seed, cfg)
                        if stage == "control"
                        else module.final_case(saved["record"], task, seed, cfg)
                    )
                save(
                    destination,
                    {
                        "stage": stage,
                        "task": task,
                        "seed": seed,
                        "record": record,
                        "wall_before_serialization": time.perf_counter() - begin,
                        "cpu_before_serialization": time.process_time() - cpu_begin,
                    },
                )
                failures = record_failures(record)
                if failures:
                    raise ValueError(
                        f"failed records preserved in {destination.name}: {failures}"
                    )
            except Exception as error:
                save(
                    destination.with_suffix(".failure.json"),
                    {
                        "stage": stage,
                        "task": task,
                        "seed": seed,
                        "error": repr(error),
                        "wall_seconds": time.perf_counter() - begin,
                        "phase_remains_consumed": True,
                    },
                )
                raise
            entry = {
                "stage": stage,
                "task": task,
                "seed": seed,
                "path": str(destination.relative_to(output)),
                "sha256": sha(destination),
                "bytes": destination.stat().st_size,
                "complete_case_wall_seconds": time.perf_counter() - begin,
                "complete_case_cpu_seconds": time.process_time() - cpu_begin,
            }
            summary["cases"].append(entry)
            print(
                json.dumps(
                    {
                        "completed": {
                            k: entry[k] for k in ("stage", "task", "seed", "sha256")
                        },
                        "phase": phase,
                        "case_seconds": entry["complete_case_wall_seconds"],
                    }
                ),
                flush=True,
            )
    validate_source(manifest["source"])
    expected = sum(len(cases(plan, stage)) for stage in STAGES)
    if len(summary["cases"]) != expected:
        raise ValueError("incomplete case grid")
    summary["wall_before_summary_serialization"] = time.perf_counter() - started
    summary["cpu_before_summary_serialization"] = time.process_time() - cpu_started
    summary["peak_process_rss_native_units"] = (
        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if resource is not None
        else None
    )
    destination = output / ("selection.json" if phase == "fit" else "final.json")
    save(destination, summary)
    save(
        destination.with_suffix(".completion.json"),
        {
            "summary_sha256": sha(destination),
            "complete_seconds": time.perf_counter() - started,
            "complete_cpu_seconds": time.process_time() - cpu_started,
            "outer_meter_required_for": "cold import before execute, completion serialization, stdout, process exit",
        },
    )
    return {"summary_sha256": sha(destination), "cases": expected}
