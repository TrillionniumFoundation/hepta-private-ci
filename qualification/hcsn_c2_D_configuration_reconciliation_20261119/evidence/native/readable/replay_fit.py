"""One fresh full-D evaluation; no optimizer is constructed or restored."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import resource
import sys
import time
import traceback

from audit_io import (bind_candidate, checkpoint_metadata, construction, read_dev,
                      require, save, sha, verify_files, verify_program)


def tensor_digest(state, prefix=''):
    import hashlib
    digest = hashlib.sha256()
    for name, tensor in sorted(state.items()):
        if name.startswith(prefix):
            digest.update(name[len(prefix):].encode())
            digest.update(str((tuple(tensor.shape), tensor.dtype)).encode())
            digest.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def fresh_forward(model, rows, batch_size, batches, budget, batch_record):
    import torch
    model.eval()
    values, labels, order = [], [], []
    before = tensor_digest(model.state_dict())
    require(all(p.grad is None for p in model.parameters()), 'unexpected existing parameter gradient')
    with torch.no_grad():
        for number, (ids, x, dt, y) in enumerate(batches(rows, list(range(len(rows))), batch_size)):
            budget()
            started = time.monotonic()
            value = model(x, dt)
            selected = y >= 0
            require(value.shape == (*y.shape, 11) and value.dtype == torch.float64, 'forward shape/dtype differs')
            require(not value.requires_grad and value.grad_fn is None and bool(torch.isfinite(value).all()),
                    'nonfinite or differentiable replay output')
            values.append(value[selected].detach().clone())
            labels.append(y[selected].detach().clone())
            order.extend(ids)
            batch_record(dict(batch=number, episode_ids=ids, events=int(selected.sum()),
                              forward_wall_seconds=time.monotonic() - started))
            budget()
    require(before == tensor_digest(model.state_dict()), 'fresh forward mutated trained tensors')
    require(all(p.grad is None for p in model.parameters()), 'replay produced a parameter gradient')
    require(order == [row['id'] for row in rows], 'fresh episode order differs')
    return torch.cat(values), torch.cat(labels), before


def run(name, output):
    started = float(os.environ.get('HCSN_REPLAY_FIT_STARTED', time.monotonic()))
    out, program = Path(output), Path(__file__).resolve().parent
    out.mkdir(parents=True, exist_ok=False)
    inputs = {}
    result = dict(schema='independent-HCSN-best-full-D-replay-v1', name=name,
                  started_utc=datetime.now(timezone.utc).isoformat(), execution_status='started',
                  quality_reproducibility='HOLD', scientific_admission='HOLD',
                  original_training_adequacy=False, confirmation_E_access=False,
                  optimizer_operations=0, training_updates=0, backward_calls=0)
    plan = json.loads((program / 'PLAN.json').read_bytes())
    def budget():
        require(time.monotonic() - started <= plan['resources']['per_fit_wall_seconds'], 'per-fit wall budget exceeded')
        require(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024 <= plan['resources']['per_fit_RSS_bytes'],
                'self observed peak RSS exceeds budget')
    try:
        result['program_manifest_sha256_before'] = verify_program(program)
        inputs, root, report, fit_plan, best, outer = bind_candidate(program, plan, name)
        rows = read_dev(plan, inputs)
        result.update(original_status=report['status'], original_outer=outer, best_epoch=best['epoch'],
                      expected_development=best['development'], report_sha256=sha(root / 'result.json'),
                      best_checkpoint_sha256=sha(root / 'best.pt'), original_complete_epochs=len(report['epochs']))
        save(out / 'input-identities-before.json', inputs)
        budget()
        import torch
        import numpy as np
        from independent_metrics import metrics, compare_metrics
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        torch.use_deterministic_algorithms(True)
        require(torch.__version__ == report['torch_version'] == plan['runtime']['torch_version'], 'runtime Torch differs')
        require(torch.version.git_version == report['torch_git_version'] == plan['runtime']['torch_git_version'], 'Torch build differs')
        source = Path(plan['source']).resolve()
        sys.path.insert(0, str(source / 'proposals/localization-v3'))
        import cores
        from hcsn_study_support import batches, sources
        require(Path(cores.__file__).resolve() == source / 'proposals/localization-v3/cores.py', 'wrong core module origin')
        checkpoint = torch.load(root / 'best.pt', weights_only=True, mmap=True, map_location='cpu')
        checkpoint_metadata(checkpoint, report, fit_plan, best)
        model = cores.CoreStudyModel(**checkpoint['model_configuration'])
        model.load_state_dict(checkpoint['model'], strict=True)
        initial = torch.load(root / 'initial.pt', weights_only=True, mmap=True, map_location='cpu')
        require(initial['model_configuration'] == construction(fit_plan), 'initial construction differs')
        require(sources(model) == report['source_before'], 'actual module dependency map differs from original')
        loaded = {}
        for module_name, module in list(sys.modules.items()):
            if module_name.startswith('qualification.hcsn_differentiable') or module_name in ('cores', 'frozen_tables', 'hcsn_study_support'):
                path = Path(module.__file__).resolve()
                require(path.is_relative_to(source) and str(path) in report['source_before']
                        and sha(path) == report['source_before'][str(path)], 'loaded module origin/hash differs')
                loaded[module_name] = dict(path=str(path), sha256=sha(path))
        state = model.state_dict()
        for key, value in state.items():
            if key.startswith(('frontend.', 'head.')) or '.physics.' in key:
                require(torch.equal(value, initial['model'][key]), 'frozen shared/physical tensor differs')
        for prefix, key in [('frontend.', 'initial_frontend_sha256'), ('head.', 'initial_head_sha256')]:
            require(tensor_digest(state, prefix) == report[key], 'shared tensor digest differs')
        require(model.core.recorder is None and all(not p.requires_grad for layer in model.core.network.layers
                                                   for p in layer.physics.parameters()), 'unexpected capture/learnable physics')
        result.update(model_configuration=checkpoint['model_configuration'],
                      best_checkpoint_main_updates=checkpoint['main_updates'],
                      actual_loaded_sources=loaded, runtime=dict(python=sys.version, executable=sys.executable,
                      torch_version=torch.__version__, torch_git_version=torch.version.git_version,
                      numpy_version=np.__version__), frozen_shared_and_physics_equal_initial=True)
        # These payload fields are never inspected, restored or passed to any optimizer.
        del checkpoint, initial, state
        with (out / 'batches.jsonl').open('x') as journal:
            def record(row):
                row.update(process_wall_seconds=time.monotonic() - started, process_cpu_seconds=time.process_time())
                journal.write(json.dumps(row, allow_nan=False) + '\n')
                journal.flush()
            logits, labels, before = fresh_forward(model, rows, plan['evaluation']['batch_size'], batches, budget, record)
        expected_labels = torch.tensor([y for row in rows for y in row['y']], dtype=torch.long)
        require(torch.equal(labels, expected_labels) and len(labels) == plan['expected_dev_events'], 'full-D labels/order mismatch')
        payload = dict(logits=logits, labels=labels, episode_ids=[row['id'] for row in rows],
                       event_episode_index=torch.tensor([i for i, row in enumerate(rows) for _ in row['y']]),
                       event_position=torch.tensor([j for row in rows for j in range(len(row['y']))]),
                       source_rows=torch.tensor([i for row in rows for i in row['source_rows']]),
                       best_epoch=best['epoch'], best_checkpoint_sha256=result['best_checkpoint_sha256'])
        torch.save(payload, out / 'fresh-development-logits.pt')
        result.update(fresh_logits=dict(path='fresh-development-logits.pt', bytes=(out / 'fresh-development-logits.pt').stat().st_size,
                                      sha256=sha(out / 'fresh-development-logits.pt')),
                      fresh_development=metrics(logits.numpy(), labels.numpy()),
                      tensor_digest_before=before, tensor_digest_after=tensor_digest(model.state_dict()),
                      frozen_table_cache=[layer.operator.cache_receipt() for layer in model.core.network.layers])
        result['metric_absolute_differences'] = compare_metrics(result['fresh_development'], best['development'],
                                                              plan['metrics']['absolute_tolerance'])
        require(sources(model) == report['source_before'], 'model dependencies changed during replay')
        budget()
        result.update(execution_status='completed_full_D_replay', quality_reproducibility='passed')
    except Exception:
        result.update(execution_status='failed_or_budget_censored_replay', quality_reproducibility='HOLD',
                      error=traceback.format_exc())
    finally:
        try:
            verify_files(inputs)
            result['inputs_unchanged'] = True
            result['program_manifest_sha256_after'] = verify_program(program)
            budget()
        except Exception:
            result.update(execution_status='failed_or_budget_censored_replay', quality_reproducibility='HOLD',
                          final_identity_or_budget_error=traceback.format_exc(), inputs_unchanged=False)
        save(out / 'input-identities-after.json', {path: sha(path) if Path(path).is_file() else None for path in inputs})
        result.update(process_wall_seconds=time.monotonic() - started, process_cpu_seconds=time.process_time(),
                      self_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                      finished_utc=datetime.now(timezone.utc).isoformat(), energy_joules=None,
                      scope='Quality reproducibility only; original censored/insufficient training and numerical/scientific HOLD unchanged.')
        save(out / 'RESULT.json', result)
    return 0 if result['quality_reproducibility'] == 'passed' else 2


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.name, args.output))
