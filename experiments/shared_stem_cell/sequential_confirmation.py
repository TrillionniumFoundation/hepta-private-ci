"""Encode only active confirmation Cells, then evaluate a locked frozen panel.

Opt-in successor, NOT a reinterpretation of the old fixed-sample decision.
All original producer and preceding confirmation/evaluation contents are excluded.
No fitting, candidate search, lost-row filtering or hidden Encoder work.
An explicitly sealed prefix can be replayed to a NEW output directory.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import torch

from experiments.shared_stem_cell import consolidation as c, execution as e
from experiments.shared_stem_cell import fresh_confirmation as f
from experiments.shared_stem_cell import residual_consolidation as rc
from experiments.shared_stem_cell.sequential_evidence import PairedEvidence, BETS

CONFIRM = 4096
FINAL = 512
CHUNK_PER_CELL = 32
ALPHA = 0.025
NAMES = {'bank', 'shared', *rc.MODES}


def cohort(texts, excluded, *, confirmation=CONFIRM, final=FINAL):
    """Reuse old label-free ordering; reserve exact full pools before any forward."""
    for n in (confirmation, final):
        e.integer(n, 2, 4096, 'sequential pool size')
        if n % 2:
            raise e.InputError('even Cell-balanced pools required')
    rows = f.cohort(texts, excluded, per_phase=(confirmation+final)//2)
    return [{**row, 'split':'confirmation' if i < confirmation else 'evaluation'}
            for i,row in enumerate(rows)]


def prior_rows(directory, report_sha, panel_lock):
    """Trust only an externally SHA-bound prior report and its exact locked cohort."""
    report = e.decode(e.bound_file(directory/'report.json',report_sha,16*1024**2))
    decision = e.decode(e.bound_file(directory/'confirmation.json',report['confirmation_sha256']))
    previous = e.decode(e.bound_file(directory/'candidate-lock.json',decision['candidate_lock_sha256']))
    rows = e.decode(e.bound_file(directory/'cohort.json',report['cohort_sha256'],16*1024**2))
    if (any(previous[k] != panel_lock[k] for k in ('component_manifests','model_revision',
            'dataset_revision','scope','selected')) or len(rows) != 2*f.PER_PHASE
            or len({r['case_id'] for r in rows}) != len(rows)
            or any(r['text_sha256'] != e.sha(r['text'].encode())
                   or r['normalized_sha256'] != f.normalized(r['text']) for r in rows)):
        raise e.InputError('prior cohort or frozen model panel changed')
    return rows


def stream(output, rows, lock, predict_rows, label_at):
    """Save each predicted batch BEFORE answers; never request stopped Cell rows."""
    if (not isinstance(rows,list) or not 4 <= len(rows) <= 8192
            or len({r['case_id'] for r in rows}) != len(rows)
            or len({r['source_index'] for r in rows}) != len(rows)
            or len({r['normalized_sha256'] for r in rows}) != len(rows)
            or set(r['split'] for r in rows) != {'confirmation','evaluation'}
            or any(type(r['cell']) is not int or r['cell'] not in (0,1)
                   or type(r['source_index']) is not int or not 0 <= r['source_index'] < 16384
                   or r['text_sha256'] != e.sha(r['text'].encode())
                   or r['normalized_sha256'] != f.normalized(r['text']) for r in rows)
            or lock.get('selected') not in NAMES):
        raise e.InputError('complete unique sequential cohort and fixed proposal required')
    for phase in ('confirmation','evaluation'):
        counts = [sum(r['split']==phase and r['cell']==i for r in rows) for i in (0,1)]
        if not counts[0] or counts[0] != counts[1]:
            raise e.InputError('exact balanced phase coverage required')
    proposed = lock['selected']
    smaller = lock['parameter_counts'][proposed] < lock['parameter_counts']['bank']
    lock_sha = e.write_once(output/'candidate-lock.json',lock)
    cohort_sha = e.write_once(output/'cohort.json',rows)
    state = PairedEvidence(cells=2,classes=4,alpha=ALPHA)
    pools = [[r for r in rows if r['split']=='confirmation' and r['cell']==cell] for cell in (0,1)]
    positions, chain, consumed, batches = [0,0], e.sha(e.canonical([lock_sha,cohort_sha])), [], []

    def predict(part, name, previous):
        raw = predict_rows(part)
        if (not isinstance(raw,dict) or set(raw.get('predictions',{})) != NAMES
                or not set(raw) <= {'predictions','inference_costs','selected','encoding','feature_sha256'}):
            raise e.InputError('missing original panel control')
        matrices = {}
        for key, values in raw['predictions'].items():
            p = torch.tensor(values,dtype=torch.float64)
            if (p.shape != (len(part),4) or not bool(torch.isfinite(p).all())
                    or bool(((p<0)|(p>1)).any())
                    or not torch.allclose(p.sum(-1),torch.ones(len(p),dtype=p.dtype),atol=1e-5,rtol=0)):
                raise e.InputError('invalid full panel prediction batch')
            matrices[key] = p
        payload = {'case_ids':[r['case_id'] for r in part], 'previous_sha256':previous,
            'candidate_lock_sha256':lock_sha,'cohort_sha256':cohort_sha,**raw}
        seal = e.write_once(output/f'{name}-predictions.json',payload)
        if e.decode(e.bound_file(output/f'{name}-predictions.json',seal,16*1024**2)) != payload:
            raise e.InputError('predictions changed before labels')
        e.bound_file(output/'candidate-lock.json',lock_sha)
        e.bound_file(output/'cohort.json',cohort_sha,16*1024**2)
        return matrices,seal

    while smaller:
        part = []
        for cell in (0,1):
            if not state.counts[cell]['crossed']:
                part.extend(pools[cell][positions[cell]:positions[cell]+CHUNK_PER_CELL])
        if not part:
            break
        name = f'batch-{len(batches):04d}'
        matrices,seal = predict(part,name,chain)
        labels = [e.integer(label_at(r['source_index']),0,3,'confirmation label') for r in part]
        evidence = state.update([r['case_id'] for r in part],matrices['bank'].argmax(-1).tolist(),
            matrices[proposed].argmax(-1).tolist(),labels,[r['cell'] for r in part])
        chain = e.write_once(output/f'{name}-outcomes.json',{'predictions_sha256':seal,
            'previous_sha256':chain,'labels':labels,'evidence':evidence})
        for cell in (0,1):
            positions[cell] += sum(r['cell']==cell for r in part)
        consumed.extend(r['case_id'] for r in part)
        batches.append({'name':name,'predictions_sha256':seal,'outcomes_sha256':chain})
    evidence = state.snapshot()
    chosen = proposed if smaller and evidence['all_crossed'] else 'bank'
    decision = {'proposed':proposed,'chosen':chosen,'strictly_smaller':smaller,'evidence':evidence,
        'candidate_lock_sha256':lock_sha,'cohort_sha256':cohort_sha,'last_batch_sha256':chain,
        'batches':batches,'consumed_confirmation_ids':consumed,
        'unencoded_confirmation_ids':[r['case_id'] for pool in pools for r in pool if r['case_id'] not in state.seen],
        'production_accepted':False}
    decision_sha = e.write_once(output/'decision.json',decision)
    if e.decode(e.bound_file(output/'decision.json',decision_sha,16*1024**2)) != decision:
        raise e.InputError('decision changed before final inference')
    final = [r for r in rows if r['split']=='evaluation']
    matrices,final_sha = predict(final,'evaluation',decision_sha)
    # No final answer exists in this process before the immutable decision above.
    e.bound_file(output/'decision.json',decision_sha,16*1024**2)
    labels = [e.integer(label_at(r['source_index']),0,3,'final label') for r in final]
    routes = torch.tensor([r['cell'] for r in final],dtype=torch.long)
    scores = {key:c.score(p.tolist(),torch.tensor(labels),routes,2) for key,p in matrices.items()}
    return {'schema':'hepta.sequential-confirmation.v1','decision_sha256':decision_sha,
        'evaluation_predictions_sha256':final_sha,'evaluation_labels':labels,'scores':scores,
        'chosen':chosen,'proposed':proposed,'chosen_score':scores[chosen],
        'reserved_confirmation_rows':sum(map(len,pools)),'encoded_confirmation_rows':len(consumed),
        'unencoded_confirmation_rows':sum(map(len,pools))-len(consumed),'evaluation_rows':len(final),
        'assumptions_verified':False,'retention_certified':False,'production_accepted':False}


def run(study, consolidation, producer_sha, consolidation_sha, previous, previous_sha, output,
        *, resume_checkpoint=None, resume_sha256=None):
    from datasets import load_dataset
    from experiments.shared_stem_cell.sequential_replay import Replay, source_identity
    if (resume_checkpoint is None) != (resume_sha256 is None):
        raise e.InputError('checkpoint path AND external SHA256 required together')
    # Before acquisition or model loading, recompute the entire saved prefix.
    with e.measured() as recovery_validation:
        replay = Replay(resume_checkpoint, resume_sha256) if resume_checkpoint is not None else None
    output.mkdir(parents=True,exist_ok=False)
    try:
        panel,config,old,lock = f.load_panel(study,consolidation,producer_sha,consolidation_sha)
        previous_cohort = prior_rows(previous,previous_sha,lock)
        plan = {**lock,'confirmation_cap':CONFIRM,'final_size':FINAL,'alpha':ALPHA,
            'bets':list(BETS),'chunk_per_cell':CHUNK_PER_CELL,'previous_report_sha256':previous_sha,
            'source_sha256':source_identity(),
            'error_budget_scope':'this_new_stream_only_not_all_prior_research',
            'prior_results_not_pooled':True,'extra_optimizer_steps':0,'extra_svd_calls':0}
        e.write_once(output/'plan.json',plan)
        with e.measured() as acquisition:
            source = load_dataset('fancyzhx/ag_news',revision=f.DATA_REVISION,split='test',
                                  cache_dir=str(study/'dataset-cache'))
            texts = source['text']
            # Reconstruct the entire previous exclusion set without reading its answers.
            reconstructed = f.cohort(texts,[r.text for r in old],per_phase=f.PER_PHASE)
            if reconstructed != previous_cohort:
                raise e.InputError('prior content acquisition drift')
            rows = cohort(texts,[r.text for r in old]+[r['text'] for r in previous_cohort],
                          confirmation=CONFIRM,final=FINAL)
        expected = {r['source_index']:r['text'] for r in rows}
        if replay is not None:
            replay.bind(rows, plan)
        encoder = None
        with e.measured() as model_load:
            if replay is None or replay.needs_encoder:
                encoder = e.LocalEncoder(study/'model',config['model'],config['maximum_tokens'])
                if (encoder.identity != e.sha(e.canonical(config['model']))
                        or bool(encoder.simulated) != lock['source_simulated_encoder']):
                    raise e.InputError('sequential encoder identity drift')
        model_load['encoder_loaded'] = encoder is not None
        def forward(part):
            cases = tuple(e.Case(r['case_id'],r['case_id'],r['split'],None,r['cell'],lock['scope'],r['text']) for r in part)
            x,cost = e.encode_cases(encoder,cases,batch_size=config['batch_size'])
            result = rc.predict(*panel,x,torch.tensor([r['cell'] for r in part]))
            return {**result,'encoding':cost,'feature_sha256':e.tensor_digest(x)}
        def answer(index):
            item = source[index]
            if item['text'] != expected[index]:
                raise e.InputError('changed source before answer access')
            return int(item['label'])
        with e.measured() as execution:
            result = (stream(output,rows,plan,forward,answer) if replay is None else
                      replay.run(output,rows,plan,forward,answer))
        if encoder is not None:
            encoder.close()
        _,_,_,relocked = f.load_panel(study,consolidation,producer_sha,consolidation_sha)
        if relocked != lock or prior_rows(previous,previous_sha,lock) != previous_cohort:
            raise e.InputError('source changed during sequential execution')
        result.update(acquisition=acquisition,model_load=model_load,whole_execution=execution,
                      extra_optimizer_steps=0,extra_svd_calls=0,
                      source_simulated_encoder=lock['source_simulated_encoder'],
                      recovery_validation=recovery_validation)
        e.write_once(output/'report.json',result)
        return result
    except Exception as error:
        e.write_once(output/'failure.json',{'error':type(error).__name__,'message':str(error),'production_accepted':False})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ('study','consolidation','previous','output'):
        parser.add_argument('--'+field,type=Path,required=True)
    for field in ('producer-sha256','consolidation-sha256','previous-sha256'):
        parser.add_argument('--'+field,required=True)
    parser.add_argument('--resume-checkpoint', type=Path)
    parser.add_argument('--resume-sha256')
    args = parser.parse_args()
    torch.set_num_threads(2)
    run(args.study,args.consolidation,args.producer_sha256,args.consolidation_sha256,
        args.previous,args.previous_sha256,args.output,
        resume_checkpoint=args.resume_checkpoint,resume_sha256=args.resume_sha256)
