"""Replay every published sweep from original Allen timestamps using SciPy's distribution implementations."""
import argparse,hashlib,json,math,zipfile
from pathlib import Path
import numpy as np
from scipy import stats


def sha(raw):return hashlib.sha256(raw).hexdigest()


def verify(archive,model_file,scores_file):
    models=json.loads(model_file.read_bytes());scored=json.loads(scores_file.read_bytes())
    assert sha(model_file.read_bytes())==scored['selection_seal_sha256']
    with zipfile.ZipFile(archive) as z:
        raw=z.read('nwb_predictions.json')
        assert sha(raw)=='d7ce39c34ba3fc8892d2b9c33360b68359db8ab026f65f421ef4d1dd35a57491'
        all_rows=json.loads(raw)
    source={(int(cid),r['row_id']):r for cid,cell in all_rows.items() for r in cell['sweeps']}
    maximum=0.;comparisons=0;nonsupport=0
    for ext,records in scored['groups'].items():
        for panel,info in models['panels'].items():
            for arm,detail in info['arms'].items():
                fit=detail['refit']
                if fit['status']!='finite':continue
                params=fit['params'];shape=1 if arm=='exponential' else math.exp(params[2])
                if arm.startswith('ig'):
                    d=stats.invgauss(1/shape,scale=shape);n=int(arm[2:])
                elif arm=='gamma':
                    d=stats.gamma(shape,scale=1/shape);n=1
                elif arm=='exponential':
                    d=stats.expon();n=1
                else:
                    d=stats.lognorm(1/math.sqrt(shape),scale=math.exp(-.5/shape));n=1
                for rec in records:
                    r=source[rec['cell'],rec['row_id']];times=np.asarray(r['true_relative_times']);dead=0. if panel=='no_deadtime' else .0005
                    assert r['I_pA']==rec['current_pA'] and r['duration']==rec['pulse_length_s']
                    if len(times)==0:
                        value=0.
                    else:
                        exposures=np.diff(np.r_[times,r['duration']])
                        if np.any(exposures[:-1]<=dead):
                            assert rec['ll'][panel][arm] is None
                            nonsupport+=1;continue
                        scale=np.exp(params[0]+params[1]*np.tanh(r['I_pA']/200)
                                     +(params[-1]*(times/r['duration']-.5) if panel=='elapsed_adaptation' else np.zeros(len(times))))
                        u=(exposures-dead)/scale
                        value=(float(np.sum(np.log(n)+d.logpdf(u[:-1])+(n-1)*d.logsf(u[:-1])-np.log(scale[:-1])))
                               if len(u)>1 else 0.)
                        if u[-1]>0:value+=n*float(d.logsf(u[-1]))
                    error=abs(value-rec['ll'][panel][arm])
                    assert np.isfinite(error) and error<1e-6,(ext,rec['cell'],arm,panel,error)
                    comparisons+=1;maximum=max(maximum,error)
    return {'score_computations_checked_against_scipy_from_original_times':comparisons,
            'outside_support_confirmed':nonsupport,'maximum_absolute_difference_per_sweep_loglikelihood':maximum,
            'archive_sha256':sha(archive.read_bytes()),'models_sha256':sha(model_file.read_bytes()),
            'cold_scores_sha256':sha(scores_file.read_bytes()),'verification_sha256':sha(Path(__file__).read_bytes())}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('archive',type=Path);p.add_argument('model',type=Path)
    p.add_argument('ratings',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();results=verify(a.archive,a.model,a.ratings);a.output.write_text(json.dumps(results,sort_keys=True,indent=2)+'\n');print(results)
