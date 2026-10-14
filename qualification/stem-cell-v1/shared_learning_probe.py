"""Public-data learning diagnostic on one frozen Encoder and existing CellBank.

Three topology controls share exact input features and final parameter counts.
Equal update schedules are NOT equal measured computation. No nine-arm relabel,
split/NDU activation, native serving, independent efficacy or promotion claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path

from execution_meter import WorkLedger, EXTENDED_POLICY_SCHEMA
from matrix_bank import CellBank, state_digest, train_bank
from matrix_materials import file_sha256, strict_json
from matrix_runtime import write_json_exclusive
from next_round_matrix import _digest
from paired_execution import PHASES
from public_news_materials import acquire_news, prepare_news, input_identity, validate_disjoint
from transformer_work_v3 import PROFILE

TOPOLOGIES = (('dense16', 16, 16), ('sparse16', 16, 2), ('direct32', 32, 2))


def freeze_study(*, seed=7347, train_steps=32, batch_size=16, width_units=32):
    for name, value, limit in (('seed', seed, 2**31-1), ('steps', train_steps, 128),
                               ('batch', batch_size, 64), ('width', width_units, 128)):
        if type(value) is not int or not 1 <= value <= limit:
            raise ValueError('invalid bounded study ' + name)
    if width_units < 2:
        raise ValueError('direct32 needs a nonempty hidden layer')
    body = dict(schema='hepta.public-shared-learning-config.v1', seed=seed,
        train_steps=train_steps, batch_size=batch_size, width_units=width_units,
        measurement_policy=dict(schema=EXTENDED_POLICY_SCHEMA, arithmetic_profile=PROFILE,
            mode='strict', wall_time_ns=900_000_000_000, max_process_rss_bytes=None,
            rapl_zone=None, rapl_max_power_watts=None),
        phase_caps=dict.fromkeys(PHASES, 5_000_000_000_000), classes=4, context_tokens=512,
        max_feature_bytes=4*1024*1024, schedule='fixed_updates_no_quality_selection')
    return {**body, 'study_id': _digest(body)}


def _tensor_digest(tensor):
    return hashlib.sha256(tensor.detach().contiguous().numpy().tobytes()).hexdigest()


def fit_controls(encode, train, targets, evaluation, root, *, dimension, study):
    """No evaluation labels in this API. Calls actual Encoder and CellBank paths.

    Feature encoding is measured once and reused. Each arm's standalone cost
    must include its share of that common work; the physical campaign paid once.
    Arm failures remain explicit; no successful-only selection or retries.
    """
    import torch
    from safetensors.torch import save_file
    expected = freeze_study(**{k: study[k] for k in ('seed', 'train_steps', 'batch_size', 'width_units')})
    if _digest(study) != _digest(expected):
        raise ValueError('study policy changed')
    validate_disjoint(train, evaluation)
    if (type(dimension) is not int or not 1 <= dimension <= 8192
            or not 4 <= len(train) <= 128 or not 4 <= len(evaluation) <= 128
            or not isinstance(targets, list) or len(targets) != len(train)
            or any(type(t) is not int or not 0 <= t < 4 for t in targets)
            or any(len(r['options']) != 4 for r in train + evaluation)):
        raise ValueError('bounded four-class features and training labels required')
    if (len(train) + len(evaluation)) * dimension * 4 > study['max_feature_bytes']:
        raise ValueError('shared feature payload exceeds bound')
    root = Path(root); root.mkdir(exist_ok=False)
    write_json_exclusive(root / 'STUDY.json', study)
    common = WorkLedger(study['measurement_policy'], study['phase_caps'])
    arrays, lengths = [], []
    try:
        for phase, rows in (('train', train), ('inference', evaluation)):
            with common.scope(phase, 'encoder'):
                matrix = torch.empty(len(rows), dimension)
                for i, row in enumerate(rows):
                    vector, tokens = encode(dict(row))
                    if (not isinstance(vector, torch.Tensor) or vector.shape != (dimension,)
                            or vector.dtype != torch.float32 or vector.device.type != 'cpu'
                            or vector.requires_grad or not torch.isfinite(vector).all().item()
                            or type(tokens) is not int or not 1 <= tokens <= study['context_tokens']):
                        raise ValueError('invalid frozen feature or silently truncated input')
                    matrix[i].copy_(vector)
                    lengths.append(tokens)
                arrays.append(matrix)
        shared_work = common.report()
    except Exception as exc:
        write_json_exclusive(root / 'FAILED.json', dict(error_type=type(exc).__name__,
            stage='shared_encoding', expected_arms=[t[0] for t in TOPOLOGIES], work=common.report()))
        raise
    x, heldout = arrays
    feature_id = [_tensor_digest(x), _tensor_digest(heldout)]
    y = torch.tensor(targets, dtype=torch.long)
    records, predictions = [], []
    for name, count, active in TOPOLOGIES:
        # These geometry profiles do not borrow 421M experiment IDs. The same
        # existing CellBank constructor supplies exact Head+gate matching.
        profile = dict(logical_cells=count, initial_logical_cells=count, split=False, ndu=False,
            resident_stem_copies=1, cell_head_budget_params=32_000_000//count,
            total_head_budget_params=32_000_000, active_cells_per_round_cap=active)
        arm = root / name; arm.mkdir()
        meter = WorkLedger(study['measurement_policy'], study['phase_caps'])
        bank = None
        record = dict(topology=name, cells=count, active_cells=active, status='failed',
                      initial_sha256=None, trained_sha256=None, training=None, inventory=None)
        output = dict(topology=name, before=None, after=None)
        try:
            if [_tensor_digest(x), _tensor_digest(heldout)] != feature_id:
                raise ValueError('prior arm invalidated shared frozen features')
            with meter.scope('train', 'initialization'), torch.random.fork_rng(devices=[]):
                torch.random.default_generator.manual_seed(study['seed'])
                bank = CellBank(dimension, 4, profile, study['width_units'])
                bank.eval()
                record['initial_sha256'] = state_digest(bank)
            with meter.scope('evaluation', 'bank'), torch.inference_mode():
                before = bank(heldout).tolist()
            with meter.scope('train', 'bank'):
                record['training'] = train_bank(bank, x, y, study, study['seed'])
                record['trained_sha256'] = state_digest(bank)
            with meter.scope('inference', 'bank'), torch.inference_mode():
                after = bank(heldout).tolist()
            if [_tensor_digest(x), _tensor_digest(heldout)] != feature_id:
                raise ValueError('shared frozen features changed')
            record['inventory'] = bank.inventory()
            if record['initial_sha256'] == record['trained_sha256']:
                raise ValueError('no observed parameter update')
            save_file(bank.state_dict(), str(arm / 'bank.safetensors'))
            record['bank_file_sha256'] = file_sha256(arm / 'bank.safetensors')
            output.update(before=before, after=after)
            record['status'] = 'completed'
        except Exception as exc:
            record['error_type'] = type(exc).__name__
            # Partial weights are diagnostic only and are never selected for scoring.
        finally:
            record['work'] = meter.report()
            write_json_exclusive(arm / ('RUN.json' if record['status']=='completed' else 'FAILED.json'), record)
            records.append(record); predictions.append(output)
            del bank
    inputs = [dict(sample_id=r['sample_id'], input_digest=input_identity(r)) for r in evaluation]
    sealed = dict(schema='hepta.public-learning-predictions.v1', study_id=study['study_id'],
        heldout_inputs=inputs, training_inputs=[dict(sample_id=r['sample_id'], input_digest=input_identity(r)) for r in train],
        training_labels_sha256=_digest(targets), feature_sha256=feature_id, token_counts=lengths,
        shared_encoder_calls=len(train)+len(evaluation), shared_encoder_work=shared_work,
        feature_payload_bytes=(x.numel()+heldout.numel())*4, arms=records, predictions=predictions,
        final_labels_loaded=False, independent_pretrained_provenance_verified=False,
        backbone_kind='caller_supplied_requires_driver_provenance', production_authorized=False)
    write_json_exclusive(root / 'predictions.json', sealed)
    marker = dict(schema='hepta.public-learning-seal.v1', predictions_sha256=file_sha256(root/'predictions.json'),
        bank_files={r['topology']: r.get('bank_file_sha256') for r in records}, study_id=study['study_id'])
    marker['seal_id'] = _digest(marker)
    write_json_exclusive(root/'COMMITTED.json', marker)
    return marker


def score_sealed(root, labels, *, expected_seal_id):
    """Describe all three preregistered arms; no model work or winner selection."""
    root = Path(root)
    if (root/'FAILED.json').exists():
        raise ValueError('shared execution did not complete')
    marker = strict_json(root/'COMMITTED.json')
    if (marker['seal_id'] != expected_seal_id or
            _digest({k:v for k,v in marker.items() if k!='seal_id'}) != expected_seal_id or
            file_sha256(root/'predictions.json') != marker['predictions_sha256']):
        raise ValueError('prediction seal changed before scoring')
    run = strict_json(root/'predictions.json')
    if (not isinstance(labels, list) or len(labels)!=len(run['heldout_inputs']) or
            any(type(t) is not int or not 0<=t<4 for t in labels)):
        raise ValueError('complete four-class score denominator required')
    expected_names = [t[0] for t in TOPOLOGIES]
    if [a['topology'] for a in run['arms']] != expected_names or [a['topology'] for a in run['predictions']] != expected_names:
        raise ValueError('a planned arm was dropped or reordered')
    results = []
    for arm, output in zip(run['arms'], run['predictions'], strict=True):
        result = dict(topology=arm['topology'], status=arm['status'], requests=len(labels))
        if arm['status'] == 'completed':
            if file_sha256(root/arm['topology']/'bank.safetensors') != marker['bank_files'][arm['topology']]:
                raise ValueError('trained bank artifact changed')
            for when in ('before', 'after'):
                rows = output[when]
                if len(rows)!=len(labels) or any(len(r)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in r) for r in rows):
                    raise ValueError('invalid full prediction denominator')
                correct, brier, per_class = 0, 0., {i:[0,0] for i in range(4)}
                for row, target in zip(rows, labels, strict=True):
                    chosen = max(range(4), key=row.__getitem__)
                    hit = int(chosen==target); correct += hit
                    per_class[target][0] += hit; per_class[target][1] += 1
                    e = [math.exp(v-max(row)) for v in row]; prob=[v/sum(e) for v in e]
                    brier += sum((p-int(i==target))**2 for i,p in enumerate(prob))
                result[when] = dict(accuracy=correct/len(labels), brier=brier/len(labels),
                    per_class={str(c):dict(correct=v[0],rows=v[1]) for c,v in per_class.items()})
        else:
            result.update(before=None, after=None, error_type=arm.get('error_type'))
        results.append(result)
    completed = [a for a in run['arms'] if a['status']=='completed']
    params = [a['inventory']['parameters'] for a in completed]
    train_cost = [a['work']['phase_flops']['train'] for a in completed]
    matched = len(completed)==3 and all(v is not None for v in train_cost) and max(train_cost)-min(train_cost)<=.01*max(train_cost)
    return dict(schema='hepta.public-learning-scores.v1', seal_id=expected_seal_id,
        labels_sha256=_digest(labels), arms=results,
        all_arms_completed=len(completed)==3,
        parameter_matched=len(params)==3 and len(set(params))==1,
        observed_training_work_matched_within_one_percent=matched,
        fixed_update_schedule_not_compute_matching=True,
        shared_encoding_cost_paid_once_in_campaign=True,
        standalone_arm_must_add_shared_encoder_work=True,
        initial_prediction_evaluation_is_extra_control_work=True,
        scoring_and_io_formula_cost_unmeasured=True, independent_observer=False,
        statistically_independent_cases_established=False, pretraining_contamination_ruled_out=False,
        learning_superiority_established=False, full_system_efficiency_established=False,
        production_authorized=False)


def run_public_learning(snapshot, news, output):
    """Explicit real local-HF path; no randomly initialized fallback."""
    root = Path(output); root.mkdir(exist_ok=False)
    try:
        import torch
        import transformers
        from transformers import AutoTokenizer
        from hf_complete_checkpoint import load_complete_mlm, TIED_ALIASES
        from hf_encoder_kernel import snapshot_digest, vectorize_case, verify_loaded_safetensors
        from head_surgery import tensor_inventory
        sources={p.name:file_sha256(p) for p in Path(__file__).parent.glob('*.py')}
        write_json_exclusive(root/'source_files.json', sources)
        train, targets, heldout, final_labels, material = prepare_news(news)
        study = freeze_study()
        write_json_exclusive(root/'selection.json', material)
        write_json_exclusive(root/'STUDY.json', study)
        torch.set_num_threads(1)
        before = snapshot_digest(snapshot); start=time.perf_counter_ns()
        complete, encoder, loading = load_complete_mlm(snapshot)
        tokenizer = AutoTokenizer.from_pretrained(str(snapshot), local_files_only=True, trust_remote_code=False)
        load_ns=time.perf_counter_ns()-start
        def encode(row):
            return vectorize_case(torch, encoder, tokenizer, row, 'cpu', max_tokens=study['context_tokens'])
        def forbidden(*args):
            raise AssertionError('MLM head must not execute for shared features')
        handle=complete.head.register_forward_pre_hook(forbidden)
        try:
            marker=fit_controls(encode, train, targets, heldout, root/'controls', dimension=encoder.config.hidden_size, study=study)
        finally:
            handle.remove()
        verify_loaded_safetensors(torch, complete, snapshot, tied_aliases=TIED_ALIASES)
        if snapshot_digest(snapshot)!=before or prepare_news(news)[4]!=material:
            raise ValueError('model or dataset changed during experiment')
        # Scoring starts only after every arm has a recorded disposition and a
        # single sealed prediction bundle. Same-process order is not isolation.
        scores=score_sealed(root/'controls', final_labels, expected_seal_id=marker['seal_id'])
        scores.update(model_snapshot_sha256=before, complete_checkpoint=loading,
            actual_retained_weights=tensor_inventory(complete), model_loading_ns=load_ns,
            selected_material_id=_digest(material), backbone_kind='local_complete_ModernBERT_MLM_checkpoint',
            runtime=dict(torch=torch.__version__, transformers=transformers.__version__))
        if sources != {p.name:file_sha256(p) for p in Path(__file__).parent.glob('*.py')}:
            raise ValueError('first-party source changed during experiment')
        write_json_exclusive(root/'scores.json', scores)
        write_json_exclusive(root/'COMMITTED.json', dict(seal_id=marker['seal_id'],
            files={n:file_sha256(root/n) for n in ('scores.json','selection.json','STUDY.json','source_files.json')}))
        return scores
    except Exception as exc:
        write_json_exclusive(root/'FAILED.json', dict(error_type=type(exc).__name__,
            completed=False, production_authorized=False))
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--news-dir', required=True)
    parser.add_argument('--acquire-news', action='store_true')
    parser.add_argument('--output', required=True)
    args=parser.parse_args()
    if Path(args.output).exists():
        raise FileExistsError('study output already exists')
    if args.acquire_news:
        acquire_news(args.news_dir)
    report=run_public_learning(args.snapshot,args.news_dir,args.output)
    print(json.dumps({'parameter_matched':report['parameter_matched'],
        'learning_superiority_established':False,'production_authorized':False}))
    return 0 if report['all_arms_completed'] else 2


if __name__=='__main__':
    raise SystemExit(main())
