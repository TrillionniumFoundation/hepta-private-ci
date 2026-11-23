"""Read captured prints as partial orders on the single test-process clock."""
import argparse
import collections
import hashlib
import json
import re
from zipfile import ZipFile

parser=argparse.ArgumentParser()
parser.add_argument('archive')
args=parser.parse_args()
stamp=r'(\d+)'
scope=re.compile(r'Q24_CLOCK case=(\w+) pid=(\d+) thread=ThreadId\((\d+)\) role=(\w+) id=(\d+) cut=(\d+) io=(\w+) depth=(\d+) bound=(\w+) deadline=(\d+) points=([^\s]+)')
stage=re.compile(r'Q24_STAGE case=(\w+) pid=(\d+) thread=ThreadId\((\d+)\) layer=(\w+) tag=(\d+)((?: \w+=\d+)+)')
bound=re.compile(r'Q24_BOUND case=(\w+) pid=(\d+) thread=ThreadId\((\d+)\) layer=(\w+) tag=(\d+) start=(\d+) bound=(\w+) deadline=(\d+)')
name_re=re.compile(r'^test (\S+::(?:original_next_use_evidence_timing_diagnostic|q24_next_use_command_healthy_evidence_readback_then_publication_withdrawal)) \.\.\. (ok|FAILED)$',re.M)
cases={'healthy':'q24_next_use_command_healthy_evidence_readback_then_publication_withdrawal','timing':'original_next_use_evidence_timing_diagnostic'}
ordered=lambda v: all(i<=j for i,j in zip(v,v[1:]))
with open(args.archive,'rb') as f:
    assert hashlib.sha256(f.read()).hexdigest()=='4f43ffedc4a4843c9396456944ac00b476f0b1b7ab97e3f0524555a514000026'
with ZipFile(args.archive) as z:
    root=next(n[:-len('record.json')] for n in z.namelist() if n.endswith('/record.json'))
    report=json.loads(z.read(root+'record.json'))
    code=int(z.read(root+'exit.txt'))
    src=z.read(root+'ref.txt').decode().strip()
    assert src=='910fee9b64cafdf1da406b815d64e51f7c32fc20'
    assert {v['id']['shard'] for v in report['bep_results']}=={1,2,3,4}
    assert all(not r['result'].get('cachedLocally') and not r['result'].get('executionInfo',{}).get('cachedRemotely') for r in report['bep_results'])
    assert all(r['result']['executionInfo']['strategy']=='remote' for r in report['bep_results'])
    summaries={};flags={};collected={key:dict(stages=[],scopes=[],bounds=[]) for key in cases}
    for sh in range(1,5):
        path=f'logs/shard_{sh}_of_4/test.log';data=z.read(root+path)
        row=next(i for i in report['outputs'] if i['path']==path)
        assert hashlib.sha256(data).hexdigest()==row['sha256']
        txt=data.decode(errors='replace')
        summary=re.findall(r'^test result: (?:ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;',txt,re.M)
        assert summary,sh
        summaries[sh]=[int(x) for x in summary[-1]]
        for n,v in name_re.findall(txt):flags[n.rsplit('::',1)[-1]]=dict(shard=sh,outcome=v)
        for c,p,t,layer,tag,s in stage.findall(txt):
            pts={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',s)}
            assert ordered(list(pts.values()))
            collected[c]['stages'].append(dict(pid=int(p),thread=int(t),layer=layer,tag=int(tag),p=pts,shard=sh))
        for c,p,t,l,tag,start,kind,deadline in bound.findall(txt):
            collected[c]['bounds'].append(dict(pid=int(p),thread=int(t),layer=l,tag=int(tag),start=int(start),kind=kind,deadline=int(deadline)))
        for c,p,t,role,i,cut,io,d,b,dt,events in scope.findall(txt):
            seq=[(k,int(v)) for k,v in re.findall(r'(\w+)@(\d+)',events)]
            assert len(seq)>=2 and ordered([v for k,v in seq]) and seq[0][0]=='enter' and seq[-1][0]=='exit'
            collected[c]['scopes'].append(dict(pid=int(p),thread=int(t),role=role,id=int(i),cut=int(cut),io=io,depth=int(d),bound=b,deadline=int(dt),events=seq))
assert set(flags)==set(cases.values())
result={'head':src,'bazel_exit':code,'shard_counts_pass_fail_ignore_measured_filtered':summaries,'focus_outcomes':flags,'cases':{}}
total=lambda i:sum(v[i] for v in summaries.values())
assert total(0)+total(1)==1552 and total(2)==171
for c,case_name in cases.items():
    data=collected[c];stages=data['stages'];scopes=data['scopes'];bounds=data['bounds']
    pidset={s['pid'] for col in (stages,scopes,bounds) for s in col}
    assert len(pidset)==1 and scopes and bounds
    assert {s['shard'] for s in stages}=={flags[case_name]['shard']}
    clients=sorted([s for s in stages if s['layer']=='evidence_client' and s['tag']==1],key=lambda s:s['p']['start'])
    assert clients
    records=[]
    for index,client in enumerate(clients,1):
        x,y=client['p']['start'],client['p']['end']
        matched=[s for s in stages if s['layer']=='transport' and s['thread']==client['thread'] and x<=s['p']['start']<=s['p']['end']<=y]
        assert len(matched)<=1
        row=dict(index=index,meaning='initial healthy read' if index==1 else 'after explicit withdrawal',caller_us=y-x,client_points=client['p'])
        if not matched:
            row['observation']='no unique transport entered';records.append(row);continue
        p=matched[0]['p'];v=[b for b in bounds if b['thread']==client['thread'] and b['start']==p['start'] and b['layer']=='transport'];assert len(v)==1
        row.update(transport_bound=v[0],outer_points=p)
        selected=[m for m in ('pre_select_expired','deadline_fired','select_root_readable','select_frame_error','select_frame_ok') if m in p]
        assert len(selected)==1, selected
        row['outer_selection']=selected[0]; row['post_decode_expired']='post_decode_expired' in p
        outer=[s for s in scopes if s['role']=='nextuse_service' and s['io']=='exchange' and s['depth']==1 and 'handler_enter' in dict(s['events']) and x<=dict(s['events'])['handler_enter']<=y]
        assert len(outer)<=1
        if outer:
            outer=outer[0]; se=dict(outer['events']);lo=se['handler_enter'];hi=se['exit']
            row['matched_outer_server']=outer
            selection_at=p[selected[0]]
            if 'shutdown_enter' in se and 'shutdown_return' in se:
                if se['shutdown_return']<selection_at: order='service shutdown returned before outer selection'
                elif selection_at<se['shutdown_enter']: order='outer selection before service shutdown began'
                else: order='overlapping syscall interval or microsecond tie'
            else: order='no shutdown bracket on this exact outer service operation'
            row['direct_order']=order
            exercised=[]
            for s in scopes:
                pts=dict(s['events'])
                if s['role'] in ('published_service','published_client','selector_service') and s['depth']==1 and lo<=pts.get('handler_enter',pts['enter'])<=hi:
                    if s['io']=='request' or 'handler_enter' in pts:
                        exercised.append(s)
            row['nested_operations']=sorted(exercised,key=lambda s:dict(s['events']).get('handler_enter',dict(s['events'])['enter']))
            row['published_service_pairs']=[[s['cut'],s['id']] for s in row['nested_operations'] if s['role']=='published_service' and s['io']=='exchange']
            if index==1 and 'authenticated' in client['p']:
                expected_pairs={'healthy': [[4, 4], [3, 8], [3, 9], [4, 5], [3, 10], [3, 11]], 'timing': [[4, 6], [3, 12], [3, 13], [4, 7], [3, 14], [3, 15]]}
                assert row['published_service_pairs']==expected_pairs[c],row['published_service_pairs']
        else:
            row['direct_order']='outer service entry unobserved in caller interval'
        if outer:
            window_lo,window_hi=row['client_points']['start'],row['outer_points'][selected[0]]
            owner_rows=[]
            for operation in row['nested_operations']:
                if operation['role']!='published_service' or operation['io']!='exchange':
                    continue
                e=dict(operation['events']); h_start=e['handler_enter']; h_end=e['exit']
                matches=[s for s in stages if s['layer']=='published_owner' and s['tag']==operation['cut']
                         and s['thread']==operation['thread'] and h_start<=s['p']['start']<=s['p']['end']<=h_end]
                assert len(matches)==1
                o=matches[0]['p']
                assert not owner_rows or owner_rows[-1]['points']['end']<=o['start']
                positive='reply_written' in e
                before_selection=max(0,min(window_hi,o['end'])-max(window_lo,o['start']))
                owner_rows.append({'cut':operation['cut'],'id':operation['id'],'points':o,
                                   'full_span_us':o['end']-o['start'],'inside_caller_until_selection_us':before_selection,
                                   'service_replied':positive,'last_completed_marker':list(o)[-2]})
            row['published_owner_spans']=owner_rows
            row['six_original_owner_us']=sum(o['full_span_us'] for o in owner_rows)
            row['owner_us_inside_caller_until_selection']=sum(o['inside_caller_until_selection_us'] for o in owner_rows)
            row['outer_timer_lateness_us']=p['deadline_fired']-v[0]['deadline'] if 'deadline_fired' in p else None
            row['outer_service_shutdown_after_selection_us']=se.get('shutdown_enter')-selection_at if 'shutdown_enter' in se else None
        records.append(row)
    result['cases'][c]={'pid':pidset.pop(),'stage_rows':len(stages),'scope_rows':len(scopes),'bound_rows':len(bounds),'calls':records}
assert total(0)==1550 and total(1)==2 and code!=0
expected={'healthy':[[4,4],[3,8],[3,9],[4,5],[3,10],[3,11]],'timing':[[4,6],[3,12],[3,13],[4,7],[3,14],[3,15]]}
for c,v in result['cases'].items():
    assert len(v['calls'])==1 and flags[cases[c]]['outcome']=='FAILED'
    r=v['calls'][0]
    assert r['published_service_pairs']==expected[c]
    assert r['outer_selection']=='deadline_fired' and r['transport_bound']['kind']=='per_request'
    assert r['direct_order']=='outer selection before service shutdown began'
    six=r['published_owner_spans']
    assert [o['service_replied'] for o in six]==([True]*5+[False] if c=='healthy' else [True]*6)
    if c=='healthy':
        assert six[-1]['last_completed_marker']=='decision'
        req11=next(x for x in r['nested_operations'] if x['role']=='published_service' and x['id']==11)
        e=dict(req11['events']); assert e['original_handler_error']>r['outer_points']['deadline_fired'] and e['shutdown_return']>=e['shutdown_enter']
    else:
        e=dict(r['matched_outer_server']['events'])
        assert e['handler_ok']<=e['clock_expired']<=e['shutdown_enter'] and 'err_deadline_elapsed' in e
print(json.dumps(result,indent=2,sort_keys=True))
