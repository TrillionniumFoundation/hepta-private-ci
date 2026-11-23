"""Group nonoverlapping owner spans. All values are wall microseconds."""
import hashlib, json, re, sys
from pathlib import Path
from zipfile import ZipFile

root=Path(__file__).resolve().parent
current_path,prior_path=map(Path,sys.argv[1:3])
current=json.loads(current_path.read_bytes())
assert current['head']=='910fee9b64cafdf1da406b815d64e51f7c32fc20'
def group(rows):
    sums=dict(current=0,selection=0,observation=0,remaining_marks=0)
    for r in rows:
        ordered=['start','input1','decision','selection1','binding','stage_observation','input2','selection2','input3','end']
        prev='start'
        for field in ordered[1:]:
            if field not in r:continue
            dur=r[field]-r[prev];assert dur>=0
            name=('current' if field in ('input1','input2','input3') else
                  'selection' if field in ('selection1','selection2') or (field=='end' and prev=='decision') else
                  'observation' if field=='stage_observation' else 'remaining_marks')
            sums[name]+=dur;prev=field
    assert sum(sums.values())==sum(r['end']-r['start'] for r in rows)
    return sums
prior={}
with ZipFile(prior_path) as z:
    for case,sh in [('healthy',2),('timing',4)]:
        raw=z.read(f'observed/logs/shard_{sh}_of_4/test.log').decode()
        spans=[]
        pat=r'Q24_STAGE case='+case+r' pid=(\d+) thread=ThreadId\((\d+)\) layer=(\w+) tag=(\d+)((?: \w+=\d+)+)'
        for p,thread,l,t,s in re.findall(pat,raw):
            stamps={k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',s)}
            spans.append((l,int(t),stamps))
        outer=sorted([p for l,t,p in spans if l=='evidence_client' and t==1],key=lambda p:p['start'])[0]
        assert 'authenticated' in outer
        owners=sorted([p for l,t,p in spans if l=='published_owner' and outer['start']<=p['start']<=p['end']<=outer['end']],key=lambda p:p['start'])
        assert len(owners)==6 and all(b['start']>=a['end'] for a,b in zip(owners,owners[1:]))
        prior[case]={'outer_us':outer['end']-outer['start'],'owner_us':group(owners)}
red={}
for case,d in current['cases'].items():
    r=d['calls'][0];p=[v['points'] for v in r['published_owner_spans']]
    assert len(p)==6 and all(b['start']>=a['end'] for a,b in zip(p,p[1:]))
    se=dict(r['matched_outer_server']['events'])
    red[case]={'outer_us':r['caller_us'],'owner_us':group(p),'caller_elected_late_us':r['outer_timer_lateness_us'],
               'outer_service_posthandler_clock_late_us':(se['clock_expired']-r['matched_outer_server']['deadline']) if 'clock_expired' in se else None}
    assert sum(red[case]['owner_us'].values())==r['six_original_owner_us']
if len(sys.argv)>3:
    checkout=Path(sys.argv[3]);donor=json.loads((root/'parser-donor.json').read_bytes())
    for name,digest in donor['tested_files'].items():
        assert hashlib.sha256((checkout/name).read_bytes()).hexdigest()==digest,name
print(json.dumps({'green_control_zip_sha256':hashlib.sha256(prior_path.read_bytes()).hexdigest(),'historical_positive':prior,'current_reproduction':red},indent=2,sort_keys=True))
