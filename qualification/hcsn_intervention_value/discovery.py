"""Discover on registered source splits, lock one camera and open TEST only after model selection."""
import argparse
import json
import time
from pathlib import Path

import numpy as np

from . import frontend as front
from . import independent as audit


HERE=Path(__file__).parent


def source_hashes():
    return {str(f.relative_to(HERE)):front.digest(f) for f in
            [HERE/'frontend.py',HERE/'independent.py',HERE/'discovery.py',HERE/'protocol.json',
             HERE/'media'/'recording_features.py',HERE/'media'/'vision.py']}


def archive(path,columns):
    with path.open('xb') as stream:
        np.savez_compressed(stream,**columns)


def metadata(sets):
    return {name:dict(query_id=s['query_id'],group=s['group'],source=s['recording']) for name,s in sets.items()}


def fit(args):
    start=time.time()
    args.output.mkdir(parents=True,exist_ok=False)
    names=('gallery','train','dev','retain')
    raw={n:front.load_raw(args.raw/(n+'.npz')) for n in names}
    external={n:front.digest(args.raw/(n+'.npz')) for n in names}
    rosters=audit.verify_disjoint(metadata(raw))
    semantic={n:front.semantic_array(args.vision/(n+'.npz'),raw[n]) for n in names[1:]}
    printed={n:front.digest(args.vision/(n+'.npz')) for n in names[1:]}
    rendered,model=front.build(raw['gallery'],raw['train'],{n:raw[n] for n in ('dev','retain')},semantic)
    panels={}
    choosers={}
    for which in front.METHODS:
        tr=front.candidate(rendered['train'],which)
        dv=front.candidate(rendered['dev'],which)
        chooser=audit.fit_causal(tr)
        choosers[which]=chooser.state_dict()
        panels[which]=dict(train=audit.opportunity(tr),dev=audit.opportunity(dv),
                           dev_policy=audit.evaluate(chooser,dv,stage='development'))
    selected=audit.select_frontend(panels)
    front.dump(args.output/'panels.json',panels)
    front.dump(args.output/'front_weights.json',model)
    if selected:
        for name,r in rendered.items():
            archive(args.output/(name+'.npz'),front.candidate(r,selected))
        front.dump(args.output/'chooser.json',choosers[selected])
    states={p.name:front.digest(p) for p in args.output.iterdir() if p.is_file()}
    front.dump(args.output/'frontend_seal.json',dict(selected=selected,raw_inputs=external,vision_inputs=printed,
              rosters=rosters,sha256=states,source=source_hashes(),duration_seconds=time.time()-start,
              start_unix=start,end_unix=time.time(),heldout_opened=False,
              immediate_baseline=panels[selected]['dev_policy']['immediate_baseline'] if selected else None))


def confirm(args):
    seal=json.loads((args.output/'frontend_seal.json').read_text())
    which=seal['selected']
    if not which or set(seal['source'])!=set(source_hashes()) or seal['source']!=source_hashes():
        raise ValueError('no qualified frozen frontend')
    if (not args.policy_seal or not args.policy_seal.is_file()
            or any(front.digest(args.output/k)!=v for k,v in seal['sha256'].items())):
        raise ValueError('missing policy or altered frontend seal')
    from .run import check_seal
    if args.policy_seal.name!='selection_seal.json':
        raise ValueError('registered policy seal required')
    check_seal(args.policy_seal.parent)
    policy=json.loads(args.policy_seal.read_text())
    prepare=json.loads((args.policy_seal.parent/'prepare'/'metadata.json').read_text())
    if policy.get('arm_count')!=66 or any(prepare['inputs'][n]!=front.digest(args.output/(n+'.npz'))
                                           for n in ('train','dev','retain')):
        raise ValueError('policy seal belongs to a different selection')
    test=front.load_raw(args.raw/'test.npz')
    old={n:front.load_raw(args.raw/(n+'.npz')) for n in ('gallery','train','dev','retain')}
    coverage=audit.verify_disjoint(metadata({**old,'test':test}))
    weights=json.loads((args.output/'front_weights.json').read_text())
    sem=front.semantic_array(args.vision/'test.npz',test) if which.startswith('imagenet') else None
    result=front.candidate(front.render(test,weights['final'],weights['reference'],sem),which)
    archive(args.output/'test.npz',result)
    chooser=audit.CausalChooser.from_state_dict(json.loads((args.output/'chooser.json').read_text()))
    front.dump(args.output/'heldout_controls.json',dict(opportunity=audit.opportunity(result),
               policy=audit.evaluate(chooser,result,stage='confirmation',immediate_baseline=seal['immediate_baseline']),
               input_hash=front.digest(args.raw/'test.npz'),paid_vision_hash=front.digest(args.vision/'test.npz') if sem is not None else None,
               ready_hash=front.digest(args.output/'test.npz'),policy_seal=front.digest(args.policy_seal),
               frontend_seal=front.digest(args.output/'frontend_seal.json'),coverage=coverage))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['fit','confirm'])
    parser.add_argument('raw',type=Path)
    parser.add_argument('vision',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--policy-seal',type=Path)
    args=parser.parse_args()
    (fit if args.phase=='fit' else confirm)(args)
