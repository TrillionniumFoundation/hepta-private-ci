"""Freeze decisions from the original free acoustic frontend before loading any paid model."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import time
import numpy as np
import torch
from qualification.hcsn_intervention_value import frontend,run
from qualification.hcsn_intervention_value.media import recording_features
from qualification.hcsn_blocker_followup import readout_edit

HERE=Path(__file__).resolve().parent
def load(path):return json.loads(path.read_text())
def digest(path):
    with path.open('rb') as stream:
        h=sha256()
        for chunk in iter(lambda:stream.read(1<<20),b''): h.update(chunk)
    return h.hexdigest()
def save(path,document):path.write_text(json.dumps(document,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
def checked(path,identifier,protocol):
    if digest(path)!=protocol['frozen_sha256'][identifier]:raise ValueError(f'Unbound input {identifier}')
    return load(path)

def process(args):
    started=time.perf_counter()
    rule=load(HERE/'protocol.json')
    assert digest(HERE/'cohort.json')==rule['cohort_sha256']
    cohort=load(HERE/'cohort.json')
    selected={r['pageid']:r for r in cohort['sources']}
    rows=[];paths={}
    for pid in cohort['qualified_ids']:
        record=selected[pid]
        name=str(pid)+Path(record['title']).suffix
        original=next(root/name for root in args.originals if (root/name).is_file())
        assert digest(original)==record['source_sha256']
        paths[str(pid)]=str(original.resolve())
        for j,start in enumerate(record['starts']):
            rows.append(dict(recording=str(pid),group='production-'+str(pid),query_id=f'fresh-{pid}-w{j+1:02d}',
                             split='test',label=int(record['instrument']=='guitar'),start_seconds=start,
                             dt=[.48]*6))
    clock=time.perf_counter()
    def acoustic(row):
        return recording_features.extract(paths[row['recording']],row['start_seconds'])['audio']
    with ThreadPoolExecutor(max_workers=2) as pool: audio=np.stack(list(pool.map(acoustic,rows)))
    assert audio.shape==(48,6,52)
    out=args.out;out.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(out/'audio.npz',audio=audio)
    save(out/'roster.json',rows)
    extract_seconds=time.perf_counter()-clock
    raw={key:np.asarray([r[key] for r in rows]) for key in rows[0]}
    raw['audio']=audio
    # The original renderer also accepts a visual descriptor array. Its unused path is
    # set to a constant. Only the renderer's free acoustic fields enter the decision functions.
    raw['visual']=np.zeros((len(rows),6,76))
    w=checked(args.discovery/'front_weights.json','audio_gallery',rule)
    free,_=frontend.render(raw,w['final'],w['reference'])
    # Neither a true class nor a purchased observation is passed into any frozen policy.
    state={k:free[k] for k in ('x','scores','gallery_audio','dt')}
    meta=checked(args.policies/'prepare/metadata.json','policies/prepare/metadata.json',rule)
    teacher=checked(args.policies/'prepare/read.json','policies/prepare/read.json',rule)
    run.init()
    qtable={};acts={};timings={}
    with torch.inference_mode():
        inputs=run.frontend(state.copy(),meta,teacher)
        for mode in rule['architectures']:
            for how in ('keep','bp'):
                for seed in rule['seeds']:
                    key=f'read-{mode}-{how}-{seed}'; file='fit/'+key+'.json'
                    params=checked(args.policies/file,'policies/'+file,rule)
                    clock=time.perf_counter()
                    model=run.representation(mode,seed,len(meta['mu']))
                    features=run.features(model,mode,True)
                    theta=torch.tensor(params['theta'],dtype=torch.float64)
                    head=torch.tensor(params['head'],dtype=torch.float64)
                    q=run.predict(features(theta,inputs),head).numpy()
                    assert q.shape==(48,6,3) and np.isfinite(q).all()
                    masked=q.copy();masked[:,-1,run.WAIT]=-np.inf
                    actions=masked.argmax(-1)
                    end=(actions!=run.WAIT).argmax(1)
                    qtable[key]=q
                    acts[key]={'end':end.tolist(),'action':actions[np.arange(len(end)),end].tolist()}
                    timings[key]=time.perf_counter()-clock
    base=checked(args.selector/'fit.json','old_source_svd',rule)['full-svd-.1']
    edits=checked(args.selector/'edit_seal.json','old_bounded_edits',rule)
    six=checked(args.six,'train_only_six',rule)
    X=readout_edit.matrix(state,base)
    w0=np.r_[base['beta'],base['bias']]
    deltas={'svd':np.zeros_like(w0),'train_only_six':np.array(six['delta'],dtype=float)}
    for k in ('lp','gradient'):deltas[k]=np.array(edits['rows'][k][edits['selected'][k]]['delta'])
    for key,delta in deltas.items():
        score=X@(w0+delta)
        acts[key]={'end':[0]*len(rows),'action':(score>.30).astype(int).tolist()}
    for key,value in [('free',run.STOP),('paid',run.READ)]:acts[key]={'end':[0]*len(rows),'action':[value]*len(rows)}
    np.savez_compressed(out/'qvalues.npz',**qtable)
    np.savez_compressed(out/'free.npz',scores=state['scores'],gallery_audio=state['gallery_audio'])
    save(out/'actions.json',acts)
    save(out/'action-seal.json',{'protocol_sha256':digest(HERE/'protocol.json'),'code_sha256':digest(Path(__file__)),
         'cohort_sha256':digest(HERE/'cohort.json'),'files':{n:digest(out/n) for n in ['roster.json','audio.npz','free.npz','qvalues.npz','actions.json']},
         'policies':len(acts),'windows':len(rows),'acoustic_extraction_wall_seconds':extract_seconds,
         'per_old_head_wall_seconds':timings,'implementation_wall_seconds':time.perf_counter()-started,'reads_of_paid_camera_output':0})
    print('Sealed',len(acts),'sets of decisions on',len(rows),'windows.')
if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    for k in ('discovery','policies','selector','six','out'):ap.add_argument('--'+k,type=Path,required=True)
    ap.add_argument('--originals',nargs='+',type=Path,required=True)
    process(ap.parse_args())
