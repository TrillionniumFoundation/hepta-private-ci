"""Verify raw equivalence traces, selected output probabilities, and bundle integrity."""
import argparse,hashlib,json,shutil,sys,zipfile
from pathlib import Path
import numpy as np
D=Path(__file__).resolve().parent
sys.path.insert(0,str(D.parent))
from finalize import split_zip,copy_file
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--stages',nargs='+',choices=['first','second'],required=True)
    a=ap.parse_args();dest=D.parent/('publish_exact_'+('_'.join(a.stages)));dest.mkdir(exist_ok=True);src=D/'results';files=[];rows=[]
    for s in (107,211,431):
        base=src/str(s);qual=base/'qualification.json';files.append(qual);q=json.loads(qual.read_text())
        assert q['qualified'] and q['implementation']==sha(D/'exact.py') and q['protocol']==sha(D/'PROTOCOL.md')
        absolute=[a['abs_error'] for v in q['comparisons'].values() for a in v.values() if isinstance(a,dict)]
        summary=dict(seed=s,feature_cases=len(q['comparisons']),largest_absolute_feature_or_trace_error=max(absolute),
                     largest_gradient_error=max(r['abs_error'] for r in q['gradients'].values()),
                     largest_candidate_norm_error=max(q['solve_norm_difference'].values()),timings={k:v['median_paired_ratio'] for k,v in q['measurements'].items()},replay={})
        for stage in a.stages:
            model_name='direct' if stage=='first' else 'secant'
            ref=D.parent/stage/str(s)/model_name
            stat=base/(stage+'-replay.json');out=base/(stage+'-predictions.npz');files.extend((stat,out))
            info=json.loads(stat.read_text());assert info['pass_gate'] and sha(out)==info['raw_sha256'] and sha(ref/'predictions.npz')==info['source_raw']
            with np.load(ref/'predictions.npz',allow_pickle=False) as orig, np.load(out,allow_pickle=False) as new:
                for k in (('eng','ar') if stage=='first' else ('cmd',)):
                    assert np.array_equal(orig[k+'_id'],new[k+'_ids']) and np.array_equal(orig[k+'_y'],new[k+'_y'])
                    absolute=float(np.abs(orig[k+'_scores']-new[k+'_scores']).max())
                    mismatches=int((orig[k+('_class' if stage=='first' else '_pred')]!=new[k+'_pred']).sum())
                    assert info[k]['max_abs']==absolute and info[k]['disagreement']==mismatches
                    summary['replay'][k]=dict(records=len(new[k+'_y']),max_abs=absolute,argmax_mismatches=mismatches)
        rows.append(summary)
    for f in ('exact.py','qualify.py','replay.py','run_replay.py','summarize.py','PROTOCOL.md'):copy_file(D/f,dest/f)
    archives=split_zip(src,files,dest)
    doc={'rows':rows,'source_sha256':sha(D/'exact.py'),'protocol_sha256':sha(D/'PROTOCOL.md'),'archives':archives}
    (dest/'results.json').write_text(json.dumps(doc,indent=2,sort_keys=True)+'\n')
    print(dest,sha(dest/'results.json'))
if __name__=='__main__':main()
