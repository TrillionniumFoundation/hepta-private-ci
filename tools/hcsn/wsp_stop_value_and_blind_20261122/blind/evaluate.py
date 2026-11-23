"""Score the sealed five-model entrant submission without exposing holdout feedback."""
import hashlib,json,sys
from pathlib import Path
import numpy as np

design,inputs,entrant,output=map(Path,sys.argv[1:])
sys.path.insert(0,str(inputs/'pinned'))
from study_io import gen_items,context
import value_graph as vg
protocol=json.loads((design/'protocol.json').read_text())
source=json.loads((inputs/'pinned/PROTOCOL_FROZEN.json').read_text())
ctx=context(source)
rows=[]
for uid,spec in protocol['cases'].items():
    name=uid+'.npz'
    base,items=gen_items(source,inputs/'inputs',spec['fit']); net=base['network']
    perm=np.array(spec['perm']);sgn=np.array(spec['signs'])
    clean=dict(W1=np.array(net['w1'])[perm]*sgn[:,None],b1=np.array(net['b1'])[perm]*sgn,
               W2=np.array(net['w2'])[:,perm]*sgn[None,:],b2=np.array(net['b2']))
    with np.load(entrant/'output'/name,allow_pickle=False) as f:
        supplied={k:f[k] for k in clean}
    with np.load(design/'support'/name,allow_pickle=False) as f:
        assert hashlib.sha256((design/'support'/name).read_bytes()).hexdigest()==spec['file_sha256']
        damaged={k:f[k] for k in clean}
    for k in clean:
        if supplied[k].shape!=clean[k].shape or not np.isfinite(supplied[k]).all():raise ValueError(k)
    clean_dist={k:int((supplied[k]!=clean[k]).sum()) for k in clean}
    changed={k:int((supplied[k]!=damaged[k]).sum()) for k in clean}
    worlds=[]
    for wi in protocol['holdout_worlds']:
        g=items[wi]['graph']
        X,_=vg.semantic_inputs(ctx,g['public'],ctx.NumpyPolicy(base),g['states'],lambda:None)
        forward=lambda m:np.tanh(X@m['W1'].T+m['b1'])@m['W2'].T+m['b2']
        pred={k:forward(m) for k,m in [('clean',clean),('damaged',damaged),('repaired',supplied)]}
        def payoff(logits):
            p=1/(1+np.exp(-logits[:,3]))
            scores=np.c_[np.zeros(len(X)),logits[:,:3],1-2*p,2*p-1]
            choice=np.where(np.asarray(g['masks']),scores,-np.inf).argmax(axis=1)
            val,_=vg.evaluate(g,scores)
            return choice,val['utility']
        actions,orig=payoff(pred['clean']);dam,v0=payoff(pred['damaged']);rep,v1=payoff(pred['repaired'])
        worlds.append(dict(states=len(X),world=wi,max_logit_error=float(abs(pred['repaired']-pred['clean']).max()),
                 original_payoff=orig,damaged_payoff=v0,repaired_payoff=v1,
                 damaged_changed_actions=int((actions!=dam).sum()),repaired_changed_actions=int((actions!=rep).sum())))
    rows.append(dict(id=uid,fit=spec['fit'],fault=spec['fault'],edited_elements=changed,
          healthy_disagreement=clean_dist,model_hash=hashlib.sha256((entrant/'output'/name).read_bytes()).hexdigest(),worlds=worlds))
output.write_text(json.dumps(dict(protocol_hash=hashlib.sha256((design/'protocol.json').read_bytes()).hexdigest(),
       solver_hash=hashlib.sha256((entrant/'solver.py').read_bytes()).hexdigest(),results=rows),indent=2))
