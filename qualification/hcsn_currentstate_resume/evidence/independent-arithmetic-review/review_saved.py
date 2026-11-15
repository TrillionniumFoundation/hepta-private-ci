"""Independent stdlib saved-evidence verifier; never import target code.

Reproduce: python review_saved.py --root /path/to/checkout --output /tmp/review
Keep GIT_INVENTORY.json beside this source.  Local scratch layout also works.
"""
import argparse
from collections import Counter
from fractions import Fraction as F
import hashlib
import json
import math
from pathlib import Path

COMMIT='2d43f01f4ccda743a6cba0a18484334b2d447f0f'
SOURCE='9e9dc3fb698ce53046790e09497420eaaee8df5f'
KEYS={'active','upper','M','H','A','R','Z'}
FLOOR=1e-12
TOL=2e-11

def read(p):return json.loads(p.read_text())
def sha(raw):return hashlib.sha256(raw).hexdigest()
def blob(raw):return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
def canon(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()

def flat(x):
    if isinstance(x,list):
        for y in x:yield from flat(y)
    else:yield x

def diff(a,b):
    aa,bb=list(flat(a)),list(flat(b));assert len(aa)==len(bb)
    return max((abs(x-y) for x,y in zip(aa,bb)),default=0.)

def exactsum(x):return sum((F.from_float(float(y)) for y in flat(x)),F(0))

def finite(x):assert all(type(v) in (int,float) and math.isfinite(v) for v in flat(x))

def decode(x):
    assert set(x)=={'shape','hex'}
    shape=x['shape'];assert all(type(n) is int and n>=0 for n in shape)
    data=[float.fromhex(h) for h in x['hex']]
    assert len(data)==math.prod(shape) and all(math.isfinite(v) for v in data)
    return shape,data

def fraction(x):
    assert len(x)==2 and all(type(n) is int for n in x)
    t=F(*x);assert [t.numerator,t.denominator]==x
    return t

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,default=Path('/workspace/scratch/c06d659c1e72/currentstate-resume-raw'))
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parent)
    args=parser.parse_args();root=args.root.resolve();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    repo_evidence=root/'qualification/hcsn_currentstate_resume/evidence/saved-fullraw-attempt001'
    evidence=repo_evidence if repo_evidence.exists() else root/'evidence/saved-fullraw-attempt001'
    old=root/'qualification/hcsn_currentstate/evidence/currentstate-attempt001'
    inventory=read(Path(__file__).with_name('GIT_INVENTORY.json'))
    assert inventory['artifact_commit']==COMMIT
    entries=[]
    for item in json.loads(inventory['root']['content']):
        if item['type']=='file':entries.append((item['name'],item['size'],item['sha']))
        else:
            tree=json.loads(inventory['subtrees'][item['name']]['content'])
            assert tree['sha']==item['sha'] and tree.get('truncated') is False
            entries.extend((item['name']+'/'+x['path'],x['size'],x['sha']) for x in tree['tree'] if x['type']=='blob')
    assert len(entries)==len({x[0] for x in entries})==33
    def local(name):
        p=evidence/name
        if p.exists():return p
        return {'FREEZE.json':root/'FREEZE.json','RUN.stdout':root/'SAVED-fullraw-attempt001.stdout',
                'RUN.stderr':root/'SAVED-fullraw-attempt001.stderr'}[name]
    paths={name:local(name) for name,_,_ in entries}
    before={}
    for name,size,gsha in entries:
        raw=paths[name].read_bytes()
        assert len(raw)==size and blob(raw)==gsha,name
        before[name]={'bytes':len(raw),'sha256':sha(raw),'git_blob':blob(raw)}
    freeze=read(paths['FREEZE.json']);summary=read(paths['SUMMARY.json']);rows=read(paths['ROWS.json'])
    assert freeze['source_commit']==summary['source_freeze_commit']==SOURCE
    assert freeze['identity']==summary['identity']=='currentstate-saved-continuation-fullraw-attempt001'
    assert len(freeze['source_sha256'])==10 and len(freeze['input_sha256'])==5
    source_before={p:sha((root/p).read_bytes()) for p in freeze['source_sha256']}
    inputs_before={p:sha((root/p).read_bytes()) for p in freeze['input_sha256']}
    assert summary['before']==summary['after']=={'source_sha256':source_before,'input_sha256':inputs_before}
    assert source_before==freeze['source_sha256'] and inputs_before==freeze['input_sha256']
    assert summary['unchanged'] is True
    assert len(summary['artifacts'])==29
    for name,meta in summary['artifacts'].items():
        assert meta=={k:before[name][k] for k in ('bytes','sha256')}
    stdout=read(paths['RUN.stdout']);assert all(stdout[k]==summary[k] for k in stdout)
    assert paths['RUN.stderr'].read_bytes()==b''
    original=read(old/'ROWS.json')
    old_index={(r['fixture'],r['time']):r for r in original};assert len(old_index)==18
    assert len(rows)==summary['rows']==10
    row_index={(r['fixture'],r['mode'],r['time']):r for r in rows};assert len(row_index)==10
    max_abs={};max_rel={};eligible=0;null=0;count=Counter();comparisons={};snapshots={};rawpairs=[]
    channel_initial={};max_conservation=0.;max_firsthit_balance=0.;max_r2m2=0.
    all_trajectories={};scalar_checks=0;max_vs_old=0.
    for name in ('mixed','rare'):
        initial_state=json.loads((old/f'{name}.resume.json').read_text())['state']
        # Initial pending totals are read from original .201 observations, not
        # inferred by evaluating any packet or propagator.
        initial_obs=old_index[(name,'201/1000')]['observed']
        baseline=[exactsum(initial_obs['active'][c])+exactsum(initial_obs['upper'][c])+exactsum(initial_obs['R'][c]) for c in range(3)]
        channel_initial[name]=[str(v) for v in baseline]
        for mode in ('warm','coarse','cold'):
            directory=evidence/name/mode;traj=read(directory/'TRAJECTORY.json')
            all_trajectories[(name,mode)]=traj
            expected=['9/25'] if mode=='coarse' else ['7/25','9/25']
            assert [r['time'] for r in traj['rows']]==expected
            assert traj['fixture']==name and traj['initial_trajectory_advances']==traj['reference_evaluations']==0
            inputraw=(directory/'INPUT.json').read_bytes()
            assert inputraw==(old/f'{name}.resume.json').read_bytes()
            assert traj['input_sha256']==sha(inputraw) and traj['input_direct_bytes_equal'] is True
            assert traj['ledger']==summary['cost'][name][mode]
            for trow in traj['rows']:
                row=row_index[(name,mode,trow['time'])]
                assert all(row[k]==trow[k] for k in trow)
                original_row=old_index[(name,row['time'])]
                assert row['retained_reference64']==original_row['reference64']
                assert row['retained_warm_observed']==original_row['observed']
                assert set(row['observed'])==set(row['error'])==set(row['retained_reference64'])==KEYS
                for key in KEYS:
                    actual=row['observed'][key];ref=row['retained_reference64'][key];finite(actual);finite(ref)
                    err=row['error'][key]
                    vectors=[list(flat(x)) for x in (actual,ref,err['absolute'],err['relative_eligible'])]
                    assert len({len(x) for x in vectors})==1
                    for a,r,e,relative in zip(*vectors):
                        assert e==abs(a-r)
                        max_abs[key]=max(max_abs.get(key,0.),e)
                        if abs(r)>=FLOOR:
                            assert relative==e/abs(r)
                            max_rel[key]=max(max_rel.get(key,0.),relative);eligible+=1
                        else:assert relative is None;null+=1
                        count[(name,mode,key)]+=1;scalar_checks+=1
                    max_vs_old=max(max_vs_old,diff(actual,row['retained_warm_observed'][key]))
                obs=row['observed']
                physical=[exactsum(obs['active'][c])+exactsum(obs['upper'][c])+exactsum(obs['R'][c]) for c in range(3)]
                max_conservation=max(max_conservation,float(max(abs(a-b) for a,b in zip(physical,baseline))))
                max_firsthit_balance=max(max_firsthit_balance,float(max(abs(F.from_float(obs['M'][c][0])-
                     exactsum(obs['active'][c][1])-F.from_float(obs['upper'][c][2])-
                     F.from_float(obs['M'][c][1])-F.from_float(obs['R'][c][1])) for c in range(3))))
                max_r2m2=max(max_r2m2,max(abs(obs['R'][c][2]-obs['M'][c][1]) for c in range(3)))
                assert all(v>=0 for key in KEYS for v in flat(obs[key][0]))
                raw=(directory/trow['snapshot_name']).read_bytes();capsule=json.loads(raw)
                assert sha(raw)==trow['snapshot_sha256'] and canon(capsule)==raw
                assert sha(canon(capsule['state']))==capsule['sha256']
                state=capsule['state'];assert fraction(state['time'])==F(row['time'])
                for key in ('active','upper','M','H','A'):
                    shape,data=decode(state[key]);assert data==list(flat(obs[key]))
                assert state['operator']=='finite-exponential-flux-packets-v1'
                assert state['physics_id']==initial_state['physics_id']
                assert len(state['pending'])<=128
                for p in state['pending']:
                    assert p['kind']=='flux' and type(p['target']) is int and type(p['origin']) is int
                    assert p['target']==p['origin']+1 and 1<=p['target']<=3
                    assert fraction(state['time'])<=fraction(p['start'])<fraction(p['end'])
                    ash,alpha=decode(p['alpha']);gsh,g=decode(p['generator']);osh,o=decode(p['output'])
                    k=osh[0];assert ash==[3,k] and gsh==[k,k] and k<=64
                    assert min(alpha[:k])>=0 and min(o)>=0
                    assert all(g[i*k+j]>=0 for i in range(k) for j in range(k) if i!=j)
                snapshots[str((directory/trow['snapshot_name']).relative_to(evidence))]={
                    'canonical_checksum_valid':True,'hex_state_equals_observed':True,'packet_count':len(state['pending']),
                    'sha256':sha(raw),'time':row['time']}
            # All six input raw capsules independently match their immutable
            # original; the warm/cold pairwise checks below include two inputs.
            assert sha(inputraw)==before[str((directory/'INPUT.json').relative_to(evidence))]['sha256']
        guard=read(evidence/name/'cold/GUARD.json')
        assert guard['before']==guard['after']==summary['before'] and guard['unchanged'] is True
        for label in ('INPUT','STATE-028','STATE-036'):
            warm=evidence/name/'warm'/(label+'.json');cold=evidence/name/'cold'/(label+'.json')
            aa,bb=warm.read_bytes(),cold.read_bytes();assert aa==bb
            actual={'byte_equal':True,'warm_sha256':sha(aa),'cold_sha256':sha(bb)}
            assert actual==summary['comparisons'][name]['direct_cold_fullraw'][label]
            rawpairs.append({'fixture':name,'label':label,'bytes_each':len(aa),**actual})
        warmraw=(evidence/name/'warm/STATE-036.json').read_bytes()
        oldraw=(old/f'{name}.final.json').read_bytes()
        assert warmraw==oldraw
        assert summary['comparisons'][name]['new_warm_final_matches_retained_original_warm_bytes'] is True
        warmlast=all_trajectories[(name,'warm')]['rows'][-1]['observed']
        coarselast=all_trajectories[(name,'coarse')]['rows'][-1]['observed']
        schedule={k:diff(warmlast[k],coarselast[k]) for k in KEYS}
        assert schedule==summary['comparisons'][name]['fine_coarse_max_abs']
        assert summary['comparisons'][name]['fine_coarse_full_vectors_retained'] is True
        coarse_state=json.loads((evidence/name/'coarse/STATE-036.json').read_text())['state']
        assert all(decode(coarse_state[k])[1]==list(flat(coarselast[k])) for k in ('active','upper','M','H','A'))
        comparisons[name]={'recomputed_fullvector_schedule_errors':schedule,
                           'coarse_state_raw_retained_and_hex_verified':True,
                           'new_warm_final_directly_equals_old_warm_raw':True,
                           'warm_coarse_packet_partition_counts':[
                               snapshots[f'{name}/warm/STATE-036.json']['packet_count'],
                               snapshots[f'{name}/coarse/STATE-036.json']['packet_count']]}
    assert len(rawpairs)==6 and len(snapshots)==10
    assert scalar_checks==570 and (eligible,null)==(510,60)
    assert eligible==summary['eligible_scalar_rows'] and null==summary['ineligible_relative_scalar_rows']
    assert max_abs==summary['max_abs_against_retained_reference'] and max_rel==summary['max_relative_eligible_diagnostic']
    max_schedule=max(v for item in comparisons.values() for v in item['recomputed_fullvector_schedule_errors'].values())
    assert summary['finite_absolute_check_passed']==all(v<=TOL for v in max_abs.values())
    assert summary['schedule_fullraw_check_passed']==(max_schedule<=TOL)
    assert max(max_conservation,max_firsthit_balance,max_r2m2)<=TOL
    expm=sum(c['expm_calls'] for modes in summary['cost'].values() for c in modes.values())
    segments=sum(c['segments'] for modes in summary['cost'].values() for c in modes.values())
    assert (expm,segments)==(284,28)
    for modes in summary['cost'].values():
        for c in modes.values():assert c['maximum']==100 and c['expm_calls']<=100 and c['segments']<=20
    assert all(summary[k]==0 for k in ('reference_evaluations','initial_trajectory_advances','old72_kernel_replays','torch','training'))
    assert summary['admission']=='HOLD_NO_GO' and summary['all_closed'] is False
    after={name:{'bytes':len(p.read_bytes()),'sha256':sha(p.read_bytes()),'git_blob':blob(p.read_bytes())} for name,p in paths.items()}
    source_after={p:sha((root/p).read_bytes()) for p in source_before}
    inputs_after={p:sha((root/p).read_bytes()) for p in inputs_before}
    assert before==after and source_before==source_after and inputs_before==inputs_after
    costpath=Path(__file__).with_name('cost-review')/'REVIEW.json'
    costreceipt=read(costpath)
    result={
      'identity':'independent-saved-fullraw-arithmetic-review-v1','artifact_commit':COMMIT,'source_freeze_commit':SOURCE,
      'method':'stdlib JSON/hex/SHA/Git-blob comparison, saved-array scalar arithmetic and exact rational balances only',
      'reproduction':'python review_saved.py --root /path/to/checkout --output /tmp/review; GIT_INVENTORY.json and cost-review/REVIEW.json accompany the script',
      'git_artifacts_matched':33,'summary_artifacts_matched':29,'artifacts_before':before,'artifacts_after':after,
      'source_sha256_before':source_before,'source_sha256_after':source_after,
      'input_sha256_before':inputs_before,'input_sha256_after':inputs_after,
      'query_rows':10,'scalar_error_checks':scalar_checks,'eligible_scalar_rows':eligible,'relative_null_rows':null,
      'floor':FLOOR,'tolerance':TOL,'max_abs_against_retained_reference':max_abs,
      'max_relative_eligible_diagnostic':max_rel,'max_fine_coarse_fullvector_difference':max_schedule,
      'max_new_observation_difference_from_original_warm':max_vs_old,
      'six_direct_raw_pairs':rawpairs,'snapshots_hex_checked':snapshots,'comparisons':comparisons,
      'channel_totals_at_input':channel_initial,'max_exact_conservation_residual_from_input':max_conservation,
      'max_firsthit_current_state_balance_residual':max_firsthit_balance,'max_R2_M2_residual':max_r2m2,
      'retained_candidate_expm':expm,'retained_candidate_segments':segments,
      'retained_reference_evaluations':0,'retained_initial_trajectory_advances':0,'retained_old72_replays':0,
      'cost_review':{'sha256':sha(costpath.read_bytes()),'receipt':costreceipt},
      'reviewer_candidate_calls':0,'reviewer_reference_calls':0,'reviewer_expm_calls':0,'reviewer_quadratures':0,
      'findings':[],
      'scope':'new .201-to-.36 finite continuation from retained state; no repair/reconstruction of missing old#6249 cold/coarse raw',
      'limitations':['The retained GL64 reference is reused without new reference evaluations; shared-backend roundoff is not certified.',
                     'Fullstate restore observation is limited to the two finite fixtures and three independent linear channels.',
                     'No continuum, large spatial profile, full network, training, gradient or production checkpoint qualification.',
                     '33CPU/45wall resource limits are frozen launcher configurations; retained getrlimit values were not separately recorded.'],
      'admission':'HOLD_NO_GO','all_closed':False,'reviewer_source_sha256':sha(Path(__file__).read_bytes())
    }
    raw=(json.dumps(result,indent=2,allow_nan=False)+'\n').encode();(out/'REVIEW.json').write_bytes(raw)
    print(json.dumps({'read_only':True,'git_artifacts':33,'source_files':10,'inputs':5,'rows':10,
                      'scalar_checks':570,'eligible':eligible,'null':null,'direct_raw_pairs':6,
                      'coarse_raw_files':2,'max_abs':max(max_abs.values()),'max_schedule':max_schedule,
                      'candidate_expm_retained':expm,'candidate_segments_retained':segments,
                      'new_candidate_calls':0,'new_reference_calls':0,'new_expm_calls':0,
                      'review_sha256':sha(raw),'admission':'HOLD_NO_GO'}))

if __name__=='__main__':main()
