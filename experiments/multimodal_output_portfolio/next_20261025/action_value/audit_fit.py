"""Recompute saved OOF choices and backup labels from actual historical paths."""

import argparse
import json
from pathlib import Path

import torch
from torch.nn import functional as F

from ...abc_recovery.base_recovery import file_sha, write_json


@torch.inference_mode()
def run(asset, development, output):
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    result = json.loads((development / "result.json").read_text())
    checked = []
    for row in result["records"]:
        seed = row["seed"]
        table = torch.load(asset / f"abc4-control-runs/development-001/seed-{seed}/fit/data.pt", map_location="cpu", weights_only=True)
        public, utility = table["features"], table["metrics"]["primary"]["utility"]
        cases = torch.tensor(table["cases"])
        for candidate in row["candidates"]:
            pins = candidate["fit"]["audit_files_sha256"]
            if any(file_sha(Path(p)) != digest for p, digest in pins.items()): raise ValueError("Saved fold evidence changed")
            folder = development / f"seed-{seed}-width-{candidate['width']}-audit"
            backups = torch.load(folder / "backups.pt", map_location="cpu", weights_only=True)
            if not torch.equal(backups["cases"], cases): raise ValueError("Source grouping changed")
            choices = backups["fold_selected_actions"]
            differences, norm_error, hindsight_differences = [], 0., 0
            for fold in (0, 1):
                saved = torch.load(folder / f"fold-{fold}.pt", map_location="cpu", weights_only=True)
                keep, held = cases % 2 != fold, cases % 2 == fold
                if (set(saved["fit_cases"].tolist()) & set(saved["held_cases"].tolist())
                        or not torch.equal(saved["fit_cases"], torch.unique(cases[keep]))
                        or not torch.equal(saved["held_cases"], torch.unique(cases[held]))):
                    raise ValueError("A source entered both fold fitting and evaluation")
                train = public[keep].clone(); train[:, 0, -1] = .5; train = train.flatten(0, 1)
                scale = train.std(0, unbiased=False); scale = torch.where(scale > 1e-6, scale, torch.ones_like(scale))
                weights = saved["state"]
                norm_error = max(norm_error, float((train.mean(0) - weights["mean"]).abs().max()), float((scale - weights["scale"]).abs().max()))
                held_public = public[held, 1:].flatten(0, 1)
                x = (held_public - weights["mean"]) / weights["scale"]
                y = F.linear(torch.tanh(F.linear(x, weights["net.0.weight"], weights["net.0.bias"])), weights["net.2.weight"], weights["net.2.bias"])
                value = torch.cat((torch.zeros(len(x), 1), y), 1); value[:, 1] = float("inf")
                recomputed = value.argmin(-1).reshape(-1, 4)
                if not torch.equal(recomputed, choices[held]): raise ValueError("Saved backup action differs from public-only fold network")
            for first in range(1, 5):
                second = choices[:, first - 1]
                if (second == 1).any(): raise ValueError("Strictly dominated H1 semantic action selected")
                path = torch.where(second == 0, first, 5 + (first - 1) * 4 + second - 1)
                terminal = utility[torch.arange(len(public)), path].double()
                costs = .002 * (1 + (second != 0).double())
                direct = torch.exp(-2 * (terminal - costs)) - torch.exp(-2 * utility[:, 0].double())
                differences.append(float((direct - backups["root_targets"][:, first - 1].double()).abs().max()))
                possible = torch.cat((utility[:, first:first + 1], utility[:, 5 + (first - 1) * 4:9 + (first - 1) * 4]), 1).double()
                cost_vector = torch.tensor([0., .002, .002, .002, .002])
                hindsight = torch.exp(-2 * (possible - cost_vector)); hindsight[:, 1] = float("inf")
                hindsight_differences += int((second != hindsight.argmin(-1)).sum())
            if norm_error > 1e-6 or max(differences) > 2e-6: raise ValueError("Normalization or direct terminal-cost backup differs")
            checked.append({"seed": seed, "width": candidate["width"], "backup_labels": len(public) * 4,
                "fit_only_normalizer_max_absolute_error": norm_error, "direct_total_cost_backup_max_absolute_error": max(differences),
                "fold_choices_different_from_private_realized_best": hindsight_differences,
                "all_source_groups_disjoint": True, "all_fold_choices_recomputed_without_targets": True})
    if output.exists(): raise FileExistsError("Do not overwrite an independent audit")
    report = {"status": "passed", "checks": checked, "fresh_sources_opened": False,
              "development_result_sha256": file_sha(development / "result.json"), "auditor_sha256": file_sha(__file__),
              "scope": "Saved fold model/normalizer/action identity and direct terminal-cost labels. This verifies one approximate policy backup, not final-policy optimality."}
    write_json(output, report); print(json.dumps(report))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--asset-root", type=Path, required=True); p.add_argument("--development", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(); run(a.asset_root, a.development, a.output)
