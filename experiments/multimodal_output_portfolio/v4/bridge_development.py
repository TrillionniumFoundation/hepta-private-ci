"""Single development fixture: four real one-refine streams, no quality claim.

Candidate utilities come from actual three-branch neural outputs. INIT binds a
one-step plan so every modality is exercised without fake priority utilities.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / "v3")]
from allocation_bridge import NativeBridge
from allocation_control import noise_support
from allocation_model import AllocationModel, ACTIONS, BUDGET, EMIT_COST, INIT_COST, REFINE_COST, tensor_hash
from metrics import score_outputs
from model import MODALITIES
from risk import entropic_ce
from world import _render_modality, canonical


def decision(action, value):
    scores, eligible = np.zeros(5), np.zeros(5, dtype=bool)
    scores[action], eligible[action] = value, True
    return {"action": action, "scores": scores, "eligible": eligible}


def reconcile(native, state):
    expected = state.receipt
    assert (native["version"], native["remaining"], native["refinement_counts"], native["total_refinements"]) == (
        expected["version"], expected["remaining_macs"], expected["refinement_counts"], sum(expected["refinement_counts"]))


def run(binary, checkpoint, checkpoint_sha256, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    started, cpu = time.perf_counter(), time.process_time()
    model = AllocationModel(checkpoint, checkpoint_sha256)
    _, banks, modes = noise_support(5)
    targets, arrays, rows, native = canonical(), {}, [], None
    result = {"schema": "hepta-v4-four-action-development-v1", "status": "running", "development_seed": 5,
              "checkpoint_sha256": model.checkpoint_sha256, "scope": "actual synthetic neural/native interface only; no formal R05 or natural-model quality claim"}
    try:
        with gzip.open(directory / "native.tsv.gz", "wt", encoding="ascii", newline="\n") as stream:
            with NativeBridge(binary, stream) as native:
                for m, name in enumerate(MODALITIES):
                    sid = "development-one-refine-" + name
                    raw = _render_modality(np.array([m]), "text", np.random.default_rng(6000 + m), True)
                    before = model.work_receipt()["linear_macs"]
                    state = model.initialize(raw, modes[[m]])
                    feedback = model.feedback(state)
                    assert feedback["condition"] == m
                    arrays[sid + "_raw_text"] = raw
                    arrays[sid + "_initial_latents"] = feedback["latents"].numpy().copy()
                    assert model.work_receipt()["linear_macs"] - before == INIT_COST
                    offline_before = model.work_receipt()["linear_macs"]
                    with torch.inference_mode():
                        anchor = model.anchor_tensor(feedback["q"])
                        children = model.refine_tensor(feedback["q"].repeat(3, 1), feedback["latents"].repeat(3, 1, 1),
                                                       m, banks[0, m], anchor.repeat(3, 1))
                        previews = model.decode_tensor(children)
                    arrays[sid + "_candidate_latents"] = children.numpy().copy()
                    preview_arrays = {key: value.numpy() for key, value in previews.items()}
                    for key, value in preview_arrays.items():
                        arrays[sid + "_candidates_" + key] = value
                    stop = -score_outputs(preview_arrays, np.full(3, m), targets)["loss"] - .015 * EMIT_COST / REFINE_COST
                    plan_value = float(entropic_ce(stop, np.array([.25, .5, .25]), 2.)) - .015
                    offline = model.work_receipt()["linear_macs"] - offline_before
                    assert offline == 512 + 3 * (REFINE_COST + EMIT_COST)
                    began = native.begin(sid, feedback, "COMMITTED", (m,))
                    reconcile(began, state)
                    if m == 0:
                        requests = native.requests
                        try:
                            native.choose(sid, dict(feedback, q_hash="f" * 64), decision(m + 1, plan_value))
                        except ValueError:
                            pass
                        else:
                            raise AssertionError("altered semantic digest was accepted")
                        assert native.requests == requests
                    chosen = native.choose(sid, feedback, decision(m + 1, plan_value))
                    assert chosen["action"] == m + 1
                    rng = np.random.default_rng(np.random.SeedSequence([5200000, 5, m, 1, m]))
                    branch = int(rng.choice(3, p=[.25, .5, .25]))
                    state = model.refine_step(state, m, banks[0, m, branch][None])
                    updated = model.feedback(state)
                    assert all(torch.equal(feedback["latents"][:, j], updated["latents"][:, j]) for j in range(4) if j != m)
                    assert not torch.equal(feedback["latents"][:, m], updated["latents"][:, m])
                    ack = native.refined(sid, updated)
                    reconcile(ack, state)
                    arrays[sid + "_refined_latents"] = updated["latents"].numpy().copy()
                    emit_choice = native.choose(sid, updated, decision(0, float(stop[branch])))
                    assert emit_choice["action"] == 0
                    emitted = model.emit(state)
                    hashes = {key: tensor_hash(emitted[key]) for key in MODALITIES}
                    sealed = native.emitted(sid, updated, hashes)
                    reconcile(sealed, state)
                    for key, value in emitted.items():
                        arrays[sid + "_output_" + key] = value.numpy().copy()
                        assert torch.isfinite(value).all() and value.shape == (1, model.source.dimensions[key])
                        np.testing.assert_allclose(value.numpy()[0], preview_arrays[key][branch], atol=2e-5, rtol=0)
                    online = model.work_receipt()["linear_macs"] - before - offline
                    assert online == INIT_COST + REFINE_COST + EMIT_COST == BUDGET - REFINE_COST
                    assert state.receipt["sealed"] and sealed["phase"] == "sealed"
                    rows.append({"modality": name, "branch": branch, "plan_value": plan_value,
                                 "native_begin": began, "native_choice": chosen, "native_refined": ack,
                                 "native_emit_choice": emit_choice, "native_emitted": sealed,
                                 "online_linear_macs": online, "offline_linear_macs": offline, "model_receipt": state.receipt})
        assert model.work_receipt()["linear_macs"] == sum(r["online_linear_macs"] + r["offline_linear_macs"] for r in rows)
        result["status"] = "passed"
    except Exception:
        result.update(status="failed", traceback=traceback.format_exc())
        raise
    finally:
        arrays["future_banks"], arrays["initial_modes"] = banks, modes
        np.savez_compressed(directory / "actual-arrays.npz", **arrays)
        result.update(streams=rows, actual_model_work=model.work_receipt(), native=native.receipt if native else None,
                      wall_seconds=time.perf_counter() - started, python_cpu_seconds=time.process_time() - cpu,
                      source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in (Path(__file__), HERE / "allocation_bridge.py", HERE / "allocation_model.py")},
                      artifact_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                       for p in directory.iterdir() if p.is_file()})
        (directory / "receipt.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for option in ("binary", "checkpoint", "checkpoint-sha256", "output"):
        parser.add_argument("--" + option, required=True)
    args = parser.parse_args()
    receipt = run(args.binary, args.checkpoint, args.checkpoint_sha256, args.output)
    print(json.dumps({"status": receipt["status"], "streams": len(receipt["streams"]), "native": receipt["native"]}))
