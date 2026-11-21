"""Independent arithmetic reader: no Torch import, model, AD or optimizer calls."""
import hashlib
import json
from pathlib import Path
import resource
import statistics
import time

import numpy as np

ROOT=Path(__file__).resolve().parent
start_cpu,start_wall=time.process_time(),time.perf_counter()
protocol=json.loads((ROOT/'PROTOCOL_FROZEN.json').read_text())
for item in protocol['sources']:
    data=(ROOT/item['path']).read_bytes()
    assert len(data)==item['bytes'] and hashlib.sha256(data).hexdigest()==item['sha256']
result=json.loads((ROOT/'attempt001/RESULTS.json').read_text())
assert result['protocol_sha256']==hashlib.sha256((ROOT/'PROTOCOL_FROZEN.json').read_bytes()).hexdigest()
assert result['status']=='COMPLETE' and result['semantic_tolerance_passed'] is True
assert result['counters']['optimizer_calls']==result['counters']['checkpoint_writes']==0
all_rows=[]; npz_count=0; arrays=0; coordinates=0; mismatches=0; maximum=0.0
for arm in protocol['arms']:
    for seed in protocol['seeds']:
        folder=ROOT/'attempt001'/f'{arm}-s{seed}'
        unchanged=json.loads((folder/'UNCHANGED.json').read_text())
        checkpoint=ROOT/'originals/campaign/fits'/f'{arm}-s{seed}'/'selected.pt'
        assert unchanged['all_tensor_bytes_equal'] is True
        assert hashlib.sha256(checkpoint.read_bytes()).hexdigest()==unchanged['checkpoint_sha256']
        for recordpath in sorted(folder.glob('*.json')):
            if recordpath.name=='UNCHANGED.json':continue
            record=json.loads(recordpath.read_text());npz_count+=1
            with np.load(recordpath.with_suffix('.npz'),allow_pickle=False) as source:
                expected={'reference::'+r['key'] for r in record['rows']} | {'specialized::'+r['key'] for r in record['rows']}
                assert set(source.files)==expected
                for item in record['rows']:
                    a,b=source['reference::'+item['key']],source['specialized::'+item['key']]
                    assert a.shape==b.shape and a.dtype==b.dtype==np.dtype('float64')
                    assert np.isfinite(a).all() and np.isfinite(b).all()
                    delta=np.abs(a-b)
                    bound=protocol['absolute_tolerance']+protocol['relative_tolerance']*np.abs(a)
                    mx=float(np.max(delta,initial=0.0));bits=int(np.count_nonzero(a.view(np.uint64)!=b.view(np.uint64)))
                    assert item['shape']==list(a.shape) and item['coordinates']==a.size
                    assert item['max_abs']==mx and item['bitwise_mismatches']==bits
                    assert item['passed'] is True and np.all(delta<=bound)
                    arrays+=1;coordinates+=a.size;mismatches+=bits;maximum=max(maximum,mx)
            all_rows.append({'file':str(recordpath.relative_to(ROOT)),
                             'coordinates':sum(r['coordinates'] for r in record['rows']),
                             'passed':True})
timing=[]
for case in ['training64','synthetic1','synthetic20']:
    rows=[r for r in result['results'] if r['case']==case]
    assert len(rows)==6
    assert all(r['same_argmax'] and r['full']['passed'] and r['cold']['passed'] and r['gradient']['passed'] for r in rows)
    assert all(r['full_state_bytes']==r['specialized_full_state_bytes'] for r in rows)
    ref=[v for r in rows for v in r['timings'] if v['path']=='reference']
    opt=[v for r in rows for v in r['timings'] if v['path']=='specialized']
    assert len(ref)==len(opt)==18
    for kind in ['cpu_seconds','wall_seconds']:
        assert all(v[kind]>=0 for v in ref+opt)
    rc,sc=sum(v['cpu_seconds'] for v in ref),sum(v['cpu_seconds'] for v in opt)
    rw,sw=sum(v['wall_seconds'] for v in ref),sum(v['wall_seconds'] for v in opt)
    break_even=[]
    for r in rows:
        steps=20 if case=='synthetic20' else 10
        cc=next(c for c in result['compile_costs'] if c['fit']==r['fit'] and c['steps']==steps)
        saving=statistics.mean(v['wall_seconds'] for v in r['timings'] if v['path']=='reference')-statistics.mean(v['wall_seconds'] for v in r['timings'] if v['path']=='specialized')
        break_even.append(cc['wall_seconds']/saving if saving>0 else None)
    timing.append(dict(case=case,reference_wall_total=rw,specialized_wall_total=sw,
        wall_total_ratio=rw/sw,reference_cpu_total=rc,specialized_cpu_total=sc,cpu_total_ratio=rc/sc,
        specialized_zero_cpu_observations=sum(v['cpu_seconds']==0 for v in opt),
        wall_median_reference=statistics.median(v['wall_seconds'] for v in ref),
        wall_median_specialized=statistics.median(v['wall_seconds'] for v in opt),
        build_only_break_even_calls=break_even,
        excludes_qualification_and_development_cost=True))
assert len(result['rejections'])==30 and all(r['rejected'] for r in result['rejections'])
summary=dict(schema='hepta.hcsn.specialization.arithmetic-review.v1',status='PASS',
    source_files=len(protocol['sources']),npz_files=npz_count,paired_arrays=arrays,
    paired_coordinates=coordinates,bitwise_mismatches=mismatches,max_abs=maximum,
    timings=timing,rows=all_rows,model_calls=0,torch_imports=0,optimizer_calls=0,
    body_cpu_seconds=time.process_time()-start_cpu,body_wall_seconds=time.perf_counter()-start_wall,
    peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
    source_reader_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
with (ROOT/'INDEPENDENT_REVIEW.json').open('x') as handle:
    json.dump(summary,handle,indent=2,allow_nan=False);handle.write('\n')
print(json.dumps({k:v for k,v in summary.items() if k not in ('timings','rows')}),flush=True)
