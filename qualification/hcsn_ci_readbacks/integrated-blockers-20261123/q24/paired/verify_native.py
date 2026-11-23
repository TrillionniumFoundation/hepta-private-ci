"""Read the original job artifact independently and bind every attempted case and timing."""
import argparse
from pathlib import Path
import hashlib
import json
from statistics import median
import re
from zipfile import ZipFile

ap=argparse.ArgumentParser()
ap.add_argument('archive',type=Path)
args=ap.parse_args()
digest=lambda b:hashlib.sha256(b).hexdigest()
with ZipFile(args.archive) as archive:
    read=archive.read
    res=json.loads(read('results.json'))
    assert res['source']=={'base':'6a5a02835206697d154fc4a1977b4627aad372d9','candidate':'53a2877f11a550ec4fca694bacc5b449f20addc2'}
    assert read('tests-'+res['source']['base']+'.txt')==read('tests-'+res['source']['candidate']+'.txt')
    sha={arm:re.findall(r'^([0-9a-f]{64}) ',read('binary-'+arm+'.txt').decode(),re.M)[0] for arm in res['source']}
    assert sha['base']!=sha['candidate']
    rows=[]
    for i,t in enumerate(res['attempts']):
        a=t['arm']; label=t['label']
        body=read(f'{label}-{a}.log'); s=body.decode()
        assert digest(body)==t['log_sha256']
        summ=re.search(r'^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored;',s,re.M)
        assert summ and int(summ[4])==0 and ((summ[1]=='ok')==(t['returncode']==0))
        row={'arm':a,'label':label,'passed':int(summ[2]),'failed':int(summ[3]),'log_sha256':digest(body)}
        if label=='owners':
            cases=dict(re.findall(r'^test (\S+) \.\.\. (ok|FAILED)$',s,re.M))
            assert len(cases)==13 and len(t['cases'])==13
            for case, verdict in cases.items(): assert (verdict=='ok')==t['cases'][case.split('::')[-1]]
            row['cases']={case.split('::')[-1]:verdict for case,verdict in cases.items()}
        else:
            call=re.search(r'LEARN_FDE_C_TIMING evidence_readback_elapsed_us=(\d+) result=([^\n]+)',s)
            assert (int(call[1]) if call else None)==t['evidence_us']
            if call: assert call[2]==t['evidence_status']
            row.update(evidence_us=t['evidence_us'],evidence_status=t['evidence_status'])
            if call:
                later=s.split('LEARN_FDE_C_TIMING command_readback_elapsed_us=',1)[1]
                phys=[(int(req),int(cut),int(owner),int(handler)) for req,cut,owner,handler in re.findall(r'HEPTA_PUBLISHED_ORIGINAL_READ request_id=(\d+) cut_receipts=(\d+) owner_io_us=(\d+) total_handler_us=(\d+)',later)]
                if call[2]=='Ok(())': assert [(r,c) for r,c,_,_ in phys]==[(6,4),(12,3),(13,3),(7,4),(14,3),(15,3)]
                row.update(original_calls=phys,owner_total_us=sum(x[2] for x in phys),handler_total_us=sum(x[3]for x in phys))
                row['terminals']=dict(re.findall(r'LEARN_FDE_C_TIMING (\w+_terminal)=(.*)',later))
        rows.append(row)
    assert len(rows)==22
    assert sorted({t['label'] for t in rows if t['label'].startswith('solo')})==[f'solo-pair-{i:02}' for i in range(1,7)]
    assert sorted({t['label'] for t in rows if t['label'].startswith('two-way')})==[f'two-way-pair-{p}-{i}' for p in (1,2) for i in(1,2)]
    lookup={(x['label'],x['arm']):x for x in rows}
    summary={}
    for mode in ('solo','two-way'):
        arms={}
        for arm in res['source']:
            group=[t for t in rows if t['label'].startswith(mode) and t['arm']==arm]
            timings=[t['evidence_us'] for t in group if t['evidence_us'] is not None]
            arms[arm]={'attempts':len(group),'passes':sum(t['passed'] for t in group),'actual_call_us':[t['evidence_us'] for t in group],
                       'median_us':median(timings) if timings else None,'min_us':min(timings) if timings else None,'max_us':max(timings) if timings else None}
        summary[mode]=arms
    pairs=[]
    for i in range(1,7):
        l=f'solo-pair-{i:02}'
        x=lookup[l,'base']['evidence_us'];y=lookup[l,'candidate']['evidence_us']
        pairs.append(y-x if x is not None and y is not None else None)
    comparable=[v for v in pairs if v is not None]
    summary['solo_candidate_minus_base_us']=pairs
    summary['candidate_shorter_pairs']=sum(v<0 for v in comparable)
    summary['median_paired_change_us']=median(comparable) if comparable else None
    print(json.dumps({'archive_sha256':digest(args.archive.read_bytes()),'sources':res['source'],'binary_sha256':sha,
                      'fixture_deadline_ms':500,'benchmark':'same VM Linux musl, individual libtest executable, solo and two concurrent process groups','arms':summary,'rows':rows},indent=2))
