"""Fit on new sources, lock picker and code, then confirm on unopened recordings."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from qualification.hcsn_intervention_value import frontend as frozen
from . import metrics, selector

HERE = Path(__file__).parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def write(path, obj):
    with path.open('x') as f:
        json.dump(obj, f, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(',', ':'))
        f.write('\n')


def bindings():
    return {f.name:digest(f) for f in (HERE/'protocol.json', Path(__file__), Path(selector.__file__),
                                      Path(metrics.__file__), Path(frozen.__file__))}


def verify_registry(root):
    registry = read(root/'data_freeze.json')
    previous = HERE.parent/'hcsn_intervention_value/media/sources.json'
    guards = [(root/'sources.json',registry['sources_sha256']),
              (previous,registry['previous_sources_sha256']),
              (HERE/'recording_plan.json',registry['plan_sha256']),
              (HERE/'evidence/data_freeze.json',digest(root/'data_freeze.json'))]
    guards += [(root/'roster'/(name+'.json'),signature)
               for name,signature in registry['rosters_sha256'].items()]
    if any(digest(f)!=h for f,h in guards):
        raise ValueError('unregistered media')
    original, new = read(previous), read(root/'sources.json')
    for key in ('pageid','sha1','uploader','group','producer'):
        normalize=lambda rows: [str(r[key]).strip().casefold() for r in rows]
        fresh=normalize(new)
        if len(fresh)!=len(set(fresh)) or set(fresh)&set(normalize(original)):
            raise ValueError('shared recording or production identity: '+key)
    return registry


def panel(root, old, name):
    rawfile, camera = root/'features'/(name+'.npz'), root/'semantic'/(name+'.npz')
    registry = verify_registry(root)
    rec = read(root/'receipts'/(name+'.json'))
    camera_rec = read(root/'semantic'/(name+'.receipt.json'))
    rule=read(HERE/'protocol.json')['frontend']
    if (rec['sha256']!=digest(rawfile) or rec['frozen_source_sha256']!=registry['sources_sha256']
            or rec['roster_sha256']!=registry['rosters_sha256'][name]
            or camera_rec['weight_sha256']!=rule['camera_sha256']
            or camera_rec['output_sha256']!=digest(camera)
            or camera_rec['roster_sha256']!=rec['roster_sha256']):
        raise ValueError('unbound features, camera weights or clocks')
    raw = frozen.load_raw(rawfile)
    if set(raw['split'].astype(str)) != {name}:
        raise ValueError('incorrect split label')
    weights = old/'front_weights.json'
    if digest(weights) != read(HERE/'protocol.json')['frontend']['frozen_weights_sha256']:
        raise ValueError('old frontend parameters differ')
    model = read(weights)
    sem = frozen.semantic_array(camera, raw)
    data = frozen.candidate(frozen.render(raw, model['final'], model['reference'], sem), 'imagenet_visual')
    roster = read(root/'roster'/(name+'.json'))
    source_by_row = {r['query_id']:(str(r['group']),str(r['recording']),int(r['label'])) for r in roster}
    actual = {str(i):(str(g),str(rec),int(t)) for i,g,rec,t in zip(data['query_id'],data['group'],data['source'],data['target'],strict=True)}
    if len(source_by_row) != len(roster) or actual != source_by_row:
        raise ValueError('raw IDs or source identities differ from the registered windows')
    return data, {'raw':digest(rawfile),'camera':digest(camera),'roster':digest(root/'roster'/(name+'.json'))}


def ids(data):
    return {s:sorted(set(data[s].astype(str))) for s in ('query_id','source','group')}


def exclude(a, b):
    for s in a:
        if set(a[s]) & set(b[s]):
            raise ValueError('overlap on '+s)


def features(d):
    return selector.visible(d['scores'],d['gallery_audio'],d['x'])


def fit_all(train, dev):
    x, z = features(train), features(dev)
    y, groups = selector.target(train), train['group']
    fits, pred, cv, timing = {}, {}, {}, {}
    for m in selector.MODELS:
        start, cpu = time.perf_counter(), time.process_time()
        fits[m] = selector.fit(m,x,y,groups)
        pred[m] = selector.predict(m,fits[m],z)
        full_wall = time.perf_counter()-start
        cv[m] = np.empty(len(y))
        for g in np.unique(groups):
            mask = groups == g
            fold = selector.fit(m,x[~mask],y[~mask],groups[~mask])
            cv[m][mask] = selector.predict(m,fold,x[mask])
        timing[m] = {'full_fit_and_dev_predict_seconds':full_wall,
                     'with_held_source_refits_wall_seconds':time.perf_counter()-start,
                     'with_held_source_refits_cpu_seconds':time.process_time()-cpu,
                     'held_source_refits':len(np.unique(groups))}
    return fits, pred, cv, timing


def scores(d, pred):
    return {p:metrics.evaluate(d,selector.actions(p,pred),pred.get(p.split('/')[0])) for p in selector.POLICIES}


def traces(data, predictions):
    return {'query_id':data['query_id'].tolist(), 'group':data['group'].tolist(),
            'source':data['source'].astype(str).tolist(),'target':data['target'].tolist(),
            'free_answer':data['scores'][:,0].argmax(-1).tolist(),
            'paid_answer':data['read_scores'][:,0].argmax(-1).tolist(),
            'predicted_gain':{k:v.tolist() for k,v in predictions.items()}}


def fit(args):
    t=time.perf_counter()
    d=args.output
    d.mkdir(parents=True,exist_ok=False)
    train, tb = panel(args.root,args.old,'train')
    dev, db = panel(args.root,args.old,'dev')
    exclude(ids(train),ids(dev))
    models, pred, cv, timing = fit_all(train,dev)
    write(d/'fit_cost.json',timing)
    validation, training = scores(dev,pred), scores(train,cv)
    def rank(name):
        return (round(validation[name]['utility'],12),round(validation[name]['worst_delta_free'],12),
                round(training[name]['utility'],12),-selector.POLICIES.index(name))
    ordered=sorted(selector.POLICIES,key=rank,reverse=True)
    primary=ordered[0]; active=next(p for p in ordered if p not in ('free','paid'))
    write(d/'fit.json',models)
    write(d/'selection.json',{'primary':primary,'active':active,'rank':ordered,'dev':validation,'train_out_of_source':training})
    write(d/'train_dev_traces.json',{'dev':traces(dev,pred),'train_out_of_source':traces(train,cv)})
    write(d/'seal.json',{'source':bindings(),'inputs':{'train':tb,'dev':db},
          'identities':{'train':ids(train),'dev':ids(dev)},'files':{n:digest(d/n) for n in ['fit.json','selection.json','train_dev_traces.json','fit_cost.json']},
          'heldout_scored':False,'wall_seconds':time.perf_counter()-t})
    print(primary,active)


def confirm(args):
    t=time.perf_counter()
    out=args.output; seal=read(out/'seal.json')
    if not args.expected_seal or digest(out/'seal.json') != args.expected_seal:
        raise ValueError('supply the pre-confirmation seal digest')
    if seal['source']!=bindings() or any(digest(out/n)!=v for n,v in seal['files'].items()):
        raise ValueError('source or selected model changed')
    for split, b in seal['inputs'].items():
        for folder, key, suffix in [('features','raw','.npz'),('semantic','camera','.npz'),('roster','roster','.json')]:
            if digest(args.root/folder/(split+suffix)) != b[key]:raise ValueError('fit-time input changed')
    test, b=panel(args.root,args.old,'test')
    for prior in seal['identities'].values():
        exclude(ids(test),prior)
    x=features(test);models=read(out/'fit.json')
    pred={m:selector.predict(m,models[m],x) for m in selector.MODELS}
    sel=read(out/'selection.json')
    evaluated=scores(test,pred)
    write(out/'test_traces.json',traces(test,pred))
    write(out/'test.json',{'primary':sel['primary'],'active':sel['active'],'metrics':evaluated,
          'identities':ids(test),'test_inputs':b,'seal':args.expected_seal,'trace_hash':digest(out/'test_traces.json'),'wall_seconds':time.perf_counter()-t})
    print(sel['primary'],evaluated[sel['primary']]['utility'],evaluated[sel['primary']]['adopt'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=['fit','confirm']);p.add_argument('root',type=Path);p.add_argument('old',type=Path)
    p.add_argument('output',type=Path);p.add_argument('--expected-seal')
    a=p.parse_args(); (fit if a.phase=='fit' else confirm)(a)
