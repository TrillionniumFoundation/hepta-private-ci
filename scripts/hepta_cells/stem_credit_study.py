"""Five-arm readout credit replay on retained CORD development observations.

Only the pre-action initial observation enters a fixed GRU and its readout. The
GRU resets per document; this does not test recurrent-body eligibility, lifelong
adaptation, authenticated feedback availability or ordinary-daemon adoption.
"""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from .readout_credit import ARMS, ReadoutCredit
from .semantic import LocalHead, LocalObjective
from .temporal import TemporalConfig, TemporalKernel


from .stem_credit_support import (
    BANDS,
    WIDTH,
    CPU_SCOPE,
    _sha,
    _write,
    _event,
    _cpu,
    _documents,
    _features,
    _score,
    _semantic_state,
)


def _cold(request):
    """Run in a fresh interpreter; no expected outputs or dev labels are supplied."""
    wall, cpu = time.perf_counter(), _cpu()
    k = request["kernel"]
    kernel, state = TemporalKernel.restore_checkpoint(
        k["path"],
        expected_sha256=k["pin"],
        cell_id=k["cell_id"],
        config=TemporalConfig(**k["config"]),
    )
    model = ReadoutCredit.restore_checkpoint(
        request["path"],
        expected_sha256=request["pin"],
        expected_contract=request["contract"],
    )
    pending = model.record()["pending"][request["decision_id"]]
    if _features(kernel, request["pending_doc"]).tolist() != pending["features"]:
        raise ValueError("cold GRU features differ from saved pre-label trace")
    model, receipt = model.feedback(
        request["decision_id"], request["targets"], **request["feedback"]
    )
    x = np.stack([_features(kernel, d) for d in request["dev_docs"]])
    predictions = model.head.predict(x).tolist()
    return dict(
        head_sha256=model.head.digest,
        state_sha256=_semantic_state(model),
        kernel_weights_sha256=kernel.weights_sha256,
        kernel_state_sha256=_sha(state),
        predictions=predictions,
        receipt=receipt,
        wall_seconds=time.perf_counter() - wall,
        cpu_seconds=_cpu() - cpu,
        cpu_scope=CPU_SCOPE,
        local_candidate_predictions=len(predictions),
        ordinary_daemon_adoptions=0,
    )


def _attempt(output, docs, features, kernel_info, protocol, seed, tau, arm):
    folder = output / f"s{seed}-t{tau}-{arm}"
    folder.mkdir()
    wall, cpu = time.perf_counter(), _cpu()
    train = [d for d in docs if d["split"] == "train"]
    dev = [d for d in docs if d["split"] == "dev"]
    dev_x = np.stack([features[d["source_group"]] for d in dev])
    result = dict(
        seed=seed,
        tau_us=tau,
        arm=arm,
        status="started",
        curves=[],
        feedback_count=0,
        attempted_readout_mac=0,
        attempted_cold_gru_mac=0,
        attempted_cold_readout_mac=0,
        attempted_feedback_calls=0,
    )
    _write(folder / "STARTED.json", dict(result, protocol_sha256=_sha(protocol)))
    model = ReadoutCredit(
        LocalHead.initialize(WIDTH, 3),
        LocalObjective("mse", 3, "retained-region-post-acquisition-correctness"),
        cell_ids=BANDS,
        owner_id="cord-credit-replay",
        version="v1",
        clock_id="fabricated-replay-us",
        arm=arm,
        tau_us=tau,
        learning_rate=0.01,
        max_pending=1,
        max_decisions=72,
        seed=seed,
    )
    initial_head = model.head.digest
    now, receipts = 0, []
    try:
        for epoch in range(protocol["passes"] + 1):
            if epoch:
                for index, doc in enumerate(train):
                    identity = f"pass{epoch}:{doc['source_group']}"
                    result["attempted_readout_mac"] += WIDTH * 3
                    model, row = model.decide(
                        identity,
                        features[doc["source_group"]],
                        reference_logits=(0.0, 0.0, 0.0),
                        mask=(True, True, True),
                        at_us=now,
                    )
                    _event(folder / "EVENTS.jsonl", dict(kind="decision", row=row))
                    due = now + doc["delay_us"]
                    feedback = dict(
                        decision_sha256=row["decision_sha256"],
                        binding=model.binding,
                        outcome_us=due,
                        available_us=due,
                        now_us=due,
                    )
                    final = epoch == protocol["passes"] and index == len(train) - 1
                    if final:
                        pending_path = folder / "PENDING.json"
                        pin = model.checkpoint(pending_path)
                        request = dict(
                            path=str(pending_path.resolve()),
                            pin=pin,
                            contract=model.contract,
                            decision_id=identity,
                            feedback=feedback,
                            targets=doc["targets"],
                            kernel=kernel_info,
                            pending_doc={
                                k: doc[k] for k in ("source_group", "initial")
                            },
                            dev_docs=[
                                {k: d[k] for k in ("source_group", "initial")}
                                for d in dev
                            ],
                        )
                        _write(folder / "COLD_REQUEST.json", request)
                    result["attempted_feedback_calls"] += 1
                    result["attempted_readout_mac"] += (
                        WIDTH * 3 * (int(arm != "frozen") + int(arm == "replay_sgd"))
                    )
                    model, receipt = model.feedback(
                        identity, doc["targets"], **feedback
                    )
                    receipts.append(receipt)
                    result["feedback_count"] += 1
                    _event(
                        folder / "EVENTS.jsonl",
                        dict(
                            kind="feedback",
                            source_group=doc["source_group"],
                            targets=doc["targets"],
                            at_us=due,
                            receipt=receipt,
                        ),
                    )
                    now = due + 1
            result["attempted_readout_mac"] += len(dev) * WIDTH * 3
            predictions = model.head.predict(dev_x).tolist()
            result["curves"].append(
                dict(
                    pass_index=epoch,
                    predictions=predictions,
                    **_score(predictions, [d["targets"] for d in dev]),
                )
            )
        # Retain the numerical candidate before a separate real-process recovery check.
        result["candidate_sha256"] = model.checkpoint(folder / "CANDIDATE.json")
        result["candidate_head_sha256"] = model.head.digest
        result["parent_head_sha256"] = initial_head
        result["updates"] = model.updates
        result["attempted_cold_gru_mac"] = 9 * 3 * (129 * 4 + 4 * 4)
        result["attempted_cold_readout_mac"] = (
            WIDTH * 3 * (len(dev) + int(arm != "frozen") + int(arm == "replay_sgd"))
        )
        result["attempted_feedback_calls"] += (
            1  # Verification duplicate, not training novelty.
        )
        child = subprocess.run(
            [
                sys.executable,
                "-m",
                "hepta_cells.stem_credit_study",
                "--cold",
                str((folder / "COLD_REQUEST.json").resolve()),
                str((folder / "COLD_RESULT.json").resolve()),
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=60,
        )
        _write(folder / "CHILD_STDOUT.txt", child.stdout.encode())
        _write(folder / "CHILD_STDERR.txt", child.stderr.encode())
        child.check_returncode()
        cold = json.loads((folder / "COLD_RESULT.json").read_text())
        result["cold_exact"] = all(
            (
                cold["head_sha256"] == model.head.digest,
                cold["state_sha256"] == _semantic_state(model),
                cold["kernel_weights_sha256"] == kernel_info["weights_sha256"],
                cold["kernel_state_sha256"] == kernel_info["state_sha256"],
                cold["predictions"] == predictions,
            )
        )
        if not result["cold_exact"]:
            raise ValueError(
                "cold next feedback, ledger, GRU or prediction parity failed"
            )
        result.update(
            status="completed_candidate_only",
            local_restored_predictions=len(dev),
            pending_checkpoint_sha256=pin,
        )
    except Exception as error:
        result.update(
            status="failed", error_type=type(error).__name__, error=str(error)
        )
        result["failure_state_sha256"] = model.checkpoint(folder / "FAILED_STATE.json")
    result.update(
        wall_seconds=time.perf_counter() - wall,
        measured_cpu_seconds=_cpu() - cpu,
        cpu_scope=CPU_SCOPE,
        full_cost_known=False,
        fresh_confirmation=0,
        ordinary_daemon_adoptions=0,
    )
    _write(folder / "RECEIPT.json", result)
    return result, receipts


def run_credit_study(
    dataset_path,
    output_directory,
    *,
    seeds=(1101, 1102, 1103),
    taus_us=(10_000_000, 100_000_000),
    passes=3,
):
    """Run a prespecified bounded replay; failed attempts remain in the report."""
    if (
        not 1 <= len(seeds) <= 3
        or len(set(seeds)) != len(seeds)
        or any(type(s) is not int or not 0 <= s < 2**63 for s in seeds)
        or not 1 <= len(taus_us) <= 2
        or len(set(taus_us)) != len(taus_us)
        or any(type(t) is not int or not 0 < t < 2**53 for t in taus_us)
        or type(passes) is not int
        or not 1 <= passes <= 3
    ):
        raise ValueError("invalid bounded credit replay protocol")
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter(), _cpu()
    _write(
        output / "STARTED.json",
        dict(dataset=str(dataset_path), seeds=seeds, taus_us=taus_us, passes=passes),
    )
    try:
        raw = Path(dataset_path).read_bytes()
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError("retained dataset exceeds byte bound")
        dataset = json.loads(raw)
        docs = _documents(dataset)
        _write(output / "DATASET.json", raw)
        protocol = dict(
            schema="hepta.cell.stem-credit-protocol.v1",
            dataset_sha256=_sha(raw),
            python=sys.version,
            numpy=np.__version__,
            seeds=list(seeds),
            taus_us=list(taus_us),
            passes=passes,
            arms=list(ARMS),
            learning_rate=0.01,
            feature_dim=WIDTH,
            hidden_width=4,
            cell_ids=list(BANDS),
            order="source_group lexical order; repeat unchanged each pass",
            input="fixed GRU: raw initial64 + present mask64 + dt0; reset for each document",
            readout="unit-bounded L2 direct initial64 plus fixed GRU hidden4; linear scalar MSE",
            reference="zero prediction for every arm before labels; no learned reference",
            feedback="three retained correctness values together after max captured region interval",
            time="monotonic fabricated replay schedule; capture spacing is not authenticated label availability",
            learning="frozen-reference readout sensitivity trace; ordinary replay SGD uses own current logits",
            control="routed vs deranged: same vector, mask and delay; scalar is unequal-information ablation",
            recovery="pending checkpoint; fresh interpreter; same next update and dev predictions",
            exactness="all numerical/optimizer/RNG/clock/ledger fields; measured wall/CPU receipt fields excluded",
            kernel_admission="existing numerically checked GRU reference; frozen, not production-qualified",
            cost_scope="shared initial-feature cache separately; all arm attempts and cold checks retained",
            selection="none; dev already historically exposed; report every budget point",
            fresh_confirmation=0,
            ordinary_daemon_adoptions=0,
            core_body_eligibility=False,
        )
        _write(output / "PROTOCOL.json", protocol)
        scripts = Path(__file__).resolve().parents[1]
        pins = {
            name: _sha((scripts / name).read_bytes())
            for name in (
                "hepta_cells/stem_credit_study.py",
                "hepta_cells/stem_credit_support.py",
                "hepta_cells/readout_credit.py",
                "hepta_cells/semantic.py",
                "hepta_cells/temporal.py",
                "hepta_cells/cfc.py",
                "hepta_pred1/models.py",
            )
        }
        _write(output / "SOURCE_PINS.json", pins)
        attempts, setups, controls = [], [], []
        for seed in seeds:
            setup_wall, setup_cpu = time.perf_counter(), _cpu()
            config = TemporalConfig(129, 1, 3, hidden_dim=4, seed=seed, kind="gru")
            kernel = TemporalKernel("fixed-credit-gru", config)
            state = kernel.initial_state("saved-fresh-state")
            path = output / f"GRU-{seed}.npz"
            kernel_info = dict(
                path=str(path),
                pin=kernel.checkpoint(path, state),
                cell_id=kernel.cell_id,
                config=asdict(config),
                weights_sha256=kernel.weights_sha256,
                state_sha256=_sha(state),
            )
            features = {d["source_group"]: _features(kernel, d) for d in docs}
            setups.append(
                dict(
                    seed=seed,
                    kernel=kernel_info,
                    resources=kernel.resources(state),
                    feature_cache_sha256=_sha(
                        {k: v.tolist() for k, v in features.items()}
                    ),
                    gru_forward_mac=len(docs) * 3 * (129 * 4 + 4 * 4),
                    feature_cache_bytes=len(docs) * WIDTH * 8,
                    wall_seconds=time.perf_counter() - setup_wall,
                    cpu_seconds=_cpu() - setup_cpu,
                )
            )
            for tau in taus_us:
                feedback = {}
                for arm in ARMS:
                    result, feedback[arm] = _attempt(
                        output, docs, features, kernel_info, protocol, seed, tau, arm
                    )
                    attempts.append(result)
                a, b = feedback["routed"], feedback["shuffled"]
                equal = len(a) == len(b) == 24 * passes and all(
                    x["teaching_vector"] == y["teaching_vector"]
                    and x["teaching_sha256"] == y["teaching_sha256"]
                    and x["delay_us"] == y["delay_us"]
                    and sorted(x["applied_vector"]) == sorted(y["applied_vector"])
                    and all(i != j for i, j in enumerate(y["permutation"]))
                    for x, y in zip(a, b)
                )
                controls.append(
                    dict(seed=seed, tau_us=tau, same_vector_derangement_verified=equal)
                )
        train_y = [d["targets"] for d in docs if d["split"] == "train"]
        dev_y = [d["targets"] for d in docs if d["split"] == "dev"]
        mean = np.mean(train_y, axis=0).tolist()
        report = dict(
            schema="hepta.cell.stem-credit-study.v1",
            protocol=protocol,
            source_pins=pins,
            shared_setup=setups,
            attempts=attempts,
            controls=controls,
            constant_train_mean=dict(
                prediction=mean, **_score([mean] * len(dev_y), dev_y)
            ),
            train_documents=24,
            dev_documents=8,
            failed_attempts=sum(a["status"] == "failed" for a in attempts),
            historical_costs=dataset.get("historical_costs"),
            source_inventory_sha256=dataset.get("source_inventory_sha256"),
            wall_seconds=time.perf_counter() - wall,
            measured_cpu_seconds=_cpu() - cpu,
            cpu_scope=CPU_SCOPE,
            full_cost_known=False,
            energy_joules=None,
            peak_ram_bytes=None,
            cost_exclusions="original encoder/route/solver failures and storage service costs not reconstructed",
            dataset_fixture_only=bool(dataset.get("fixture_only", False)),
            selection=None,
            scientific_status="HOLD",
            fresh_confirmation=0,
            source_independence_verified=False,
            ordinary_daemon_adoptions=0,
            lifelong_adaptation_tested=False,
            recurrent_body_credit_tested=False,
        )
        _write(output / "REPORT.json", report)
        inventory = [
            {
                "path": str(p.relative_to(output)),
                "bytes": p.stat().st_size,
                "sha256": _sha(p.read_bytes()),
            }
            for p in sorted(output.rglob("*"))
            if p.is_file()
        ]
        _write(
            output / "MANIFEST.json",
            dict(scope="all retained files except this manifest", files=inventory),
        )
        return report
    except Exception as error:
        _write(
            output / "FAILED.json",
            dict(
                error_type=type(error).__name__,
                error=str(error),
                wall_seconds=time.perf_counter() - wall,
                measured_cpu_seconds=_cpu() - cpu,
                cpu_scope=CPU_SCOPE,
            ),
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cold", action="store_true")
    parser.add_argument("input")
    parser.add_argument("output")
    args = parser.parse_args()
    if args.cold:
        _write(args.output, _cold(json.loads(Path(args.input).read_text())))
    else:
        report = run_credit_study(args.input, args.output)
        print(
            json.dumps(
                dict(
                    output=args.output,
                    attempts=len(report["attempts"]),
                    failed_attempts=report["failed_attempts"],
                    status="HOLD",
                )
            )
        )
        if report["failed_attempts"] or not all(
            c["same_vector_derangement_verified"] for c in report["controls"]
        ):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
