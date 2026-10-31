"""Run original initial-registration validators without invoking any science."""

import argparse
import importlib
from pathlib import Path
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from operational.parameter_field_recovery07 import common as c  # noqa: E402
from operational.parameter_field_recovery07.process import (  # noqa: E402
    EPISODE,
    GIB,
    PREFIX,
    checked,
    descriptor,
    read,
    require,
    write,
)
from operational.parameter_field_recovery07.job_queue import ORDER, canonical  # noqa: E402


def validate_initial(config, item):
    started, cpu = time.monotonic(), time.process_time()
    raw, cas = Path(config["raw_root"]), Path(config["cas_root"])
    require(
        all(path.is_dir() and not any(path.iterdir()) for path in (raw, cas)),
        "Initial semantic preflight requires untouched fresh RAW and CAS",
    )
    require(
        not any(name.split(".")[0] in ("torch", "numpy") for name in sys.modules),
        "Metadata preflight process already imported a scientific runtime",
    )
    resource = importlib.import_module(PREFIX + "resource_v2")
    launcher = importlib.import_module(PREFIX + "launch_v2")
    original_a = importlib.import_module(PREFIX + "run_v2")
    original_c = importlib.import_module(PREFIX + "architecture_run_v2")
    pins = config["descriptors"]
    registration = resource.load_registration(
        pins["amendment"]["path"], pins["amendment"]["sha256"]
    )
    control = launcher.verify_controller(
        SimpleNamespace(freeze=pins["controller_freeze"]["path"]), registration
    )
    initial = canonical(read(pins["initial_queue"]), 4)
    require(
        initial.get("finalize") is False, "Initial canonical queue cannot be finalized"
    )
    jobs = launcher.validate_queue(initial, raw)
    validated = []
    for job in jobs:
        launcher.verify_job(job, registration)
        flags = launcher.arguments(job["argv"])
        args = SimpleNamespace(
            **{key[2:].replace("-", "_"): value for key, value in flags.items()}
        )
        if job["phase"] == "A":
            frozen = original_a.validate_freeze(args, registration)
            function = "run_v2.validate_freeze"
        else:
            require(
                job["id"] == "C" and args.reference_root == config["source_root"],
                "Initial architecture job identity differs",
            )
            frozen = original_c.validate_freeze(args, registration)
            function = "architecture_run_v2.validate_freeze"
        original_a.ensure_loaded_closure(frozen)
        validated.append(
            {
                "id": job["id"],
                "original_validator": function,
                "source_freeze": descriptor(Path(flags["--freeze"])),
                "original_scientific_parent": frozen["scientific_parent"],
                "validator_returned_without_model_or_data_loader": True,
            }
        )
    original_a.ensure_loaded_closure(control)
    memory = resource.memory_profile()
    require(
        memory["limit"] == 8 * GIB,
        "Actual original memory reader did not observe the finite eight-GiB cgroup",
    )
    require(
        [row["id"] for row in validated] == ORDER[:4],
        "Initial semantic population differs",
    )
    require(
        all(not any(path.iterdir()) for path in (raw, cas))
        and not any(name.split(".")[0] in ("torch", "numpy") for name in sys.modules),
        "Metadata-only preflight touched RAW/CAS or imported scientific loaders",
    )
    checked(item)
    c.committed_sources(ROOT, config["source_commit"], config["source_files"])
    return {
        "schema": "hepta.execution07.initial-semantic-preflight.1",
        "complete": True,
        "execution_episode": EPISODE,
        "pipeline_config": item,
        "source_commit": config["source_commit"],
        "initial_jobs": validated,
        "controller_freeze": pins["controller_freeze"],
        "original_resource_registration_validator_passed": True,
        "original_controller_queue_job_and_phase_validators_passed": True,
        "loaded_repository_source_closure_verified": True,
        "memory": memory,
        "scientific_workers_started": 0,
        "scheduled_gradient_microsteps": 0,
        "model_created": False,
        "scientific_inputs_opened": False,
        "raw_and_cas_untouched": True,
        "deferred_gates": [
            "followups require actual A completion and ACKs",
            "endpoints require the fixed completed grid",
            "aggregate requires 26 original seals",
            "literal finalization requires 30 original seals",
        ],
        "wall_seconds_until_receipt": time.monotonic() - started,
        "self_cpu_seconds_until_receipt": time.process_time() - cpu,
        "full_process_cost_requires_external_owned_wait4": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--expected-config-sha256", required=True)
    args = parser.parse_args()
    config, item = c.load_config(args.config, args.expected_config_sha256)
    target = Path(config["ops_root"]) / "registrations/initial/SEMANTIC_PREFLIGHT.json"
    require(
        not target.exists(),
        "Initial semantic preflight cannot overwrite or repeat evidence",
    )
    try:
        result = validate_initial(config, item)
        write(target, result)
    except BaseException as error:
        write(
            target.with_name("SEMANTIC_FAILED.json"),
            {
                "schema": "hepta.execution07.initial-semantic-preflight-failure.1",
                "complete": False,
                "execution_episode": EPISODE,
                "pipeline_config": item,
                "error_type": type(error).__name__,
                "message": str(error)[:8192],
                "scientific_workers_started": 0,
                "automatic_retry": False,
            },
        )
        raise


if __name__ == "__main__":
    main()
