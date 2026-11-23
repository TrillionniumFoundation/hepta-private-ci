"""Replay physically observed prefixes through the sealed six-step policies."""
import argparse
from collections import Counter
from pathlib import Path
import time

import numpy as np
import torch

from . import frontend as front
from . import run
from .independent import CausalChooser
from .policy import HORIZON, PRICE, RATE, READ, RHO, STOP, WAIT, _actions

FIRST_GAP = "commons-112833470-w01"
LAST_GAP = "commons-31045040-w04"
CONTROL = "commons-31045040-w03"


def arrays(path):
    with np.load(path, allow_pickle=False) as archive:
        return {key: archive[key] for key in archive}


def prefix(s, row, steps):
    return {key: value[row:row+1, :steps] if value.ndim >= 2 else value[row:row+1]
            for key, value in s.items()}


def render(s, weights, semantic, choice):
    steps = s['dt'].shape[1]
    # Gallery entries are indexed by elapsed duration. Subset the same static references.
    ref = {channel: {**model, 'gallery': np.asarray(model['gallery'])[:, :steps]}
           for channel, model in weights['reference'].items()}
    paid = np.stack([semantic[str(q)][:steps] for q in s['query_id']])
    return front.candidate(front.render(s, weights['final'], ref, paid), choice)


def evaluate_exit(action, step, target, prob, dt):
    hit = int(int(np.argmax(prob)) == int(target))
    elapsed = float(np.cumsum(dt)[step] - dt[0])
    utility = np.exp(-RHO*elapsed)*(hit - PRICE*(action == READ)) + RATE*np.expm1(-RHO*elapsed)/RHO
    return dict(exit_prefix=int(step), terminal_action=int(action), hit=hit, utility=float(utility))


def replay(q, free, paid, target, dt, can_read, restriction=None):
    if q.shape != (len(dt),3) or not np.isfinite(q).all():
        raise ValueError("invalid prefix scores")
    for t, qt in enumerate(q):
        if restriction == 'immediate_free':
            action = STOP
        elif restriction == 'immediate_paid':
            if not can_read:
                raise ValueError("unavailable paid action")
            action = READ
        elif restriction == 'immediate_conditional':
            allowed = qt[:2] if can_read else qt[:1]
            action = int(allowed.argmax())
        else:
            # _actions uses the true six-step horizon. At t=4 a WAIT remains legal.
            action = int(_actions(qt, t, can_read))
        if action != WAIT:
            return evaluate_exit(action, t, target, (paid if action == READ else free)[t], dt)
    return None


def controls(s,i,q,k,can_read):
    args = (s['scores'][i], s['read_scores'][i], s['target'][i], s['dt'][i])
    outcomes = dict(chosen=replay(q,*args,can_read), keep=replay(k,*args,can_read),
                    disable_read=replay(q,*args,False))
    for mode in ('immediate_free','immediate_conditional','immediate_paid'):
        if can_read or mode != 'immediate_paid':
            outcomes[mode] = replay(q,*args,can_read,mode)
    return outcomes


def table_controls(table,s,i):
    free = s['scores'][i]
    bins = np.searchsorted(table.edges,np.abs(free[:,0]-free[:,1]))
    args = (free,s['read_scores'][i],s['target'][i],s['dt'][i])
    q = table.q[np.arange(len(free)),bins]
    qn = table.q_no_read[np.arange(len(free)),bins]
    return dict(full=replay(q,*args,True),mask_read=replay(q,*args,False),
                refit_no_read=replay(qn,*args,False),immediate=replay(q,*args,True,'immediate_conditional'),
                always_stop=replay(q,*args,False,'immediate_free'),
                always_read=replay(q,*args,True,'immediate_paid'))


def compare(outcome, complete, row, n):
    t = complete['exit_prefix'][row]
    if t >= n:
        assert outcome is None, (outcome,t)
        return
    assert outcome is not None and (
        outcome['exit_prefix'],outcome['terminal_action'],outcome['hit']) == (
            t,complete['terminal_action'][row],complete['episode_hit'][row])
    np.testing.assert_allclose(outcome['utility'],complete['episode_utility'][row],rtol=0,atol=1.e-12)


def run_partial(root):
    begin = time.perf_counter()
    data, policies, commons = root/'discovery',root/'policies',root/'commons'
    seal = run.check_test_receipt(data,policies)
    frontseal = run.load(data/'frontend_seal.json')
    for filename, h in frontseal['source'].items():
        if run.sha(Path(__file__).parent/filename) != h:
            raise ValueError('unsealed frontend code '+filename)
    semantic_path = root/'semantic/test.npz'
    receipt = run.load(root/'semantic/test.receipt.json')
    validity = run.load(root/'observed/validity_seal.json')
    roster_path = commons/'roster/test.json'
    if not (run.sha(semantic_path)==validity['full_semantic']==receipt['output_sha256']
            and run.sha(roster_path)==validity['original_roster']==receipt['roster_sha256']
            and sorted(validity['omitted']) == [FIRST_GAP,LAST_GAP]):
        raise ValueError('mismatching roster or full semantic source')
    if frontseal['selected'] != 'imagenet_visual':
        raise ValueError('paid-only result requires the frozen pure camera modality')
    sem = arrays(semantic_path)
    semantic = dict(zip(sem['query_id'].astype(str),sem['probability'],strict=True))
    roster = {r['query_id']:r for r in run.load(roster_path)}
    if set(semantic)!=set(roster) or any(p.shape!=(HORIZON,2) or not np.isfinite(p).all()
          or (p<0).any() or not np.allclose(p.sum(axis=-1),1) for p in semantic.values()):
        raise ValueError('invalid original semantic ranks')
    raw_path = commons/'features/valid_prefix_tail.npz'
    raw_receipt = run.load(commons/'receipts/valid_prefix_tail.json')
    n = len(raw_receipt['observed_prefixes'])
    tail = arrays(raw_path)
    if (raw_receipt['shard_sha256'] != run.sha(raw_path) or
        raw_receipt['query_id'] != LAST_GAP or raw_receipt['control_query_id'] != CONTROL or
        raw_receipt['input_synthesis'] or raw_receipt['observed_prefixes'] != list(range(1,6)) or
        tail['query_id'].tolist() != [LAST_GAP] or tail['dt'].shape != (1,n) or
        not np.array_equal(tail['dt'][0],roster[LAST_GAP]['dt'][:n]) or
        int(tail['label'][0]) != int(roster[LAST_GAP]['label'])):
        raise ValueError('invalid observed prefix receipt')
    complete_raw = front.load_raw(commons/'features/test.complete.npz')
    control_row = complete_raw['query_id'].astype(str).tolist().index(CONTROL)
    subset = prefix(complete_raw,control_row,n)
    pair = {key:np.concatenate([tail[key],subset[key]]) for key in subset}
    weights = run.load(data/'front_weights.json')
    s = render(pair,weights,semantic,frontseal['selected'])
    full = arrays(data/'test.npz')
    test_row = full['query_id'].astype(str).tolist().index(CONTROL)
    for key in ('x','scores','read_scores','dt','gallery_audio'):
        np.testing.assert_allclose(s[key][1],full[key][test_row,:n],rtol=1.e-12,atol=1.e-12)
    table = CausalChooser.from_state_dict(run.load(data/'chooser.json'))
    ticket = run.load(data/'heldout_controls.json')
    tab = table_controls(table,s,0)
    for name,val in table_controls(table,s,1).items():
        obs=ticket['policy']['policies'][name]
        compare(val,obs,obs['query_ids'].index(CONTROL),n)
    observed = {FIRST_GAP:0,LAST_GAP:n}
    probabilities = {qid:dict(target=roster[qid]['label'],
        free_probability=(s['scores'][0].tolist() if qid==LAST_GAP else []),
        paid_probability=semantic[qid].tolist()) for qid in observed}
    paid_outcome = {qid:evaluate_exit(READ,0,roster[qid]['label'],semantic[qid][0],roster[qid]['dt'])
                    for qid in observed}
    partial = {qid:{} for qid in observed}
    wide = {FIRST_GAP:dict(always_read=paid_outcome[FIRST_GAP]),
            LAST_GAP:{k:v for k,v in tab.items() if v is not None}}
    np.testing.assert_equal(wide[LAST_GAP]['always_read'],paid_outcome[LAST_GAP])
    meta = run.load(policies/'prepare/metadata.json')
    checks, verified, unresolved = 0,Counter(),{}
    max_q_error = 0.
    run.init()
    with torch.inference_mode():
        for availability in run.AVAIL:
            can_read = availability=='read'
            teacher=run.load(policies/'prepare'/(availability+'.json'))
            inputs=run.frontend(s.copy(),meta,teacher)
            complete_inputs=run.frontend(prefix(full,test_row,HORIZON),meta,teacher)
            # Same model, different call lengths: compare dynamic states and head
            # outputs on all five overlapping clocks, including the matched KEEP.
            for seed in run.SEEDS:
                for mode, method in run.ARMS:
                    stem = f'{availability}-{mode}-{method}-{seed}'
                    fit = run.load(policies/'fit'/(stem+'.json'))
                    confirmed = run.load(policies/'confirm'/(stem+'.json'))
                    if (confirmed['task_resources']['selection_seal_sha'] != seal or
                        confirmed['task_resources']['test_sha'] != ticket['ready_hash'] or
                        confirmed['task_resources']['sealed_fit_sha'] != run.sha(policies/'fit'/(stem+'.json'))):
                        raise ValueError('stale confirmation '+stem)
                    control_ix = confirmed['query_id'].index(CONTROL)
                    model=run.representation(mode,seed,len(meta['mu']))
                    get=run.features(model,mode,can_read)
                    outputs=[]
                    for head_key in ('','keep_'):
                        theta=torch.tensor(fit[head_key+'theta'],dtype=torch.float64)
                        head=torch.tensor(fit[head_key+'head'],dtype=torch.float64)
                        h=get(theta,inputs)
                        hc=get(theta,complete_inputs)
                        q=run.predict(h,head).numpy()
                        c=run.predict(hc,head).numpy()[0,:n]
                        np.testing.assert_allclose(h.numpy()[1],hc.numpy()[0,:n],atol=1.e-9,rtol=1.e-10)
                        np.testing.assert_allclose(q[1],c,atol=1.e-9,rtol=1.e-10)
                        max_q_error=max(max_q_error,float(np.max(np.abs(q[1]-c))))
                        if not head_key:
                            published=np.asarray(confirmed['q'][control_ix])[:n]
                            np.testing.assert_allclose(q[1],published,atol=1.e-9,rtol=1.e-10)
                            max_q_error=max(max_q_error,float(np.max(np.abs(q[1]-published))))
                        outputs.append(q)
                        checks+=1
                    outcomes=controls(inputs,0,outputs[0][0],outputs[1][0],can_read)
                    control=controls(inputs,1,outputs[0][1],outputs[1][1],can_read)
                    for name,val in control.items():
                        actual = (confirmed['immediate_controls'][name] if name.startswith('immediate_')
                                  else confirmed[name])
                        compare(val,actual,control_ix,n)
                    for name,val in outcomes.items():
                        if val is not None:
                            verified[name]+=1
                    partial[LAST_GAP][stem] = {k:v for k,v in outcomes.items() if v is not None}
                    if outcomes[fit['immediate_choice']] is not None:
                        partial[LAST_GAP][stem]['dev_immediate']=outcomes[fit['immediate_choice']]
                    partial[FIRST_GAP][stem] = {}
                    if can_read:
                        partial[FIRST_GAP][stem]['immediate_paid']=paid_outcome[FIRST_GAP]
                        if fit['immediate_choice']=='immediate_paid':
                            partial[FIRST_GAP][stem]['dev_immediate']=paid_outcome[FIRST_GAP]
                    if any(v is None for v in outcomes.values()):
                        unresolved[stem]=[k for k,v in outcomes.items() if v is None]
    return dict(ready_hash=ticket['ready_hash'],selection_seal=seal,observed_prefixes=observed,
                partial=partial,always_paid=paid_outcome,partial_frontend=probabilities,
                table=wide,table_dev_immediate=ticket['policy']['immediate_baseline'],
                unresolved_after_known_prefixes=unresolved,
                provenance=dict(control=CONTROL,control_raw_bitwise=raw_receipt['control_arrays_equal_bitwise'],
                    control_exact_ordinal_decisions=True,control_heads_compared=checks,
                    maximum_abs_q_difference=max_q_error,known_tail_exits=dict(verified),
                    input_synthesis=False,observed_rewards_only=True,full_camera_sha256=run.sha(semantic_path),
                    raw_receipt_sha256=run.sha(commons/'receipts/valid_prefix_tail.json'),
                    tail_sha256=run.sha(raw_path),ready_feature_slots=['piano','guitar'],
                    partial_script_sha256=run.sha(Path(__file__)),wall_seconds=time.perf_counter()-begin))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    run.write(args.output,run_partial(args.root))
