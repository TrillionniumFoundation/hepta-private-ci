"""Load all archived T4 weights on a separate physical CPU and replay cold interventions."""
import argparse
import json
from pathlib import Path
import runpy
import sys
import tempfile
import time
import zipfile

import numpy as np
import torch


def main(source,original,out):
    assert torch.get_num_threads()==1
    started=time.perf_counter();code=runpy.run_path(str(source),run_name='frozen_colab_source')
    report=json.loads((original/'result.json').read_text())
    with tempfile.TemporaryDirectory() as tmp:
        folder=Path(tmp);code['expand'](folder);sys.path.insert(0,str(folder))
        import panel
        panel.DEVICE='cpu';panel.wait_time=time.perf_counter
        d=panel.StudyData(folder)
        test=d.splits[2];y=d.y[test].numpy()
        cols={};primary_logits=0;conditions=0
        with np.load(original/'cold.npz',allow_pickle=False) as archived,zipfile.ZipFile(original/'weights.zip') as weights:
            assert np.array_equal(d.ids[test],archived['ids']) and np.array_equal(y,archived['y'])
            da,dv=archived['audio_donor_global'],archived['vision_donor_global']
            def compare(key,z):
                nonlocal primary_logits,conditions
                _,loss,pred=panel.clipped_score(z,y)
                saved_loss,saved_pred=archived[key+'__loss'],archived[key+'__prediction']
                delta=abs(loss-saved_loss)
                rec={'max_abs_nll_error':float(delta.max()),'mean_abs_nll_error':float(delta.mean()),
                     'prediction_disagreements':int(np.sum(pred!=saved_pred))}
                if key.endswith('-normal'):
                    logit_delta=abs(z-archived[key+'__logits'])
                    rec['max_abs_logit_error']=float(logit_delta.max())
                    rec['mean_abs_logit_error']=float(logit_delta.mean())
                    primary_logits+=z.size
                cols[key]=rec;conditions+=1
            for arm in panel.ARMS:
                for seed in panel.SEEDS:
                    model=panel.Encoder(arm,seed,int(d.tokens.max())+1,folder/'law4.npz').cpu()
                    for tag in panel.ENDPOINTS:
                        r=report['fits'][f'{arm}-{seed}']['checkpoints'][tag]
                        p=folder/r['file'];p.write_bytes(weights.read(r['file']));assert panel.digest(p)==r['sha256']
                        model.load_state_dict(torch.load(p,weights_only=True,map_location='cpu'))
                        for name,pair in [('normal',None),('perm_audio',(None,da)),('perm_vision',(dv,None))]:
                            compare(f'{arm}-{seed}-{tag}-{name}',panel.infer(model,d,test,pair))
                        if arm=='literal':
                            model.mix[1].kind='no_wire'
                            compare(f'{arm}-{seed}-{tag}-no_wire',panel.infer(model,d,test))
                            model.mix[1].kind='literal'
            ridge,cfg=panel.ridge(d); assert (cfg['regularization'],cfg['scale'])==(report['ridge']['regularization'],report['ridge']['scale'])
            for name,donors in [('normal',None),('perm_audio',(test,da)),('perm_vision',(dv,test))]:
                compare('ridge-'+name,ridge(d.get(test,donors)))
    assert conditions==81 and primary_logits==25*1311*72
    res={'device':'cpu','torch':str(torch.__version__),'cpu_threads':torch.get_num_threads(),'conditions':conditions,
         'primary_logits':primary_logits,'per_clip_predictions':conditions*len(y),'seconds':time.perf_counter()-started,
         'disagreed_argmax':sum(r['prediction_disagreements'] for r in cols.values()),
         'max_abs_cpu_gpu_nll':max(r['max_abs_nll_error'] for r in cols.values()),
         'max_abs_cpu_gpu_logit':max(r.get('max_abs_logit_error',0) for r in cols.values()),'conditions_detail':cols}
    out.write_text(json.dumps(res,indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('original',type=Path);p.add_argument('out',type=Path)
    a=p.parse_args();torch.set_num_threads(1);main(a.source,a.original,a.out)
