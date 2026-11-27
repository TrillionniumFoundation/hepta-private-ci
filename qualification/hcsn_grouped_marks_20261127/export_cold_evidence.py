"""Deduplicate exact held-out score arrays while retaining every original receipt hash."""
import argparse,hashlib,io,json,tarfile
from pathlib import Path
import numpy as np


def sha(path):
    with path.open('rb') as s:return hashlib.file_digest(s,'sha256').hexdigest()


def read(path):return json.loads(path.read_text())


def export(root,dest):
    dest.mkdir(parents=True,exist_ok=True);raw=read(root/'final.json');seal=read(root/'evaluation_seal.json');tune=read(root/'tuning_seal.json')
    assert len(seal['assignments'])==72 and raw['seal']==sha(root/'evaluation_seal.json') and seal['tuning']==sha(root/'tuning_seal.json')
    fields=('test_sum','test_swapped','development_sum','development_swapped');mat={k:[] for k in fields};same={};states=[];state_arms=[];fits=[];indices={}
    json_paths=[root/name for name in ['source_seal.json','gpu_qualification.json','tuning_seal.json','evaluation_seal.json','final.json','attempts.jsonl']]
    for phase in ['tune','confirm']:
        for d in sorted((root/'runs'/phase).iterdir()):
            done=read(d/'complete.json');assert done['history_sha256']==sha(d/'history.json');json_paths.extend([d/'complete.json',d/'history.json'])
            if phase=='tune':continue
            bind=seal['assignments'][d.name];c=read(d/'cold.json');json_paths.append(d/'cold.json')
            assert c['complete']==bind['complete']==sha(d/'complete.json') and c['seal']==raw['seal']
            assert set(c['references'])==set(bind['assignment']);unique={};source_receipts={};model_indices={}
            for key,state in c['references'].items():
                a=bind['assignment'][key];assert a['state']==state;unique[state]=d/('cold-'+state[:16]+'.npz')
            for state,p in sorted(unique.items()):
                assert sha(p)==c['arrays'][p.name]
                compound=(c['arm'],state);prior=indices.get(compound)
                with np.load(p,allow_pickle=False) as z:
                    assert set(z.files)=={f'{sp}_{k}' for sp in ['test','development'] for k in ['sum','swapped','ids','counts']}
                    for sp,expected in [('test',800),('development',320)]:
                        ids=z[sp+'_ids'];counts=z[sp+'_counts'];assert len(ids)==expected and len(set(ids))==expected and (counts>0).all()
                        for suffix,arr in [('ids',ids),('counts',counts)]:
                            tag=sp+'_'+suffix
                            if tag in same:assert np.array_equal(arr,same[tag])
                            else:same[tag]=arr.copy()
                        loss=z[sp+'_sum'];shift=z[sp+'_swapped'];assert np.isfinite(loss).all() and np.isfinite(shift).all() and (loss>=0).all() and (shift>=0).all()
                        saved=c['scores'][state][sp];assert abs(loss.sum()/counts.sum()-saved['nll'])<1e-10 and abs((shift-loss).sum()/counts.sum()-saved['conditioning_gain'])<1e-10
                    for k in fields:
                        if prior is None:mat[k].append(z[k].copy())
                        else:assert np.array_equal(mat[k][prior],z[k])
                    source_receipts[state]={'original_npz_sha256':sha(p),'keys':z.files,'array_sha256':{k:hashlib.sha256(z[k].tobytes(order='C')).hexdigest() for k in z.files}}
                if prior is None:
                    indices[compound]=len(states);states.append(state);state_arms.append(c['arm'])
                model_indices[state]=indices[compound]
            fits.append({'arm':c['arm'],'seed':c['seed'],'cold_sha256':sha(d/'cold.json'),'complete_sha256':sha(d/'complete.json'),'assignments':bind['assignment'],'model_indices':model_indices,'original_arrays':source_receipts})
    assert len(fits)==72 and 1<=len(states)<=288 and len(set(same['test_ids']) & set(same['development_ids']))==0
    npz=dest/'heldout_losses.npz';np.savez_compressed(npz,states=np.array(states,dtype='S64'),state_arms=np.asarray(state_arms,dtype='S32'),**same,**{k:np.stack(v) for k,v in mat.items()})
    receipt=dest/'training_receipts.tar.gz'
    with tarfile.open(receipt,'w:gz',compresslevel=7) as tar:
        for p in sorted(json_paths):
            data=p.read_bytes();info=tarfile.TarInfo(str(p.relative_to(root)));info.size=len(data);info.mtime=0;tar.addfile(info,io.BytesIO(data))
    index={'scope':'exact loss sums and token counts per photograph for every distinct jointly frozen checkpoint, with every fit assignment','states':len(states),'fits':fits,'final_sha256':sha(root/'final.json'),'evaluation_seal':raw['seal'],'tuning_seal':sha(root/'tuning_seal.json'),'primary_control':tune['control'],'targets':tune['targets'],'packed_losses_sha256':sha(npz),'training_receipts_sha256':sha(receipt),'counts':{sp:int(same[sp+'_counts'].sum()) for sp in ['test','development']}}
    (dest/'heldout_index.json').write_text(json.dumps(index,sort_keys=True,separators=(',',':'))+'\n');print('exported',len(states),len(fits),npz.stat().st_size,receipt.stat().st_size,flush=True)


if __name__=='__main__':
    c=argparse.ArgumentParser();c.add_argument('root',type=Path);c.add_argument('dest',type=Path);args=c.parse_args();export(args.root,args.dest)
