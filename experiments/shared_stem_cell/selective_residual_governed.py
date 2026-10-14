"""Research-only selective residual learning on exposed frozen pretrained material.

A fixed 40-step AdamW correction is fitted only for a Cell whose frozen
shared Head underperforms its original bank on calibration. Holdout scoring
happens after an immutable selection receipt; the historical labels are
already public and this does NOT create an independent/future evaluation,
optimizer resume, model selection, authority or production acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time
from zipfile import ZipFile

import torch
from torch import nn
from torch.nn import functional as F
from safetensors.torch import load

ORIGINAL_ZIP = "05b6ec4b33a7563ea368f7d5be212ad1dbf1220bbccb9195ac900ac5adde34a6"
ROOT = "hepta-public-study/"
FROZEN = ROOT + "execution/frozen-features/"
BANK = ROOT + "execution/heads/gated/"
SHARED = "hepta-consolidation/heads/supervised/"
SEED = 20261014
STEPS = 40
LR = 0.01
BATCH = 16


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def owned_json(z, name, maximum=2_000_000):
    raw = z.read(name)
    require(len(raw) <= maximum, "oversized research input")
    return json.loads(raw)


class Head(nn.Module):
    def __init__(self, width, kind, rank=8):
        super().__init__()
        self.kind = kind
        self.base = nn.Linear(width, 4)
        if kind == "gated":
            self.down = nn.Linear(width, rank)
            self.up = nn.Linear(rank, 4, bias=False)
            self.gate = nn.Linear(width, 4)

    def forward(self, x):
        y = self.base(x)
        if self.kind == "gated":
            return y + self.up(torch.tanh(self.down(x))) * torch.sigmoid(self.gate(x))
        return y


def material(z, prefix, width, kind):
    m = owned_json(z, prefix + "manifest.json")
    raw = z.read(prefix + "weights.safetensors")
    require(len(raw) == m["weights_bytes"] and digest(raw) == m["weights_sha256"],
            "Head material byte identity mismatch")
    require(m["architecture"]["kind"] == kind and m["architecture"]["width"] == width
            and m["architecture"]["classes"] == 4 and m["production_accepted"] is False,
            "Head material profile mismatch")
    with torch.random.fork_rng(devices=[]):
        head = Head(width, kind)
    head.load_state_dict(load(raw), strict=True)
    head.eval().requires_grad_(False)
    require(sum(p.numel() for p in head.parameters()) == m["parameters"]["parameters"],
            "physical Head parameter identity mismatch")
    return head, m


def selection_from_calibration(bank_correct, shared_correct, corrected_correct):
    require(all(type(v) is int and 0 <= v <= 16
                for v in (bank_correct, shared_correct, corrected_correct)),
            "bounded calibration counts required")
    if shared_correct >= bank_correct:
        return "shared"
    if corrected_correct >= bank_correct:
        return "corrected"
    return "bank"


def study(archive, output):
    archive = Path(archive)
    require(digest(archive.read_bytes()) == ORIGINAL_ZIP, "original ZIP digest required")
    torch.set_num_threads(1)
    with ZipFile(archive) as z:
        require(z.testzip() is None, "corrupt historical ZIP")
        m = owned_json(z, FROZEN + "manifest.json")
        source = z.read(FROZEN + "features.safetensors")
        require(len(source) == m["file_bytes"] and digest(source) == m["file_sha256"]
                and m["simulated_encoder"] is False and m["contains_labels"] is False,
                "frozen physical pretrained Stem material required")
        x = load(source)["features"].detach().clone().contiguous()
        require(x.shape == (128, 384) and x.dtype == torch.float32
                and bool(torch.isfinite(x).all()), "frozen feature shape/dtype mismatch")
        source_rows = z.read(ROOT + "dataset.jsonl")
        require(len(source_rows) <= 16 * 1024 * 1024, "bounded original dataset required")
        rows = [json.loads(line) for line in source_rows.splitlines()]
        require(len(rows) == len(m["rows"]) == 128, "incomplete original source rows")
        for row, item in zip(rows, m["rows"], strict=True):
            require(all(row[k] == item[k] for k in ("case_id", "split", "cell",
                                                   "scope", "group"))
                    and type(row["label"]) is int and 0 <= row["label"] < 4,
                    "original source label/Scope/Cell identity mismatch")
        require({(r["split"], r["cell"]) for r in rows}
                == {(split, cell) for split in ("train", "calibration", "holdout")
                    for cell in (0, 1)}, "complete three-stage two-Cell workload required")
        require(all(sum(r["split"] == stage and r["cell"] == cell for r in rows) == n
                    for stage, n in (("train", 32), ("calibration", 16), ("holdout", 16))
                    for cell in (0, 1)), "bounded per-Cell cohort size changed")
        models, bindings = {}, {}
        for name, path, width, kind in (
            ("bank0", BANK + "cell-0/learned/", 384, "gated"),
            ("bank1", BANK + "cell-1/learned/", 384, "gated"),
            ("shared", SHARED, 386, "gated"),
        ):
            models[name], bindings[name] = material(z, path, width, kind)
        require(len({(v["binding"]["stem_sha256"], v["binding"]["dataset_sha256"],
                      v["binding"]["scope"]) for v in bindings.values()}) == 1,
                "cross-source or cross-Scope Head material")

    def positions(stage, cell):
        return torch.tensor([i for i, row in enumerate(rows)
                             if row["split"] == stage and row["cell"] == cell],
                            dtype=torch.long)

    routes = torch.tensor([r["cell"] for r in rows], dtype=torch.long)

    def frozen_logit(arm, ids):
        if arm == "bank":
            return models[f"bank{int(routes[ids[0]])}"](x[ids])
        return models["shared"](torch.cat([x[ids],
            F.one_hot(routes[ids], num_classes=2).float()], dim=-1))

    def correct_count(probs, labels):
        return int((probs.argmax(-1) == labels).sum())

    def labels(stage, cell):
        # Deliberately no holdout answer accessor before selection is sealed.
        require(stage in ("train", "calibration"), "evaluation requires sealed selection")
        return torch.tensor([rows[int(i)]["label"] for i in positions(stage, cell)],
                            dtype=torch.long)

    calibration = {}
    for cell in (0, 1):
        ids = positions("calibration", cell)
        y = labels("calibration", cell)
        with torch.no_grad():
            calibration[cell] = {
                "bank": correct_count(frozen_logit("bank", ids), y),
                "shared": correct_count(frozen_logit("shared", ids), y),
            }
    attempted = [cell for cell in (0, 1)
                 if calibration[cell]["shared"] < calibration[cell]["bank"]]
    trained, work = {}, {}
    originals = {name: {k: v.detach().clone() for k, v in model.state_dict().items()}
                 for name, model in models.items()}
    for cell in attempted:
        ids = positions("train", cell)
        targets = labels("train", cell)
        with torch.no_grad():
            base = frozen_logit("shared", ids).detach()
        start = time.perf_counter_ns()
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(SEED + cell)
            residual = nn.Linear(384, 4)
            with torch.no_grad():
                residual.weight.zero_()
                residual.bias.zero_()
            optimizer = torch.optim.AdamW(residual.parameters(), lr=LR, weight_decay=0)
            sample_stream = torch.Generator().manual_seed(7300 + cell)
            for _ in range(STEPS):
                chosen = torch.randint(len(ids), (BATCH,), generator=sample_stream)
                loss = F.cross_entropy(base[chosen] + residual(x[ids][chosen]),
                                       targets[chosen])
                optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(residual.parameters(), 1.0)
                optimizer.step()
        elapsed = time.perf_counter_ns() - start
        residual.eval().requires_grad_(False)
        trained[cell] = residual
        work[cell] = {"steps": STEPS, "lr": LR, "batch": BATCH,
                      "parameter_count": 1540, "training_wall_ns": elapsed,
                      "scored_training_examples": BATCH * STEPS,
                      "training_and_optimizer_work_included": True}
    for name, model in models.items():
        require(all(torch.equal(value, model.state_dict()[key])
                    for key, value in originals[name].items()),
                "training mutated a frozen inherited Head")
    chosen = {}
    for cell in (0, 1):
        ids = positions("calibration", cell)
        with torch.no_grad():
            base = frozen_logit("shared", ids)
            corrected = (base + trained[cell](x[ids])) if cell in trained else base
            n = correct_count(corrected, labels("calibration", cell))
        chosen[cell] = selection_from_calibration(
            calibration[cell]["bank"], calibration[cell]["shared"], n)
        calibration[cell]["trained_corrected"] = n if cell in trained else None
        calibration[cell]["chosen"] = chosen[cell]
    resident = 6224 if any(v != "bank" for v in chosen.values()) else 0
    resident += sum(6192 if route == "bank" else 1540 if route == "corrected" else 0
                    for route in chosen.values())
    eligible = resident < 12384
    gate = {
        "schema": "hepta.selective-residual-trainonce.v1",
        "selected_per_cell": {str(k): v for k, v in chosen.items()},
        "calibration": {str(k): v for k, v in calibration.items()},
        "attempted_training_cells": attempted,
        "trained_residual_work": {str(k): v for k, v in work.items()},
        "candidate_parameters": resident, "bank_parameters": 12384,
        "strict_parameter_saving": eligible,
        "approved_for_next_snapshot": False,
        "original_material_already_exposed": True,
        "independent_evaluation": False, "production_accepted": False,
    }
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)

    def write_once(filename, payload):
        with (output / filename).open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")

    write_once("selection.json", gate)
    # Predict and seal before any evaluation-label lookup in this function.
    predictions = {}
    for cell in (0, 1):
        ids = positions("holdout", cell)
        with torch.no_grad():
            shared = frozen_logit("shared", ids)
            corrected = shared + trained[cell](x[ids]) if cell in trained else shared
            bank = frozen_logit("bank", ids)
            chosen_logits = (bank if chosen[cell] == "bank"
                             else corrected if chosen[cell] == "corrected" else shared)
            predictions[str(cell)] = {
                "indices": [int(i) for i in ids],
                "bank": [int(q) for q in bank.argmax(-1)],
                "shared": [int(q) for q in shared.argmax(-1)],
                "corrected": [int(q) for q in corrected.argmax(-1)],
                "selected": [int(q) for q in chosen_logits.argmax(-1)],
            }
    write_once("holdout-predictions.json", predictions)
    # Software-level post-seal separation, NOT independently blinded labels.
    truth = {cell: [rows[i]["label"] for i in predictions[cell]["indices"]]
             for cell in predictions}
    observed = {cell: {
        arm: sum(value == label for value, label in
                 zip(predictions[cell][arm], truth[cell], strict=True))
        for arm in ("bank", "shared", "corrected", "selected")}
        for cell in predictions}
    totals = {arm: sum(values[arm] for values in observed.values())
              for arm in ("bank", "shared", "corrected", "selected")}
    write_once("result.json", {
        "schema": "hepta.selective-residual-trainonce-result.v1",
        "source_zip_sha256": ORIGINAL_ZIP,
        "program_uses_original_128_records": True,
        "selection_sha256": digest((output / "selection.json").read_bytes()),
        "predictions_sha256": digest((output / "holdout-predictions.json").read_bytes()),
        "heldout_score_per_cell": observed, "total_heldout_correct": totals,
        "holdout_cases": 32, "candidate_deployment_eligible": False,
        "actual_training_cells": attempted,
        "energy_joules": None, "whole_stem_flops_measured": False,
        "new_encoder_forwards": 0, "new_independent_evaluation": False,
        "production_accepted": False,
    })
    return gate, totals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    _, scores = study(args.archive, args.output)
    print(json.dumps({"original_holdout_scores": scores,
                      "production_accepted": False}, sort_keys=True))


if __name__ == "__main__":
    main()
