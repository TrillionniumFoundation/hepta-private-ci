"""Independent visible-completion and saved-record audit of R2 confirmation.

No lane campaign, scorer, neural model or posterior implementation is imported.
This is saved-evidence reconstruction, not a model rerun or new confirmation.
"""
import hashlib
import json
from pathlib import Path
import numpy as np
from experiments.hcsn_addressed_flow_20261101 import data
from experiments.hcsn_four_stage_flow_20261031.extended_eval import stress_data
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]

def load(path): return json.loads(Path(path).read_text())

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def source_check(mapping):
    for path,digest in mapping.items(): assert sha(ROOT/path)==digest, path

def close(actual,expected):
    if actual is None or expected is None: assert actual is expected
    else: assert np.allclose(actual,expected,rtol=1e-10,atol=1e-12), (actual,expected)

def missing_arrays(task,stage,condition):
    if condition=='missing_tokens_128':
        base=data.batch(task,stage['episodes'],stage['seed'],stage['split'],'missing')
        arrays=stress_data(task,base,'long_tokens_128')
        available=np.zeros_like(arrays['y'],bool);available[:,-4:]=base['target_available'][:,-4:]
        arrays['target_available']=available
        return arrays
    return data.batch(task,stage['episodes'],stage['seed'],stage['split'],condition)

def expected_probabilities(task,arrays):
    """Count visible-consistent completions, independent of candidate code."""
    expected=np.zeros((len(arrays['x']),4,8));cardinalities=[]
    offset=4 if task=='binding' else 0;end=offset+8
    for row in range(len(arrays['x'])):
        initial={};updates={};aliases={};erased=[]
        for t in range(end+(2 if task=='selective' else 0)):
            if not arrays['observed'][row,t]: erased.append(t);continue
            event=arrays['x'][row,t];kind=event[12:16].argmax()
            if kind==0: (initial if t<end else updates)[int(event[:4].argmax())]=int(event[4:12].argmax())
            elif kind==3: aliases[int(event[19:23].argmax())]=int(event[:4].argmax())
        worlds=[]
        if not erased:
            final=initial.copy();final.update(updates);worlds.append(final)
        elif erased[0]<end:
            key=next(iter(set(range(4))-set(initial)))
            for value in sorted(set(range(8))-set(initial.values())-set(updates.values())):
                final=initial.copy();final[key]=value;final.update(updates);worlds.append(final)
        else:
            for key in sorted(set(range(4))-set(updates)):
                for value in sorted(set(range(8))-set(initial.values())-set(updates.values())):
                    final=initial.copy();final.update(updates);final[key]=value;worlds.append(final)
        assert worlds;cardinalities.append(len(worlds))
        for slot,t in enumerate(range(arrays['x'].shape[1]-4,arrays['x'].shape[1])):
            event=arrays['x'][row,t]
            key=aliases[int(event[19:23].argmax())] if task=='binding' else int(event[:4].argmax())
            for world in worlds:expected[row,slot,world[key]]+=1/len(worlds)
    return expected,cardinalities

def visible_acceptance(task,arrays,group):
    """Independent implementation of the declared fixed visible-state hash."""
    output=np.zeros_like(group,bool);offset=4 if task=='binding' else 0;end=offset+8
    for row in range(len(arrays['x'])):
        initial=np.full(4,255,np.uint8);updates=np.full(4,255,np.uint8);aliases=np.full(4,255,np.uint8)
        missing_initial=missing_final=0
        for t in range(end+(2 if task=='selective' else 0)):
            if not arrays['observed'][row,t]:
                if t<end: missing_initial+=1
                else: missing_final+=1
                continue
            event=arrays['x'][row,t];kind=event[12:16].argmax()
            if kind==0:
                key=event[:4].argmax();value=event[4:12].argmax()
                (initial if t<end else updates)[key]=value
            elif kind==3: aliases[event[19:23].argmax()]=event[:4].argmax()
        for slot,t in enumerate(range(arrays['x'].shape[1]-4,arrays['x'].shape[1])):
            event=arrays['x'][row,t]
            key=int(aliases[event[19:23].argmax()]) if task=='binding' else int(event[:4].argmax())
            state=initial.tobytes()+updates.tobytes()+aliases.tobytes()+bytes([key,missing_initial,missing_final])
            coin=int.from_bytes(hashlib.blake2b(b'hcsn-r2-fixed-quarter-20261101'+task.encode()+state,digest_size=8).digest(),'big')
            output[row,slot]=group[row,slot]==0 or (group[row,slot]==2 and coin<2**62)
    return output

def probability_metrics(p,y,available,accepted,group):
    correct=p.argmax(-1)==y;confidence=p.max(-1)
    nll=-np.log(p[np.arange(len(y)),y].clip(1e-15));brier=((p-np.eye(8)[y])**2).sum(-1)
    result=dict(accuracy=float(correct.mean()),all4=float(correct.reshape(-1,4).all(-1).mean()),
                nll=float(nll.mean()),brier=float(brier.mean()),coverage=float(accepted.mean()),
                accepted_correctness=float(correct[accepted].mean()) if accepted.any() else None,
                accepted_known_coverage=float(accepted[available].mean()),
                accepted_unavailable_rate=float(accepted[~available].mean()) if (~available).any() else None,
                known_accuracy=float(correct[available].mean()),branches={})
    for name,mask in [('unavailable',~available),('certain',group==0),('initial_unknown',group==1),('final_ambiguous',group==2)]:
        result['branches'][name]=dict(count=int(mask.sum()),accuracy=float(correct[mask].mean()),
            nll=float(nll[mask].mean()),brier=float(brier[mask].mean()),confidence=float(confidence[mask].mean()),
            accepted_count=int((accepted&mask).sum()),accepted_correct=int((accepted&mask&correct).sum())) if mask.any() else None
    return result

def nested_close(actual,expected):
    assert actual.keys()==expected.keys()
    for key,value in expected.items():
        if isinstance(value,dict): nested_close(actual[key],value)
        else: close(actual[key],value)

def missing():
    lane=ROOT/'experiments/hcsn_missing_reliability_r2_20261101';out=lane/'results/run001'
    if not (out/'PROTOCOL.json').exists(): return dict(status='pending_source')
    p=load(out/'PROTOCOL.json'); source_check(p['source_hashes'])
    law=load(lane/'AUDIT_LAW.json');source_check(law['source_sha256']);assert law['passed']
    if not (out/'confirmation/SUMMARY.json').exists(): return dict(status='pending_confirmation',law_query_checks=law['query_checks'])
    candidate=load(out/'CANDIDATE.json');s=load(out/'confirmation/SUMMARY.json')
    assert s['candidate_sha256']==sha(out/'CANDIDATE.json') and s['source_unchanged']
    assert candidate['protocol_sha256']==sha(out/'PROTOCOL.json')
    cache={};unique_rows=[];branches=[]
    for r in s['records']:
        key=(r['task'],r['condition'])
        if key not in cache:
            arrays=missing_arrays(r['task'],p['confirmation'],r['condition']);mask=arrays['y']>=0
            raw_path=out/'confirmation'/r['raw_file'];assert sha(raw_path)==r['raw_sha256']
            with np.load(raw_path,allow_pickle=False) as z: raw={k:z[k] for k in z.files}
            for name,value in arrays.items(): assert hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest()==r['data_sha256'][name]
            assert np.array_equal(raw['labels'],arrays['y'][mask]);assert np.array_equal(raw['available'],arrays.get('target_available',mask)[mask])
            expected,_=expected_probabilities(r['task'],arrays)
            expected=expected.reshape(-1,8);close(raw['exact_probabilities'],expected)
            group=np.where((expected>0).sum(-1)==1,0,np.where(expected.max(-1)>.5,2,1))
            assert np.array_equal(group,raw['group'])
            fitted=expected.copy();ambiguous=group==2
            for i in np.flatnonzero(ambiguous):
                support=expected[i]>0;old=expected[i].argmax();fitted[i,support]=(1-candidate['q'])/3;fitted[i,old]=candidate['q']
            close(raw['probabilities'],fitted)
            accepted=visible_acceptance(r['task'],arrays,group.reshape(-1,4)).reshape(-1)
            assert np.array_equal(accepted,raw['accepted'])
            cache[key]=(raw,expected,fitted,accepted,group)
        raw,expected,fitted,accepted,group=cache[key]
        if r['version']=='ordinary_exact_law': probability=expected
        elif r['version']=='shared_posterior_readout': probability=fitted
        elif r['version']=='r1_neural':
            path=out/'confirmation'/r['neural_raw_file'];assert sha(path)==r['neural_raw_sha256']
            with np.load(path,allow_pickle=False) as z: logits=z['logits'].astype(np.float64)/r['calibration']['temperature']
            e=np.exp(logits-logits.max(-1,keepdims=True));probability=e/e.sum(-1,keepdims=True)
            accepted=probability.max(-1)>=r['calibration']['threshold']
        else: raise AssertionError('Unexpected version')
        calculated=probability_metrics(probability,raw['labels'],raw['available'],accepted,group)
        nested_close(r['metrics'],calculated)
        if r['version']=='shared_posterior_readout' and r['core']=='flow' and r['seed']==17:
            unique_rows.append(dict(task=r['task'],condition=r['condition'],metrics=calculated))
            branch=calculated['branches']['final_ambiguous']
            if branch: branches.append(dict(task=r['task'],condition=r['condition'],**branch))
    assert len(s['records'])==156 and len(cache)==12 and len(unique_rows)==12
    gates=p['gates'];checks=[]
    for row in unique_rows:
        m=row['metrics'];passed=(m['known_accuracy']>=gates['known_accuracy_min']
            and m['accepted_correctness'] is not None and m['accepted_correctness']>=gates['accepted_correctness_min']
            and m['accepted_known_coverage']>=gates['accepted_known_coverage_min']
            and ('missing' in row['condition'] or m['all4']>=gates['nonmissing_all4_min']))
        checks.append(dict(task=row['task'],condition=row['condition'],passed=passed))
    return dict(status='verified',record_checks=len(s['records']),distinct_posterior_records=len(cache),
                gate_checks=checks,restricted_interface_point_gates_pass=all(r['passed'] for r in checks),
                final_ambiguous_branch=branches,summary_sha256=sha(out/'confirmation/SUMMARY.json'),
                law_audit_sha256=sha(lane/'AUDIT_LAW.json'),law_query_checks=law['query_checks'],
                limits=['Same posterior repeated across six core/seed pairs; not independent evidence',
                        'Class-law parser bypasses neural state; analytic-core increment is zero by construction',
                        'Overall selective correctness is not per-answer 95 percent confidence; accepted ambiguous queries retain about two-thirds correctness',
                        'No resample, multiple-erasure, unknown-generator or open-language qualification'])

def main():
    result=missing()
    if result['status']!='verified':
        raise RuntimeError('Complete confirmation evidence required: '+str(result))
    result.update(schema='hcsn.missing-r2.independent-record-audit.v1',
                  audit_source_sha256=sha(__file__),
                  scope='Independent saved inputs, visible-consistent hidden completions, fixed hash acceptance and raw metrics; not neural reexecution or population certification')
    with (HERE/'AUDIT_RECORDS.json').open('x') as stream:
        json.dump(result,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')
    print(json.dumps(dict(status=result['status'],record_checks=result['record_checks'],distinct_posterior_records=result['distinct_posterior_records'],restricted_interface_point_gates_pass=result['restricted_interface_point_gates_pass']),sort_keys=True))

if __name__=='__main__': main()
