"""Independent reconstruction of video/seed-paired external quality, timing and perturbations."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np

SEEDS=(413,677,941)
RUNGS=(15,60,180)
WIDTHS=(64,256,1024)
SHARED=('fp_h','fp_r','random_h','bp_h','transformer')
DESIGNS=[(w,k) for w in WIDTHS for k in SHARED]+[(64,k) for k in ('fp_h_text','transformer_text','fp_h_shuffle')]+[(0,k) for k in ('raw_all','raw_text','raw_av')]


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def write(path,value):path.write_text(json.dumps(value,sort_keys=True,indent=1,allow_nan=False)+'\n')


def by_group(a,vid):
    return np.asarray([a[vid==v].mean() for v in np.unique(vid)])


def summary(z,y,vid):
    d=z-y;g=by_group(np.abs(d),vid)
    sign=y!=0;center=z-z.mean();v=center@center
    slope=None if v==0 else float((center@(y-y.mean()))/v)
    corr=None if v==0 or y.std()==0 else float(np.corrcoef(z,y)[0,1])
    return {'video_mae':float(g.mean()),'pooled_mae':float(abs(d).mean()),'pooled_rmse':float(np.sqrt((d*d).mean())),'pearson':corr,'sign_acc_nonzero':float(np.mean((z[sign]>0)==(y[sign]>0))),'excluded_zero_labels':int((~sign).sum()),'mean_residual_bias':float(d.mean()),'calibration_slope':slope,'video_mae_vector':g.tolist()}


def bootstrap(d,sv,vv,adjust=False):
    # Rows are matched initializations; columns are entire intact source videos.
    draws=np.einsum('bi,ij,bj->b',sv,d,vv)
    out={'mae_delta':float(d.mean()),'two_way_ci95':np.quantile(draws,[.025,.975]).tolist(),'seed_delta':d.mean(1).tolist(),'video_delta':d.mean(0).tolist(),'video_only_ci95':np.quantile(vv@d.mean(0),[.025,.975]).tolist()}
    if adjust:out['familywise_bonferroni9_ci']=np.quantile(draws,[.025/9,1-.025/9]).tolist()
    return out


def main():
    p=argparse.ArgumentParser()
    for k in ('models','scores','data_manifest','seal','out'):p.add_argument(k,type=Path)
    a=p.parse_args();sealed=json.loads(a.seal.read_bytes());data=json.loads(a.data_manifest.read_bytes())
    assert sha(a.data_manifest)==sealed['data_manifest_sha256']
    summary_rows={};dist={};pert={};embedded={};actual=0;prefixes=0;vectors=0
    for w,arm in DESIGNS:
        for seed in SEEDS:
            key=f'{w}-{arm}-{seed}';f=a.scores/(key+'.npz');receipt=json.loads(f.with_suffix('.json').read_bytes());assert sha(f)==receipt['pred_sha256'] and sha(a.seal)==receipt['seal_sha256']
            fitp=a.models/(key+'.json');assert sha(fitp)==sealed['fits'][fitp.name];fit=json.loads(fitp.read_bytes())
            with np.load(f) as z:
                y=z['y'];vid=z['video'];clips=z['clip'];donors=z['donors']
                if not embedded:embedded={'y':y,'video':vid,'clip':clips,'donors':donors}
                else:assert all(np.array_equal(z[k],v) for k,v in embedded.items())
                assert len(set(clips))==len(y)==686 and len(set(vid))==31
                for d in donors:assert len(set(d))==len(y) and np.all(vid!=vid[d])
                assert np.isfinite(y).all()
                for rung in RUNGS:
                    m=fit['selected'][str(rung)]
                    if m is None:continue
                    yy=z['r'+str(rung)];assert yy.shape==y.shape and np.isfinite(yy).all()
                    assert m['cpu']<=rung and m['sha256']==sealed['weights'][m['file']]
                    stat=summary(yy,y,vid);dist[w,arm,seed,rung]=np.array(stat['video_mae_vector'])
                    later=[row['wall'] for row in fit['history'] if row['cpu']>rung]
                    selection=min(later+[fit['fit_wall']])
                    rec=receipt['rungs'][str(rung)]
                    pipeline=data['feature_prep_total_wall_s']+fit['common_process']['wall']+selection+fit['serialization_wall']+receipt['source_and_start_wall']+rec['model_load_and_inference_wall']
                    stat.update({'parameter_count':fit['parameter_count'],'feature_prep_wall':data['feature_prep_total_wall_s'],'common_fit_init_wall':fit['common_process']['wall'],'optimizer_and_full_dev_selection_upper_wall':selection,'all_selected_checkpoint_save_wall':fit['serialization_wall'],'cold_start_read_build_wall':receipt['source_and_start_wall'],'cold_model_load_predict_wall':rec['model_load_and_inference_wall'],'end_to_end_upper_wall':pipeline,'selected_dev_mae':m['dev_video_mae'],'selected':{k:m[k] for k in ('lr','steps','penalty','hidden_writes','hidden_write_fro','cpu','wall','sha256') if k in m}})
                    summary_rows[f'{key}-{rung}']=stat;actual+=len(y);prefixes+=1;vectors+=1
                if 'r180' not in z:continue
                base=np.abs(z['r180']-y)
                for mm in ('text','audio','vision','av'):
                    d=z['drop_'+mm]
                    sw=np.stack([z[f'swap_{mm}_{i}'] for i in range(3)])
                    assert d.shape==y.shape and sw.shape==(3,len(y))
                    err=np.abs(d-y)-base
                    pert[w,arm,seed,'drop_'+mm]=by_group(err,vid)
                    err=np.mean(np.abs(sw-y),0)-base
                    pert[w,arm,seed,'swap_'+mm]=by_group(err,vid)
                    actual+=4*len(y);vectors+=4
    rng=np.random.default_rng(68773);count=10000
    si=rng.multinomial(len(SEEDS),np.ones(len(SEEDS))/len(SEEDS),count)/len(SEEDS)
    vv=rng.multinomial(31,np.ones(31)/31,count)/31
    curves={};effects={};sensitivity={};threshold={};ranks={}
    for w,arm in DESIGNS:
        short=f'{w}-{arm}';curves[short]={};threshold[short]={}
        for r in RUNGS:
            keys=[f'{short}-{s}-{r}' for s in SEEDS]
            if any(k not in summary_rows for k in keys):continue
            rows=[summary_rows[k] for k in keys]
            curves[short][r]={k:float(np.mean([v[k] for v in rows])) for k in ('video_mae','pooled_mae','pooled_rmse','sign_acc_nonzero','mean_residual_bias','end_to_end_upper_wall')}
            curves[short][r]['parameter_count']=rows[0]['parameter_count']
            curves[short][r]['pearson_mean']=None if any(v['pearson'] is None for v in rows) else float(np.mean([v['pearson'] for v in rows]))
            curves[short][r]['by_seed_mae']=[v['video_mae'] for v in rows]
            curves[short][r]['by_seed_wall']=[v['end_to_end_upper_wall'] for v in rows]
        for target in (1.20,1.05,.90):
            ok=[r for r,v in curves[short].items() if max(v['by_seed_mae'])<=target]
            threshold[short][f'{target:.2f}']=None if not ok else {'first_observed_prefix':min(ok),'mean_end_to_end_upper_wall':curves[short][min(ok)]['end_to_end_upper_wall'],'by_seed_wall':curves[short][min(ok)]['by_seed_wall']}
        if not all((w,arm,s,180) in dist for s in SEEDS):continue
        sensitivity[short]={}
        for perturb in [q+'_'+m for q in ('drop','swap') for m in ('text','audio','vision','av')]:
            mat=np.stack([pert[w,arm,s,perturb] for s in SEEDS])
            sensitivity[short][perturb]=bootstrap(mat,si,vv,arm=='fp_h' and perturb in ('swap_text','swap_audio','swap_vision'))
        if arm=='fp_h':
            rivals=[(w,r) for r in SHARED if r!='fp_h']+[(0,r) for r in ('raw_all','raw_text','raw_av')]
            if w==64:rivals.extend([(64,r) for r in ('fp_h_text','transformer_text','fp_h_shuffle')])
            for rw,ra in rivals:
                for rung in RUNGS:
                    if all((w,arm,s,rung) in dist and (rw,ra,s,rung) in dist for s in SEEDS):
                        mat=np.stack([dist[w,arm,s,rung]-dist[rw,ra,s,rung] for s in SEEDS])
                        effects[f'{w}-fp_h_minus_{rw}-{ra}-{rung}']=bootstrap(mat,si,vv)
    a.out.mkdir(exist_ok=True,parents=True)
    agg={'scope':{'cases':len(y),'videos':len(np.unique(vid)),'seeds':SEEDS,'rungs':RUNGS,'real_fit_jobs':len(sealed['fits']),'eligible_prefix_selections':prefixes,'intact_or_perturbation_vectors':vectors,'raw_scalar_prediction_entries':actual,'source_groups':{k:len(v['videos']) for k,v in data['splits'].items()},'bootstrap_repetitions':count,'seal_sha256':sha(a.seal)},'curves':curves,'time_to_external_quality':threshold,'paired_fp_h':effects,'perturbation_mae_minus_intact':sensitivity}
    write(a.out/'SUMMARY.json',agg);write(a.out/'all_intact_models.json',summary_rows)
    print('verified',len(sealed['fits']),prefixes,vectors,actual,'scalar predictions')


if __name__=='__main__':main()
