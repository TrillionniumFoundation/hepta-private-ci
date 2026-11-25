"""Frozen-parent communication interventions; no optimization or topology claim.

Each clock calls the ORIGINAL SignedHCSN forward. Only its incoming old message
is deleted or relabeled; density, physical kernel, masks and weights are intact.
The three arms share examples and initial state and receive equal clock budgets.
"""

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import platform
import sys
import time

import numpy as np
import torch

from qualification.hcsn_smallnet_20261124.data import probability_metrics
from .data import generate_sources
from .models import make_model


ARMS = ("intact", "deleted", "shuffled")
WIDTHS, SEEDS = (8, 32, 64), (17011, 27011, 37011)
SOURCES = tuple(range(83000, 83008))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def create(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def tensors_identity(values):
    h = hashlib.sha256()
    for name, tensor in sorted(values.items()):
        a = tensor.detach().cpu().contiguous().numpy()
        h.update(str((name, a.dtype.str, a.shape)).encode())
        h.update(a.tobytes())
    return h.hexdigest()


def population_identity(state):
    return tensors_identity({k: getattr(state, k) for k in
                             ("density", "boundary", "drift", "cost", "message")})


def permutation(neurons, seed):
    """Fixed derangements within sender/receiver roles, shared across channels."""
    rng, half = np.random.default_rng(seed ^ 0x5A17), neurons // 2
    pieces = []
    for offset in (0, half):
        for _ in range(1000):
            p = rng.permutation(half)
            if np.all(p != np.arange(half)):
                pieces.append(p + offset)
                break
        else:
            raise RuntimeError("could not construct a frozen derangement")
    return torch.as_tensor(np.concatenate(pieces), dtype=torch.long)


def route_messages(message, arm, order):
    if arm == "intact":
        return message
    if arm == "deleted":
        return torch.zeros_like(message)
    if arm == "shuffled":
        return message.index_select(-1, order.to(message.device))
    raise ValueError("undeclared communication intervention")


@torch.no_grad()
def forward_interventions(model, batch, order, *, chunk=64, deadline=None):
    """Batch all three arms together; the ORIGINAL forward handles each tick."""
    if not 1 <= chunk <= 85 or model.config.message_mode != "flow":
        raise ValueError("bounded three-arm batch and original signed flow required")
    n = model.config.neurons
    if (tuple(order.shape) != (n,) or sorted(order.tolist()) != list(range(n))
            or not bool((order[:n//2] < n//2).all())
            or not bool((order[n//2:] >= n//2).all())):
        raise ValueError("message permutation must preserve sender/receiver roles")
    before = tensors_identity(model.state_dict())
    model.eval()
    outputs = {arm: [] for arm in ARMS}
    diagnostics, initial_hashes, terminal_hashes = [], [], []
    energy = {arm: [0.] * batch.x.shape[0] for arm in ARMS}
    for start in range(0, len(batch.y), chunk):
        part = batch.select(torch.arange(start, min(start + chunk, len(batch.y))))
        width = len(part.y)
        x = part.x.repeat(1, len(ARMS), 1)
        state = model.initial_state(width * len(ARMS),
                                    initial_margin=part.initial_margin.repeat(len(ARMS))[:, None])
        field_names = ("density", "boundary", "drift", "cost", "message")
        initial = [tensors_identity({k: getattr(state, k)[i*width:(i+1)*width]
                                    for k in field_names}) for i in range(len(ARMS))]
        if len(set(initial)) != 1:
            raise ValueError("initial physical states differ across arms")
        initial_hashes.append(initial)
        per_arm = {arm: [] for arm in ARMS}
        for tick in range(len(x)):
            if deadline is not None and time.perf_counter() > deadline:
                raise TimeoutError("frozen parent inference safety budget exhausted")
            forwarded = []
            for i, arm in enumerate(ARMS):
                value = route_messages(state.message[i*width:(i+1)*width], arm, order)
                forwarded.append(value)
                energy[arm][tick] += float(value[:, 2].square().sum())
            state = replace(state, message=torch.cat(forwarded, 0))
            logits, _, state = model(x[tick:tick+1], return_features=True, state=state)
            diagnostics.append(dict(model.last_diagnostics))
            for i, arm in enumerate(ARMS):
                per_arm[arm].append(logits[:, i*width:(i+1)*width].cpu())
        for arm in ARMS:
            outputs[arm].append(torch.cat(per_arm[arm], 0))
        terminal_hashes.append([tensors_identity({k: getattr(state, k)[i*width:(i+1)*width]
                                                  for k in field_names}) for i in range(len(ARMS))])
        if state.step != len(batch.x):
            raise ValueError("intervention changed the clock budget")
    after = tensors_identity(model.state_dict())
    if before != after:
        raise ValueError("frozen parent weights or buffers changed")
    return {arm: torch.cat(outputs[arm], 1) for arm in ARMS}, {
        "parent_before_sha256": before, "parent_after_sha256": after,
        "initial_state_sha256_by_chunk_arm": initial_hashes,
        "terminal_state_sha256_by_chunk_arm": terminal_hashes,
        "forwarded_signed_message_squared_norm_by_tick": energy,
        "max_mass_error": max(d["mass_error"] for d in diagnostics),
        "maximum_mark_excess": max(d["mark_excess"] for d in diagnostics),
        "minimum_probability": min(d["probability_min"] for d in diagnostics),
        "all_finite": all(d["all_finite"] for d in diagnostics),
        "original_forward_calls": len(diagnostics),
        "example_ticks_per_arm": len(batch.y) * len(batch.x),
        "initial_and_final_clock": [0, len(batch.x)], "updates": 0}


def source_manifest():
    result = {"experiment": digest(__file__)}
    for name, module in sorted(sys.modules.items()):
        if name.startswith("qualification.") and getattr(module, "__file__", None):
            if ".pft_" in name:
                continue
            result[name] = digest(module.__file__)
    return result


def original_source_key(name):
    prefix = "qualification.hcsn_closure_20261124"
    return prefix + ".__init__.py" if name == prefix else name + ".py" if name.startswith(prefix + ".") else name


def freeze(parents_root, output, expected_seal, *, per_source=64):
    """Seal operators, parent bytes and source IDs before generating any data."""
    parents_root, output = Path(parents_root), Path(output)
    if per_source not in (64, 128) or digest(parents_root / "SEAL.json") != expected_seal:
        raise ValueError("parent seal or requested sample budget differs")
    original = json.loads((parents_root / "PROTOCOL.json").read_text())
    seal = json.loads((parents_root / "SEAL.json").read_text())
    if identity(original) != seal["protocol_sha256"]:
        raise ValueError("original parent protocol changed")
    sources = source_manifest()
    for name, sha in sources.items():
        if name != "experiment" and original["source_hashes"].get(original_source_key(name)) != sha:
            raise ValueError("original executable differs: " + name)
    selected = []
    for n in WIDTHS:
        for seed in SEEDS:
            name = f"n{n}-qvi-value_risk-mixed-s{seed}"
            slot = next(s for s in original["slots"] if s["id"] == name)
            path = parents_root / name / "checkpoint.pt"
            expected = seal["attempts"][name]["checkpoint.pt"]
            if digest(path) != expected:
                raise ValueError("parent checkpoint differs: " + name)
            selected.append(dict(slot=slot, checkpoint=str(path), sha256=expected,
                                 permutation=permutation(n, seed).tolist()))
    used = {s for k, values in original["data"].items() if k.endswith("_sources") for s in values}
    if used.intersection(SOURCES):
        raise ValueError("intervention sources overlap original data")
    protocol = dict(schema="hcsn-pft-message-intervention-v1", parents=selected,
        original_seal_sha256=expected_seal, original_protocol_sha256=seal["protocol_sha256"],
        source_sha256=sources, source_ids=list(SOURCES), per_source=per_source,
        length=12, chunk=64, arms=list(ARMS), selected_state="selected_model",
        intervention="route old messages before original masked recurrent forwarding at every clock",
        deletion="all channels zero; only signed flow is enabled by original mask",
        shuffle="fixed seed derangement within sender and receiver halves; weights and mask unchanged",
        budgets={"updates_per_arm": 0, "ticks_per_example_arm": 12,
                 "examples_per_arm_parent": per_source * len(SOURCES), "safety_wall_seconds_per_parent": 600},
        runtime={"torch": torch.__version__, "numpy": np.__version__, "python": platform.python_version(),
                 "threads": torch.get_num_threads(), "device": "cpu"},
        primary="paired final accuracy and cross-entropy differences by parent and source; descriptive",
        scope="new independent synthetic source laws, same frozen trained parents; communication necessity only",
        interpretation="no learned topology superiority, complete Circuit comparator, real user or native E6 claim",
        selection="none; every frozen parent and intervention retained, failures retained, no retry on outcomes")
    output.mkdir(parents=True, exist_ok=False)
    create(output / "PROTOCOL_FROZEN.json", protocol)
    return protocol


def run_parent(item, batch, output, protocol):
    started, cpu = time.perf_counter(), time.process_time()
    if digest(item["checkpoint"]) != item["sha256"]:
        raise ValueError("parent bytes changed after freeze")
    saved = torch.load(item["checkpoint"], weights_only=True, map_location="cpu")
    if (saved["slot"] != item["slot"] or saved["smoke"] is not False
            or saved["protocol_sha256"] != protocol["original_protocol_sha256"]):
        raise ValueError("original checkpoint header differs")
    model = make_model(item["slot"])
    expected = model.state_dict()
    selected = saved[protocol["selected_state"]]
    for key in ("synaptic_mask", "reset_absolute", "fixed_boundary"):
        if not torch.equal(expected[key], selected[key]):
            raise ValueError("original signed mask or physical buffers differ")
    model.load_state_dict(selected, strict=True)
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    logits, audit = forward_interventions(model, batch, torch.tensor(item["permutation"]), chunk=protocol["chunk"],
        deadline=started + protocol["budgets"]["safety_wall_seconds_per_parent"])
    scores = {arm: probability_metrics(logits[arm], batch) for arm in ARMS}
    differences = {arm: {
        "accuracy_intact_minus_arm": scores["intact"]["accuracy"] - scores[arm]["accuracy"],
        "cross_entropy_arm_minus_intact": scores[arm]["cross_entropy"] - scores["intact"]["cross_entropy"],
        "source_accuracy_intact_minus_arm": {source: scores["intact"]["source_accuracy"][source] - value
            for source, value in scores[arm]["source_accuracy"].items()}}
        for arm in ARMS[1:]}
    path = output / (item["slot"]["id"] + ".npz")
    with path.open("xb") as stream:
        np.savez_compressed(stream, **{arm: value.numpy() for arm, value in logits.items()},
                            labels=batch.y.numpy(), source=batch.source.numpy())
    if digest(item["checkpoint"]) != item["sha256"]:
        raise ValueError("parent file changed during inference")
    return dict(status="completed", parent=item["slot"], checkpoint_sha256=item["sha256"],
        original_selected_step=saved["selected_step"], original_updates=saved["updates"],
        metrics=scores, paired_differences=differences, audit=audit, prediction_sha256=digest(path),
        wall_seconds=time.perf_counter()-started, cpu_seconds=time.process_time()-cpu)


def evaluate_frozen(output, expected_protocol):
    output = Path(output)
    protocol = json.loads((output / "PROTOCOL_FROZEN.json").read_text())
    if identity(protocol) != expected_protocol or protocol["source_sha256"] != source_manifest():
        raise ValueError("frozen protocol or executable changed")
    create(output / "EVALUATION_CLAIM.json", {"protocol_sha256": expected_protocol})
    wall, cpu = time.perf_counter(), time.process_time()
    batch = generate_sources(protocol["source_ids"], per_source=protocol["per_source"],
        length=protocol["length"], namespace="pft-intervention-20261125-v1")
    create(output / "DATA_BINDING.json", {"sha256": batch.digest(), "ids": list(batch.ids),
        "source_ids": protocol["source_ids"], "examples": len(batch.y)})
    rows = []
    for item in protocol["parents"]:
        try:
            result = run_parent(item, batch, output, protocol)
        except Exception as error:
            result = dict(status="failed", parent=item["slot"], error=repr(error))
        rows.append(result)
        create(output / (item["slot"]["id"] + ".json"), result)
        print(json.dumps({"parent": item["slot"]["id"], "status": result["status"],
                          "differences": result.get("paired_differences"), "error": result.get("error")}), flush=True)
    summary = dict(protocol_sha256=expected_protocol, data_sha256=batch.digest(), rows=rows,
        expected=9, completed=sum(row["status"] == "completed" for row in rows),
        wall_seconds=time.perf_counter()-wall, cpu_seconds=time.process_time()-cpu,
        cost_scope="body includes data generation, all arms, audits and raw prediction writes; outer launcher adds imports and shutdown",
        inference="descriptive paired effects within frozen HCSN; seeds and source laws are synthetic, not users")
    create(output / "RESULTS.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parents-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--original-seal", required=True)
    parser.add_argument("--per-source", type=int, choices=(64, 128), default=64)
    args = parser.parse_args()
    torch.set_num_threads(1)
    protocol = freeze(args.parents_root, args.output, args.original_seal, per_source=args.per_source)
    result = evaluate_frozen(args.output, identity(protocol))
    raise SystemExit(0 if result["completed"] == result["expected"] else 1)


if __name__ == "__main__":
    main()
