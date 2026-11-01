"""Fixed-budget training of the exact conditional finite-cell supervised loss.

Uniform cell-independent behavior records supply the state distribution. This
objective is neither a policy gradient nor a DQN convergence claim. Validation
is diagnostic only; the final optimizer update is always exported.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np
import torch
import torch.nn.functional as F

from .model import CELL_SEED_BASE, FAMILIES, HEAD_SEED_BASE, Policy, identity

BATCH_SEED_BASE = 733000
HERE = Path(__file__).resolve().parent


def _clock():
    return time.perf_counter(), time.process_time()


def _elapsed(start):
    return dict(wall_seconds=time.perf_counter()-start[0], cpu_seconds=time.process_time()-start[1])


def _write(path, value):
    """Full-precision compact JSON; no silent overwrite of a frozen attempt."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)+"\n").encode()
    with path.open("xb") as stream:
        stream.write(payload)
    return dict(path=str(path), sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload))


def source_identity():
    return {name: hashlib.sha256((HERE/name).read_bytes()).hexdigest()
            for name in ("model.py", "train.py", "bank.py", "task.py", "data.py", "protocol.json")}


def expected_loss(policy, rows, protocol, details=False):
    """Mean over records of sum_s p(s|complete prefix) * nonlinear loss(s).

    All transitions, representations, and complete-prefix masses are cached only
    inside this forward call. Shared autograd paths are retained until backward.
    Neither loss(mean representation) nor a sampled latent-state substitute is
    used. Teacher posterior and Q enter targets only, never policy features.
    """
    if not rows:
        raise ValueError("expected loss requires nonempty decision rows")
    cache = {}
    inputs = torch.stack([policy.latent_inputs(r["public"], r["state"], cache) for r in rows])
    mass = torch.stack([policy.prefix_mass(r["prefix"], cache) for r in rows])
    target = inputs.new_tensor([r["q"] for r in rows])
    legal = torch.tensor([r["legal"] for r in rows], dtype=torch.bool, device=inputs.device)
    belief = inputs.new_tensor([r["posterior"] for r in rows])
    if (target.shape != (len(rows), 6) or legal.shape != target.shape
            or not bool(torch.isfinite(target).all()) or not bool(torch.isfinite(belief).all())
            or bool(torch.any(legal.sum(-1) == 0)) or bool(torch.any((belief < 0) | (belief > 1)))
            or not bool(torch.isfinite(mass).all()) or bool(torch.any(mass.detach() < -2e-10))
            or float((mass.detach().sum(-1)-1).abs().max()) > 2e-9):
        raise ValueError("invalid teacher, legality, or conditional cell mass")
    output = policy(inputs)
    q_loss = ((output[..., :6]-target[:, None]).square()*legal[:, None]).sum(-1)/legal.sum(-1)[:, None]
    belief_loss = F.binary_cross_entropy_with_logits(output[..., 6], belief[:, None].expand_as(output[..., 6]), reduction="none")
    expected_q, expected_belief = (mass*q_loss).sum(-1).mean(), (mass*belief_loss).sum(-1).mean()
    regularizer = output.new_zeros(())
    if policy.cell is not None:
        regularizer = protocol["raw_regularizer"]*policy.cell.raw[:policy.cell.effective_parameter_count].square().sum()
    loss = expected_q + protocol["belief_loss_weight"]*expected_belief + regularizer
    if not bool(torch.isfinite(loss)):
        raise FloatingPointError("nonfinite exact expected loss")
    if not details:
        return loss
    with torch.no_grad():
        actions = output[..., :6].masked_fill(~legal[:, None], -torch.inf).argmax(-1)
        chosen = target.gather(1, actions)
        best = target.masked_fill(~legal, -torch.inf).max(-1).values
        brier = (torch.sigmoid(output[..., 6])-belief[:, None]).square()
        metrics = dict(loss=float(loss), teacher_expected_q_mse=float(expected_q),
                       teacher_expected_belief_bce=float(expected_belief), raw_regularizer=float(regularizer),
                       teacher_expected_belief_brier=float((mass*brier).sum(-1).mean()),
                       teacher_behavior_state_regret=float((mass*(best[:, None]-chosen)).sum(-1).mean()),
                       max_mass_defect=float((mass.sum(-1)-1).abs().max()), records=len(rows),
                       latent_states=int(mass.shape[1]), cached_transitions=len(cache.get("transition", {})),
                       cached_feature_contexts=len(cache.get("features", {})), cached_prefixes=len(cache.get("mass", {})))
    return loss, metrics


def diagnostic(policy, rows, protocol):
    start = _clock()
    with torch.no_grad():
        _, result = expected_loss(policy, rows, protocol, details=True)
    return dict(**result, timing=_elapsed(start), selection=False,
                scope="Fitted-law teacher targets on behavior states; not actual-outcome or on-policy efficacy calibration")


def train_family(family, fit, train_rows, validation_rows, protocol):
    """No checkpoint selection; common mini-batch RNG is reset for each family."""
    preparation = _clock()
    policy = Policy(family, fit, protocol["hidden_width"])
    if protocol["optimizer"] != "AdamW" or protocol["dtype"] != "float64":
        raise ValueError("unsupported frozen optimizer/dtype")
    optimizer = torch.optim.AdamW(policy.parameters(), lr=protocol["learning_rate"], weight_decay=protocol["weight_decay"])
    initial_head = policy.head_identity()
    initial_vector = torch.cat([p.detach().flatten().clone() for p in policy.parameters()])
    initial_raw = [] if policy.cell is None else policy.cell.raw.detach().tolist()
    initial_physical = None if policy.cell is None else {k: float(v.detach()) for k, v in policy.cell.physical().items()}
    preparation_timing = _elapsed(preparation)
    initial_validation = diagnostic(policy, validation_rows, protocol)
    rng = np.random.default_rng(BATCH_SEED_BASE+fit)
    batch_hash, updates = hashlib.sha256(), []
    started = _clock()
    for update in range(1, int(protocol["updates"])+1):
        indices = rng.integers(0, len(train_rows), int(protocol["batch_states"]))
        batch_hash.update(indices.astype("<i8").tobytes())
        rows = [train_rows[int(i)] for i in indices]
        optimizer.zero_grad(set_to_none=True)
        loss, metrics = expected_loss(policy, rows, protocol, details=True)
        loss.backward()
        if any(p.grad is not None and not bool(torch.isfinite(p.grad).all()) for p in policy.parameters()):
            raise FloatingPointError("nonfinite model gradient")
        raw_gradient, task_gradient = [], []
        if policy.cell is not None:
            raw_gradient = policy.cell.raw.grad.detach().tolist()
            regularizer_gradient = torch.zeros_like(policy.cell.raw)
            count = policy.cell.effective_parameter_count
            regularizer_gradient[:count] = 2*protocol["raw_regularizer"]*policy.cell.raw[:count].detach()
            task_gradient = (policy.cell.raw.grad.detach()-regularizer_gradient).tolist()
        norm = float(torch.nn.utils.clip_grad_norm_(policy.parameters(), protocol["gradient_clip"]))
        optimizer.step()
        updates.append(dict(update=update, **metrics, gradient_norm_before_clip=norm,
                            raw_gradient_before_clip=raw_gradient, raw_task_gradient_before_clip=task_gradient))
        if update == 1 or update % 40 == 0 or update == protocol["updates"]:
            print(json.dumps(dict(stage="training", fit=fit, family=family, update=update, loss=metrics["loss"])), flush=True)
    training_timing = _elapsed(started)
    final_validation = diagnostic(policy, validation_rows, protocol)
    final_vector = torch.cat([p.detach().flatten() for p in policy.parameters()])
    final_raw = [] if policy.cell is None else policy.cell.raw.detach().tolist()
    if policy.cell is not None and policy.cell.mode == "ordinary" and final_raw[4:] != [0., 0., 0.]:
        raise AssertionError("inactive ordinary parameters changed")
    receipt = dict(schema="digital-read-before-training-family-v1", family=family, fit=fit,
                   head_seed=HEAD_SEED_BASE+fit, cell_seed=None if policy.cell is None else CELL_SEED_BASE+fit,
                   batch_seed=BATCH_SEED_BASE+fit, initial_head_sha256=initial_head,
                   final_head_sha256=policy.head_identity(), minibatch_sha256=batch_hash.hexdigest(),
                   train_records=len(train_rows), validation_records=len(validation_rows),
                   parameter_count_allocated=policy.allocated_parameter_count,
                   parameter_count_effective=policy.effective_parameter_count,
                   initial_raw=initial_raw, final_raw=final_raw,
                   raw_parameter_shift=(np.asarray(final_raw)-np.asarray(initial_raw)).tolist(),
                   initial_physical=initial_physical,
                   final_physical=None if policy.cell is None else {k: float(v.detach()) for k, v in policy.cell.physical().items()},
                   all_parameter_shift_l2=float(torch.linalg.vector_norm(final_vector-initial_vector)),
                   initial_validation=initial_validation, final_validation=final_validation,
                   selected_update=int(protocol["updates"]), validation_used_for_selection=False,
                   convergence_claim=False, stopping_reason="Registered fixed update budget exhausted; final update always selected",
                   objective="Exact conditional finite-cell expected nonlinear supervised loss over cell-independent behavior states",
                   policy_gradient_or_dqn_claim=False, updates=updates,
                   preparation=preparation_timing, training=training_timing)
    return policy, receipt


def train_fit(datafile, protocol, outdir):
    """Train all registered families for one fit, preserving every final model."""
    outer = _clock()
    if isinstance(protocol, (str, Path)):
        protocol = json.loads(Path(protocol).read_text())
    if protocol["families"] != list(FAMILIES):
        raise ValueError("registered family set/order changed")
    torch.set_num_threads(int(protocol["cpu_threads"]))
    payload = Path(datafile).read_bytes()
    data = json.loads(payload)
    fit, train_rows, validation_rows = int(data["fit"]), data["train"]["rows"], data["validation"]["rows"]
    if not train_rows or not validation_rows or not data["train"]["behavior_cell_independent"]:
        raise ValueError("nonempty cell-independent behavior data required")
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=False)
    sources = source_identity()
    started = dict(schema="digital-read-before-training-start-v1", fit=fit,
                   started_at=datetime.now(timezone.utc).isoformat(), source_sha256=sources,
                   data_sha256=hashlib.sha256(payload).hexdigest(), protocol_sha256=identity(protocol),
                   protocol=protocol, confirmation_generated=False,
                   versions=dict(python=platform.python_version(), torch=torch.__version__, numpy=np.__version__, cpu_threads=torch.get_num_threads()))
    _write(outdir/"STARTED.json", started)
    common_preparation = _elapsed(outer)
    results, head_hashes, batch_hashes = {}, set(), set()
    for family in FAMILIES:
        policy, receipt = train_family(family, fit, train_rows, validation_rows, protocol)
        head_hashes.add(receipt["initial_head_sha256"])
        batch_hashes.add(receipt["minibatch_sha256"])
        export_start = _clock()
        artifact = policy.export()
        receipt["export_preparation"] = _elapsed(export_start)
        serialization = _clock()
        model_info = _write(outdir/f"{family}.json", artifact)
        receipt["model_serialization"] = _elapsed(serialization)
        receipt["model"] = model_info
        receipt["model_identity"] = identity(artifact)
        receipt["source_sha256"] = sources
        receipt_info = _write(outdir/f"{family}_training.json", receipt)
        results[family] = dict(model=model_info, model_identity=receipt["model_identity"], training_receipt=receipt_info,
                               preparation=receipt["preparation"], training=receipt["training"],
                               initial_validation=receipt["initial_validation"], final_validation=receipt["final_validation"],
                               export_preparation=receipt["export_preparation"], model_serialization=receipt["model_serialization"],
                               allocated_parameters=receipt["parameter_count_allocated"], effective_parameters=receipt["parameter_count_effective"],
                               raw_parameter_shift=receipt["raw_parameter_shift"], all_parameter_shift_l2=receipt["all_parameter_shift_l2"])
    if len(head_hashes) != 1 or len(batch_hashes) != 1:
        raise AssertionError("head initialization or minibatches differed between families")
    if source_identity() != sources:
        raise RuntimeError("source changed during fit; preserve attempt and do not admit it")
    result = dict(schema="digital-read-before-training-fit-v1", fit=fit, models=results,
                  common_initial_head_sha256=next(iter(head_hashes)), common_minibatch_sha256=next(iter(batch_hashes)),
                  source_sha256=sources, data_sha256=started["data_sha256"], protocol_sha256=started["protocol_sha256"],
                  versions=started["versions"], common_preparation=common_preparation, total=_elapsed(outer),
                  timing_scope="Total includes data parsing, optimizer setup, training, diagnostics, export and serialization. Nested timers are attributions, not additional costs.",
                  confirmation_generated=False, selection="Final registered update for every family")
    _write(outdir/"COMPLETE.json", result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=HERE/"protocol.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = train_fit(args.data, args.protocol, args.out)
    print(json.dumps(dict(stage="fit_complete", fit=result["fit"], total=result["total"])), flush=True)


if __name__ == "__main__":
    main()
