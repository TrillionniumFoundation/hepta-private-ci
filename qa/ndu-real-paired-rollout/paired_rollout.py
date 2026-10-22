"""Generate REAL same-source/same-seed single-Cell arms without reference leakage.

Paired rollouts are a prerequisite for terminal-risk covariance, not evidence of
NDU optimality. The actor receives observation only; terminal truth is parent-only.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

import torch

# Local sibling imports are explicit; this is an isolated research tool.
P2 = Path(__file__).resolve().parent.parent / 'ndu-terminal-portfolio'
if P2.is_dir():
    sys.path.insert(0, str(P2))
from terminal_risk import ARMS, SCHEMA, digest, validate

P1_CELLS_SHA256 = "1508a2f4f633b1fa44e05f2a7b750c642e3a39360cf59224d3d4790f31a04396"

# Keep v1 scientific code frozen: reuse the exact published backend and scorer.
V1 = Path(__file__).resolve().parent.parent / 'ndu-grounded-generation'
if V1.is_dir():
    sys.path.insert(0, str(V1))


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def stable_seed(task, seed):
    if type(seed) is not int or not 0 <= seed < 2**31:
        raise ValueError('invalid stochastic seed')
    return (seed + int(hashlib.sha256(task.encode()).hexdigest()[:8], 16)) % (2**31 - 1)


class FrozenArm:
    """Equal structural constraints on zero Cell and each individual Cell."""
    def __init__(self, arm, cells, location_tokens, eos_token, constraints):
        if arm not in ARMS:
            raise ValueError('unsupported Cell arm')
        self.arm, self.cells = arm, cells
        self.locations, self.eos, self.constraints = location_tokens, eos_token, constraints
        self.seconds = 0.0
        self.applied = 0

    @torch.no_grad()
    def __call__(self, state):
        from cells import apply_constraints
        t0 = time.perf_counter()
        weights = [float(i + 1 == ARMS.index(self.arm)) for i in range(4)]
        logits = state['logits'].clone()
        cell_seconds = 0.0
        if self.arm != 'nochange':
            started = time.perf_counter()
            delta, _ = self.cells.delta(state['hidden'], weights, len(logits))
            cell_seconds = time.perf_counter() - started
            logits += delta
        if self.constraints:
            logits = apply_constraints(logits, state['token_ids'], self.locations, self.eos)
        self.applied += 1
        elapsed = time.perf_counter() - t0
        self.seconds += elapsed
        return {'logits': logits, 'weights': weights, 'action': ARMS.index(self.arm),
                'extra': {'cell_seconds': cell_seconds,
                          'controller_seconds': max(0., elapsed - cell_seconds),
                          'fixed_arm': self.arm}}


def run_arm(backend, cells, observation, arm, *, seed=23, budget=10., artifact_root,
            max_new_tokens=48, temperature=0.7, geometry=True):
    """Real encoder/decoder only. Never accepts a reference, loss or final score.

    Every arm incurs an encoder forward; across-arm caching is deliberately
    disabled to preserve independent observed cost and avoid cross-arm leakage.
    """
    if arm not in ARMS or not 0 < budget < 3600 or not math.isfinite(budget):
        raise ValueError('unknown arm or invalid positive budget')
    if not 0 < temperature <= 2 or not math.isfinite(temperature):
        raise ValueError('invalid sampling temperature')
    if type(max_new_tokens) is not int or not 1 <= max_new_tokens <= 512:
        raise ValueError('invalid token budget')
    from backend import OBSERVATION_FIELDS, MODEL_REVISION, explanation
    from generation import render
    if set(observation) != OBSERVATION_FIELDS:
        raise ValueError('actor observation contains missing or reference fields')
    began, cpu_started = time.perf_counter(), time.process_time()
    components = {key: {'component': key, 'calls': 0, 'wall_seconds': 0.}
                  for key in ('encoder','backbone','cell','controller','critic','verifier','render','communication')}
    modifier = FrozenArm(arm, cells, backend.location_token_ids, backend.eos_token_id, geometry)
    result, error, artifact_path, artifact_digest = None, None, None, None
    try:
        encoded = backend.encode(observation)
        components['encoder'].update(calls=1, wall_seconds=float(encoded.costs['encoder_seconds']))
        if time.perf_counter() - began >= budget:
            raise TimeoutError('image encoder consumed entire episode wall budget; no decoder invoked')
        # The backend's soft cap counts this episode's encoder and decoding work.
        remaining = max(0.001, budget - (time.perf_counter() - began - encoded.costs['encoder_seconds']))
        result = backend.generate(encoded, modifier=modifier, max_new_tokens=max_new_tokens,
                                  checkpoint_stride=4, max_checkpoints=16,
                                  max_wall_seconds=remaining, do_sample=True,
                                  temperature=temperature, seed=stable_seed(observation['task_id'], seed))
        rc = result['costs']
        components['backbone'].update(calls=1, wall_seconds=float(rc['decoder_seconds']+rc['parsing_seconds']+rc['loop_overhead_seconds']))
        components['cell'].update(calls=int(modifier.seconds > 0 and arm != 'nochange'),
                                  wall_seconds=float(rc['cell_seconds']))
        components['controller'].update(calls=int(modifier.seconds > 0),
                                        wall_seconds=max(0., float(rc['modifier_seconds']-rc['cell_seconds'])))
        artifact_path, artifact_digest, seconds = render(observation, result['boxes'], artifact_root)
        components['render'].update(calls=1, wall_seconds=float(seconds))
    except Exception as exc:
        error = f'{type(exc).__name__}: {str(exc)[:300]}'
    total = time.perf_counter() - began
    allocated = sum(c['wall_seconds'] for c in components.values())
    # On exceptions, decoder costs may not have been returned. Preserve elapsed
    # work in a distinct failure component rather than inventing call counts.
    if total + 1e-4 < allocated:
        raise ValueError('non-exclusive timing instrumentation exceeded actual wall duration')
    components['unallocated'] = {'component': 'unallocated', 'calls': int(error is not None),
                                 'wall_seconds': max(0., total-allocated)}
    termination = ('completed' if error is None and result['termination'] == 'eos'
                   else 'incomplete')
    return {'task_id': observation['task_id'], 'method':f'terminal-{arm}', 'arm':arm, 'seed':seed,
            'budget_cap':budget, 'budget_unit':'wall_seconds', 'termination':termination,
            'text':explanation(observation['target_category'], result['boxes'] if result else []),
            'boxes':result['boxes'] if result else [], 'label':observation['target_category'],
            'artifact_path':artifact_path, 'artifact_sha256':artifact_digest,
            'controls':result['controls'] if result else [], 'costs':list(components.values()),
            'model_revision':MODEL_REVISION, 'policy_version':f'paired-five-arm/{arm}/v1',
            'actual_wall_seconds':total, 'actual_cpu_seconds':time.process_time()-cpu_started,
            'source_image_sha256':observation['image_sha256'], 'executed_encoder_calls':components['encoder']['calls'],
            'decoder_forward_calls':int(result['costs']['decoder_forward_calls']) if result else None,
            'generated_tokens':int(result['costs']['generated_tokens']) if result else None,
            'failure':error, 'sampling_seed':stable_seed(observation['task_id'],seed),
            'actual_checkpoints':result['costs']['actual_checkpoints'] if result else 0,
            'ledger_minus_wall_seconds':sum(x['wall_seconds'] for x in components.values())-total}


def pinned_model_inventory(model_path):
    """Verify *all* actual decoder assets, not merely frozen weight tensors.

    Processors, tokenizer mappings and generation config influence decoded
    grounding tokens. Their hashes must match the acquisition contract before
    any TRAIN/DEV inference or resume, and foreign sidecar assets are refused.
    This does not establish independent signature/provenance custody.
    """
    from acquisition import FILES, REVISION
    from backend import MODEL_REVISION, WEIGHT_SHA256
    directory = Path(model_path)
    if (directory.is_symlink() or not directory.is_dir() or
            REVISION != MODEL_REVISION or
            FILES.get('model.safetensors', (None, None))[1] != WEIGHT_SHA256):
        raise ValueError('model asset root or frozen revision/weight identity differs')
    inventory = {}
    for name, (size, expected_digest) in sorted(FILES.items()):
        path = directory / name
        if (path.is_symlink() or not path.is_file() or
                path.stat().st_size != size or sha(path) != expected_digest):
            raise ValueError(f'model processor/tokenizer/config/weights asset pin mismatch: {name}')
        inventory[name] = {'bytes': size, 'sha256': expected_digest}
    if {path.name for path in directory.iterdir()} != set(FILES):
        raise ValueError('untracked model directory assets invalidate frozen input identity')
    return inventory


def plan_identity(cohort, split, *, model_path, cells_path, budget, seeds, code_dir, temperature):
    """Frozen header binds exact identities. No previous V1 results permitted."""
    from backend import MODEL_REVISION, WEIGHT_SHA256
    cohort=Path(cohort)
    mf=json.loads((cohort/'manifest.json').read_text())
    if mf.get('evidence_kind') != 'real-coco' or mf.get('schema') != 'hepta.grounded-cohort.v1':
        raise ValueError('real unmodified COCO cohort only; no synthetic scoring')
    if not 640 <= mf.get('prior_images_excluded',-1):
        raise ValueError('must exclude historical 384 and frozen v1 256 image sources')
    if not (cohort / f'{split}.references.jsonl').exists():
        raise ValueError('missing separately stored evaluator references')
    if (len(seeds) < 2 or not all(type(s) is int and 0 <= s < 2**31 for s in seeds)
            or len(set(seeds)) != len(seeds)):
        raise ValueError('at least two unique seeds per source required; duplicates are forbidden')
    # Cell proposal identity includes the exact frozen base, adapter, control
    # implementation and decoding parameters. Identity is not signed proof.
    src=Path(code_dir)
    algorithm=sha(src/'paired_rollout.py')
    cell_digest=sha(cells_path)
    if cell_digest != P1_CELLS_SHA256:
        raise ValueError('Cell checkpoint does not match the frozen P1 trained four-Cell artifact')
    model_inventory = pinned_model_inventory(model_path)
    model_digest = model_inventory['model.safetensors']['sha256']
    model_inventory_digest = digest(model_inventory)
    tracked_v1 = ('backend.py','cells.py','generation.py','cohort.py','evaluate.py','acquisition.py')
    tracked_v3 = ('paired_rollout.py','fresh_cohort.py')
    required_paths = {f'v1/{name}':src.parent/'ndu-grounded-generation'/name for name in tracked_v1}
    required_paths.update({f'v3/{name}':src/name for name in tracked_v3})
    required_paths['v2/terminal_risk.py'] = src.parent/'ndu-terminal-portfolio'/'terminal_risk.py'
    dependency_digests = {name:sha(path) for name,path in required_paths.items()}
    return {'schema':'hepta.ndu-real-five-arm-plan.v1', 'split':split,
            'cohort_manifest_sha256':sha(cohort/'manifest.json'), 'model_digest':model_digest,
            'model_asset_inventory_digest':model_inventory_digest,
            'model_revision':MODEL_REVISION, 'cell_digest':cell_digest,
            'algorithm_digest':algorithm, 'source_code_digests':dependency_digests, 'objective_digest':sha(Path(code_dir).parent/'ndu-grounded-generation'/'evaluate.py'),
            'budget_seconds':budget, 'temperature':temperature, 'seeds':list(seeds),
            'geometry_constraints':'all_arms_including_nochange',
            'proposals':{arm:digest({'model':model_digest,'cell':cell_digest,'algorithm':algorithm,
                                     'arm':arm,'temperature':temperature,'budget':budget,
                                     'model_assets':model_inventory_digest}) for arm in ARMS},
            'scientific_claim':'unverified until independently evaluated on new blind data',
            'promotion':'DENY_ALL'}


def to_terminal_batch(header, records, references, observations):
    """Parent-only conversion after generation: scorer sees references, actor never does."""
    from evaluate import score_episode
    if len({(r['task_id'],r['arm'],r['seed']) for r in records}) != len(records):
        raise ValueError('duplicate arm receipt')
    planned={(obs['task_id'],arm,seed) for obs in observations for arm in ARMS for seed in header['seeds']}
    if {(r['task_id'],r['arm'],r['seed']) for r in records} != planned:
        raise ValueError('incomplete exact five-arm sample roster')
    by_ref={ref['task_id']:ref for ref in references}
    by_obs={obs['task_id']:obs for obs in observations}
    if len(by_ref)!=len(references) or len(by_obs)!=len(observations) or set(by_ref)!=set(by_obs):
        raise ValueError('task/reference identity mismatch')
    entries=[]
    for row in records:
        reference=by_ref[row['task_id']]
        obs=by_obs[row['task_id']]
        if row.get('plan_digest') != digest(header):
            raise ValueError('plan identity mismatch: receipts cannot be substituted')
        if row['source_image_sha256'] != obs['image_sha256']:
            raise ValueError('source image checksum changed')
        if row['budget_cap']!=header['budget_seconds'] or row['method']!=f'terminal-{row["arm"]}':
            raise ValueError('budget or method identity changed')
        score=score_episode(row,reference)
        is_valid=(bool(score['coverage']) and row['failure'] is None and
                  row['actual_wall_seconds'] <= header['budget_seconds'])
        loss=float(score['loss']) if is_valid else 1.
        entries.append({'source_id':reference['source_id'],'image_digest':obs['image_sha256'],
                        'seed':row['seed'],'arm':row['arm'],'proposal_digest':header['proposals'][row['arm']],
                        'loss':loss,'covered':is_valid,'wall_seconds':float(row['actual_wall_seconds']),
                        'overrun':bool(row['actual_wall_seconds']>header['budget_seconds'])})
    cohort={'schema':SCHEMA,'split':header['split'],
            'cohort_digest':digest({'manifest':header['cohort_manifest_sha256'],'split':header['split']}),
            'model_digest':header['model_digest'],'objective_digest':header['objective_digest'],
            'budget_seconds':header['budget_seconds'],'rows':entries}
    validate(cohort, min_source_groups=1, min_seeds=2)
    return cohort


def verify_frozen_train(work, dev_plan, manifest, *, min_source_groups=128):
    """Do not unlock DEV from a mere filename or a stale previous TRAIN run.

    This validates internal, content-addressed custody only. File digests do
    not provide an independent attestation or authorize scientific promotion.
    The test split remains sealed independently of this function.
    """
    from terminal_risk import validate
    work = Path(work)
    receipt_path = work/'train.complete.json'
    if not receipt_path.is_file():
        raise ValueError('DEV requires a published and complete frozen TRAIN receipt')
    receipt = json.loads(receipt_path.read_text())
    if not isinstance(receipt, dict) or receipt.get('status') != 'completed_no_scientific_claim':
        raise ValueError('TRAIN receipt has no successful terminal publication')
    train_dir = work/'train'
    source_paths = {
        'plan': train_dir/'plan.json',
        'journal': train_dir/'episodes.jsonl',
        'terminal': train_dir/'terminal-batch.json',
    }
    digest_fields = {'plan':'plan_sha256', 'journal':'journal_sha256',
                     'terminal':'terminal_batch_sha256'}
    for kind,path in source_paths.items():
        if not path.is_file() or sha(path) != receipt.get(digest_fields[kind]):
            raise ValueError(f'TRAIN {kind} missing or digest changed after completion')
    train_plan = json.loads(source_paths['plan'].read_text())
    if train_plan.get('split') != 'train' or dev_plan.get('split') != 'dev':
        raise ValueError('dev/train roles or immutable plan identity mismatch')
    excluded = {'split'}
    if (set(train_plan) != set(dev_plan) or any(
            train_plan[key] != dev_plan[key] for key in train_plan if key not in excluded)):
        raise ValueError('DEV model, Cell, budget, seed, objective or source code differs from frozen TRAIN')
    if (manifest.get('schema') != 'hepta.grounded-cohort.v1' or
            sha(Path(manifest['manifest_path'])) != dev_plan['cohort_manifest_sha256']):
        raise ValueError('original-image manifest is not the frozen TRAIN/DEV source')
    train_sources = manifest.get('splits',{}).get('train',{}).get('sources',[])
    expected_count = manifest.get('splits',{}).get('train',{}).get('count')
    if (type(expected_count) is not int or expected_count < min_source_groups or
            len(train_sources) != expected_count or
            receipt.get('source_groups') != expected_count or
            receipt.get('episodes') != expected_count*len(train_plan['seeds'])*len(ARMS)):
        raise ValueError('TRAIN sources, seeds or five-arm episode count incomplete')
    terminal = json.loads(source_paths['terminal'].read_text())
    if (terminal.get('split') != 'train' or
            terminal.get('cohort_digest') != digest({'manifest':dev_plan['cohort_manifest_sha256'],
                                                     'split':'train'}) or
            terminal.get('model_digest') != dev_plan['model_digest'] or
            terminal.get('objective_digest') != dev_plan['objective_digest'] or
            terminal.get('budget_seconds') != dev_plan['budget_seconds']):
        raise ValueError('TRAIN terminal objective/model/cohort/budget identity changed')
    validated = validate(terminal, min_source_groups=expected_count,
                         min_seeds=len(train_plan['seeds']))
    expected_source_images = {(s['source_id'],s['image_sha256']) for s in train_sources}
    actual_source_images = set(validated['image_by_source'].items())
    if actual_source_images != expected_source_images:
        raise ValueError('TRAIN terminal source/image identity disagrees with original images')
    if any(seeds != set(train_plan['seeds']) for seeds in validated['roster'].values()):
        raise ValueError('TRAIN terminal seeds differ from frozen plan')
    if validated['proposal_by_arm'] != train_plan['proposals']:
        raise ValueError('TRAIN terminal Cell proposal digests differ from frozen plan')
    # The original journal must be complete, not merely an arbitrary hash file.
    journal = [json.loads(line) for line in source_paths['journal'].read_text().splitlines() if line.strip()]
    lookup = {s['task_id']:s['image_sha256'] for s in train_sources}
    expected_roster = {(task,arm,seed) for task in lookup
                       for arm in ARMS for seed in train_plan['seeds']}
    actual_roster = [(row.get('task_id'),row.get('arm'),row.get('seed')) for row in journal]
    if (len(journal) != receipt['episodes'] or len(set(actual_roster)) != len(actual_roster) or
            set(actual_roster) != expected_roster or
            any(row.get('source_image_sha256') != lookup.get(row.get('task_id')) or
                row.get('plan_digest') != digest(train_plan) for row in journal)):
        raise ValueError('TRAIN journal does not match the original source/seed/arm roster')
    # A mutable local receipt can be rehashed after its terminal scores are
    # altered. Reproduce EVERY observed loss from the executed generator
    # journal and original reference records, not from the terminal batch.
    # This is internal consistency, not external custody/signature proof.
    from cohort import iter_pairs
    cohort_path = Path(manifest['manifest_path']).parent
    pairs = list(iter_pairs(cohort_path, 'train'))
    if {obs['task_id']: obs['image_sha256'] for obs, _ in pairs} != lookup:
        raise ValueError('TRAIN evaluator input roster differs from source manifest')
    rescored = to_terminal_batch(train_plan, journal,
                                [ref for _, ref in pairs],
                                [obs for obs, _ in pairs])
    if rescored != terminal:
        raise ValueError('TRAIN terminal scores differ from original journal and independent reference')
    return {'verified':True,'sources':expected_count,'episodes':len(journal),
            'plan_sha256':receipt['plan_sha256'],
            'terminal_batch_sha256':receipt['terminal_batch_sha256']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort',required=True)
    parser.add_argument('--model',required=True)
    parser.add_argument('--cells',required=True)
    parser.add_argument('--split',choices=['train','dev','test'],required=True)
    parser.add_argument('--work',required=True)
    parser.add_argument('--budget',type=float,default=10.)
    parser.add_argument('--seeds',default='23,41')
    parser.add_argument('--temperature',type=float,default=0.7)
    args=parser.parse_args()
    from backend import FlorenceBackend
    from cells import FourCells
    from cohort import validate_splits,load_observations,iter_pairs
    validate_splits(args.cohort)
    if args.split in ('dev','test') and not (Path(args.work)/'train.complete.json').exists():
        raise ValueError('train must finish and freeze before any holdout execution')
    if args.split == 'test':
        raise ValueError('blind TEST remains sealed: independent policy selection, calibration, preregistration and third-party unseal not implemented; no test leakage')
    seeds=[int(s) for s in args.seeds.split(',')]
    identity=plan_identity(args.cohort,args.split,model_path=args.model,cells_path=args.cells,
                           budget=args.budget,seeds=seeds,code_dir=Path(__file__).resolve().parent,
                           temperature=args.temperature)
    out=Path(args.work)
    if args.split == 'dev':
        manifest=json.loads((Path(args.cohort)/'manifest.json').read_text())
        manifest['manifest_path']=str(Path(args.cohort)/'manifest.json')
        verify_frozen_train(out, identity, manifest)
    if (out/f'{args.split}.complete.json').exists():
        raise FileExistsError('phase already completed; preserve the immutable receipt')
    out.mkdir(parents=True,exist_ok=True)
    phase_dir=out/args.split;phase_dir.mkdir(exist_ok=True)
    record_path=phase_dir/'episodes.jsonl'; plan_path=phase_dir/'plan.json'
    if plan_path.exists():
        if json.loads(plan_path.read_text()) != identity:
            raise ValueError('frozen plan or checksums differ; create a new run directory')
    else:
        if record_path.exists():
            raise ValueError('unbound prior episode journal')
        plan_path.write_text(json.dumps(identity,sort_keys=True,indent=2)+'\n')
    observations=load_observations(args.cohort,args.split)
    if len(observations)<32:
        raise ValueError('need at least 32 separate original-image groups per split')
    previous=[json.loads(line) for line in record_path.read_text().splitlines()] if record_path.exists() else []
    plan_digest=digest(identity)
    planned={(obs['task_id'],arm,seed) for obs in observations for arm in ARMS for seed in seeds}
    seen=set()
    for row in previous:
        key=(row['task_id'],row['arm'],row['seed'])
        if (key not in planned or key in seen or row['budget_cap']!=args.budget or
                row.get('plan_digest') != plan_digest or
                row.get('source_image_sha256') != next(o['image_sha256'] for o in observations if o['task_id']==row['task_id'])):
            raise ValueError('journal contains duplicate, unplanned or foreign-budget result')
        seen.add(key)
    backend=FlorenceBackend(args.model,threads=4)
    cells=FourCells.load(args.cells)
    with record_path.open('a') as stream:
        for obs in observations:
            for seed in seeds:
                # Rotate arms for each source/seed to distribute execution-order effects.
                arms=list(ARMS)
                offset=stable_seed(obs['task_id'],seed)%len(arms)
                arms=arms[offset:]+arms[:offset]
                for arm in arms:
                    key=(obs['task_id'],arm,seed)
                    if key in seen:continue
                    row=run_arm(backend,cells,obs,arm,seed=seed,budget=args.budget,
                                temperature=args.temperature,artifact_root=phase_dir/'artifacts')
                    row['plan_digest']=plan_digest
                    stream.write(json.dumps(row,sort_keys=True,allow_nan=False)+'\n')
                    stream.flush()
                    os.fsync(stream.fileno())
                    seen.add(key)
                    previous.append(row)
    # Truth is not loaded until all generated outputs have been committed.
    references=[ref for _,ref in iter_pairs(args.cohort,args.split)]
    terminal=to_terminal_batch(identity,previous,references,observations)
    output=phase_dir/'terminal-batch.json'
    if output.exists():
        raise FileExistsError('terminal batch already published; do not re-score or overwrite')
    output.write_text(json.dumps(terminal,sort_keys=True,indent=2,allow_nan=False)+'\n')
    complete={'episodes':len(previous),'terminal_batch_sha256':sha(output),
              'journal_sha256':sha(record_path),'plan_sha256':sha(plan_path),
              'source_groups':len(observations),'status':'completed_no_scientific_claim'}
    (out/f'{args.split}.complete.json').write_text(json.dumps(complete,sort_keys=True,indent=2)+'\n')
    print(json.dumps(complete))


if __name__ == '__main__':
    main()
