"""Run a reproducible SYNTHETIC six-stage mechanism study, never model acceptance.

Real CPU tensor training and real LLVM execution, synthetic task/feature data.
Use development_trial.train_shared_head_trial for actual approved Stem weights;
this study never upgrades generated features to observed pretrained execution.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import sys

import torch
from torch import nn

from development_ablation import (
    ChanceEdge, ComputeOption, FoldIdentity, InformationState, PhaseClock,
    RecurrentClassifier, finite_compute_allocation, fit_candidate,
    paired_predictions, run_depth_candidates, incremental_depth_candidates, structural_arms, validate_folds,
)
from development_generation import CodecSpec, SharedByteGenerator, fit_generator, render_generated
from development_native import DecisionIR, Rule, benchmark_fixed_policy
from development_tensors import BasisCellHeads, parameter_digest


def summarize_logits(predictions, gold):
    # Deliberately separate from candidate training/prediction calls.
    return {"accuracy": float((predictions.argmax(-1) == gold).float().mean()),
            "cross_entropy": float(torch.nn.functional.cross_entropy(predictions, gold))}


def summarize_pair(report, gold):
    return {"frozen": summarize_logits(report['frozen_logits'], gold),
            "trained": summarize_logits(report['trained_logits'], gold),
            **{key: value for key, value in report.items() if not key.endswith('_logits')}}


def modality_corpus(width, *, seed):
    rng = torch.Generator().manual_seed(seed)
    conditions, modalities, payloads, specs = [], [], [], []
    for modality in range(4):
        for signal in range(4):
            condition = torch.randn(width, generator=rng) * .02
            condition[signal] += 2
            condition[4+modality] += 2
            conditions.append(condition)
            modalities.append(modality)
            if modality == 0:
                payloads.append(bytes((65+signal, 65+signal)))
                specs.append(CodecSpec('text', 2))
            elif modality == 1:
                payloads.append(bytes((32+64*signal,)) * 4)
                specs.append(CodecSpec('image', 4, 2, 2))
            elif modality == 2:
                payloads.append(bytes((16+32*signal,)) * 4 + bytes((32+32*signal,)) * 4)
                specs.append(CodecSpec('video', 8, 2, 2, 2, 8))
            else:
                payloads.append(bytes((32+32*signal, 128+32*signal)) * 4)
                specs.append(CodecSpec('audio', 8, rate=8000))
    return torch.stack(conditions), torch.tensor(modalities), tuple(payloads), tuple(specs)


def run_study(*, output: Path):
    if output.exists():
        raise FileExistsError('study output must be a new path')
    output.mkdir(parents=True, exist_ok=False)
    # Record source bytes before any training; this is integrity, not attestation.
    roots = [Path(__file__).parent / name for name in (
        'development_experiment.py', 'development_ablation.py', 'development_generation.py',
        'development_native.py', 'development_tensors.py', 'development_composition.py')]
    sources = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in roots}
    before_threads = torch.get_num_threads()
    torch.set_num_threads(1)
    clock = PhaseClock()
    try:
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(721)
            train = torch.randn(64, 4)
            heldout = torch.randn(32, 4)
            labels = (train[:, 0] - train[:, 1] > 0).long()
            gold = (heldout[:, 0] - heldout[:, 1] > 0).long()
            validate_folds(FoldIdentity('synthetic', tuple(f't{i}' for i in range(64)), (1,)*64),
                           FoldIdentity('synthetic', tuple(f'h{i}' for i in range(32)), (2,)*32), 64, 32)
            initial = nn.Linear(4, 2)
            _, head_report = paired_predictions(initial, train, labels, heldout, steps=120)
            stage1 = summarize_pair(head_report, gold)

            x = torch.cat((train, torch.arange(64).remainder(2)[:, None]), 1)
            xt = torch.cat((heldout, torch.arange(32).remainder(2)[:, None]), 1)
            y = labels ^ x[:, -1].long()
            yg = gold ^ xt[:, -1].long()
            structural = structural_arms(BasisCellHeads(4, 2, 16, ('parent',)), x, y, xt, steps=120,
                train_fold=FoldIdentity('synthetic', tuple(f't{i}' for i in range(64)), (1,)*64),
                holdout_fold=FoldIdentity('synthetic', tuple(f'h{i}' for i in range(32)), (2,)*32))
            stage2 = {name: summarize_pair(receipt, yg) for name, receipt in structural.items()}

            sequence = torch.randn(32, 3, 8)
            test_sequence = torch.randn(16, 5, 8)
            sequence_y = (sequence[:, :, 0].sum(1) > 0).long()
            sequence_gold = (test_sequence[:, :, 0].sum(1) > 0).long()
            reasoner, reasoner_fit = fit_candidate(RecurrentClassifier(8, 2, depth=4), sequence,
                                                  sequence_y, steps=100)
            depth_reports = run_depth_candidates(reasoner, test_sequence)
            stage3 = {str(d): {**summarize_logits(r['logits'], sequence_gold),
                               **{k: v for k, v in r.items() if k != 'logits'}}
                      for d, r in depth_reports.items()}
            # Independent exact cheap control has the same observed features.
            exact = (test_sequence[:, :, 0].sum(1) > 0).long()
            stage3['cheap_exact_accuracy'] = float((exact == sequence_gold).float().mean())
            shared_depths = incremental_depth_candidates(reasoner, test_sequence)
            if any(not torch.equal(depth_reports[d]['logits'], v) for d, v in shared_depths['depths'].items()):
                raise RuntimeError('shared-prefix/fixed-depth numerical mismatch')
            stage3['shared_prefix'] = {k: v for k, v in shared_depths.items() if k != 'depths'}
            stage3['shared_prefix']['all_logits_equal_to_fixed'] = True
            stage3['independent_fixed_transitions'] = sum(v['cell_transitions'] for v in depth_reports.values())
            stage3['training'] = reasoner_fit
            stage3['heldout_sequence_lengths'] = [5]
            stage3['semantic_reasoning_claim'] = False

            graph = (
                InformationState('root', .5, (ComputeOption('observe-a', .1, (ChanceEdge(.5, 'a0'), ChanceEdge(.5, 'a1'))),)),
                InformationState('a0', .5, (ComputeOption('observe-b', .1, (ChanceEdge(.5, 'l0'), ChanceEdge(.5, 'l1'))),)),
                InformationState('a1', .5, (ComputeOption('observe-b', .1, (ChanceEdge(.5, 'l0'), ChanceEdge(.5, 'l1'))),)),
                InformationState('l0', 1., ()), InformationState('l1', 1., ()),
            )
            stage4 = {'two_step': finite_compute_allocation(graph, 'root', budget=.2),
                      'one_step_budget': finite_compute_allocation(graph, 'root', budget=.1),
                      'exact_analytic_value': max(.5, 1 - .2), 'learned_ndu_controller': False}

            c, m, targets, specs = modality_corpus(24, seed=21)
            ct, mt, test_targets, test_specs = modality_corpus(24, seed=52)
            generator = SharedByteGenerator(24, maximum_bytes=8)
            frozen_outputs = generator.generate(ct, mt, maximum_bytes=8)
            candidate, gen_fit = fit_generator(generator, c, m, targets, steps=200)
            trained_outputs = candidate.generate(ct, mt, maximum_bytes=8)
            # Fixed condition interventions; neither receives target bytes.
            condition_controls = {
                'zero_condition': candidate.generate(torch.zeros_like(ct), mt, maximum_bytes=8),
                'permuted_within_modality': candidate.generate(
                    ct.reshape(4, 4, -1).roll(1, dims=1).reshape_as(ct), mt, maximum_bytes=8),
            }
            rendered = render_generated(trained_outputs, test_specs)
            # Freeze inference bytes before comparing any test target payload.
            records = []
            for index, (spec, result) in enumerate(zip(test_specs, rendered)):
                entry = {'index': index, 'codec': asdict(spec), 'status': result['status']}
                if result['content'] is not None:
                    extension = {'text':'txt', 'image':'pgm', 'video':'y4m', 'audio':'wav'}[spec.modality]
                    name = f'generated-{index:02d}.{extension}'
                    with (output / name).open('xb') as stream:
                        stream.write(result['content'])
                    entry.update({'file': name, 'sha256': result['sha256']})
                records.append(entry)
            generated_identity = hashlib.sha256(json.dumps(trained_outputs['tokens']).encode()).hexdigest()
            stage5 = {'training': gen_fit, 'generated_token_digest_before_scoring': generated_identity,
                      'frozen_exact_payloads': sum(tuple(t) == o and end for t,o,end in zip(test_targets, frozen_outputs['tokens'], frozen_outputs['terminated'])),
                      'trained_exact_payloads': sum(tuple(t) == o and end for t,o,end in zip(test_targets, trained_outputs['tokens'], trained_outputs['terminated'])),
                      'cases': len(test_targets), 'outputs': records,
                      'conditioning_controls': {
                          name: {'exact_payloads': sum(tuple(t) == o and end for t, o, end in
                                    zip(test_targets, arm['tokens'], arm['terminated'])),
                                 'generated_tokens_sha256': hashlib.sha256(json.dumps(arm['tokens']).encode()).hexdigest(),
                                 'inference': {k: v for k, v in arm.items() if k != 'tokens'}}
                          for name, arm in condition_controls.items()},
                      'inference': {k:v for k,v in trained_outputs.items() if k != 'tokens'},
                      'general_multimodal_capability_established': False}

            program = DecisionIR(4, (Rule((1., -1., 0., 0.), 0., 1),), 0)
            observations = tuple(tuple(float(v) for v in row) for row in heldout)
            stage6 = {'tiny_policy': benchmark_fixed_policy(program, observations, repeats=50)}
            wider = DecisionIR(16, tuple(Rule(tuple(float((i+j)%3-1) for j in range(16)),
                                                  float(i-8), i) for i in range(16)), 17)
            wider_observations = tuple(tuple(float(v) for v in row) for row in torch.randn(16, 16))
            stage6['wider_policy'] = benchmark_fixed_policy(wider, wider_observations, repeats=50)
            report = {'schema': 'hepta.stem.six-stage.synthetic-execution.v1',
                      'synthetic_features_and_tasks': True, 'pretrained_encoder_executed': False,
                      'source_sha256': sources, 'python': sys.version, 'torch': torch.__version__,
                      'platform': platform.platform(), 'torch_threads': 1,
                      'stage1': stage1, 'stage2': stage2, 'stage3': stage3,
                      'stage4': stage4, 'stage5': stage5, 'stage6': stage6,
                      'total': clock.finish(), 'production_authorized': False}
            if sources != {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in roots}:
                raise RuntimeError('source changed during study')
            with (output / 'report.json').open('x') as stream:
                json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
                stream.write('\n')
            return report
    except Exception as error:
        # Preserve partial outputs as FAILED evidence, never overwrite/relabel.
        with (output / 'FAILED.json').open('x') as stream:
            json.dump({'error_type': type(error).__name__, 'message': str(error),
                       'production_authorized': False, 'source_sha256': sources}, stream)
        raise
    finally:
        torch.set_num_threads(before_threads)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthetic', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = run_study(output=args.output)
    print(json.dumps({'report': str(args.output / 'report.json'),
                      'pretrained_encoder_executed': False, 'production_authorized': False}))
