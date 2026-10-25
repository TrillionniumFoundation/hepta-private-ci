"""Freeze then execute an H=1, common-public-history information diagnostic.

No formal holdout is evaluated. The fit-only finite-history lookup and legacy
critic action are sealed before any independent evaluation branch is emitted.
All hidden targets and output scores stay in this owner-side diagnostic runner.
"""

import argparse
from collections import Counter
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
import traceback

import numpy as np
import torch

from ...abc_recovery.control import load_feedback
from ...abc_recovery.media import RawMediaArchive, reopen_archive_records
from ...abc_recovery.runtime import ACTIONS, initialize, public_digest, public_features, public_frame, transition, work_counts
from ...v7.evaluation import load_reward
from ...v7.model import observation_digest
from ...v7.snapshot import Snapshot
from ...v7.sources import load_roles, read_manifest
from .common_history_data import offline_utilities, private_targets, public_observation, replicate_public_run, stream_seed
from .conditional_information import analyze_history, select_public_action


ROOT = Path(__file__).resolve().parents[4]
WORKSPACE = ROOT.parent
AREA = Path("experiments/multimodal_output_portfolio")
SCHEMA = "hepta.abc-next.common-history-protocol.v1"
SETTINGS = {
    "role": "forecast_fit", "pair_start": 448, "pair_count": 32,
    "private_prior": "uniform finite support, exactly integrated",
    "public_view": "both_missing", "swaps": [0, 1], "drafts_per_swap": 4,
    "remaining_horizon": 1, "fit_replicas": 32, "evaluation_replicas": 64,
    "actions": list(ACTIONS), "action_costs": [0, .002, .002, .002, .002],
    "gamma": 2.0, "net_utility_bounds": [-1.002, 1.0],
    "deterministic_action_indices": [0, 1], "alpha": .05,
    "history_observer_confidence_family": 16, "cpu_threads": 2,
    "selection": "primary fit replicas only; lowest action index breaks ties",
    "baselines": {"fixed_h1_stop": 0, "fixed_h1_couple": 4},
    "scope": "fixed finite target law, eight fixed public histories, H1; no H2/global/population claim",
}
ARTIFACTS = {
    "generator": "abc2-runs/training-001/seed-17/output_ndu/model.pt",
    "legacy_policy": "abc2-runs/control-001/seed-17/output_ndu/policies/feedback.pt",
    "primary_observer": "abc2-runs/base-recovery-001/reward-observer.pt",
    "secondary_observer": "abc2-runs/qualification-001/secondary-observer.pt",
    "manifest": "abc2-runs/source-recovery-001/source-manifest.json",
}
PIN_FILES = [str(AREA / folder / (name + ".py")) for folder, names in (
    ("v6", ("data", "neural", "observer")),
    ("v7", ("data", "model", "snapshot", "sources", "evaluation")),
    ("abc_recovery", ("emission", "media", "runtime", "risk", "critic", "control")),
    ("abc_next/design", ("common_history_data", "common_history_run", "conditional_information",
                         "conditional_information_tests", "common_history_tests"))) for name in names]


def file_sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_new(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def phase(timings, name):
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    try:
        yield
    finally:
        item = timings.setdefault(name, {"calls": 0, "wall_ns": 0, "cpu_ns": 0})
        item["calls"] += 1
        item["wall_ns"] += time.perf_counter_ns() - wall
        item["cpu_ns"] += time.process_time_ns() - cpu


def freeze(path):
    """Read only metadata/checksums; do not load targets or run a generator."""
    artifacts = {key: {"path": str(WORKSPACE / relative), "file_sha256": file_sha(WORKSPACE / relative)}
                 for key, relative in ARTIFACTS.items()}
    manifest = read_manifest(artifacts["manifest"]["path"])
    ids = manifest["roles"][SETTINGS["role"]]["source_ids"][896:960]
    if len(ids) != 64 or len(set(ids)) != 64:
        raise ValueError("The frozen private support must contain 64 distinct sources")
    cache = WORKSPACE / "abc2-assets/mnist"
    archives = {str(item): file_sha(item) for item in sorted(cache.glob("*.gz"))}
    if len(archives) != 4:
        raise ValueError("Four pinned local MNIST source archives are required")
    protocol = {"schema": SCHEMA, "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "settings": SETTINGS, "artifacts": artifacts, "cache": str(cache), "archives": archives,
        "source_code_sha256": {relative: file_sha(ROOT / relative) for relative in PIN_FILES},
        "source_support_ids_sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest(),
        "source_manifest_declared_sha256": manifest["manifest_sha256"],
        "new_diagnostic_outcomes_read_before_freeze": False,
        "raw_data_in_git": False,
        "selection_barrier": "All eight primary fit selections are durably sealed before any evaluation future draw",
        "public_conditioning_law": "Command and independently sampled initial draft do not depend on private target; complete target prior remains uniform given every public history",
        "future_law": "Independent registered PRNG streams across history/phase/action; independent sampled decoder rows within each stream",
        "determinism_justification": "Stop keeps the draft at zero cost; semantic changes latent state but retains both actual modalities and charges .002 at H1",
        "known_limitations": ["PRNG samples treated as iid under registered generator law", "imperfect local observers",
            "eight fixed histories, not independent task samples", "finite support is not an empirical posterior for other views",
            "bounded Monte Carlo intervals can be wide", "the fit-selected lookup is a diagnostic finite-history reference, not a new general neural policy",
            "step cost is a utility proxy; measured compute/time are reported separately, without converting wall time to utility"]}
    write_new(path, protocol)
    return {"protocol_path": str(path), "protocol_sha256": file_sha(path), "source_support_ids_sha256": protocol["source_support_ids_sha256"]}


def verify(protocol):
    if protocol["schema"] != SCHEMA or protocol["settings"] != SETTINGS:
        raise ValueError("Unregistered diagnostic protocol")
    if protocol["source_code_sha256"] != {relative: file_sha(ROOT / relative) for relative in PIN_FILES}:
        raise ValueError("Execution source changed after protocol freeze")
    for artifact in protocol["artifacts"].values():
        if file_sha(artifact["path"]) != artifact["file_sha256"]:
            raise ValueError("Frozen input artifact changed")
    if any(file_sha(path) != expected for path, expected in protocol["archives"].items()):
        raise ValueError("Frozen source archive changed")


@torch.inference_mode()
def collect_phase(name, replicas, roots, snapshot, targets, observers, directory, timings, work):
    archive_path, records = directory / (name + "-actual-media.zip"), []
    with RawMediaArchive(archive_path) as archive, (directory / (name + "-ledger.jsonl")).open("x") as ledger:
        for history_index, root in enumerate(roots):
            for action_index, action in enumerate(ACTIONS):
                with phase(timings, name + "_generation_and_transition"):
                    parent = replicate_public_run(root, replicas)
                    rng = torch.Generator().manual_seed(stream_seed(name, history_index, action))
                    child = transition(snapshot._model, parent, action, generator=rng)
                    work.update(work_counts(child))
                with phase(timings, name + "_archive_append"):
                    _, _, media = archive.append(child.pixels, child.tokens)
                    records.extend(media)
                ledger.write(json.dumps({"history": history_index, "action": action,
                    "action_index": action_index, "phase": name, "replicas": replicas,
                    "public_parent_sha256": public_digest(public_frame(root)),
                    "transition_ledger": child.ledger, "actual_media": media}, sort_keys=True) + "\n")
            ledger.flush()
            os.fsync(ledger.fileno())
    with phase(timings, name + "_independent_closed_archive_readback"):
        pixels, captions = reopen_archive_records(archive_path, records)
    if len(records) != len(roots) * len(ACTIONS) * replicas:
        raise ValueError("Incomplete actual-media census")
    arrays = {name: [] for name in observers}
    for history_index, root in enumerate(roots):
        selected = slice(history_index * len(ACTIONS) * replicas, (history_index + 1) * len(ACTIONS) * replicas)
        for observer_name, observer in observers.items():
            with phase(timings, name + "_offline_" + observer_name + "_scoring"):
                arrays[observer_name].append(offline_utilities(observer, pixels[selected], captions[selected],
                    targets[history_index // SETTINGS["drafts_per_swap"]], replicas, SETTINGS["action_costs"]))
    arrays = {key: np.stack(value) for key, value in arrays.items()}
    np.savez_compressed(directory / (name + "-utilities.npz"), **arrays)
    receipt = {"archive_file_sha256": file_sha(archive_path), "actual_terminal_media_rows": len(records),
        "complete_required_media_rows": sum(row["required_output_complete"] for row in records),
        "target_scoring_rows_per_observer": int(next(iter(arrays.values())).size),
        "utility_arrays_file_sha256": file_sha(directory / (name + "-utilities.npz")),
        "ledger_file_sha256": file_sha(directory / (name + "-ledger.jsonl"))}
    return arrays, receipt


@torch.inference_mode()
def run(protocol_path, directory):
    directory.mkdir(parents=True, exist_ok=False)
    timings, work, public_policy_work = {}, Counter(), Counter()
    wall_start, cpu_start = time.perf_counter_ns(), time.process_time_ns()
    started = datetime.now(timezone.utc).isoformat()
    try:
        with phase(timings, "registration_and_loading"):
            protocol = json.loads(protocol_path.read_text())
            verify(protocol)
            torch.set_num_threads(SETTINGS["cpu_threads"])
            artifacts = protocol["artifacts"]
            snapshot = Snapshot.load(artifacts["generator"]["path"], expected_file_sha256=artifacts["generator"]["file_sha256"])
            policy = load_feedback(artifacts["legacy_policy"]["path"])
            if policy.profile != {"gamma": 2., "draft_mode": "observed", "allocation_only": False, "utility": "joint"}:
                raise ValueError("Legacy policy does not match the diagnostic utility/risk profile")
            observers = {name: load_reward(artifacts[name + "_observer"]["path"], artifacts[name + "_observer"]["file_sha256"])[0]
                         for name in ("primary", "secondary")}
            corpus = load_roles(protocol["cache"], artifacts["manifest"]["path"], roles=(SETTINGS["role"],))
            pool = corpus.splits[SETTINGS["role"]]
            ids = pool.ids[896:960]
            if hashlib.sha256("\n".join(ids).encode()).hexdigest() != protocol["source_support_ids_sha256"]:
                raise ValueError("Private finite support changed")
            targets = {swap: private_targets(pool, SETTINGS["pair_start"], SETTINGS["pair_count"], swap) for swap in SETTINGS["swaps"]}
            write_new(directory / "registration.json", {"protocol_sha256": file_sha(protocol_path),
                "started_at_utc": started, "materialized_source_roles": list(corpus.splits),
                "scored_source_pair_range": [448, 480], "formal_holdout_outcomes_evaluated": False,
                "snapshot_fingerprint": snapshot.fingerprint, "torch_version": torch.__version__,
                "numpy_version": np.__version__})
        roots, histories = [], []
        for swap in SETTINGS["swaps"]:
            for draft in range(SETTINGS["drafts_per_swap"]):
                observation = public_observation(swap)
                with phase(timings, "initial_public_draft_generation"):
                    root = initialize(snapshot._model, observation,
                                      generator=torch.Generator().manual_seed(stream_seed("initial", swap, draft)))
                    root = replace(root, remaining=1)
                    work.update(work_counts(root))
                with phase(timings, "legacy_public_policy"):
                    frame = public_frame(root)
                    features = public_features(snapshot._model, frame, work=public_policy_work)
                    predictions = policy.critic.one_step_model.predict(features).numpy()[0]
                    choice = int(predictions.argmin())
                    public_policy_work.update({"critic_calls": 1, "critic_examples": 1})
                public_sha = public_digest(frame)
                full_sha = hashlib.sha256((observation_digest(observation) + public_sha).encode()).hexdigest()
                roots.append(root)
                histories.append({"history_index": len(roots) - 1, "swap": swap, "initial_draft_index": draft,
                    "public_observation_sha256": observation_digest(observation), "public_frame_sha256": public_sha,
                    "complete_public_history_sha256": full_sha, "legacy_predicted_moments": predictions.tolist(),
                    "selected_actions": {**SETTINGS["baselines"], "legacy_feedback_q1": choice}})
        write_new(directory / "public-policy-before-fit.json", histories)
        fit, fit_receipt = collect_phase("fit", SETTINGS["fit_replicas"], roots, snapshot, targets, observers, directory, timings, work)
        weights = np.full(SETTINGS["pair_count"], 1 / SETTINGS["pair_count"])
        for i, history in enumerate(histories):
            history["selected_actions"]["fit_only_public_lookup"] = select_public_action(fit["primary"][i], weights,
                gamma=SETTINGS["gamma"], utility_bounds=SETTINGS["net_utility_bounds"])
        barrier = {"sealed_at_utc": datetime.now(timezone.utc).isoformat(),
            "protocol_sha256": file_sha(protocol_path), "fit_receipt": fit_receipt,
            "evaluation_branches_emitted_or_scored": False, "histories": histories}
        write_new(directory / "fit-selection-sealed.json", barrier)
        barrier_sha = file_sha(directory / "fit-selection-sealed.json")
        print(json.dumps({"phase": "all_fit_choices_sealed", "file_sha256": barrier_sha}), flush=True)
        evaluation, evaluation_receipt = collect_phase("evaluation", SETTINGS["evaluation_replicas"], roots, snapshot, targets, observers, directory, timings, work)
        summaries = {}
        for observer in observers:
            summaries[observer] = [analyze_history(fit[observer][i], evaluation[observer][i], weights,
                public_history_digests=[history["complete_public_history_sha256"]] * len(weights),
                action_names=ACTIONS, selected_actions=history["selected_actions"], gamma=SETTINGS["gamma"],
                utility_bounds=SETTINGS["net_utility_bounds"], alpha=SETTINGS["alpha"],
                family_history_count=SETTINGS["history_observer_confidence_family"],
                deterministic_actions=tuple(SETTINGS["deterministic_action_indices"]),
                predicted_moments={"legacy_q1": history["legacy_predicted_moments"]} if observer == "primary" else None)
                for i, history in enumerate(histories)]
        snapshot.verify_integrity()
        verify(protocol)
        if file_sha(directory / "fit-selection-sealed.json") != barrier_sha:
            raise ValueError("Fit selection seal changed during evaluation")
        report = {"schema": "hepta.abc-next.common-history-result.v1", "protocol_sha256": file_sha(protocol_path),
            "fit_selection_seal_sha256": barrier_sha, "started_at_utc": started,
            "completed_at_utc": datetime.now(timezone.utc).isoformat(), "settings": SETTINGS,
            "histories": histories, "observer_results": summaries,
            "fit_receipt": fit_receipt, "evaluation_receipt": evaluation_receipt,
            "actual_generator_work": dict(work), "legacy_public_policy_work": dict(public_policy_work),
            "timing_phases": timings, "total_wall_ns": time.perf_counter_ns() - wall_start,
            "total_cpu_ns": time.process_time_ns() - cpu_start,
            "timing_scope": "Measured full diagnostic execution with vectorized future branches and all offline scores; not isolated production latency or an amortization claim",
            "raw_data_archive_required_for_completion": False,
            "limitations": protocol["known_limitations"]}
        write_new(directory / "report.json", report)
        print(json.dumps({"phase": "complete", "report_path": str(directory / "report.json"),
            "report_file_sha256": file_sha(directory / "report.json"), "wall_seconds": report["total_wall_ns"] / 1e9}), flush=True)
    except Exception as error:
        write_new(directory / "failure.json", {"error_type": type(error).__name__, "error": str(error),
            "traceback": traceback.format_exc(), "timings": timings, "work": dict(work)})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--freeze", type=Path)
    modes.add_argument("--protocol", type=Path)
    parser.add_argument("--outdir", type=Path)
    args = parser.parse_args()
    if args.freeze:
        if args.outdir:
            parser.error("Freeze writes the protocol only")
        print(json.dumps(freeze(args.freeze)), flush=True)
    else:
        if args.outdir is None:
            parser.error("Execution requires an exclusive new --outdir")
        run(args.protocol, args.outdir)


if __name__ == "__main__":
    main()
