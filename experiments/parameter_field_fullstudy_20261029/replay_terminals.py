"""R: reconstruct and archive every A terminal, without changing A evidence.

These are newly reconstructed complete terminal records. Matching the original
component hashes is distinct from claiming the original tensor bytes were
archived. R has its own source/protocol freeze, work ledger and storage ceiling.
"""

import argparse
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import time

import torch

from ..multimodal_output_portfolio.field_bridge_v3_20261027 import learning
from ..multimodal_output_portfolio.field_bridge_v3_20261027.assets import load_assets
from ..multimodal_output_portfolio.field_bridge_v3_20261027.training_common import Costs
from .bank import initialize
from .branching import BASELINES, codec, dynamics_identity, strict, timed
from .run import ROOT, file_hash, verify_freeze
from .sources import load_training_roles

PROTOCOL_SCHEMA = "hepta.fullstudy.branch-terminal-reconstruction.protocol.1"
REGISTRATION = {
    "stage": "R", "source_stage": "A", "model_seeds": [17, 29, 43],
    "schedule_ids": [6000, 6001, 6002, 6003], "prefixes": ["baseline", "balanced"],
    "parent_clocks": [0, 48, 96, 144, 192, 240], "candidate_actions": [0, 1, 2, 3],
    "baseline_actions": {"17": 2, "29": 3, "43": 3}, "terminal_clock": 288, "guard_grain": 48,
    "parents_per_seed": 48, "terminals_per_seed": 192, "parents_total": 144, "terminals_total": 576,
    "scheduled_gradient_microsteps_per_seed": 32256, "scheduled_gradient_microsteps_total": 96768,
    "global_raw_cap_bytes": 2 * 1024 ** 3, "allocatable_reserve_bytes": 2 * 1024 ** 3,
    "minimum_available_inodes": 2000, "cpu_seconds_per_seed": 7200, "wall_seconds_per_seed": 10800,
    "threads": 2, "interop_threads": 1,
    "cost_scope": "Additional reconstruction work only; original scientific counts remain unchanged.",
    "evidence_scope": "Newly reconstructed terminal bytes matching original component/dynamics/history hashes, not previously archived original bytes.",
    "new_source_roles": [], "new_fitting_or_selection": False,
}
TRAINING_ROLES = ["development_gradient", "development_rehearsal", "development_probe", "development_guard"]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def expected_parent_keys():
    return [(schedule, prefix, clock) for schedule in REGISTRATION["schedule_ids"]
            for prefix in REGISTRATION["prefixes"] for clock in REGISTRATION["parent_clocks"]]


def deterministic_receipt(receipt):
    require(type(receipt) is dict and "resources" in receipt, "Transaction has no separate work ledger")
    return {key: value for key, value in receipt.items() if key != "resources"}


def compare_receipt(expected, actual):
    left, right = deterministic_receipt(expected), deterministic_receipt(actual)
    require(set(left) == set(right), "Replayed transaction field inventory differs")
    different = [key for key in left if codec.digest(left[key]) != codec.digest(right[key])]
    require(not different, "Replayed deterministic transaction differs: " + ", ".join(different))
    return {"equal": True, "fields": sorted(left), "sha256": codec.digest(right)}


def compare_identity(expected, actual, label):
    require(set(expected) == {"components", "dynamics", "controller_history"}
            and set(actual) == set(expected), label + " identity inventory differs")
    different = [key for key in expected["components"]
                 if expected["components"][key] != actual["components"].get(key)]
    require(not different and codec.digest(expected) == codec.digest(actual),
            label + " complete declared identity differs: " + ", ".join(different))
    return {"equal": True, "dynamics": actual["dynamics"], "controller_history": actual["controller_history"],
            "components": actual["components"]}


class ReplayBudget:
    """Shared-write locking enforces the new global cap across the R workers."""

    def __init__(self, root, costs):
        self.root, self.costs = Path(root).resolve(), costs
        self.wall, self.cpu = time.monotonic(), time.process_time()

    def check(self, additional=0):
        require(type(additional) is int and additional >= 0, "Invalid pending R payload size")
        stat = os.statvfs(self.root)
        require(stat.f_bavail * stat.f_frsize >= REGISTRATION["allocatable_reserve_bytes"] + additional
                and stat.f_favail >= REGISTRATION["minimum_available_inodes"], "R disk/inode reserve exhausted")
        raw = sum(path.stat().st_size for path in self.root.rglob("*") if path.is_file())
        require(raw + additional <= REGISTRATION["global_raw_cap_bytes"], "R global raw evidence cap exhausted")
        require(time.monotonic() - self.wall <= REGISTRATION["wall_seconds_per_seed"]
                and time.process_time() - self.cpu <= REGISTRATION["cpu_seconds_per_seed"], "R CPU/wall ceiling exhausted")
        require(self.costs.values.get("scheduled_gradient_microsteps", 0)
                <= REGISTRATION["scheduled_gradient_microsteps_per_seed"], "R physical gradient ceiling exceeded")

    def write(self, path, payload):
        path = Path(path).resolve()
        require(path.is_relative_to(self.root), "R evidence escapes the shared raw root")
        self.check()
        with (self.root / "R_WRITE.lock").open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                self.check(len(payload))
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                digest = hashlib.sha256(payload).hexdigest()
                require(path.stat().st_size == len(payload) and file_hash(path) == digest, "R literal file readback differs")
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        self.costs.add("R_persisted_bytes", len(payload))
        return {"path": path.relative_to(self.root).as_posix(), "bytes": len(payload), "sha256": digest}

    def json(self, path, value, compress=False):
        raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
        return self.write(path, gzip.compress(raw, mtime=0) if compress else raw)


def read_terminal(path, artifact):
    packed = Path(path).read_bytes()
    require(len(packed) == artifact["bytes"] and hashlib.sha256(packed).hexdigest() == artifact["sha256"],
            "Reconstruction archive bytes changed")
    raw = gzip.decompress(packed)
    require(len(raw) == artifact["raw_bytes"] and hashlib.sha256(raw).hexdigest() == artifact["raw_sha256"],
            "Reconstruction uncompressed state changed")
    codec.loads(raw, artifact["raw_sha256"], artifact["raw_bytes"])
    return raw


def persist_terminal(adapter, raw, path, budget, costs):
    packed = timed(costs, "R_terminal_compress", lambda: gzip.compress(raw, mtime=0))
    artifact = timed(costs, "R_terminal_write", lambda: budget.write(path, packed))
    artifact.update(raw_bytes=len(raw), raw_sha256=hashlib.sha256(raw).hexdigest(),
                    reconstructed_after_original_run=True, original_terminal_tensor_previously_archived=False)
    reread = timed(costs, "R_terminal_archive_readback", lambda: read_terminal(path, artifact))
    require(reread == raw, "R decompression failed literal byte equality")
    adapter.restore(reread, artifact["raw_sha256"])
    require(codec.dumps(adapter.capture()) == raw, "R live terminal restore failed literal byte equality")
    costs.add("R_literal_terminal_restores_verified")
    artifact["literal_archive_and_live_restore_equal"] = True
    return artifact


def load_inputs(root, seed, source_protocol_sha256):
    directory = Path(root) / "stage_A" / f"seed-{seed}" / "bank"
    require(not (directory.parent / "FAILED.json").exists(), "A failed scientific instance cannot supply R evidence")
    bank_path, trace_path = directory / "BANK.json", directory / "trace.jsonl.gz"
    bank = json.loads(bank_path.read_text())
    require(bank.get("complete") is True and bank["seed"] == seed, "Source A bank is incomplete")
    rows = bank["records"]
    keys = [(row["schedule_id"], row["prefix"], row["step"]) for row in rows]
    require(keys == expected_parent_keys(), "Source A parent population/order differs")
    traces = {}
    with gzip.open(trace_path, "rt") as stream:
        for line in stream:
            record = json.loads(line)
            key = (record["schedule_id"], record["prefix"], record["step"], record["action"])
            require(key not in traces, "Duplicate original branch trace")
            traces[key] = record
    expected_trace_keys = {(*key, action) for key in keys for action in REGISTRATION["candidate_actions"]}
    require(set(traces) == expected_trace_keys, "Original trace population is incomplete")
    parents, environment = [], None
    for row, key in zip(rows, keys, strict=True):
        schedule, prefix, clock = key
        path = directory / f"schedule-{schedule}-{prefix}-step-{clock}.state"
        raw = path.read_bytes()
        require(len(raw) == row["parent_bytes"], "Source parent byte count differs")
        parent = codec.loads(raw, row["parent_sha256"], row["parent_bytes"])
        cursor = parent["cursor"]
        require((cursor["seed"], cursor["schedule_id"], cursor["path_kind"], cursor["clock"])
                == (seed, schedule, prefix, clock) and cursor["remaining_steps"] == 288 - clock,
                "Source parent cursor differs")
        require(parent["binding"]["protocol_sha256"] == source_protocol_sha256,
                "R source-stage protocol identity differs")
        fixed = codec.digest({"binding": parent["binding"], "immutable": parent["immutable"]})
        environment = fixed if environment is None else environment
        require(fixed == environment, "A parent immutable environments differ within seed")
        require([branch["action"] for branch in row["branches"]] == REGISTRATION["candidate_actions"],
                "Original four-action branch population differs")
        for action, branch in enumerate(row["branches"]):
            trace = traces[(*key, action)]
            require(trace["parent"] == row["parent_sha256"] and trace["branch"] == branch,
                    "A trace does not bind its bank parent and branch")
            transactions = trace["transactions"]
            require(len(transactions) == (288 - clock) // 48, "Original tail length differs")
            for offset, receipt in enumerate(transactions):
                selected = action if offset == 0 else BASELINES[seed]
                require((receipt["start"], receipt["end"], receipt["action_index"], receipt["schedule_id"])
                        == (clock + 48 * offset, clock + 48 * (offset + 1), selected, schedule),
                        "Original action/baseline continuation differs")
                deterministic_receipt(receipt)
        parents.append({"row": row, "parent": parent, "raw": raw, "path": path,
                        "traces": [traces[(*key, action)] for action in REGISTRATION["candidate_actions"]]})
    return parents, {"bank_sha256": file_hash(bank_path), "trace_sha256": file_hash(trace_path),
                     "source_protocol_sha256": source_protocol_sha256,
                     "source_freeze_sha256": parents[0]["parent"]["binding"]["source_freeze_sha256"],
                     "source_parent_count": len(parents)}


def replay_parent(adapter, source, directory, budget):
    row, raw, costs = source["row"], source["raw"], adapter.context.costs
    stem = f"schedule-{row['schedule_id']}-{row['prefix']}-step-{row['step']}"
    artifacts = []
    for action, original_branch in enumerate(row["branches"]):
        budget.check()
        before_work = costs.snapshot()
        adapter.restore(raw, row["parent_sha256"])
        observed, comparisons = [], []
        expected = source["traces"][action]["transactions"]
        first_identity = None
        for offset, original_receipt in enumerate(expected):
            budget.check()
            chosen = action if offset == 0 else BASELINES[adapter.context.seed]
            receipt = adapter.transition(chosen)
            comparisons.append(compare_receipt(original_receipt, receipt))
            observed.append(receipt)
            if offset == 0:
                first_identity = compare_identity(original_branch["first"], dynamics_identity(adapter.capture()), "First legal successor")
                require(receipt["accepted"] == original_branch["accepted"], "Original first-guard result differs")
        require(adapter.clock == 288, "Reconstruction did not reach the registered terminal clock")
        terminal_raw, terminal_sha = adapter.seal()
        terminal_identity = compare_identity(original_branch["terminal"], dynamics_identity(adapter.capture()), "Terminal")
        checkpoint = persist_terminal(adapter, terminal_raw, directory / f"{stem}-action-{action}.bin.gz", budget, costs)
        require(checkpoint["raw_sha256"] == terminal_sha, "Terminal seal identity differs from saved reconstruction")
        receipt = {"schema": "hepta.fullstudy.R.branch-replay.1", "seed": adapter.context.seed,
                   "schedule_id": row["schedule_id"], "prefix": row["prefix"], "parent_clock": row["step"],
                   "action": action, "source_parent_sha256": row["parent_sha256"],
                   "first_identity_match": first_identity, "terminal_identity_match": terminal_identity,
                   "transaction_comparisons": comparisons, "actual_transactions": observed,
                   "checkpoint": checkpoint, "costs": costs.since(before_work),
                   "scheduled_gradient_microsteps": 288 - row["step"],
                   "new_samples_or_fits": False, "original_tensor_previously_archived": False}
        trace = budget.json(directory / f"{stem}-action-{action}.trace.json.gz", receipt, compress=True)
        artifacts.append({key: receipt[key] for key in ("seed", "schedule_id", "prefix", "parent_clock", "action",
                         "source_parent_sha256", "checkpoint", "costs", "scheduled_gradient_microsteps")}
                         | {"trace": trace, "all_original_deterministic_receipts_equal": True,
                            "first_dynamics_sha256": first_identity["dynamics"],
                            "terminal_dynamics_sha256": terminal_identity["dynamics"]})
    return artifacts


def validate_protocol(protocol, freeze, protocol_path):
    require(protocol.get("schema") == PROTOCOL_SCHEMA and protocol.get("execution_ready") is True
            and protocol.get("registration") == REGISTRATION, "R protocol does not freeze the exact reconstruction design")
    require(file_hash(protocol_path) == freeze["protocol_sha256"], "R protocol bytes differ from the source freeze")
    original = protocol.get("source_stage_A_protocol_sha256")
    require(type(original) is str and len(original) == 64 and all(c in "0123456789abcdef" for c in original),
            "R must identify the original A protocol without rewriting it")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--freeze", required=True)
    parser.add_argument("--seed", required=True, type=int, choices=[17, 29, 43])
    parser.add_argument("--protocolR", required=True)
    args = parser.parse_args()
    torch.set_num_threads(REGISTRATION["threads"])
    torch.set_num_interop_threads(REGISTRATION["interop_threads"])
    torch.use_deterministic_algorithms(True)
    freeze = verify_freeze(args.freeze, "R")
    require(Path(__file__).resolve().relative_to(ROOT).as_posix() in freeze["source_files"], "R source is not frozen")
    protocol = json.loads(Path(args.protocolR).read_text())
    validate_protocol(protocol, freeze, args.protocolR)
    root, costs = Path(args.root).resolve(), Costs()
    budget = ReplayBudget(root, costs)
    budget.check()
    parents, source_identity = timed(costs, "R_input_validation", lambda: load_inputs(
        root, args.seed, protocol["source_stage_A_protocol_sha256"]))
    runtime = codec.digest(strict.runtime_descriptor())
    require(all(item["parent"]["binding"]["runtime_sha256"] == runtime for item in parents),
            "R runtime differs from original A state environment")
    directory = root / "stage_R" / f"seed-{args.seed}"
    directory.mkdir(parents=True, exist_ok=False)
    try:
        originals, observers, assets = timed(costs, "R_asset_load", lambda: load_assets(args.assets, [args.seed], ["reward"]))
        corpus = timed(costs, "R_context_sources_load", lambda: load_training_roles(args.assets, "A", TRAINING_ROLES))
        learning_protocol = json.loads(Path(learning.__file__).with_name("PROTOCOL.json").read_text())
        context = learning.make_context(originals[args.seed], corpus, observers, args.seed, "development", learning_protocol, costs)
        adapter = initialize(context, parents[0]["parent"]["binding"], 6000, "baseline")
        terminals = []
        for source in parents:
            terminals.extend(replay_parent(adapter, source, directory, budget))
            print(json.dumps({"stage": "R", "seed": args.seed, "terminals_verified": len(terminals),
                              "scheduled_gradient_microsteps": costs.values.get("scheduled_gradient_microsteps", 0)}), flush=True)
        require(len(terminals) == REGISTRATION["terminals_per_seed"]
                and costs.values.get("scheduled_gradient_microsteps") == REGISTRATION["scheduled_gradient_microsteps_per_seed"]
                and costs.values.get("R_literal_terminal_restores_verified") == REGISTRATION["terminals_per_seed"],
                "R terminal or physical-work population is incomplete")
        result = {"schema": "hepta.fullstudy.R.complete-reconstruction.1", "complete": True, "seed": args.seed,
                  "source_stage_identity": source_identity, "terminal_count": len(terminals), "terminals": terminals,
                  "all_original_component_and_receipt_hashes_equal": True, "all_literal_terminal_restores_equal": True,
                  "original_scientific_counts_changed": False, "reconstruction_work": costs.snapshot(),
                  "scheduled_gradient_microsteps": REGISTRATION["scheduled_gradient_microsteps_per_seed"],
                  "wall_seconds": time.monotonic() - budget.wall, "cpu_seconds": time.process_time() - budget.cpu,
                  "process_cpu_seconds_total": time.process_time(), "assets": assets,
                  "new_endpoint_roles_opened": [], "new_fitting_or_selection": False,
                  "reconstructed_terminal_bytes_not_originally_archived": True,
                  "source_freeze_sha256": file_hash(args.freeze), "registered_commit": freeze["registered_commit"],
                  "protocol_R_sha256": file_hash(args.protocolR)}
        budget.json(directory / "COMPLETE.pending.json", result)
        budget.check()
        (directory / "COMPLETE.pending.json").rename(directory / "COMPLETE.json")
    except BaseException as error:
        failure = {"complete": False, "seed": args.seed, "error_type": type(error).__name__, "message": str(error),
                   "reconstruction_work": costs.snapshot(), "partial_evidence_preserved": True,
                   "original_scientific_evidence_unchanged": True}
        try:
            with (directory / "FAILED.json").open("x") as stream:
                json.dump(failure, stream, allow_nan=False)
                stream.write("\n")
        except OSError:
            print(json.dumps(failure), flush=True)
        raise


if __name__ == "__main__":
    main()
