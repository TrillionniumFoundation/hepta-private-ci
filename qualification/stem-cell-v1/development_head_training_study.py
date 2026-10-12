"""Fixed synthetic scalar/grouped training comparisons; not Encoder qualification.

Same initial Heads, per-Cell RNG, examples, SGD steps, losses and clipping.
All fits are executed independently; no cached trained result crosses arms.
Frozen inputs simulate an Encoder output. No pretrained or future-data claim.
"""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import resource
import sys

import torch
from torch import nn

from development_ablation import PhaseClock, fit_candidate
from development_head_training import fit_linear_cells
from development_tensors import parameter_digest


PROFILES = (("tiny", 1, 16, 2, 20), ("bank64", 64, 384, 4, 30),
            ("bank256", 256, 384, 4, 10), ("bank4096", 4096, 384, 2, 5))


def run(output, *, seed=1111):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).parent
    names = ('development_head_training.py', 'development_head_training_study.py',
             'development_ablation.py', 'development_tensors.py')
    sources = {n: hashlib.sha256((source/n).read_bytes()).hexdigest() for n in names}
    with (output/'plan.json').open('x') as stream:
        json.dump({"seed": seed, "profiles": PROFILES, "source_sha256": sources,
            "max_parameter_error": 5e-6, "max_logit_error": 2e-5,
            "train_rows": 64, "heldout_rows": 64, "cell_group_limit": 32,
            "synthetic_features": True, "pretrained_encoder_executed": False}, stream, sort_keys=True)
    threads = torch.get_num_threads()
    torch.set_num_threads(1)
    total = PhaseClock()
    results = []
    try:
        with torch.random.fork_rng(devices=[]):
            # Pay one separate warmup for both operators, not hidden within one arm.
            torch.manual_seed(seed)
            warm_head = nn.Linear(4, 2)
            warm_x, warm_y = torch.ones(4,4), torch.zeros(4, dtype=torch.long)
            warm = PhaseClock()
            fit_candidate(warm_head, warm_x, warm_y, steps=1, seed=seed)
            fit_linear_cells((warm_head,), warm_x, (torch.arange(4),), (warm_y,), seeds=(seed,), steps=1)
            warm_cost = warm.finish()
            for profile_index, (name, cells, width, classes, steps) in enumerate(PROFILES):
                prepare = PhaseClock()
                rng = torch.Generator().manual_seed(seed+profile_index)
                features = torch.randn(64, width, generator=rng)
                heldout = torch.randn(64, width, generator=rng)
                teachers = torch.randn(4, width, classes, generator=rng)
                labels_by_task = tuple((features @ teacher).argmax(-1) for teacher in teachers)
                heldout_by_task = tuple((heldout @ teacher).argmax(-1) for teacher in teachers)
                initials = []
                for i in range(cells):
                    torch.manual_seed(seed+i)
                    initials.append(nn.Linear(width, classes))
                initials = tuple(initials)
                row_indices = tuple(torch.arange(64) for _ in initials)
                labels = tuple(labels_by_task[i % 4] for i in range(cells))
                seeds = tuple(seed+i for i in range(cells))
                before = tuple(parameter_digest(h) for h in initials)
                preparation = prepare.finish()
                runs, models = {}, {}
                order = ('scalar', 'grouped') if (seed+profile_index) % 2 else ('grouped', 'scalar')
                for arm in order:
                    clock = PhaseClock()
                    if arm == 'scalar':
                        reports, fitted = [], []
                        for i, initial in enumerate(initials):
                            model, receipt = fit_candidate(initial, features[row_indices[i]], labels[i],
                                                           steps=steps, seed=seeds[i])
                            fitted.append(model)
                            reports.append(receipt)
                        trained = tuple(fitted)
                        counts = sum(r['examples_processed'] for r in reports)
                        optimizer_steps, details = cells*steps, None
                    else:
                        trained, details = fit_linear_cells(initials, features, row_indices, labels,
                                                            seeds=seeds, steps=steps, group_size=32)
                        counts = sum(r['examples_processed'] for r in details['cells'])
                        optimizer_steps = sum(g['optimizer_steps'] for g in details['groups'])
                    # Equal initial/final content checking is part of each timed path.
                    if before != tuple(parameter_digest(h) for h in initials):
                        raise RuntimeError('source mutation')
                    output_digests = tuple(parameter_digest(h) for h in trained)
                    runs[arm] = {**clock.finish(), "example_updates": counts,
                                 "optimizer_steps": optimizer_steps,
                                 "candidate_digests": output_digests, "details": details}
                    models[arm] = trained
                verify = PhaseClock()
                max_parameter_error, max_logit_error, reversals = 0., 0., 0
                frozen_correct = scalar_correct = grouped_correct = 0
                predictions = []
                with torch.no_grad():
                    for i, (a, b) in enumerate(zip(models['scalar'], models['grouped'])):
                        max_parameter_error = max(max_parameter_error, *(float((p-q).abs().max())
                                                  for p,q in zip(a.parameters(), b.parameters())))
                        old, left, right = initials[i](heldout), a(heldout), b(heldout)
                        max_logit_error = max(max_logit_error, float((left-right).abs().max()))
                        reversals += int((left.argmax(-1) != right.argmax(-1)).sum())
                        predictions.append({"cell": i, "frozen": old.argmax(-1).tolist(),
                                            "scalar": left.argmax(-1).tolist(), "grouped": right.argmax(-1).tolist()})
                with (output/f'{name}-predictions.json').open('x') as stream:
                    json.dump(predictions, stream, separators=(',', ':'), allow_nan=False)
                # Freeze all predictions before the separate scoring pass.
                for prediction in predictions:
                    truth = heldout_by_task[prediction['cell'] % 4]
                    frozen_correct += int((torch.tensor(prediction['frozen']) == truth).sum())
                    scalar_correct += int((torch.tensor(prediction['scalar']) == truth).sum())
                    grouped_correct += int((torch.tensor(prediction['grouped']) == truth).sum())
                result = {"profile": name, "cells": cells, "width": width, "classes": classes,
                          "steps_per_cell": steps, "preparation": preparation,
                          "runs": runs, "execution_order": order,
                          "max_parameter_error": max_parameter_error, "max_logit_error": max_logit_error,
                          "class_reversals": reversals,
                          "correct": {"frozen": frozen_correct, "scalar": scalar_correct, "grouped": grouped_correct},
                          "prediction_count": cells*64, "heldout_source_groups": 64,
                          "input_tensor_sha256": hashlib.sha256(features.numpy().tobytes()).hexdigest(),
                          "verification": verify.finish(),
                          "wall_ratio_scalar_over_grouped": runs['scalar']['wall_ns']/runs['grouped']['wall_ns'],
                          "parameter_bytes_per_candidate_bank": sum(p.numel()*p.element_size() for h in initials for p in h.parameters()),
                          "numerical_profile_passed": max_parameter_error <= 5e-6 and max_logit_error <= 2e-5 and reversals == 0}
                if runs['scalar']['example_updates'] != runs['grouped']['example_updates']:
                    raise RuntimeError('training-work mismatch')
                results.append(result)
                with (output/f'{name}.json').open('x') as stream:
                    json.dump(result, stream, sort_keys=True, allow_nan=False)
                print(name, cells, result['wall_ratio_scalar_over_grouped'], result['class_reversals'], flush=True)
            if sources != {n: hashlib.sha256((source/n).read_bytes()).hexdigest() for n in names}:
                raise RuntimeError('source changed')
            report = {"source_sha256": sources, "seed": seed, "profiles": results,
                      "warmup": warm_cost, "total": total.finish(),
                      "environment": {"torch": torch.__version__, "python": sys.version,
                                      "platform": platform.platform(), "torch_threads": 1},
                      "process_high_watermark_rss_raw": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                      "rss_scope": "whole process including BOTH arms; platform native units, not per-arm memory",
                      "pretrained_encoder_executed": False, "synthetic_features_and_labels": True,
                      "independent_efficacy_established": False, "production_authorized": False}
            with (output/'report.json').open('x') as stream:
                json.dump(report, stream, sort_keys=True, allow_nan=False)
            return report
    except Exception as error:
        with (output/'FAILED.json').open('x') as stream:
            json.dump({'error_type': type(error).__name__, 'message': str(error), 'source_sha256': sources}, stream)
        raise
    finally:
        torch.set_num_threads(threads)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthetic', action='store_true', required=True)
    parser.add_argument('--seed', type=int, choices=(1111,2222,3333), default=1111)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.output, seed=args.seed)
