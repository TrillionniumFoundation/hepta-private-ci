"""Analyze the paired wall scope, held-out predictions and sensor gradients with identical train schedules."""
import json,zipfile
from pathlib import Path
import numpy as np
here=Path(__file__).resolve().parent
plan=json.loads((here/'variant_protocol.json').read_text())
out={}
for ds in plan['datasets']:
    per={}
    for arm in plan['variants']:
        rows=[]
        for seed in plan['seeds']:
            p=here/'variants_results'/ds/f'{arm}-{seed}';q=json.loads((p/'predictions.json').read_text());f=json.loads((p/'fit.json').read_text())
            def cold(k):return json.loads((p/f'{k}-process.json').read_text())['cold_wall_s']
            a=np.array(q['p']);b=np.array(q['y']);d=a[b==1][:,None]-a[b==0]
            rows.append(dict(seed=seed,selected=f['selected'],allocated=f['trainable_parameters'],cold_fit_s=cold('fit'),cold_test_s=cold('confirm'),
                optimizer_dev_s=f['fit_dev_optimizer_s'],reload_eval_s=q['reload_eval_s'],auc=float(((d>0).sum()+.5*(d==0).sum())/d.size),ba=q['score']['balanced_accuracy'],brier=q['score']['brier']))
        per[arm]=rows
    diffs={}
    for a in plan['variants']:
        dscores=[]
        for seed in plan['seeds']:
            root=here/'variants_results'/ds
            def read(v):return json.loads((root/f'{v}-{seed}'/'predictions.json').read_text())
            old,new=read('newton'),read(a);g0=np.asarray(old['input_vjp']);g1=np.asarray(new['input_vjp']);eps=np.linalg.norm(g0)
            dscores.append(dict(seed=seed,max_abs_p=float(np.max(np.abs(np.array(old['p'])-np.array(new['p'])))),mean_abs_p=float(np.mean(np.abs(np.array(old['p'])-np.array(new['p'])))),max_abs_input_vjp=float(np.max(abs(g0-g1))),relative_vjp_norm=float(np.linalg.norm(g0-g1)/eps) if eps else None))
        diffs[a]=dscores
    out[ds]=dict(raw=per,difference_vs_newton=diffs,means={v:{k:float(np.mean([r[k] for r in rows])) for k in ['cold_fit_s','cold_test_s','optimizer_dev_s','reload_eval_s','auc','ba','brier']} for v,rows in per.items()})
(here/'variant_summary.json').write_text(json.dumps(out,sort_keys=True,indent=1)+'\n')
for ext in ('json','pt'):
    with zipfile.ZipFile(here/f'variant_{ext}.zip','w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for f in sorted((here/'variants_results').rglob('*.'+ext)):z.write(f,str(f.relative_to(here/'variants_results')))
        if ext=='json':z.write(here/'variants_results/attempts.jsonl','attempts.jsonl')
for d,o in out.items():
 print(d,o['means']);print({k:max(r['max_abs_p'] for r in rows) for k,rows in o['difference_vs_newton'].items()})
