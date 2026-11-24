"""Bind the existing protected paired consumer to one executable identity.

Production owner intake is unavailable until the protected original-turn verifier
is connected. Engineering fixtures retain cold selection and use checks, and
never qualify an independent human adoption. No original signed message changes.
Run ``identity`` first, retain its digest independently, then supply that digest
to every command. A started command is never redispatched by this wrapper.
"""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import resource
import sys
import time

from . import data, paired_consumer as consumer, paired_intake as intake

require = consumer.require
field = consumer.field
COMMANDS = ("select", "run", "report", "verify-request", "verify")
PACKAGES = ("torch", "transformers", "peft", "tokenizers", "safetensors")


def implementation():
    """Commit source/interpreter bytes and installed versions; mark the remaining closure gap."""
    root = Path(__file__).parent
    files = {}
    for path in sorted(root.rglob("*.py")):
        require(not path.is_symlink(), "symlinked loop implementation")
        files[path.relative_to(root).as_posix()] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    require(0 < len(files) <= 2048, "unbounded or empty loop implementation")
    with Path(sys.executable).resolve(strict=True).open("rb") as stream:
        executable = hashlib.file_digest(stream, "sha256").hexdigest()
    return dict(
        package_sha256=data.digest(files),
        python=sys.version,
        executable_sha256=executable,
        packages={name: importlib.metadata.version(name) for name in PACKAGES},
        dependency_identity_kind="installed_versions_only",
        runtime_closure_complete=False,
    )


def identity(config, binding, request, runtime):
    """Project an already checked original admission; equality grants no authority."""
    release = dict(binding["release"], admission_sha256=data.digest(binding))
    parent, candidate = request["parent"], request["candidate"]
    require(
        parent["family"] == candidate["family"]
        and parent["schema"] == candidate["schema"]
        and candidate["parent"] == data.digest(parent),
        "model family or parent differs",
    )
    require(
        release["request_sha256"] == data.digest(request)
        and release["candidate_sha256"] == data.digest(candidate)
        and release["study_sha256"] == config["study"]
        and release["freeze_sha256"] == config["freeze"]
        and release["scope"] == config["scope"],
        "original release differs",
    )
    frozen = {
        key: request[key]
        for key in ("parent", "candidate", "retention", "timeout_seconds")
    }
    frozen["schema"] = "hepta.paired-cold.freeze.v1"
    require(
        data.digest(frozen) == release["freeze_sha256"],
        "request is not the original freeze",
    )
    for key in (
        "study_sha256",
        "admission_sha256",
        "freeze_sha256",
        "candidate_sha256",
        "request_sha256",
    ):
        field(release[key])
    return dict(
        schema="hepta.paired-learning.loop-identity.v1",
        release=release,
        release_sha256=data.digest(release),
        family=candidate["family"],
        model_schema=candidate["schema"],
        parent_sha256=data.digest(parent),
        candidate_sha256=data.digest(candidate),
        source_exposure_sha256=data.digest(candidate.get("paired_source_exposure")),
        router_sha256=data.digest(candidate.get("router")),
        model_runtime_sha256=data.digest(
            {arm: request[arm]["runtime"] for arm in ("parent", "candidate")}
        ),
        evaluation_sha256=data.digest(
            {key: request[key] for key in ("future", "retention", "timeout_seconds")}
        ),
        native_consent_sha256=field(config["native_sha256"]),
        implementation=runtime,
    )


def stage_key(command, task):
    require(command in COMMANDS, "unsupported bound consumer command")
    if command == "select":
        return "select"
    return command + "-" + field(task)


def measured_action(directory, subject, action):
    """Keep intent and failed costs; never replay a completed or uncertain call."""
    directory.mkdir(mode=0o700)
    start = time.monotonic_ns()
    cpu0 = resource.getrusage(resource.RUSAGE_SELF)
    child0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    consumer.put(
        directory / "STARTED.json",
        dict(
            schema="hepta.paired-learning.loop-start.v1",
            subject=subject,
            clock_domain=f"process-{os.getpid()}-{start}",
            started_monotonic_ns=start,
        ),
    )
    result = None
    error = None
    try:
        result = action()
        consumer.put(directory / "RESULT.json", result)
        return result
    except BaseException as exc:
        error = type(exc).__name__
        raise
    finally:
        stop = time.monotonic_ns()
        cpu1 = resource.getrusage(resource.RUSAGE_SELF)
        child1 = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu_ns = round(
            1e9
            * (
                (cpu1.ru_utime + cpu1.ru_stime - cpu0.ru_utime - cpu0.ru_stime)
                + (
                    child1.ru_utime
                    + child1.ru_stime
                    - child0.ru_utime
                    - child0.ru_stime
                )
            )
        )
        consumer.put(
            directory / "END.json",
            dict(
                schema="hepta.paired-learning.loop-stage.v1",
                subject=subject,
                status="COMPLETE" if error is None else "FAILED",
                error_type=error,
                result_sha256=data.digest(result) if error is None else None,
                started_sha256=data.digest(
                    json.loads((directory / "STARTED.json").read_bytes())
                ),
                wall_ns=stop - start,
                cpu_ns=max(0, cpu_ns),
                cpu_scope="this process plus waited children; no other child dispatcher in this CLI",
                energy_joules=None,
                money=None,
            ),
        )


def read_stage(path, expected_subject):
    start = json.loads((path / "STARTED.json").read_bytes())
    end = json.loads((path / "END.json").read_bytes())
    result = json.loads((path / "RESULT.json").read_bytes())
    require(
        start["schema"] == "hepta.paired-learning.loop-start.v1"
        and end["schema"] == "hepta.paired-learning.loop-stage.v1"
        and start["subject"] == end["subject"] == expected_subject
        and end["status"] == "COMPLETE"
        and end["error_type"] is None
        and end["started_sha256"] == data.digest(start)
        and end["result_sha256"] == data.digest(result),
        "loop stage or result differs",
    )
    require(
        all(type(end[k]) is int and end[k] >= 0 for k in ("wall_ns", "cpu_ns")),
        "invalid stage cost",
    )
    return end, result


def readback(folder, expected_identity, task, binding, verified, *, retained=False):
    """Read engineering stages; historical v1 owner receipts cannot qualify adoption."""
    manifest = json.loads((folder / "IDENTITY.json").read_bytes())
    require(data.digest(manifest) == expected_identity, "loop identity differs")
    intake.require_engineering_scope(manifest["release"]["scope"])
    require(
        data.digest(binding) == manifest["release"]["admission_sha256"],
        "original admission binding differs",
    )
    stages, outputs = {}, {}
    for command in COMMANDS:
        subject = dict(
            loop_sha256=expected_identity,
            command=command,
            task_sha256=None if command == "select" else field(task),
        )
        stages[command], outputs[command] = read_stage(
            folder / stage_key(command, task), subject
        )
    require(outputs["verify"] == verified, "live original outcome differs")
    selected = outputs["select"]
    scope = verified["scope"]
    require(
        selected["pair"] == manifest["release"]["request_sha256"] == scope["pair"]
        and selected["candidate"] == manifest["candidate_sha256"] == scope["candidate"]
        and scope["task"] == task
        and outputs["run"]["run_receipt"]
        == outputs["verify-request"]["run_receipt"]
        == scope["run_receipt"]
        and outputs["report"] == verified,
        "selected candidate, run or outcome differs",
    )
    enrolled = (
        manifest["release"]["scope"] == "owner_intake" and "enrollment" in binding
    )
    accepted = enrolled and scope["outcome"] == "accepted"
    # One B/candidate improvement is counted once, not once per verification/retry.
    improvement = (
        data.digest(
            [
                "hepta.site-adopted-improvement.v1",
                manifest["release"]["study_sha256"],
                binding["native"]["study_principal_sha256"],
                manifest["parent_sha256"],
                manifest["candidate_sha256"],
            ]
        )
        if accepted
        else None
    )
    return dict(
        schema="hepta.paired-learning.loop-readback.v1",
        loop_identity=manifest,
        loop_sha256=expected_identity,
        stages=stages,
        authority_observation="retained_engineering_fixture_verification"
        if retained
        else "live_engineering_fixture_verification",
        consumer_outcome_sha256=data.digest(verified),
        improvement_id=improvement,
        site_attested_independent_adopted_improvements=int(accepted),
        identity_basis="engineering fixture; protected original-turn owner verifier unavailable",
        production_authorization_available=False,
        improvement_deduplication_scope="one study principal and parent/candidate; not cross-account human identity",
        observed_stage_cpu_ns=sum(item["cpu_ns"] for item in stages.values()),
        summed_stage_wall_ns=sum(item["wall_ns"] for item in stages.values()),
        end_to_end_wall_ns=None,
        complete_total_cost=False,
        missing_cost_scopes=[
            "source_acquisition",
            "diagnosis",
            "training_and_failed_searches",
            "distribution",
            "between_stage_waits",
            "external_services",
            "identity_and_admission_preflight",
        ],
        adopted_improvements_per_total_cost=None,
        independently_verified_business_effect=False,
        settlement_authorized=False,
        consensus_credit_authorized=False,
    )


def operate(args):
    require(
        args.cmd != "select" or getattr(args, "task", None) is None,
        "select does not accept a task",
    )
    if args.cmd in ("run", "report"):
        field(args.delivery)
    if args.cmd == "report":
        field(args.effect)
        require(
            args.outcome in ("accepted", "rejected"),
            "explicit consumer decision required",
        )
    config, binding, request = consumer.context(args.home, args.admission)
    manifest = identity(config, binding, request, implementation())
    commitment = data.digest(manifest)
    if args.cmd == "identity":
        return dict(loop_sha256=commitment, identity=manifest)
    require(
        commitment == field(args.expected_loop),
        "model, runtime, source or release changed",
    )
    folder = args.home / args.admission / "bound-loop" / commitment
    if args.cmd == "readback":
        task = field(args.task)
        _, verified = read_stage(
            folder / stage_key("verify", task),
            dict(loop_sha256=commitment, command="verify", task_sha256=task),
        )
        return dict(
            loop_sha256=commitment,
            result=readback(folder, commitment, task, binding, verified, retained=True),
        )
    folder.parent.mkdir(mode=0o700, exist_ok=True)
    with consumer.locked(folder):
        if not (folder / "IDENTITY.json").exists():
            require(
                args.cmd == "select", "new loop must begin with original cold selection"
            )
            consumer.put(folder / "IDENTITY.json", manifest)
        require(
            json.loads((folder / "IDENTITY.json").read_bytes()) == manifest,
            "retained identity differs",
        )
        task = getattr(args, "task", None)
        path = folder / stage_key(args.cmd, task)
        require(
            not path.exists(),
            "bound command already started; inspect originals, never redispatch",
        )
        if args.cmd != "select":
            read_stage(
                folder / "select",
                dict(loop_sha256=commitment, command="select", task_sha256=None),
            )
        dependencies = {
            "report": ("run",),
            "verify-request": ("run",),
            "verify": ("run", "report", "verify-request"),
        }
        for prior in dependencies.get(args.cmd, ()):
            read_stage(
                folder / stage_key(prior, task),
                dict(loop_sha256=commitment, command=prior, task_sha256=task),
            )
        subject = dict(loop_sha256=commitment, command=args.cmd, task_sha256=task)

        def action():
            result = consumer.operate(args, require_new=True)
            require(
                implementation() == manifest["implementation"],
                "implementation changed during operation",
            )
            return result

        result = measured_action(path, subject, action)
        if args.cmd == "verify":
            result = readback(folder, commitment, task, binding, result)
            consumer.put(folder / ("READBACK-" + task + ".json"), result)
        return dict(loop_sha256=commitment, result=result)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("home", type=Path)
    parser.add_argument("admission")
    parser.add_argument("materials", type=Path)
    parser.add_argument("cmd", choices=("identity", "readback", *COMMANDS))
    parser.add_argument("--expected-loop")
    parser.add_argument("--task")
    parser.add_argument("--effect")
    parser.add_argument("--outcome", choices=("accepted", "rejected"))
    parser.add_argument("--delivery")
    parser.add_argument("--root-pid")
    parser.add_argument("--sqlite-home")
    parser.add_argument("--route")
    args = parser.parse_args()
    if args.cmd not in ("identity", "select", "readback"):
        field(args.task)
        for descriptor in (3, 4):
            os.fstat(descriptor)
    print(data.canonical(operate(args)).decode())


if __name__ == "__main__":
    main()
