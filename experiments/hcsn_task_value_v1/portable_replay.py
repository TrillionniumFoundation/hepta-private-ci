"""Read-only replay of relocated evidence; historical filesystem time is not recreated."""

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import math
from pathlib import Path, PurePosixPath

from . import analysis
from .analysis_audit import digest, read_json, registered_jobs, pending_jobs


PACKAGE = Path(__file__).resolve().parent
RESULTS_SUFFIX = PurePosixPath("experiments/hcsn_task_value_v1/results")
CHRONOLOGY_ERROR = "Test access predates durable validation selection or is unrecorded"


def member_path(root, name):
    name = PurePosixPath(name)
    if name.is_absolute() or ".." in name.parts or "\\" in str(name) or not name.parts:
        raise ValueError("Unsafe evidence member")
    root = Path(root).resolve()
    candidate = root.joinpath(*name.parts)
    if not candidate.resolve().is_relative_to(root):
        raise ValueError("Evidence member escapes restored root")
    if not candidate.is_file() or candidate.is_symlink():
        raise ValueError("Evidence member is missing or a symlink: "+str(name))
    return candidate


def verify_members(root, manifest_path):
    manifest = read_json(manifest_path)
    if manifest.get("schema") != "hcsn-evidence-bundle.v1":
        raise ValueError("Unrecognized evidence manifest")
    index = {}
    for row in manifest["members"]:
        name = row["path"]
        if name in index:
            raise ValueError("Duplicate manifest member")
        path = member_path(root, name)
        if path.stat().st_size != row["bytes"] or digest(path) != row["sha256"]:
            raise ValueError("Evidence differs from published manifest: "+name)
        index[name] = row
    return manifest, index


class LogRelocation:
    """An exact allowlist; never search the old root or alter filesystem metadata."""

    def __init__(self, root, index):
        self.root, self.index = Path(root).resolve(), index
        self.mapping, self.records = {}, []

    def add(self, receipt, expected_member):
        old_root = PurePosixPath(receipt["cwd"])
        logged = PurePosixPath(receipt["log_path"])
        if not old_root.is_absolute() or ".." in old_root.parts or ".." in logged.parts:
            raise ValueError("Invalid original log root/path")
        absolute = logged if logged.is_absolute() else old_root/logged
        try:
            relative = absolute.relative_to(old_root/RESULTS_SUFFIX)
        except ValueError as error:
            raise ValueError("Log is outside the declared old results root") from error
        if relative.as_posix() != expected_member:
            raise ValueError("Log does not identify the expected archived job")
        record = self.index.get(expected_member)
        if record is None or record["sha256"] != receipt["log_sha256"]:
            raise ValueError("Log receipt and archive manifest hashes disagree")
        target = member_path(self.root, expected_member)
        if digest(target) != receipt["log_sha256"]:
            raise ValueError("Relocated log hash mismatch")
        for key in (str(logged), str(absolute)):
            if key in self.mapping and self.mapping[key] != target:
                raise ValueError("Ambiguous log relocation")
            self.mapping[key] = target
        self.records.append(dict(member=expected_member, sha256=record["sha256"]))
        return target

    def path(self, value, *parts):
        path = Path(value, *parts)
        return self.mapping.get(str(path), path)


def isolated_audit(resolver):
    spec = importlib.util.spec_from_file_location("_hcsn_relocated_audit", PACKAGE/"analysis_audit.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.Path = resolver.path
    return module


def recorded_order(access, meter):
    """Load-log ordering only; this cannot prove original selection-file chronology."""
    times = [row["unix_seconds"] for row in access]
    splits = [row["split"] for row in access]
    start = datetime.fromisoformat(meter["started_at_utc"]).timestamp()
    end = datetime.fromisoformat(meter["ended_at_utc"]).timestamp()
    return bool(times and all(math.isfinite(t) and start <= t <= end for t in times)
                and all(a <= b for a, b in zip(times, times[1:]))
                and splits[:2] == ["train", "val"] and "test" in splits
                and all(s == "test" for s in splits[splits.index("test"):]))


def compare_tree(actual, expected, path="root", stats=None):
    """Compare every key/value, allowing only declared floating-point roundoff."""
    stats = dict(numbers=0, maximum_absolute_error=0.) if stats is None else stats
    if isinstance(actual, dict) and isinstance(expected, dict):
        if set(actual) != set(expected):
            raise ValueError("Replayed keys differ: "+path)
        for key in actual:
            compare_tree(actual[key], expected[key], path+"."+key, stats)
    elif isinstance(actual, (list, tuple)) and isinstance(expected, (list, tuple)):
        if len(actual) != len(expected):
            raise ValueError("Replayed lengths differ: "+path)
        for i, (a, b) in enumerate(zip(actual, expected, strict=True)):
            compare_tree(a, b, f"{path}[{i}]", stats)
    elif isinstance(actual, (int, float)) and not isinstance(actual, bool) and isinstance(expected, (int, float)) and not isinstance(expected, bool):
        stats["numbers"] += 1
        stats["maximum_absolute_error"] = max(stats["maximum_absolute_error"], abs(actual-expected))
        if not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("Replayed numeric value differs: "+path)
    elif type(actual) is not type(expected) or actual != expected:
        raise ValueError("Replayed value differs: "+path)
    return stats


def replay(results_root, manifest_path, output):
    root, output = Path(results_root).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError("Replay output must be new")
    if output.is_relative_to(root):
        raise ValueError("Replay output must be outside the restored evidence root")
    manifest, index = verify_members(root, manifest_path)
    study = root/"study001"
    required = ("study001/analysis/aggregate.json", "study001/protocol.json",
                "study001/registration_receipt.json", "study001/execution.json")
    if any(name not in index for name in required):
        raise ValueError("Manifest lacks original analysis/registration evidence")
    original = read_json(study/"analysis/aggregate.json")
    protocol = read_json(study/"protocol.json")
    for name, wanted in original["source_sha256"].items():
        if digest(PACKAGE/name) != wanted:
            raise ValueError("Original analysis implementation differs: "+name)
    registered = registered_jobs(study, protocol)
    if pending_jobs(study, registered):
        raise ValueError("Published queue is not complete")
    resolver = LogRelocation(root, index)
    meters = {}
    for row in registered:
        identity = row["id"]
        meters[identity] = read_json(study/"meter"/(identity+".json"))
        resolver.add(meters[identity], f"study001/meter/{identity}.json.log")
    frontend_meter = read_json(root/"frontend_cost001/whole_process.json")
    resolver.add(frontend_meter, "frontend_cost001/whole_process.json.log")
    module = isolated_audit(resolver)
    integrity = module.global_integrity(study, protocol)
    if integrity["errors"]:
        raise ValueError("Registration integrity failure: "+str(integrity["errors"]))
    old_jobs = {row["id"]: row for row in original["job_audit"]}
    if set(old_jobs) != {row["id"] for row in registered}:
        raise ValueError("Original aggregate job membership differs")
    cache, audits, job_receipts = {}, [], []
    for registration in registered:
        identity, old = registration["id"], old_jobs[registration["id"]]
        if not old["audit_ok"] or old["errors"]:
            raise ValueError("Historical audit was not successful: "+identity)
        current = module.audit_job(study, registration, cache)
        remaining = [error for error in current["errors"] if error != CHRONOLOGY_ERROR]
        if remaining:
            raise ValueError("Recomputable audit failed: "+identity+" "+str(remaining))
        access = read_json(study/"runs"/identity/"access.json")
        if not recorded_order(access, meters[identity]):
            raise ValueError("Recorded access order invalid: "+identity)
        keys = ("job", "metrics", "validation", "costs", "allocated_parameters", "trainable_parameters",
                "actual_updates", "selected_step", "group_delta", "selected_group_delta", "mean_gradient",
                "dataset_sha256", "inference", "source_hashes")
        numeric = compare_tree({k: current[k] for k in keys}, {k: old[k] for k in keys})
        # Keep the original audit result, including its current mtime error. Do
        # not relabel it as a new successful execution-chronology audit.
        audits.append(current)
        job_receipts.append(dict(id=identity, recomputable_checks_verified=True,
            original_audit_errors_on_restored_files=current["errors"], numeric_comparison=numeric,
            recorded_load_order_verified=True,
            filesystem_chronology="not_reconstructible_from_archive",
            original_filesystem_chronology="inherited_historical_audit"))
    groups, planned = {}, {}
    for row in audits:
        key = analysis.condition(row["job"])
        arms = groups.setdefault(key, {})
        seed = row["job"]["seed"]
        seeds = arms.setdefault(row["job"]["arm"], {})
        if seed in seeds:
            raise ValueError("Duplicate paired arm/seed")
        seeds[seed] = row
        planned.setdefault(key, set()).add(row["job"]["arm"])
    e = protocol["evaluation"]
    policy = dict(accuracy_noninferiority_margin=e["accuracy_noninferiority_margin"],
                  ce_noninferiority_ratio=e["maximum_ce_ratio"], parameter_gap=e["parameter_relative_gap_max"],
                  training_cpu_gap=e["cpu_relative_gap_max"])
    compare_tree(policy, original["analysis_thresholds"])
    if e["confidence"] != .95 or abs(e["paired_seed_t_critical"]-4.302652729911275) > 1e-12:
        raise ValueError("Unsupported historical interval contract")
    pairs = []
    for key, names in planned.items():
        for a, b in analysis.planned_pairs(names):
            cases = ("length32", "missing_modality0", "missing_modality1") if key[0] == "async_av" else ("length32", "length64", "length128")
            for case in cases:
                pairs.append(analysis.pair(groups[key][a], groups[key][b], case, protocol["seeds"], policy))
    sections = dict(comparisons=pairs, factorial=analysis.factorial(groups, protocol["seeds"], planned),
                    arm_summaries=analysis.arm_summaries(groups), inference_summaries=analysis.inference_summaries(groups),
                    shared_frontend_account=module.frontend_account(study, protocol))
    statistics = {name: compare_tree(value, original[name], name) for name, value in sections.items()}
    receipt = dict(schema="hcsn-portable-evidence-replay.v1", created_at_utc=datetime.now(timezone.utc).isoformat(),
        results_root=str(root), source_package=str(PACKAGE), manifest_sha256=digest(manifest_path),
        archive_sha256=manifest["archive_sha256"], verified_members=len(index),
        original_aggregate_sha256=digest(study/"analysis/aggregate.json"),
        protocol_sha256=digest(study/"protocol.json"), analysis_source_sha256=original["source_sha256"],
        replay_source_sha256=digest(__file__), jobs=len(audits), comparisons=len(pairs),
        recomputable_checks_and_statistics_match=True, statistic_comparisons=statistics,
        historical_execution_audit="inherited_historical_audit; bound to verified original aggregate",
        independent_filesystem_chronology_audit="unavailable: deterministic archive omits original selection-file mtime",
        recorded_order_scope="Recorded train/validation/test loads within recorded worker interval; not independent proof of selection-file creation time",
        qualification_scope="Reproduces archived numerical qualification flags; historical execution chronology remains inherited",
        model_forward_or_training_executed=False, source_evidence_modified=False,
        relocated_logs=resolver.records, job_receipts=job_receipts)
    output.mkdir(parents=True)
    (output/"replay_receipt.json").write_text(json.dumps(receipt, indent=2, ensure_ascii=False, allow_nan=False)+"\n")
    print(json.dumps({key: receipt[key] for key in ("verified_members", "jobs", "comparisons", "recomputable_checks_and_statistics_match", "independent_filesystem_chronology_audit")}, indent=2))
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", required=True, type=Path)
    parser.add_argument("--manifest", type=Path, default=PACKAGE/"artifacts/study001/study001.json")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    replay(args.results_root, args.manifest, args.output)
