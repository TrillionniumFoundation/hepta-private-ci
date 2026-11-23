"""Read native per-thread CPU and wall observations for the original Q24 cases."""
from collections import defaultdict
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

archive=Path(sys.argv[1]); head="c25cf4146572501427cc35f1c03f4d585c1c4758"
if hashlib.sha256(archive.read_bytes()).hexdigest()!="72f7baef7dae44c669480b082d19e2b3f0232dadabc98f7ab8f056d35ba4cd6d":
    raise ValueError("native archive SHA-256 differs")
scope=re.compile(r'Q24_CLOCK case=(\w+) pid=(\d+) thread=ThreadId\((\d+)\) role=(\w+) id=(\d+) cut=(\d+) io=(\w+) depth=(\d+) bound=(\w+) deadline=(\d+) points=([^\s]+)')
stage=re.compile(r'Q24_STAGE case=(\w+) pid=(\d+) thread=ThreadId\((\d+)\) layer=(\w+) tag=(\d+)((?: \w+=\d+)+)')
prof=re.compile(r'Q24_OWNER case=(\w+) pid=(\d+) thread=ThreadId\((\d+)\) id=(\d+) cut=(\d+) wall_ns=(\d+) cpu_ns=(\d+) bad=(\d+) metrics=([^\s]*) errors=([^\s]*)')
names={'healthy':'q24_next_use_command_healthy_evidence_readback_then_publication_withdrawal',
       'timing':'original_next_use_evidence_timing_diagnostic'}
tables={c:{'stages':[],'scope':[],'owners':{}} for c in names}
summary={};focus={}
with ZipFile(archive) as z:
    prefix=next(n[:-len('record.json')] for n in z.namelist() if n.endswith('/record.json'))
    assert z.read(prefix+'ref.txt').decode().strip()==head
    r=json.loads(z.read(prefix+'record.json'))
    inputs=z.read(prefix+'observed-inputs.json')
    assert hashlib.sha256(inputs).hexdigest()=='3dbabbc6cf471b233c7d844f19d5cdae1f0bd5f1c48d01ae4972f5ab520382cd'
    fixtures=z.read(prefix+'fixture-blobs.txt').decode().splitlines()
    assert fixtures==[
        '100644 blob 9ba3e56e20679f2b918149c7847c49dcb9ea1902\tcodex-rs/hepta-agentd/BUILD.bazel',
        '100644 blob 5b5fbad6edc0e815231b89341c170d35af5e7383\tcodex-rs/hepta-agentd/src/circuit_next_use_command_owner_tests.rs',
    ]
    assert len(r['outputs'])==8 and len(r['bep_results'])==4
    for obj in r['outputs']:
        data=z.read(prefix+obj['path'])
        assert (len(data),hashlib.sha256(data).hexdigest())==(obj['bytes'],obj['sha256'])
        if obj['path'].endswith('.xml'):ET.fromstring(data)
    code=int(z.read(prefix+'exit.txt'))
    assert r['bazel_status']==code
    assert {b['id']['shard'] for b in r['bep_results']}=={1,2,3,4}
    for b in r['bep_results']:
        assert b['id']['run']==b['id']['attempt']==1 and b['id']['label']=='//codex-rs/hepta-agentd:hepta-agentd-unit-tests'
        execinfo=b['result']['executionInfo']
        assert execinfo['strategy']=='remote' and not execinfo.get('cachedRemotely') and not b['result'].get('cachedLocally')
    for sh in range(1,5):
        rel=f'logs/shard_{sh}_of_4/test.log';raw=z.read(prefix+rel)
        assert next(o['sha256'] for o in r['outputs'] if o['path']==rel)==hashlib.sha256(raw).hexdigest()
        txt=raw.decode(errors='replace')
        rows=re.findall(r'^test result: (?:ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;',txt,re.M)
        assert rows;summary[sh]=list(map(int,rows[-1]))
        for c,name in names.items():
            observed=re.findall(r'^test \S*::'+name+r' \.\.\. (ok|FAILED)$',txt,re.M)
            if observed: assert len(observed)==1;focus[c]=dict(outcome=observed[0],shard=sh)
        for c,p,t,l,tag,body in stage.findall(txt):
            pts={name:int(at) for name,at in re.findall(r'(\w+)=(\d+)',body)}
            tables[c]['stages'].append(dict(pid=int(p),thread=int(t),layer=l,tag=int(tag),points=pts))
        for c,p,t,role,i,cut,io,d,b,deadline,events in scope.findall(txt):
            ev={k:int(v) for k,v in re.findall(r'(\w+)@(\d+)',events)}
            tables[c]['scope'].append(dict(pid=int(p),thread=int(t),role=role,id=int(i),cut=int(cut),io=io,depth=int(d),bound=b,deadline=int(deadline),events=ev))
        for c,p,t,i,cut,wall,cpu,bad,metrics,errors in prof.findall(txt):
            key=(int(p),int(t),int(i),int(cut)); assert key not in tables[c]['owners']
            assert int(bad)==0 and int(wall)>0 and int(cpu)>0
            obs={}; failures=[]
            for name,count,elapsed,consumed,failed in re.findall(r'([\w.]+):(\d+):(\d+):(\d+):(\d+),',metrics):
                assert name not in obs and int(count)>0
                obs[name]=[int(count),int(elapsed),int(consumed),int(failed)]
            for name,reason,at in re.findall(r'([\w.]+):([\w]+):(\d+),',errors):
                assert name in obs and obs[name][3]>0
                failures.append([name,reason,int(at)])
            assert sum(v[3] for v in obs.values())==len(failures)
            tables[c]['owners'][key]=dict(id=key[2],cut=key[3],wall_ns=int(wall),cpu_ns=int(cpu),metrics=obs,errors=failures)
assert set(focus)==set(names) and sum(v[0]+v[1] for v in summary.values())==1552 and sum(v[2] for v in summary.values())==171
for b in r['bep_results']:
    assert b['result']['status']==('FAILED' if summary[b['id']['shard']][1] else 'PASSED')
assert (code==0)==all(not row[1] for row in summary.values())
answer={'bazel_exit':code,'source':head,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'shards_pass_fail_ignored_measured_filtered':summary,'focus':focus,'cases':{}}
for c,d in tables.items():
    stages,scopes,owners=d['stages'],d['scope'],d['owners'];assert owners
    clients=sorted((s for s in stages if s['layer']=='evidence_client' and s['tag']==1),key=lambda s:s['points']['start'])
    assert clients and len({s['pid'] for s in stages+scopes})==1
    reports=[]
    for idx,client in enumerate(clients,1):
        lo=client['points']['start'];hi=client['points']['end'];pid=client['pid']
        transport=[s for s in stages if s['pid']==pid and s['layer']=='transport' and s['thread']==client['thread'] and lo<=s['points']['start']<=s['points']['end']<=hi]
        assert len(transport)<=1
        report={'client_index':idx,'caller_us':hi-lo,'authenticated':'authenticated' in client['points'],'owner_calls':[]}
        if transport: report['outer_transport']=transport[0]['points']
        servers=[s for s in scopes if s['pid']==pid and s['role']=='nextuse_service' and s['io']=='exchange' and s['depth']==1
                 and lo<=s['events'].get('handler_enter',-1)<=hi]
        assert len(servers)<=1
        if servers:
            report['outer_server']=servers[0]
            start=servers[0]['events']['handler_enter'];end=servers[0]['events']['exit']
            inner=sorted((s for s in scopes if s['pid']==pid and s['role']=='published_service' and s['io']=='exchange' and s['depth']==1 and
                          start<=s['events'].get('handler_enter',-1)<=end),key=lambda s:s['events']['handler_enter'])
            total=defaultdict(lambda:[0,0,0,0]); wall_sum=cpu_sum=0
            for s in inner:
                k=(s['pid'],s['thread'],s['id'],s['cut']);a=owners.get(k)
                if a is None:
                    report['owner_calls'].append({'cut':s['cut'],'id':s['id'],'owner_not_entered':True});continue
                a=dict(a,service_replied='reply_written' in s['events'])
                report['owner_calls'].append(a)
                wall_sum+=a['wall_ns'];cpu_sum+=a['cpu_ns']
                for key,vals in a['metrics'].items():
                    for j,n in enumerate(vals):total[key][j]+=n
            if total:
                report['owner_wall_ns']=wall_sum;report['owner_cpu_ns']=cpu_sum
                report['owner_wall_minus_cpu_ns']=wall_sum-cpu_sum
                report['totals_count_wall_ns_cpu_ns_errors']=dict(total)
            if idx==1:
                expected=[[4,4],[3,8],[3,9],[4,5],[3,10],[3,11]] if c=='healthy' else [[4,6],[3,12],[3,13],[4,7],[3,14],[3,15]]
                actual=[[row['cut'],row['id']] for row in report['owner_calls']]
                assert actual==expected[:len(actual)]
                if report['authenticated']:
                    assert actual==expected and all(row['service_replied'] for row in report['owner_calls'])
        reports.append(report)
    answer['cases'][c]={'owner_profiles_in_whole_case':len(owners),'calls':reports}
print(json.dumps(answer,indent=2,sort_keys=True))
