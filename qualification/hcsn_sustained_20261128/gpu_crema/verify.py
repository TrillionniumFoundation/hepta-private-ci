"""Reconstruct all registered cold statistics from exact per-clip arrays and manifest."""
import argparse
import hashlib
import io
import json
import lzma
from pathlib import Path
import zipfile

import numpy as np


def sha(data):
    return hashlib.sha256(data).hexdigest()


def check(root):
    report=json.loads((root/'result.json').read_text())
    assert report['terminal'] and report['dot']==140 and 'T4' in report['device']
    assert sha((root/'cold.npz').read_bytes())==report['arrays_sha256']
    assert sha((root/'weights.zip').read_bytes())==report['weights_sha256']
    fits=report['fits'];expected={'seal.json'}
    assert len(fits)==12
    with zipfile.ZipFile(root/'weights.zip') as ar:
        assert sha(ar.read('seal.json'))==report['seal_sha256']
        for name,p in fits.items():
            for tag,c in p['checkpoints'].items():
                if tag=='updates78':assert c['steps']==78 and c['samples']==9968
                if tag=='time12':assert c['train_seconds']>=12
                assert sha(ar.read(c['file']))==c['sha256']
                expected.add(c['file'])
        assert expected==set(ar.namelist())
    with np.load(io.BytesIO(lzma.decompress((root/'all.xz').read_bytes()))) as original, np.load(root/'cold.npz',allow_pickle=False) as a:
        rows=np.flatnonzero(original['split']==2);y=a['y'];actor=a['actor'];names=a['ids']
        assert len(y)==1311 and np.array_equal(original['ids'][rows],names) and np.array_equal(original['labels'][rows],y)
        assert np.array_equal(rows,a['global_indices']) and len(set(actor))==report['actor_counts'][2]
        for col in ('audio_donor_global','vision_donor_global'):
            assert set(a[col])==set(rows) and np.all(a[col]!=rows)
        losses={};max_loss=0.;max_summary=0.;score_elements=0
        for k,original_score in report['cold'].items():
            loss=a[k+'__loss'];pred=a[k+'__prediction']
            if k.endswith('-normal'):
                z=a[k+'__logits'].astype(np.float64)
                assert z.shape==(len(y),72) and np.all(np.isfinite(z))
                m=z.max(1);nll=m+np.log(np.exp(z-m[:,None]).sum(1))-z[np.arange(len(z)),y]
                max_loss=max(max_loss,float(abs(loss-nll).max()));assert np.array_equal(pred,z.argmax(1))
                score_elements+=z.size
            losses[k]=loss
            max_summary=max(max_summary,abs(original_score['nll']-float(loss.mean())),
                            abs(original_score['top1']-float((pred==y).mean())))
        assert max_loss<1e-12 and max_summary<1e-12
        subjects=np.unique(actor)
        rng=np.random.default_rng(66541)
        nsub=len(subjects)
        weights=np.array([np.bincount(z,minlength=nsub) for z in rng.integers(nsub,size=(4000,nsub))])
        counts=np.array([(actor==s).sum() for s in subjects]);err=0.
        for key,rec in report['paired'].items():
            tag,contrast=key.split(':',1)
            if contrast.startswith('literal-minus-'):
                other=contrast.split('literal-minus-')[1]
                delta=np.mean([losses[f'literal-{s}-{tag}-normal']-
                    losses[f'{other}-{s}-{tag}-normal' if other!='ridge' else 'ridge-normal'] for s in (137,311,557)],axis=0)
            else:
                arm,parts=contrast.split(':')
                condition=parts.split('-minus-normal')[0]
                delta=np.mean([losses[f'{arm}-{s}-{tag}-{condition}']-losses[f'{arm}-{s}-{tag}-normal'] for s in (137,311,557)],axis=0)
            subject_sums=np.array([delta[actor==s].sum() for s in subjects])
            lo,hi=np.quantile((weights@subject_sums)/(weights@counts),[.025,.975])
            err=max(err,abs(rec['delta']-delta.mean()),abs(rec['actor_cluster_ci95'][0]-lo),abs(rec['actor_cluster_ci95'][1]-hi))
        assert err<1e-12
    return {'source_result':sha((root/'result.json').read_bytes()),'frozen_weights':len(expected)-1,
            'distinct_primary_logit_values':score_elements,'scoring_conditions':len(report['cold']),
            'per_clip_scores':len(y)*len(report['cold']),'checked_paired_contrasts':len(report['paired']),
            'maximum_disagreement_per_clip_nll':max_loss,'maximum_disagreement_summary':max_summary,
            'maximum_disagreement_cluster_contrast':float(err)}


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('folder',type=Path,nargs='?',default=Path(__file__).parent)
    args=p.parse_args()
    (args.folder/'verified.json').write_text(json.dumps(check(args.folder),indent=2)+'\n')
