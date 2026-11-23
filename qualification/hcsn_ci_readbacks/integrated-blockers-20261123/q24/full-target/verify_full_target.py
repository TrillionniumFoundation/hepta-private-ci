"""Join every native case and all four BEP shard actions to the previous source-pinned --list."""
from pathlib import Path
import argparse, hashlib, json, re, zipfile

ap=argparse.ArgumentParser()
ap.add_argument("archive",type=Path)
ap.add_argument("--roster",type=Path,default=Path(__file__).with_name("native.zip"))
a=ap.parse_args()
H=lambda b:hashlib.sha256(b).hexdigest()
def output_roster(z,arm):
    return {x.decode() for x in re.findall(rb"^(.+): test$",z.read("list-"+arm+".txt"),re.M)}
def shard_for(name):
    h=2166136261
    for c in name.encode(): h=((h^c)*16777619)&0xffffffff
    return h%4+1
timing_case='original_next_use_evidence_timing_diagnostic'
fixture_healthy='q24_next_use_command_healthy_evidence_readback_then_publication_withdrawal'
def timing(s):
    headers=list(re.finditer(r"^---- (\S+) stdout ----$",s,re.M))
    for n,m in enumerate(headers):
        if m[1].split('::')[-1]!=timing_case:continue
        txt=s[m.end():headers[n+1].start() if n+1<len(headers) else None]
        cut=re.search(r'command_readback_elapsed_us=(\d+) result=([^\n]+)',txt)
        caller=re.search(r'evidence_readback_elapsed_us=(\d+) result=([^\n]+)',txt)
        if not (cut and caller):return {'partial_failure':True}
        after=txt[cut.end():]
        reads=[list(map(int,v)) for v in re.findall(r'HEPTA_PUBLISHED_ORIGINAL_READ request_id=(\d+) cut_receipts=(\d+) owner_io_us=(\d+) total_handler_us=(\d+)',after)]
        return {'command_us':int(cut[1]),'command_status':cut[2], 'caller_us':int(caller[1]),'caller_status':caller[2],
                'original_owner_rows':reads,'owner_total_us':sum(v[2] for v in reads),'handler_total_us':sum(v[3] for v in reads),'terminals':dict(re.findall(r'LEARN_FDE_C_TIMING (\w+_terminal)=(.*)',after))}
    return None
def basic(r):
    return {k:r[k] for k in ('status','testAttemptDurationMillis','testAttemptDuration','testAttemptStartMillisEpoch','testAttemptStart','cachedLocally','executionInfo') if k in r}
with zipfile.ZipFile(a.roster) as z, zipfile.ZipFile(a.archive) as f:
    def p(name): return f.read(name)
    arms={}
    for arm in ('base','candidate'):
        roster=output_roster(z,arm)
        expected=sorted(roster)
        assert len(roster)==1723
        ev=[json.loads(line) for line in p(arm+'/test-events.jsonl').splitlines()]
        targets=[e for e in ev if 'testResult' in e]
        assert {e['id']['testResult']['label'] for e in targets}=={'//codex-rs/hepta-agentd:hepta-agentd-unit-tests'}
        sh={e['id']['testResult']['shard']:e for e in targets}
        assert sorted(sh)==[1,2,3,4] and len(targets)==4
        observed={}
        rows=[]
        counts=dict(ok=0,FAILED=0,ignored=0)
        for num,e in sorted(sh.items()):
            ident=e['id']['testResult']
            assert ident['attempt']==1 and ident['run']==1
            result=e['testResult']
            assert not result.get('cachedLocally') and not result.get('executionInfo',{}).get('cachedRemotely')
            raw=p(f'{arm}/logs/shard_{num}_of_4/test.log')
            log=raw.decode('utf-8',errors='replace')
            cases=dict(re.findall(r'^test (\S+) \.\.\. (ok|FAILED|ignored)\b',log,re.M))
            want={name for name in expected if shard_for(name)==num}
            nested={k:v for k,v in cases.items() if k not in want}
            assert not nested or nested=={'state::notes_objective::lock_tests::notes_objective_drain_child':'ok'}
            cases={k:v for k,v in cases.items() if k in want}
            unresolved=want-set(cases)
            for k in unresolved:
                assert f'test {k} ...' in log

            summ=re.findall(r'^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;',log,re.M)
            if nested:
                assert len(summ)==2 and tuple(map(int,summ[0][1:]))==(1,0,0,0,1722)
            else:
                assert len(summ)==1,(arm,num)
            summ=[summ[-1]]
            inferred={}
            if unresolved:
                assert len(unresolved)==1
                key=next(iter(unresolved))
                residual={v:int(summ[0][idx])-sum(actual==v for actual in cases.values()) for idx,v in enumerate(counts,1)}
                assert list(sorted(residual.values()))==[0,0,1]
                cases[key]=next(v for v,missing in residual.items() if missing==1)
                inferred[key]=cases[key]

            expected_counts=tuple([sum(v==k for v in cases.values()) for k in counts])
            assert expected_counts==tuple(map(int,summ[0][1:4]))
            assert int(summ[0][4])==0 and int(summ[0][5])+len(cases)==len(expected)
            for key,v in zip(counts,expected_counts):counts[key]+=v
            assert (summ[0][0]=='ok')==(result['status']=='PASSED')
            for item in result.get('testActionOutput',[]):
                if item.get('name')=='test.log' and item.get('digest'):
                    dig=item['digest']
                    if isinstance(dig,str) and re.fullmatch('[0-9a-f]{64}',dig):assert dig==H(raw)
            r={'shard':num,'attempt':ident['attempt'],'case_count':len(cases),'log_sha256':H(raw),'xml_sha256':H(p(f'{arm}/logs/shard_{num}_of_4/test.xml')),'action':basic(result),'counts':dict(zip(counts,expected_counts)),
               'failures':[k for k,v in cases.items() if v=='FAILED'],'nested_child_statuses':nested,'interleaved_label_resolved_from_unambiguous_outer_total':inferred}
            if num==shard_for(next(k for k in roster if k.endswith('::'+timing_case))):
                r['q24_current']=cases[next(k for k in cases if k.endswith('::'+timing_case))]
                r['q24_failure_timing']=timing(log)
            rows.append(r)
            observed.update(cases)
        arms[arm]={'ref':p(arm+'/ref.txt').decode().strip(),'bazel_return':int(p(arm+'/exit.txt')),
                  'roster_sha256':H(('\n'.join(sorted(observed))+'\n').encode()),'counts':counts,
                  'healthy_withdrawal':observed[next(k for k in observed if k.endswith('::'+fixture_healthy))],
                  'q24_timing_case':observed[next(k for k in observed if k.endswith('::'+timing_case))],
                  'shards':rows}
    assert arms['base']['roster_sha256']==arms['candidate']['roster_sha256']
    print(json.dumps({'archive_sha256':H(a.archive.read_bytes()),'list_source_archive':H(a.roster.read_bytes()),'scope':'Entire one target on original RBE strategy, same Actions orchestrator, fresh test actions. Unchanged default libtest concurrency; other repository targets absent. Successful libtest captures do not publish elapsed time for a successful individual case.','arms':arms},indent=2))
