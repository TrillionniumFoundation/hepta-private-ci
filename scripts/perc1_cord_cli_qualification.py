"""Execute a real trained CORD head through ordinary CLI on a TRAIN store copy.

This diagnostic does not open annotation files or add rows to the frozen pilot.
It consumes existing TRAIN evidence and has no fresh-confirmation claim.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time


def file_pin(path):
    with Path(path).open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"sha256": digest, "bytes": Path(path).stat().st_size}


def store_manifest(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("source store contains a symlink")
        if path.is_file():
            result[str(path.relative_to(root))] = file_pin(path)
        elif not path.is_dir():
            raise ValueError("source store contains a nonregular entry")
    return result


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def run(args):
    started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
    repo, pilot, output = (
        args.repo.resolve(),
        args.pilot.resolve(),
        args.output.resolve(),
    )
    task_id, operation = "cord-v2-train-00000", "cli-trained-choice"
    required = (
        "HEAD.json",
        "PROFILE.json",
        "PUBLIC_TASKS.json",
        "PLAN.json",
        task_id + "-config.json",
        task_id + "-attempt-completed.json",
    )
    input_pins = {name: file_pin(pilot / name) for name in required}
    output.mkdir(mode=0o700)
    sys.path.insert(0, str(repo / "scripts"))
    os.environ.update(
        PYTHONPATH=str(repo / "scripts"),
        PYTHONDONTWRITEBYTECODE="1",
        OMP_THREAD_LIMIT="1",
        OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
    )
    import perc1_process_meter as meter
    from perc1 import cord_task
    from perc1.capture_entry import decode_native_wire
    from perc1.owner import Owner
    from perc1.schema import require, sha
    from perc1.source_entry import operator_source_config
    from perc1.source_feature_profile import bind_head, observed_prefix

    original_store, original_manifest = None, None
    try:
        plan, head, profile = (
            read(pilot / name) for name in ("PLAN.json", "HEAD.json", "PROFILE.json")
        )
        sources = {
            repo / "scripts/perc1" / name: digest
            for name, digest in plan["source_pins"].items()
        }
        require(
            all(file_pin(p)["sha256"] == digest for p, digest in sources.items()),
            "frozen pilot source drift",
        )
        sources.update(
            {
                repo / "scripts/perc1/__main__.py": file_pin(
                    repo / "scripts/perc1/__main__.py"
                )["sha256"],
                repo / "scripts/perc1/__init__.py": file_pin(
                    repo / "scripts/perc1/__init__.py"
                )["sha256"],
                Path(meter.__file__).resolve(): file_pin(meter.__file__)["sha256"],
                Path(__file__).resolve(): file_pin(__file__)["sha256"],
            }
        )
        bind_head(profile, head)
        require(
            profile["observation"] == "first" and profile["aggregation"] == "flatten",
            "expected initial flattened profile",
        )
        tasks = [
            task for task in read(pilot / "PUBLIC_TASKS.json") if task["id"] == task_id
        ]
        require(
            len(tasks) == 1 and tasks[0]["split"] == "train",
            "one TRAIN public task required",
        )
        task = tasks[0]
        original, projection, binding = operator_source_config(
            pilot / (task_id + "-config.json")
        )
        require(
            original["sources"] == task["sources"]
            and original["model"] == task["model"],
            "task catalog/model differs from original operator config",
        )
        original_store = Path(original["state_dir"])
        require(
            original_store == original_store.resolve() and original_store.is_dir(),
            "original TRAIN store is missing or redirected",
        )
        original_manifest = store_manifest(original_store)
        require("owner.sqlite3" in original_manifest, "original owner journal missing")
        owner_root = output / "owner"
        shutil.copytree(original_store, owner_root)
        require(
            original_manifest
            == store_manifest(original_store)
            == store_manifest(owner_root),
            "source store changed during copy",
        )
        write(output / "ORIGINAL_STORE_MANIFEST.json", original_manifest)
        write(output / "INPUT_PINS.json", input_pins)
        write(
            output / "SOURCE_PINS.json",
            {str(p): digest for p, digest in sources.items()},
        )
        for name in ("HEAD.json", "PROFILE.json", "PLAN.json"):
            with (output / name).open("xb") as stream:
                stream.write((pilot / name).read_bytes())
        write(output / "PUBLIC_TASK.json", task)
        config = dict(original, state_dir=str(owner_root))
        config_path = output / "CONFIG.json"
        write(config_path, config)
        copied, copied_projection, copied_binding = operator_source_config(config_path)
        require(
            copied_binding == binding and copied_projection == projection,
            "copied operator binding changed",
        )
        require(
            {k: v for k, v in copied.items() if k != "state_dir"}
            == {k: v for k, v in original.items() if k != "state_dir"},
            "config fields other than state_dir changed",
        )
        receipts = {}
        with Owner(owner_root, copied_binding, copied["budget_units"]) as owner:
            for name in ("initial", "upper", "middle", "lower"):
                receipt = owner.receipt(name)
                require(
                    receipt["status"] == "executed", "incomplete original TRAIN receipt"
                )
                decode_native_wire(receipt["result"], source_root=owner.root)
                receipts[name] = receipt
            before = owner.status()
            require(
                before["reserved_units"] == 4
                and before["remaining_units"] >= 1
                and not before["unresolved_dispatch"],
                "expected four settled TRAIN attempts and spare budget",
            )
            require(
                not (
                    owner_root
                    / "active-decisions"
                    / (sha(operation.encode()) + ".json")
                ).exists(),
                "diagnostic operation already exists",
            )
            prefix = observed_prefix(owner, task["task_sha256"], ["initial"], profile)
            require(
                len(prefix["latent_summary"]) == 64, "expected initial dense64 features"
            )
            offerings = cord_task.candidates(
                task, prefix, cord_task.text(owner, receipts["initial"])
            )
        request = dict(
            schema="perc1.profiled-source-active.v1",
            feature_profile=profile,
            head_artifact={
                "path": str(output / "HEAD.json"),
                "sha256": file_pin(output / "HEAD.json")["sha256"],
            },
            head_sha256=sha(head),
            task_sha256=task["task_sha256"],
            observed_operations=["initial"],
            candidates=offerings,
        )
        request_path = output / "REQUEST.json"
        write(request_path, request)
        require(request_path.stat().st_size <= 65536, "CLI request exceeds bound")
        write(
            output / "BEFORE.json",
            dict(
                owner_status=before,
                prefix=prefix,
                receipt_sha256={k: v["receipt_sha256"] for k, v in receipts.items()},
            ),
        )
        write(
            output / "STARTED.json",
            dict(
                schema="perc1.cord-trained-cli-diagnostic-started.v1",
                task_id=task_id,
                operation_id=operation,
                original_state_dir=str(original_store),
                copied_state_dir=str(owner_root),
                head_sha256=sha(head),
                copied_owner_binding_sha256=sha(binding),
                budget_units=config["budget_units"],
                train_rows_added=0,
                confirmation_rows_added=0,
                labels_opened=False,
            ),
        )
        commands = []

        def cli(command, directory, with_request=False):
            argv = [
                # Keep the venv entrypoint; resolving its symlink loses site-packages.
                str(args.python.absolute()),
                "-m",
                "perc1",
                command,
                "--config",
                str(config_path),
                "--operation",
                operation,
            ]
            if with_request:
                argv += ["--request", str(request_path)]
            receipt = meter.run(
                argv,
                output / directory,
                cwd=repo,
                timeout_seconds=600,
                source_paths=list(sources),
            )
            commands.append(dict(name=directory, receipt=receipt))
            require(
                receipt["returncode"] == 0
                and receipt["measurement_valid"]
                and receipt["sources_unchanged"],
                "CLI failed; retained command logs and meter receipt contain the original outcome",
            )
            return read(output / directory / "stdout.bin")

        active = cli("source-active", "active", with_request=True)
        decision = active["active"]["decision"]
        require(
            decision["schema"] == "perc1.active-capture-decision.v3"
            and decision["head_sha256"] == sha(head),
            "wrong trained head or decision schema",
        )
        require(
            decision["prefix"] == prefix, "CLI changed retained initial feature prefix"
        )
        action = decision["selection"]["action"]
        if action == "ACQUIRE":
            require(
                active["status"] == "executed"
                and active["receipt"]["status"] == "executed",
                "selected observation did not complete",
            )
            require(
                active["this_entry"]
                == dict(
                    source_callback_invocations=1,
                    encoder_loaded=True,
                    encoder_completed_calls=1,
                ),
                "ACQUIRE did not execute the real source/encoder",
            )
            require(
                active["owner_status"]["reserved_units"]
                == before["reserved_units"] + 1,
                "ACQUIRE did not reserve exactly one unit",
            )
        else:
            require(
                action == "STOP" and active["status"] == "stopped",
                "unknown selector outcome",
            )
            require(active["owner_status"] == before, "STOP changed the owner budget")
            require(
                active["this_entry"]
                == dict(
                    source_callback_invocations=0,
                    encoder_loaded=False,
                    encoder_completed_calls=0,
                ),
                "STOP caused source effects",
            )
        (output / "HEAD.json").rename(output / "HEAD.original.json")
        cold = cli("source-decision-read", "decision-cold")
        require(
            cold["decision"] == decision
            and cold["owner_status"] == active["owner_status"],
            "cold decision/state changed",
        )
        zero_effects = dict(
            source_callback_invocations=0,
            encoder_loaded=False,
            encoder_completed_calls=0,
        )
        require(
            cold["this_entry"] == zero_effects, "cold decision read performed effects"
        )
        source_cold = None
        if action == "ACQUIRE":
            source_cold = cli("source-read", "source-cold")
            require(
                source_cold["receipt"] == active["receipt"]
                and source_cold["owner_status"] == active["owner_status"],
                "cold source receipt/state changed",
            )
            require(
                source_cold["this_entry"] == zero_effects
                and source_cold["verified_source_artifacts"] > 0,
                "selected source cold read is incomplete",
            )
        final_original = store_manifest(original_store)
        write(output / "ORIGINAL_STORE_AFTER.json", final_original)
        require(
            final_original == original_manifest, "original TRAIN store bytes changed"
        )
        require(
            input_pins == {name: file_pin(pilot / name) for name in required},
            "frozen pilot input bytes changed",
        )
        require(
            all(file_pin(p)["sha256"] == digest for p, digest in sources.items()),
            "execution source bytes changed",
        )
        report = dict(
            schema="perc1.cord-trained-cli-diagnostic.v1",
            status="PASS_REAL_TRAIN_CLI_ONLY",
            scientific_status="HOLD",
            adoption="NoUpdate",
            task_id=task_id,
            task_split="train",
            operation_id=operation,
            selected=decision["selection"],
            head_schema=head["schema"],
            head_sha256=sha(head),
            head_file_sha256=input_pins["HEAD.json"]["sha256"],
            head_bytes=input_pins["HEAD.json"]["bytes"],
            profile_sha256=sha(profile),
            feature_width=len(prefix["latent_summary"]),
            original_receipt_sha256={
                k: v["receipt_sha256"] for k, v in receipts.items()
            },
            original_store_bytes_unchanged=True,
            frozen_pilot_inputs_unchanged=True,
            frozen_input_scope=list(required),
            source_code_unchanged=True,
            owner_binding_preserved=True,
            budget_units=config["budget_units"],
            before=before,
            after=active["owner_status"],
            actual_entry_effects=active["this_entry"],
            decision_cold_effects=cold["this_entry"],
            selected_source_cold_effects=source_cold["this_entry"]
            if source_cold
            else None,
            external_head_removed_before_cold_read=not (output / "HEAD.json").exists(),
            same_decision_cold_read=True,
            training_rows_added=0,
            confirmation_rows_added=0,
            fresh_confirmation_groups=0,
            labels_opened=False,
            extra_acquisition_attempts=active["owner_status"]["reserved_units"]
            - before["reserved_units"],
            cost_scope="separate TRAIN diagnostic; parent wall envelope includes store copy, validation, subprocess startup/capture/encoder/persistence and cold recovery; command times are nested and not added to parent wall",
            driver_wall_ns=time.perf_counter_ns() - started,
            driver_process_cpu_ns=time.process_time_ns() - cpu_started,
            commands=[
                dict(
                    name=row["name"],
                    **{
                        key: row["receipt"][key]
                        for key in (
                            "returncode",
                            "command_wall_ns",
                            "waited_cpu_ns",
                            "measurement_valid",
                            "sources_unchanged",
                        )
                    },
                )
                for row in commands
            ],
            energy_joules=None,
            provider_billing=None,
            terminal_quality=None,
            task_net_benefit_established=False,
            production_daemon_integrated=False,
            native_cell_owner_executions=0,
            python_entrypoint=str(args.python.absolute()),
            thread_environment={
                key: os.environ[key]
                for key in (
                    "OMP_THREAD_LIMIT",
                    "OMP_NUM_THREADS",
                    "OPENBLAS_NUM_THREADS",
                    "MKL_NUM_THREADS",
                )
            },
            limitation="TRAIN source and its initial receipt are reused; the copied owner also contains earlier controlled branch captures, but the selector receives only the frozen initial prefix; not an added TRAIN/DEV/confirmation evaluation row",
        )
        write(output / "REPORT.json", report)
        print(json.dumps(report, sort_keys=True, indent=2))
    except BaseException as error:
        failure = dict(
            status="FAILED_DIAGNOSTIC",
            error_type=type(error).__name__,
            error=str(error),
        )
        if original_store is not None and original_manifest is not None:
            failure["original_store_bytes_unchanged"] = (
                store_manifest(original_store) == original_manifest
            )
        write(output / "FAILURE.json", failure)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--pilot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
