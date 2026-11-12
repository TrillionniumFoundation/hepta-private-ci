"""Coordinate bounded fresh actors and inspect their complete logical states."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import numpy as np
import torch

from .state import fingerprint, load, same, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    source = json.loads(args.source.read_text())
    before = {name: sha(name) for name in source["source_sha256"]}
    if before != source["source_sha256"]:
        raise ValueError("precommitted controller source differs")
    inventory = Path("qualification/hcsn_adjoint_adam_resume/SOURCE.json")
    if (
        source["prefrozen_inventory_sha256"] != sha(inventory)
        or before != json.loads(inventory.read_text())["source_sha256"]
    ):
        raise ValueError("remote-prefrozen source inventory differs")
    totals = dict(forwards=0, adjoints=0, adam_updates=0)
    expected = dict(
        continuous=(3, 3, 2),
        first=(1, 1, 1),
        resume=(2, 2, 1),
        crash=(1, 1, 1),
        reject=(0, 0, 0),
    )
    actors, checks = [], []
    started = time.perf_counter()

    def write(name, value):
        destination = args.output / name
        pending = destination.with_name(destination.name + ".pending")
        with pending.open("w") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, destination)

    def require(test, message):
        checks.append(dict(name=message, passed=bool(test)))
        if not test:
            raise ValueError(message)

    def actor(geometry, mode, label, checkpoint=None, published=None):
        bounds = dict(zip(totals, expected[mode]))
        if any(
            entry["started"] and entry["calls_status"] != "KNOWN" for entry in actors
        ):
            raise ValueError("no further admission after unreported actor work")
        if any(
            totals[k] + bounds[k] > limit
            for k, limit in dict(forwards=13, adjoints=13, adam_updates=9).items()
        ):
            raise ValueError("total admission budget exceeded")
        output = args.output / label
        nonce = f"{source['request_identity']}:{os.environ.get('GITHUB_RUN_ID', 'UNADMITTED')}:{os.environ.get('GITHUB_RUN_ATTEMPT', '0')}:{label}"
        command = [
            sys.executable,
            "-B",
            "-m",
            "qualification.hcsn_adjoint_adam_resume.actor",
            "--geometry",
            geometry,
            "--mode",
            mode,
            "--source",
            str(args.source),
            "--baseline",
            str(args.baseline),
            "--output",
            str(output),
            "--admission-nonce",
            nonce,
        ]
        if checkpoint:
            command += ["--checkpoint", str(checkpoint)]
        if published:
            command += ["--published", str(published)]
        entry = dict(
            label=label,
            admission_nonce=nonce,
            geometry=geometry,
            mode=mode,
            command=command,
            expected_maximum_calls=bounds,
            started=False,
            terminal=False,
            pid=None,
            exit_code=None,
            calls_status="NOT_STARTED",
            observed_calls=None,
            result=None,
        )
        actors.append(entry)
        write("ACTORS.json", actors)
        write(label + "-ADMISSION.json", entry)
        wall = time.perf_counter()
        try:
            with (
                (args.output / (label + ".stdout")).open("wb") as stdout,
                (args.output / (label + ".stderr")).open("wb") as stderr,
            ):
                process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
                entry.update(
                    started=True, pid=process.pid, calls_status="UNKNOWN_PENDING_RESULT"
                )
                write("ACTORS.json", actors)
                write(label + "-ADMISSION.json", entry)
                code = process.wait()
        except Exception as exc:
            entry["launch_or_wait_error"] = dict(
                type=type(exc).__name__, message=str(exc)
            )
            entry["calls_status"] = (
                "UNKNOWN" if entry["started"] else "START_FAILED_NO_CHILD"
            )
            write("ACTORS.json", actors)
            write(label + "-ADMISSION.json", entry)
            raise
        entry.update(
            terminal=True,
            exit_code=code,
            wall_seconds=time.perf_counter() - wall,
            calls_status="UNKNOWN_TERMINAL_UNREPORTED",
        )
        write("ACTORS.json", actors)
        write(label + "-ADMISSION.json", entry)
        try:
            result = json.loads((output / "RESULT.json").read_text())
            entry["result"] = result
            counts = result["calls"]
            valid = (
                result["pid"] == process.pid
                and result["admission_nonce"] == nonce
                and result["exit_code"] == code
                and result["source"] == source
                and result["source_before"] == result["source_after"] == before
            )
            valid = (
                valid
                and set(counts) == set(totals)
                and all(
                    type(counts[k]) is int and 0 <= counts[k] <= bounds[k]
                    for k in totals
                )
            )
            if not valid:
                raise ValueError(
                    "actor result lacks authoritative identity/source/call binding"
                )
        except Exception as exc:
            entry["result_error"] = dict(type=type(exc).__name__, message=str(exc))
            write("ACTORS.json", actors)
            write(label + "-ADMISSION.json", entry)
            raise ValueError(
                "started actor cost is UNKNOWN; no exact aggregate"
            ) from exc
        entry.update(calls_status="KNOWN", observed_calls=dict(counts))
        for key in totals:
            totals[key] += counts[key]
        write("ACTORS.json", actors)
        write(label + "-ADMISSION.json", entry)
        require(counts == bounds, "exact_actor_call_denominator_" + label)
        require(
            result["input_checkpoint_sha_before"]
            == result["input_checkpoint_sha_after"],
            "input_checkpoint_unchanged_" + label,
        )
        wanted_code = 73 if mode == "crash" else 42 if mode == "reject" else 0
        wanted_status = (
            "EXPECTED_CRASH_BEFORE_REPLACE"
            if mode == "crash"
            else "REJECTED_BEFORE_FORWARD"
            if mode == "reject"
            else "PASS"
        )
        require(
            code == wanted_code and result["status"] == wanted_status,
            "authoritative_terminal_" + label,
        )
        return output, result

    error = None
    try:
        for geometry in ("uniform", "graded"):
            continuous, c_result = actor(
                geometry, "continuous", geometry + "-continuous"
            )
            first, f_result = actor(geometry, "first", geometry + "-first")
            first_checkpoint = first / "state.pt"
            resume_checkpoint = first_checkpoint
            if geometry == "uniform":
                valid = load(first_checkpoint)
                bad = dict(valid)
                del bad["adam"]
                require(
                    set(valid) - set(bad) == {"adam"}
                    and all(same(valid[k], bad[k]) for k in bad),
                    "negative_changes_only_Adam",
                )
                omitted = args.output / "omit-adam.pt"
                with omitted.open("xb") as stream:
                    torch.save(bad, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                omitted_sha = sha(omitted)
                _, reject_result = actor(
                    geometry, "reject", "uniform-omit-adam", checkpoint=omitted
                )
                require(
                    sha(omitted) == omitted_sha
                    and reject_result["calls"]
                    == dict(forwards=0, adjoints=0, adam_updates=0),
                    "omit_adam_rejects_without_model_or_update",
                )
                published = args.output / "crash-published.pt"
                shutil.copyfile(first_checkpoint, published)
                with published.open("rb") as stream:
                    os.fsync(stream.fileno())
                old_sha = sha(published)
                crash, crash_result = actor(
                    geometry,
                    "crash",
                    "uniform-crash",
                    checkpoint=published,
                    published=published,
                )
                pending = published.with_name(published.name + ".pending")
                require(
                    sha(published) == old_sha == sha(first_checkpoint),
                    "crash_preserves_previous_published_bytes",
                )
                require(
                    pending.is_file() and sha(pending) != old_sha,
                    "process_crash_retains_complete_distinct_pending_bytes",
                )
                require(
                    same(load(pending), load(continuous / "state.pt")),
                    "unpublished_step2_payload_matches_continuous_complete_state",
                )
                require(
                    same(load(published), load(first_checkpoint)),
                    "crash_keeps_complete_step1_state",
                )
                resume_checkpoint = published
                write(
                    "CRASH-PUBLICATION.json",
                    dict(
                        old_published_sha256=old_sha,
                        published_after_sha256=sha(published),
                        pending_sha256=sha(pending),
                        old_step=load(published)["step"],
                        pending_step=load(pending)["step"],
                        crash_exit=crash_result["exit_code"],
                        crash_actual_updates=crash_result["calls"]["adam_updates"],
                    ),
                )
            resumed, r_result = actor(
                geometry, "resume", geometry + "-resumed", checkpoint=resume_checkpoint
            )
            require(
                len({c_result["pid"], f_result["pid"], r_result["pid"]}) == 3,
                "fresh_process_identity_" + geometry,
            )
            c_state, r_state = load(continuous / "state.pt"), load(resumed / "state.pt")
            require(same(c_state, r_state), "complete_step2_state_exact_" + geometry)
            require(
                same(load(continuous / "step1.pt"), load(first / "state.pt")),
                "complete_step1_state_exact_" + geometry,
            )
            require(
                same(c_state["rng"], r_state["rng"]),
                "all_three_rng_streams_exact_" + geometry,
            )
            require(
                same(c_state["adam"], r_state["adam"]),
                "complete_adam_moments_groups_steps_exact_" + geometry,
            )
            c_next = next(v for v in c_result["records"] if v["label"] == "next")
            r_next = next(v for v in r_result["records"] if v["label"] == "next")
            require(c_next == r_next, "next_loss_gradient_metadata_exact_" + geometry)
            with (
                np.load(continuous / "ARRAYS.npz", allow_pickle=False) as c_arrays,
                np.load(resumed / "ARRAYS.npz", allow_pickle=False) as r_arrays,
            ):
                names = [n for n in c_arrays.files if n.startswith("next_")]
                require(
                    bool(names)
                    and all(
                        c_arrays[n].dtype == r_arrays[n].dtype
                        and c_arrays[n].shape == r_arrays[n].shape
                        and c_arrays[n].tobytes() == r_arrays[n].tobytes()
                        for n in names
                    ),
                    "next_target_output_gradients_bytes_exact_" + geometry,
                )
            write(
                geometry + "-FULLSTATE.json",
                dict(
                    continuous=fingerprint(c_state),
                    resumed=fingerprint(r_state),
                    next_probe=c_next,
                ),
            )
        require(
            totals == dict(forwards=13, adjoints=13, adam_updates=9),
            "all_actual_calls_exact_budget",
        )
        require(
            len({entry["pid"] for entry in actors}) == len(actors),
            "all_actors_are_distinct_processes",
        )
    except Exception as exc:
        import traceback

        error = dict(
            type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc()
        )
    after = {name: sha(name) for name in before}
    unknown = [
        dict(
            label=e["label"],
            nonce=e["admission_nonce"],
            pid=e["pid"],
            started=e["started"],
            terminal=e["terminal"],
            exit_code=e["exit_code"],
            maximum_calls=e["expected_maximum_calls"],
        )
        for e in actors
        if e["started"] and e["calls_status"] != "KNOWN"
    ]
    exact_calls = None if unknown else totals
    result = dict(
        status="PASS" if error is None and before == after else "HOLD",
        error=error,
        source=source,
        source_before=before,
        source_after=after,
        actors=actors,
        checks=checks,
        actual_calls=exact_calls,
        observed_calls_only=totals,
        calls_status="UNKNOWN" if unknown else "EXACT_FOR_ALL_STARTED_ACTORS",
        unknown_actor_costs=unknown,
        wall_seconds=time.perf_counter() - started,
        full_network_qualified=False,
        full_prior_migration_qualified=False,
        large_mesh_qualified=False,
        cross_runtime_restore_qualified=False,
        continuous_adjoint_not_adaptive_bdf_reverse=True,
    )
    write("RESULT.json", result)
    print(
        json.dumps(
            dict(
                status=result["status"],
                actual_calls=exact_calls,
                observed_calls_only=totals,
                calls_status="UNKNOWN" if unknown else "EXACT_FOR_ALL_STARTED_ACTORS",
                unknown_actor_costs=unknown,
                actors=len(actors),
                checks=len(checks),
                error=error,
            ),
            sort_keys=True,
        )
    )
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
