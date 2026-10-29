"""Metadata-only follow-up registration; never launch workers or decode tensors.

Bundles contain proposed queue extensions, not an activated queue. Endpoint
inventory previews do not replace endpoint_v2's runtime/tensor access barrier.
All source commits are verified in an explicitly supplied local Git repository.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import time
from types import SimpleNamespace

from .endpoint_v2 import parent_freeze
from .launch_v2 import arguments, validate_queue, verify_job
from .resource_v2 import file_hash, load_registration
from .run_v2 import validate_freeze

ROOT = Path(__file__).resolve().parents[2]
PREFIX = Path(__file__).resolve().parent.relative_to(ROOT)
SEEDS = (17, 29, 43)
METHODS = ("ordinary", "field12", "full_current_state", "history6")
PROTOCOL_SHA = "2c02b5aff224f125826931f3ecf691b2a01391a719075db8a1bc9fb5f5dafd55"
R_SHA = "79c322f670c78e7c023bbe22a93ea77071c92d2cdf68d7acefa7173fe2ad478f"
INITIAL_IDS = {"A-17", "A-29", "A-43", "C"}
FOLLOWUP_IDS = {f"{phase}-{seed}" for phase in ("B", "R") for seed in SEEDS} | {"W"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def read(path):
    with Path(path).open() as stream:
        return json.load(stream)


def descriptor(path):
    path = Path(path).absolute()
    require(path.is_file() and not path.is_symlink(), "Missing or symlink artifact: " + str(path))
    before = path.stat()
    digest = file_hash(path)
    after = path.stat()
    require((before.st_ino, before.st_size, before.st_mtime_ns) ==
            (after.st_ino, after.st_size, after.st_mtime_ns), "Artifact changed while hashing")
    return {"path": str(path), "bytes": after.st_size, "sha256": digest}


def checked(root, entry):
    relative = Path(entry["path"])
    require(not relative.is_absolute() and ".." not in relative.parts, "Unsafe relative artifact")
    target = Path(root).resolve() / relative
    require(target.resolve().is_relative_to(Path(root).resolve()), "Artifact escaped its stage")
    actual = descriptor(target)
    require(type(entry.get("bytes")) is int and entry["bytes"] > 0
            and actual["bytes"] == entry["bytes"] and actual["sha256"] == entry["sha256"], "Artifact bytes differ")
    return target


def tree_artifacts(directory):
    directory = Path(directory)
    require(directory.is_dir(), "Missing completed stage")
    result = {}
    for path in sorted(directory.rglob("*")):
        require(not path.is_symlink(), "Symlinks cannot supply frozen evidence")
        if path.is_file():
            require("FAILED" not in path.name and ".pending." not in path.name, "Failed or unfinished stage artifact")
            result[str(path)] = descriptor(path)["sha256"]
    require(result, "Empty completed stage")
    return result


def source_descriptor(path, expected_sha, phase, registration):
    actual = descriptor(path)
    require(actual["sha256"] == expected_sha, "Actual training freeze differs")
    freeze = read(path)
    result = {**actual, "registered_commit": freeze["registered_commit"],
              "protocol_sha256": freeze["protocol_sha256"], "source_root": str(ROOT)}
    parent_freeze(phase, result, registration)
    return result, freeze


def operation(root, phase, seed, source, registration):
    token = f"{phase}-seed-{seed}" if seed is not None else f"{phase}-all"
    op_path = root / "operations" / (token + ".COMPLETE.json")
    require(not op_path.with_name(token + ".FAILED.json").exists(), "Failed operation")
    op = read(op_path)
    require(op.get("complete") is True and op.get("post_execution_storage_check") is True
            and op.get("attempt_id") == "attempt02" and op.get("phase") == phase and op.get("seed") == seed
            and op.get("source_freeze_sha256") == source["sha256"]
            and op.get("registered_commit") == source["registered_commit"]
            and op.get("operational_amendment_sha256") == registration["_sha256"]
            and op.get("scientific_source_bytes_unchanged") is True
            and op.get("scientific_protocol_sha256") == PROTOCOL_SHA, "Operation ancestry or resource gate differs")
    directory = root / ("stage_" + phase)
    if seed is not None:
        directory = directory / f"seed-{seed}"
    require(not (directory / "FAILED.json").exists(), "Scientific stage failed")
    complete_path = checked(root, op["scientific_complete"])
    require(complete_path == directory / "COMPLETE.json", "Wrong scientific completion path")
    complete = read(complete_path)
    binding = complete["binding"] if phase == "C" else complete
    require(complete.get("complete") is True and binding.get("source_freeze_sha256") == source["sha256"]
            and binding.get("registered_commit") == source["registered_commit"], "Scientific completion ancestry differs")
    return complete, {str(op_path): file_hash(op_path), str(complete_path): file_hash(complete_path)}


def ab_population(root, phase, source, registration):
    entries, artifacts = [], {}
    schedules = range(6000, 6004) if phase == "A" else range(106000, 106016)
    methods = METHODS if phase == "A" else METHODS + ("fixed_taper",)
    count, work = (16, 39168) if phase == "A" else (80, 23040)
    for seed in SEEDS:
        complete, seals = operation(root, phase, seed, source, registration)
        artifacts.update(seals)
        require(complete.get("phase") == phase and complete.get("seed") == seed
                and complete.get("path_count") == count
                and complete.get("costs", {}).get("scheduled_gradient_microsteps") == work, "Wrong A/B work or population")
        directory = root / ("stage_" + phase) / f"seed-{seed}"
        paths = read(directory / "paths/PATHS.json")
        require(paths.get("complete") is True and paths.get("training_complete") is True
                and paths.get("phase") == phase and paths.get("seed") == seed
                and paths.get("new_endpoint_roles_opened") == [], "A/B path population is not sealed")
        expected = {(seed, schedule, method) for schedule in schedules for method in methods}
        rows = paths["paths"]
        require(len(rows) == count and {(r["seed"], r["schedule_id"], r["method"]) for r in rows} == expected,
                "A/B checkpoint grid differs")
        for row in rows:
            identity = f"seed-{seed}-schedule-{row['schedule_id']}-{row['method']}"
            require(row["id"] == identity and row["path"] == identity + ".state", "A/B checkpoint identity differs")
            target = checked(directory / "paths", row)
            entries.append({"id": identity, **descriptor(target)})
        artifacts.update(tree_artifacts(directory))
    return entries, artifacts


def bank_population(root):
    expected = {(schedule, prefix, step) for schedule in range(6000, 6004)
                for prefix in ("baseline", "balanced") for step in range(0, 288, 48)}
    for seed in SEEDS:
        directory = root / "stage_A" / f"seed-{seed}" / "bank"
        bank = read(directory / "BANK.json")
        rows = bank["records"]
        require(bank.get("complete") is True and bank.get("seed") == seed and len(rows) == 48
                and {(r["schedule_id"], r["prefix"], r["step"]) for r in rows} == expected, "A parent grid differs")
        require(set(bank["heads"]) == set(METHODS[1:]), "A head grid differs")
        for mode in METHODS[1:]:
            for kind in ("head", "bank"):
                descriptor(directory / f"{mode}-{kind}.npz")
        descriptor(directory / "trace.jsonl.gz")
        for row in rows:
            stem = f"schedule-{row['schedule_id']}-{row['prefix']}-step-{row['step']}"
            checked(directory, {"path": stem + ".state", "sha256": row["parent_sha256"], "bytes": row["parent_bytes"]})
            require(row["seed"] == seed and [b["action"] for b in row["branches"]] == [0, 1, 2, 3]
                    and row["prefix_replay_equal"] is True, "A branch/replay population differs")
            for action in range(4):
                descriptor(directory / f"{stem}-action-{action}.npz")


def c_population(root, source, registration, plan):
    seal, artifacts = operation(root, "C", None, source, registration)
    require(seal.get("schema") == "hepta.fullstudy.C.complete-seal.1" and seal.get("training_complete") is True
            and seal.get("new_endpoint_roles_opened") == [] and seal.get("plan") == plan
            and seal.get("audit_count") == 4 and seal.get("literal_tensor_checkpoints") == 52
            and seal.get("physical_gradient_microsteps") == 57536
            and seal.get("scientific_gradient_microsteps") == 57152 and seal.get("replay_gradient_microsteps") == 384,
            "C completion population or work differs")
    require(all(seal["work"]["counts"].get(k + ".scheduled_gradient_microsteps") == v
                for k, v in {"warmup": 8000, "bank": 46080, "evaluation": 3072, "replay_audit": 384}.items()), "C ledger differs")
    require(seal["binding"].get("protocol_sha256") == PROTOCOL_SHA
            and seal["binding"].get("hcsn_reference_commit") == "68eb16caa9c14c7b5729585c86d9c293018a987c", "C scientific ancestry differs")
    stage, inventory = root / "stage_C", {}
    for item in seal["artifacts"]:
        target = checked(stage, item)
        require(str(target) not in inventory, "Duplicate C artifact")
        inventory[str(target)] = item["sha256"]
    entries, seen_warm, seen_paths = [], set(), set()
    require(len(seal["warmstarts"]) == 20 and len(seal["paths"]) == 32, "C incomplete grid")
    for warm, rows in ((True, seal["warmstarts"]), (False, seal["paths"])):
        for row in rows:
            target = checked(stage, row["checkpoint"])
            require(inventory.get(str(target)) == row["checkpoint"]["sha256"], "C checkpoint not in sealed inventory")
            seed, mode = row["seed"], row["mode"]
            if warm:
                seen_warm.add((seed, mode, row["role"]))
                if row["role"] == "development":
                    continue
                method = "frozen"
            else:
                seen_paths.add((seed, mode, row["policy"]))
                require(row["policy"] in ("baseline", "field"), "Unknown C policy")
                method = "ordinary" if row["policy"] == "baseline" else "field12"
            entries.append({"id": f"{mode}-seed-{seed}-{method}", **descriptor(target)})
    require(seen_warm == {(seed, mode, role) for role, seeds in (("development", range(701, 703)),
            ("evaluation", range(801, 809))) for seed in seeds for mode in ("ordinary", "dual")}
            and seen_paths == {(seed, mode, policy) for seed in range(801, 809)
            for mode in ("ordinary", "dual") for policy in ("baseline", "field")}
            and len({r["id"] for r in entries}) == 48, "C paired population differs")
    artifacts.update(tree_artifacts(stage))
    return entries, artifacts


def diagnostic_population(root, sources, registration):
    artifacts = {}
    witness, seals = operation(root, "W", None, sources["W"], registration)
    require(witness.get("new_endpoint_roles_opened") == [] and witness.get("scheduled_gradient_microsteps") == 2880
            and len(witness["records"]) == 3 and {r["seed"] for r in witness["records"]} == set(SEEDS), "W inventory differs")
    for row in witness["records"]:
        require(row["parent"] == {"schedule": 6000, "prefix": "baseline", "clock": 48}
                and [r["action"] for r in row["branches"]] == [0, 1, 2, 3], "W fixed diagnostic grid differs")
        directory = root / "stage_W" / f"seed-{row['seed']}"
        require(row["original_bank_sha256"] == file_hash(root / "stage_A" / f"seed-{row['seed']}" / "bank/BANK.json")
                and row["original_head_sha256"] == file_hash(root / "stage_A" / f"seed-{row['seed']}" / "bank/field12-head.npz"), "W source A identity differs")
        for key in ("original_parent", "reflected_parent", "geometry"):
            checked(directory, row[key])
        for branch in row["branches"]:
            checked(directory, branch["first_state"])
            checked(directory, branch["terminal_state"])
            checked(directory, {**branch["outputs"], "sha256": branch["outputs"]["file_sha256"]})
    artifacts.update(seals)
    artifacts.update(tree_artifacts(root / "stage_W"))
    expected = {(s, p, t, a) for s in range(6000, 6004) for p in ("baseline", "balanced")
                for t in range(0, 288, 48) for a in range(4)}
    for seed in SEEDS:
        replay, seals = operation(root, "R", seed, sources["R"], registration)
        require(replay.get("new_endpoint_roles_opened") == [] and replay.get("terminal_count") == 192
                and replay.get("scheduled_gradient_microsteps") == 32256 and replay.get("all_literal_terminal_restores_equal") is True
                and replay.get("all_original_component_and_receipt_hashes_equal") is True
                and replay.get("original_scientific_counts_changed") is False and replay.get("new_fitting_or_selection") is False
                and replay.get("reconstructed_terminal_bytes_not_originally_archived") is True, "R inventory or integrity differs")
        require(replay["source_stage_identity"]["source_freeze_sha256"] == sources["A"]["sha256"]
                and replay["source_stage_identity"]["source_protocol_sha256"] == PROTOCOL_SHA, "R source A identity differs")
        rows = replay["terminals"]
        require(len(rows) == 192 and {(r["schedule_id"], r["prefix"], r["parent_clock"], r["action"]) for r in rows} == expected,
                "R terminal grid differs")
        for row in rows:
            require(row["seed"] == seed and row["all_original_deterministic_receipts_equal"] is True, "R seed or receipt differs")
            stem = f"stage_R/seed-{seed}/schedule-{row['schedule_id']}-{row['prefix']}-step-{row['parent_clock']}-action-{row['action']}"
            require(row["checkpoint"]["path"] == stem + ".bin.gz" and row["trace"]["path"] == stem + ".trace.json.gz", "R artifact coordinate differs")
            checked(root, row["checkpoint"])
            checked(root, row["trace"])
        artifacts.update(seals)
        artifacts.update(tree_artifacts(root / "stage_R" / f"seed-{seed}"))
    return artifacts


def committed_sources(git_root, commit, sources):
    require(re.fullmatch(r"[0-9a-f]{40}", commit) is not None and len(set(commit)) > 1, "Not a full source commit")
    def git(*args):
        return subprocess.check_output(["git", "-C", str(git_root), *args], stderr=subprocess.PIPE)
    require(git("cat-file", "-t", commit).strip() == b"commit", "Source identity is not a Git commit")
    tree = {}
    for row in git("ls-tree", "-r", "-z", commit).split(b"\0"):
        if row:
            metadata, name = row.split(b"\t", 1)
            mode, kind, digest = metadata.split()
            if kind == b"blob" and mode in (b"100644", b"100755"):
                tree[name.decode()] = digest.decode()
    for name, expected in sources.items():
        path = ROOT / name
        require(file_hash(path) == expected, "Source drift before registration")
        digest = hashlib.sha1(f"blob {path.stat().st_size}\0".encode())
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1048576), b""):
                digest.update(chunk)
        require(tree.get(name) == digest.hexdigest(), "Source bytes are absent from the declared local commit: " + name)


def queue_extension(queue, additions, root, final):
    require(queue.get("schema") == "hepta.fullstudy.queue.2" and queue.get("attempt_id") == "attempt02"
            and queue.get("finalize") is False, "Wrong or finalized starting queue")
    result = {**queue, "jobs": [*queue["jobs"], *additions], "finalize": final}
    validate_queue(result, root)
    require(result["jobs"][:len(queue["jobs"])] == queue["jobs"], "Existing queue definitions changed")
    return result


def job(phase, freeze_path, freeze_sha, args, requires, seed=None, endpoint=False):
    name = phase + "_endpoint" if endpoint else "W" if phase == "W" else f"{phase}-{seed}"
    argv = ["-B", "-m", "experiments.parameter_field_fullstudy_20261029." + ("endpoint_v2" if endpoint else "run_v2"),
            "--phase", phase, "--root", str(args.root), "--assets", str(args.assets), "--freeze", str(freeze_path),
            "--amendment", str(args.amendment), "--amendment-sha256", args.amendment_sha256,
            "--protocolR" if phase == "R" else "--protocol", str(ROOT / PREFIX / ("PROTOCOL_R.json" if phase == "R" else "PROTOCOL.json")), "--execute"]
    if seed is not None:
        argv.extend(["--seed", str(seed)])
    if endpoint:
        argv.extend(["--source-manifest", str(ROOT / PREFIX / "source_allocation/SOURCE_ALLOCATION.json")])
        if phase == "C":
            argv.extend(["--reference-root", str(ROOT)])
    completion = f"stage_{phase}/" + ("endpoint_evaluation" if phase == "C" else "endpoints") + "/ENDPOINTS.json" if endpoint else (
        "operations/W-all.COMPLETE.json" if phase == "W" else f"operations/{phase}-seed-{seed}.COMPLETE.json")
    return {"id": name, "phase": phase, "seed": seed, "group": "singleton" if endpoint or phase == "W" else "reconstruction" if phase == "R" else "training",
            "requires": sorted(requires), "freeze_sha256": freeze_sha, "completion": completion, "argv": argv}


def register(args):
    started_wall, started_cpu = time.monotonic(), time.process_time()
    child_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    args.root, args.output = Path(args.root).resolve(), Path(args.output).resolve()
    args.assets, args.amendment = Path(args.assets).resolve(), Path(args.amendment).resolve()
    require(not args.output.exists() and not args.output.is_relative_to(args.root), "Registration destination already exists or lies in raw evidence")
    registration = load_registration(args.amendment, args.amendment_sha256)
    require(args.root == Path(registration["raw_root"]).resolve() and args.assets.is_dir(), "Wrong registered raw root/assets")
    require(file_hash(args.queue) == args.expected_queue_sha256, "Queue changed before registration")
    queue = read(args.queue)
    jobs = validate_queue(queue, args.root)
    for row in jobs:
        verify_job(row, registration)
    parents, freezes = {}, {}
    for phase in ("A", "C"):
        parents[phase], freezes[phase] = source_descriptor(getattr(args, phase.lower() + "_freeze"),
            getattr(args, phase.lower() + "_freeze_sha256"), phase, registration)
        matching = [r for r in jobs if r["phase"] == phase and not r["id"].endswith("_endpoint")]
        require(matching and all(r["freeze_sha256"] == parents[phase]["sha256"] and
                Path(arguments(r["argv"])["--freeze"]).resolve() == Path(parents[phase]["path"]).resolve() for r in matching), "Queue training parent differs")
    sources = {}
    for freeze in freezes.values():
        for name, digest in freeze["source_files"].items():
            require(name not in sources or sources[name] == digest, "Parent source closures disagree")
            sources[name] = digest
    for name in ("register_followups_v2.py", "witness.py", "replay_terminals.py", "PROTOCOL_R.json"):
        sources[str(PREFIX / name)] = file_hash(ROOT / PREFIX / name)
    sources[str(args.amendment.relative_to(ROOT))] = registration["_sha256"]
    require(file_hash(ROOT / PREFIX / "PROTOCOL.json") == PROTOCOL_SHA
            and file_hash(ROOT / PREFIX / "PROTOCOL_R.json") == R_SHA, "Scientific protocol drift")
    committed_sources(args.source_git_root, args.source_commit, sources)
    ids = {row["id"] for row in jobs}
    require(ids == (INITIAL_IDS if args.stage == "followups" else INITIAL_IDS | FOLLOWUP_IDS), "Starting queue population differs")
    inventories, artifacts = {}, {p["path"]: p["sha256"] for p in parents.values()}
    inventories["A"], found = ab_population(args.root, "A", parents["A"], registration)
    artifacts.update(found)
    bank_population(args.root)
    artifacts[str(args.amendment)] = registration["_sha256"]
    if args.stage == "endpoints":
        for phase in ("B", "W", "R"):
            matches = [r for r in jobs if r["phase"] == phase]
            require(len({r["freeze_sha256"] for r in matches}) == 1, "Mixed follow-up training freezes")
            path = Path(arguments(matches[0]["argv"])["--freeze"])
            freeze = read(path)
            validate_freeze(SimpleNamespace(phase=phase, freeze=path, root=args.root,
                protocol=ROOT / PREFIX / "PROTOCOL.json", protocolR=ROOT / PREFIX / "PROTOCOL_R.json"), registration)
            require(freeze.get("actual_source_A") == parents["A"], "Follow-up actual A training parent differs")
            require(all(Path(arguments(r["argv"])["--freeze"]).resolve() == path.resolve() for r in matches), "Mixed follow-up freeze paths")
            parents[phase] = {**descriptor(path), "registered_commit": freeze["registered_commit"],
                              "protocol_sha256": freeze["protocol_sha256"], "source_root": str(ROOT)}
            if phase == "B":
                parent_freeze("B", parents[phase], registration)
            artifacts[str(path)] = parents[phase]["sha256"]
        inventories["B"], found = ab_population(args.root, "B", parents["B"], registration)
        artifacts.update(found)
        plan = read(ROOT / PREFIX / "PROTOCOL.json")["stage_C"]["execution_plan"]
        inventories["C"], found = c_population(args.root, parents["C"], registration, plan)
        artifacts.update(found)
        artifacts.update(diagnostic_population(args.root, parents, registration))
    require(file_hash(args.queue) == args.expected_queue_sha256, "Queue changed during registration")
    outputs, additions = {}, []
    selected = ("B", "W", "R") if args.stage == "followups" else ("A", "B", "C")
    for phase in selected:
        endpoint = args.stage == "endpoints"
        filename = phase + ("_ENDPOINT" if endpoint else "") + "_SOURCE_FREEZE.json"
        frozen_artifacts = dict(artifacts)
        if endpoint:
            preview = encode({"schema": "hepta.fullstudy.checkpoint-metadata-preview.1", "phase": phase,
                "complete_population_byte_checks": True, "runtime_tensor_checks_deferred_to_registered_scorer": True,
                "new_endpoint_roles_opened": [], "training_parent": parents[phase], "checkpoints": inventories[phase]})
            preview_name = phase + "_CHECKPOINT_METADATA.json"
            outputs[preview_name] = preview
            frozen_artifacts[str(args.output / preview_name)] = hashlib.sha256(preview).hexdigest()
        freeze = {"schema": "hepta.fullstudy.source-freeze.1", "registered_commit": args.source_commit,
            "source_registration_scope": "LOCAL_ONLY", "allowed_phases": [phase], "attempt_id": "attempt02",
            "execution_kind": "endpoint_scoring" if endpoint else {"B": "training", "W": "diagnostic", "R": "reconstruction"}[phase],
            "protocol_sha256": R_SHA if phase == "R" else PROTOCOL_SHA,
            "operational_amendment_sha256": registration["_sha256"], "source_files": sources,
            "artifacts": frozen_artifacts, "actual_source_A": parents["A"],
            "created_at": datetime.now(timezone.utc).isoformat(), "outcome_values_used_for_registration": False}
        if endpoint:
            freeze["training_parents"] = {phase: parents[phase]}
        else:
            freeze["scientific_parent"] = freezes["A"]["scientific_parent"]
        payload = outputs[filename] = encode(freeze)
        dependencies = INITIAL_IDS | FOLLOWUP_IDS if endpoint else {f"A-{seed}" for seed in SEEDS}
        for seed in (None,) if endpoint or phase == "W" else SEEDS:
            additions.append(job(phase, args.output / filename, hashlib.sha256(payload).hexdigest(), args, dependencies, seed, endpoint))
    extended = queue_extension(queue, additions, args.root, args.stage == "endpoints")
    outputs["QUEUE_EXTENDED.json"] = encode(extended)
    outputs["BUNDLE.json"] = encode({"schema": "hepta.fullstudy.registration-bundle.1", "stage": args.stage,
        "source_registration_scope": "LOCAL_ONLY", "registered_commit": args.source_commit,
        "previous_queue_sha256": args.expected_queue_sha256, "queue_activated": False, "workers_started": 0,
        "new_endpoint_roles_opened": [], "files": {name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in outputs.items()}})
    args.output.mkdir(parents=True, exist_ok=False)
    for name, payload in outputs.items():
        with (args.output / name).open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        saved = descriptor(args.output / name)
        require(saved["bytes"] == len(payload) and saved["sha256"] == hashlib.sha256(payload).hexdigest(), "Registration write readback differs")
    bundle = descriptor(args.output / "BUNDLE.json")
    child_end = resource.getrusage(resource.RUSAGE_CHILDREN)
    cost = {"schema": "hepta.fullstudy.metadata-registration-cost.1", "stage": args.stage, "bundle": bundle,
        "wall_seconds": time.monotonic() - started_wall, "cpu_seconds": time.process_time() - started_cpu,
        "process_cpu_seconds_total": time.process_time(),
        "child_process_cpu_seconds": (child_end.ru_utime + child_end.ru_stime) - (child_start.ru_utime + child_start.ru_stime),
        "cpu_accounting": "cpu_seconds is parent delta; child_process_cpu_seconds is separate waited-child delta, including Git. process_cpu_seconds_total is not another additive component.",
        "process_peak_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024,
        "scheduled_gradient_microsteps": 0, "endpoint_scoring_performed": False,
        "measurement_scope": "Validation, hashing, source verification and sealed bundle writes; excludes serialization/write/readback of this final cost receipt."}
    cost_path = args.output / "REGISTRATION_COST.json"
    with cost_path.open("xb") as stream:
        stream.write(encode(cost))
        stream.flush()
        os.fsync(stream.fileno())
    return {"bundle": bundle, "queue": descriptor(args.output / "QUEUE_EXTENDED.json"),
            "job_count": len(extended["jobs"]), "queue_activated": False, "source_registration_scope": "LOCAL_ONLY",
            "registration_cost": descriptor(cost_path)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True, choices=("followups", "endpoints"))
    for name in ("root", "assets", "amendment", "amendment-sha256", "source-commit", "source-git-root", "a-freeze",
                 "a-freeze-sha256", "c-freeze", "c-freeze-sha256", "queue", "expected-queue-sha256", "output"):
        parser.add_argument("--" + name, required=True)
    print(json.dumps(register(parser.parse_args()), sort_keys=True))


if __name__ == "__main__":
    main()
