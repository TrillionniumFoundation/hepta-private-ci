"""Fresh execution07 metadata registration around the unchanged original helpers."""

import argparse
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from operational.parameter_field_recovery07 import common as c  # noqa: E402
from operational.parameter_field_recovery07.analysis_worker import history  # noqa: E402

PACKAGE = "experiments.parameter_field_fullstudy_20261029"


def original_module(name, config):
    relative = c.PREFIX + name + ".py"
    path = c.SOURCE / relative
    c.need(
        c.descriptor(path)["sha256"] == config["source_files"][relative],
        "Original helper changed",
    )
    # A distinct namespace leaves the original imported module and its globals intact.
    spec = importlib.util.spec_from_file_location(
        PACKAGE + "._execution07_" + name, path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def serial_extension(original, queue, additions, root, final):
    value = original(queue, additions, root, final)
    expected = list(c.ORDER[: 14 if final else 11])
    c.need(
        [j["id"] for j in value["jobs"]] == expected,
        "Original fixed queue order differs",
    )
    c.need(
        value["jobs"][: len(queue["jobs"])] == queue["jobs"],
        "Original helper changed accepted jobs",
    )
    value = deepcopy(value)
    for index in range(len(queue["jobs"]), len(value["jobs"])):
        job = value["jobs"][index]
        job["requires"] = sorted(set(job["requires"]) | {expected[index - 1]})
    value["execution_episode"] = c.EPISODE
    return value


def verified_bundle(directory):
    bundle_item = c.descriptor(directory / "BUNDLE.json")
    bundle = c.bound(bundle_item)
    c.need(
        bundle.get("workers_started") == 0, "Registration unexpectedly started workers"
    )
    files = {}
    for name, expected in bundle["files"].items():
        c.need(
            Path(name).name == name
            and name
            not in ("BUNDLE.json", "REGISTRATION_COST.json", "REGISTRATION.json"),
            "Unsafe bundle member",
        )
        item = c.descriptor(directory / name)
        c.need(
            {k: item[k] for k in ("bytes", "sha256")} == expected,
            "Sealed registration member differs",
        )
        files[name] = item
    cost = c.descriptor(directory / "REGISTRATION_COST.json")
    c.need(
        c.bound(cost)["bundle"] == bundle_item, "Registration cost binds another bundle"
    )
    files.update({"BUNDLE.json": bundle_item, "REGISTRATION_COST.json": cost})
    return files


def input_queue(config, stage):
    prior = {
        "followups": None,
        "endpoints": "followups",
        "analysis": "endpoints",
        "finalizer": "endpoints",
    }[stage]
    if prior is None:
        return config["descriptors"]["initial_queue"]
    record = c.read(
        Path(config["ops_root"]) / "registrations" / prior / "REGISTRATION.json"
    )
    c.need(
        record.get("schema") == "hepta.execution07.registration.1"
        and record.get("execution_episode") == c.EPISODE
        and record.get("stage") == prior
        and record.get("workers_started") == 0
        and record.get("queue_activated") is False,
        "Preceding registration identity differs",
    )
    return record["queue"]


def cost_context(module, config):
    """Bind a truthful new projection; do not impersonate absent old receipts."""
    original_inputs, original_bundle = module.analysis_inputs, module.write_bundle
    value, projection = history()
    adapter = c.descriptor(c.OWN / "analysis_worker.py")
    old_path = c.SOURCE / c.PREFIX / "evidence/REPORT_INPUTS_BLOCKED.json"
    original_history = c.descriptor(old_path)
    c.need(
        original_history["sha256"] == module.HISTORY_SHA,
        "Original historical declaration changed",
    )
    original_value = c.bound(original_history)
    c.need(
        original_value["integrity"] == value["original_integrity"],
        "Historical failure disposition changed",
    )

    def historical(args, artifacts):
        c.need(
            Path(args.historical_inputs) == old_path
            and args.expected_historical_sha256 == module.HISTORY_SHA,
            "Original historical declaration identity differs",
        )
        for item in (original_history, projection, adapter):
            c.need(
                module.add(artifacts, item["path"]) == item,
                "Historical projection binding changed",
            )
        return {
            "integrity": deepcopy(value["original_integrity"]),
            "engineering_preflights": [],
            "failed_attempts": [],
            "resource_status": {
                "status": "HISTORICAL_COST_PROJECTION_EXPLICIT_UNKNOWN_REMAINDER",
                "original_report_inputs": original_history,
                "projection": projection,
                "old_receipts_bundled": False,
                "whole_history_cpu_or_wall_total_known": False,
            },
        }, original_history

    def inputs(*args):
        result = original_inputs(*args)
        result["execution07_historical_costs"] = {
            "schema": "hepta.execution07.cost-adapter-binding.1",
            "projection": projection,
            "adapter_source": adapter,
        }
        result["execution_episode"] = c.EPISODE
        return result

    def bundle(output, payloads, metadata):
        # The change occurs before the original helper hashes/seals the bundle.
        for name in ("ANALYSIS_SOURCE_FREEZE.json", "FINALIZER_SOURCE_FREEZE.json"):
            if name in payloads:
                frozen = c.strict_json(payloads[name])
                frozen["execution_episode"] = c.EPISODE
                frozen["execution07_cost_adapter"] = {
                    "source": adapter,
                    "projection": projection,
                    "scientific_analysis_changed": False,
                    "original_historical_receipts_reconstructed": False,
                }
                if name == "FINALIZER_SOURCE_FREEZE.json":
                    frozen.update(
                        evidence_id="verification07",
                        evidence_relative="evidence_v2/verification07",
                    )
                payloads[name] = module.encode(frozen)
        return original_bundle(
            output, payloads, {**metadata, "execution_episode": c.EPISODE}
        )

    module.historical_inputs, module.analysis_inputs, module.write_bundle = (
        historical,
        inputs,
        bundle,
    )


def register(config, config_item, stage):
    c.need(
        stage in ("followups", "endpoints", "analysis", "finalizer"),
        "Unknown registration stage",
    )
    queue_item = input_queue(config, stage)
    c.checked(queue_item)
    count = {"followups": 4, "endpoints": 11, "analysis": 14, "finalizer": 14}[stage]
    c.need(
        [j["id"] for j in c.bound(queue_item)["jobs"]] == list(c.ORDER[:count]),
        "Input queue population differs",
    )
    target = Path(config["ops_root"]) / "registrations" / stage
    c.need(not target.exists(), "Registration cannot overwrite prior evidence")
    pins = config["descriptors"]
    common = dict(
        stage=stage,
        root=config["raw_root"],
        output=str(target),
        source_git_root=config["source_root"],
        source_commit=config["source_commit"],
        amendment=pins["amendment"]["path"],
        amendment_sha256=pins["amendment"]["sha256"],
        queue=queue_item["path"],
        expected_queue_sha256=queue_item["sha256"],
    )
    if stage in ("followups", "endpoints"):
        module = original_module("register_followups_v2", config)
        old_extension = module.queue_extension
        module.queue_extension = lambda *args: serial_extension(old_extension, *args)
        args = SimpleNamespace(
            **common,
            assets=config["assets_root"],
            a_freeze=pins["a_freeze"]["path"],
            a_freeze_sha256=pins["a_freeze"]["sha256"],
            c_freeze=pins["c_freeze"]["path"],
            c_freeze_sha256=pins["c_freeze"]["sha256"],
        )
    else:
        module = original_module("register_summary_v2", config)
        cost_context(module, config)
        analysis = None
        if stage == "finalizer":
            analysis = verified_bundle(
                Path(config["ops_root"]) / "registrations/analysis"
            )["ANALYSIS_SOURCE_FREEZE.json"]
        args = SimpleNamespace(
            **common,
            controller_freeze=pins["controller_freeze"]["path"],
            controller_freeze_sha256=pins["controller_freeze"]["sha256"],
            analysis_id="analysis07",
            analysis_freeze=None if analysis is None else analysis["path"],
            analysis_freeze_sha256=None if analysis is None else analysis["sha256"],
            historical_inputs=str(
                c.SOURCE / c.PREFIX / "evidence/REPORT_INPUTS_BLOCKED.json"
            ),
            expected_historical_sha256=module.HISTORY_SHA,
        )
    result = module.register(args)
    files = verified_bundle(target)
    c.need(
        files["BUNDLE.json"] == result["bundle"]
        and files["REGISTRATION_COST.json"] == result["registration_cost"],
        "Original helper returned another registration",
    )
    c.committed_sources(c.SOURCE, config["source_commit"], config["source_files"])
    c.checked(config_item)
    record = {
        "schema": "hepta.execution07.registration.1",
        "execution_episode": c.EPISODE,
        "stage": stage,
        "configuration": config_item,
        "input_queue": queue_item,
        "queue": files.get("QUEUE_EXTENDED.json", queue_item),
        "files": files,
        "bundle": result["bundle"],
        "registration_cost": result["registration_cost"],
        "workers_started": 0,
        "queue_activated": False,
        "scientific_payloads_decoded": False,
        "original_helper": c.descriptor(Path(module.__file__).resolve()),
        "new_operational_registration_not_old_episode_recovery": True,
    }
    return c.write_new(target / "REGISTRATION.json", record)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--expected-config-sha256", required=True)
    parser.add_argument(
        "--stage",
        required=True,
        choices=("followups", "endpoints", "analysis", "finalizer"),
    )
    args = parser.parse_args()
    config, item = c.load_config(args.config, args.expected_config_sha256)
    print(
        c.encode({"registration": register(config, item, args.stage)}).decode(), end=""
    )


if __name__ == "__main__":
    main()
