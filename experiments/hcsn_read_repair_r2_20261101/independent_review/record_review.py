"""Independent saved-world/service/prefix/logit/scoring reconstruction.

No candidate, provider, campaign, model, scorer or data generator is imported.
Only the already sealed confirmation files are read; no new world is opened.
"""
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

HERE=Path(__file__).resolve().parent
LANE=HERE.parent
ROOT=HERE.parents[2]
OUT=LANE/'results/run001'


def load(path):return json.loads(Path(path).read_text())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def close(a,b):
    if a is None or b is None:assert a is b
    else:assert np.allclose(a,b,rtol=1e-10,atol=1e-12),(a,b)


def generic_answer(x,observed):
    memory={};aliases={}
    for event,present in zip(x[:-1],observed[:-1],strict=True):
        if not present:continue
        if event[12]:memory[int(event[:4].argmax())]=int(event[4:12].argmax())
        if event[15]:aliases[int(event[19:23].argmax())]=int(event[:4].argmax())
    query=x[-1];key=aliases.get(int(query[19:23].argmax()),-1) if query[19:23].any() else int(query[:4].argmax())
    return memory.get(key,0)


def score(prediction,y,available,fees,groups):
    correct=prediction==y
    result=dict(accuracy=float(correct.mean()),all4=float(correct.all(-1).mean()),coverage=1.,
        utility=float(np.mean(correct.mean(-1)-fees)),mean_fee=float(np.mean(fees)),known_accuracy=float(correct[available].mean()),
        unavailable_accuracy=float(correct[~available].mean()) if (~available).any() else None,branches={})
    for name,mask in [('final_ambiguous',groups==2),('initial_unknown',groups==1),('unavailable',~available)]:
        result['branches'][name]=dict(queries=int(mask.sum()),correct=int(correct[mask].sum()),accuracy=float(correct[mask].mean()),coverage=1.) if mask.any() else None
    return result


def compare(a,b):
    assert a.keys()==b.keys()
    for key,value in b.items():
        if isinstance(value,dict):compare(a[key],value)
        else:close(a[key],value)


def main():
    p=load(OUT/'PROTOCOL.json');s=load(OUT/'confirmation/SUMMARY.json');candidate=load(OUT/'CANDIDATE.json')
    for path,digest in p['source_hashes'].items():assert sha(ROOT/path)==digest
    assert s['source_unchanged'] and s['candidate_sha256']==sha(OUT/'CANDIDATE.json') and candidate['protocol_sha256']==sha(OUT/'PROTOCOL.json')
    started=load(OUT/'confirmation/STARTED.json');assert started['candidate_sha256']==s['candidate_sha256'] and started['source_hashes']==p['source_hashes']
    rows=s['records'];lookup={(r['task'],r['condition'],r['core'],r['seed'],r['policy']):r for r in rows}
    assert len(rows)==len(lookup)==504
    policies=p['policies'];model_ledger={(r['task'],r['condition'],r['core'],r['seed']):r for r in s['model_execution_ledger']}
    service_ledger={(r['task'],r['condition'],r['policy']):r for r in s['provider_execution_ledger']}
    total_queries=total_requests=total_inputs=0;frames=forwards=0;service_sessions=0;cohorts=[]
    for task in p['tasks']:
        for condition in p['confirmation']['primary']+p['confirmation']['secondary']:
            reference=lookup[task,condition,'ordinary',None,policies[0]]
            world_path=OUT/'confirmation'/reference['world_file'];trace_path=OUT/'confirmation'/reference['trace_file']
            assert sha(world_path)==reference['world_sha256'] and sha(trace_path)==reference['trace_sha256']
            with np.load(world_path,allow_pickle=False) as z:w={k:z[k] for k in z.files}
            n=len(w['labels']);assert n==p['confirmation']['episodes']
            traces=json.loads(gzip.decompress(trace_path.read_bytes()));assert len(traces)==n*len(policies)
            predicted={policy:np.zeros((n,4),np.int64) for policy in policies}
            fees={policy:np.zeros(n) for policy in policies};reads={policy:np.zeros(n,np.int64) for policy in policies}
            pool={};trace_keys=set()
            for i in range(n):
                full=w['full_x'][i];observed=w['observed'][i];last={};aliases={}
                for slot,event in enumerate(full[:-4]):
                    if event[12]:last[int(event[:4].argmax())]=slot
                    if event[15]:aliases[int(event[19:23].argmax())]=int(event[:4].argmax())
                for q,event in enumerate(full[-4:]):
                    key=aliases[int(event[19:23].argmax())] if event[19:23].any() else int(event[:4].argmax())
                    assert w['labels'][i,q]==int(full[last[key],4:12].argmax())
                    assert w['available'][i,q]==observed[last[key]]
                assert np.array_equal(w['partial_x'][i,observed],full[observed]) and not w['partial_x'][i,~observed].any()
            for trace in traces:
                i,policy,plan=trace['episode'],trace['policy'],trace['plan'];j=policies.index(policy)
                assert (i,policy) not in trace_keys;trace_keys.add((i,policy))
                acquired={};markers={};requests=[];price=float(w['prices'][i]);timestamps=np.cumsum(w['dt'][i],dtype=np.float64)
                for q,query in enumerate(plan['queries']):
                    cursor=query['cursor'];assert cursor==len(w['dt'][i])-4+q
                    visible=w['partial_x'][i,:cursor+1].copy();present=w['observed'][i,:cursor+1].copy()
                    for slot,event in acquired.items():visible[slot]=event;present[slot]=True
                    unread=np.flatnonzero(~present).tolist();assert unread==query['visible_missing_slots']
                    before=np.asarray(query['pre_probability']);assert before.shape==(8,) and np.isfinite(before).all() and (before>=0).all();close(before.sum(),1.)
                    needed=bool(unread) and (query['pre_branch']=='observable_fallback' or before.max()<.95)
                    expected_slots=unread if policy=='always_read' or (policy=='confidence_read' and needed) or (policy=='simple_threshold' and needed and price<=candidate['thresholds'][task]) else []
                    assert query['requested_slots']==expected_slots and query['exact_reference_same_requests']
                    assert len(query['receipts'])==len(expected_slots);wait=0.
                    for slot,reply in zip(expected_slots,query['receipts'],strict=True):
                        assert reply['slot']==slot and slot<=cursor and not w['observed'][i,slot] and slot not in acquired
                        assert set(reply)=={'slot','original_timestamp','event','arrival_timestamp','charge','wait'}
                        assert np.array_equal(reply['event'],w['full_x'][i,slot]) and w['full_x'][i,slot,12]==1
                        close(reply['original_timestamp'],timestamps[slot]);close(reply['charge'],price);close(reply['wait'],.1)
                        wait+=reply['wait'];close(reply['arrival_timestamp'],timestamps[cursor]+wait)
                        acquired[slot]=np.asarray(reply['event'],np.float32);requests.append(reply);total_requests+=1
                    if wait:markers[cursor]=wait
                    close(query['wait_this_query'],wait);close(query['answer_timestamp'],timestamps[cursor]+wait);close(query['paid_so_far'],price*len(acquired))
                    xx=[];dd=[];oo=[];clock=0.
                    for slot in range(cursor+1):
                        elapsed=float(timestamps[slot]-clock);assert elapsed>=-1e-8
                        xx.append(acquired.get(slot,w['partial_x'][i,slot]));dd.append(max(0.,elapsed));oo.append(bool(w['observed'][i,slot] or slot in acquired));clock=float(timestamps[slot])
                        if slot in markers:
                            xx.extend([np.zeros(24,np.float32),w['partial_x'][i,slot]]);dd.extend([markers[slot],0.]);oo.extend([False,True]);clock+=markers[slot]
                    x=np.asarray(xx,np.float32);dt=np.asarray(dd,np.float32);observed=np.asarray(oo,bool)
                    digest=hashlib.sha256(x.tobytes()+dt.tobytes()+observed.tobytes()).hexdigest()
                    assert query['replay_sha256']==digest==str(w['identities'][w['replay_index'][i,j,q]])
                    assert query['replay_steps']==len(dt);close(query['replay_elapsed'],dt.astype(np.float64).sum())
                    assert np.isclose(dt.astype(np.float64).sum(),query['answer_timestamp'],atol=1e-6)
                    if digest in pool:assert pool[digest]==len(dt)
                    pool[digest]=len(dt);total_queries+=1
                    after=np.asarray(query['post_probability']);assert after.shape==(8,) and np.isfinite(after).all();close(after.sum(),1.)
                    assert query['ordinary_answer']==after.argmax()
                    if not np.any(~observed):assert query['ordinary_answer']==generic_answer(x,observed)
                    predicted[policy][i,q]=query['ordinary_answer']
                    assert query['environment_action_history_unchanged'] and query['reconstructed_after_acquisition']
                close(plan['fee'],price*len(acquired));assert plan['reads']==len(acquired)
                close(plan['read_wait'],.1*len(acquired));assert len(plan['requests'])==len(requests)
                fees[policy][i]=plan['fee'];reads[policy][i]=plan['reads']
                if policy=='always_read':assert np.array_equal(plan['answer'],w['labels'][i])
                service_sessions+=1
            assert sorted(pool)==w['identities'].tolist()
            packed=json.loads(gzip.decompress((OUT/'confirmation'/f'{task}_{condition}_POOL.json.gz').read_bytes()))
            assert packed['identities']==sorted(pool) and packed['unique_exact_inputs']==len(pool)
            assert packed['logical_query_lookups']==n*len(policies)*4 and packed['cache_hits']==packed['logical_query_lookups']-len(pool)
            lengths={length:sum(v==length for v in pool.values()) for length in set(pool.values())}
            expected_calls=sum((count+min(24,4096//length)-1)//min(24,4096//length) for length,count in lengths.items())
            for policy in policies:
                row=lookup[task,condition,'ordinary',None,policy];compare(row['metrics'],score(predicted[policy],w['labels'],w['available'],fees[policy],w['groups']))
                close(row['mean_reads'],reads[policy].mean())
                service=service_ledger[task,condition,policy]
                assert service['actual_policy_world_sessions']==n and service['actual_paid_reads']==reads[policy].sum()
                close(service['total_symbolic_fee'],fees[policy].sum());close(service['actual_read_wait'],reads[policy].sum()*.1)
            for core in p['cores']:
                for seed in p['model_seeds']:
                    ledger=model_ledger[task,condition,core,seed];path=OUT/'confirmation'/ledger['raw_file']
                    assert sha(path)==ledger['raw_sha256'] and ledger['actual_forward_calls']==expected_calls
                    assert ledger['actual_replay_sequences']==len(pool) and ledger['actual_replay_frames']==sum(pool.values())
                    with np.load(path,allow_pickle=False) as z:logits=z['logits']
                    assert logits.shape==(len(pool),8) and np.isfinite(logits).all()
                    for j,policy in enumerate(policies):
                        prediction=logits[w['replay_index'][:,j,:]].argmax(-1)
                        row=lookup[task,condition,core,seed,policy]
                        compare(row['metrics'],score(prediction,w['labels'],w['available'],fees[policy],w['groups']))
                        close(row['mean_reads'],reads[policy].mean())
                    forwards+=ledger['actual_forward_calls'];frames+=ledger['actual_replay_frames'];total_inputs+=len(pool)
            cohorts.append(dict(task=task,condition=condition,episodes=n,unique_prefixes=len(pool),service_sessions=n*len(policies)))
    assert len(cohorts)==18 and service_sessions==4608
    assert forwards==s['actual_neural_forward_calls'] and total_inputs==s['actual_neural_replay_sequences']
    result=dict(schema='hcsn.read-repair-r2.independent-record-review.v1',passed=True,record_checks=len(rows),cohorts=cohorts,
        query_prefix_checks=total_queries,actual_provider_world_sessions=service_sessions,actual_paid_read_requests=total_requests,
        actual_neural_forward_calls=forwards,actual_neural_replay_sequences=total_inputs,actual_neural_replay_frames=frames,
        summary_sha256=sha(OUT/'confirmation/SUMMARY.json'),audit_source_sha256=sha(__file__),review_cpu_seconds=None,
        limits=['Same executed service traces shared across six frozen core/seed arms and ordinary reference; not independent service repetitions',
                'No neural model rerun; every saved logit index bound to independently reconstructed prefix bytes',
                'Only conservative always_read qualified on shifted/unknown laws; confidence may fail on indistinguishable hidden histories',
                'Symbolic service fees/waits separate from actual replay CPU and external provider ownership'],all_blockers_closed=False,production_activation=False)
    with (HERE/'RECORD_REVIEW.json').open('x') as stream:json.dump(result,stream,indent=2,sort_keys=True);stream.write('\n')
    print(json.dumps({k:result[k] for k in ['passed','record_checks','query_prefix_checks','actual_provider_world_sessions','actual_neural_forward_calls','actual_neural_replay_sequences']},sort_keys=True))


if __name__=='__main__':main()
