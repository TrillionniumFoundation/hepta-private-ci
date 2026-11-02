"""Independent scalar root-action/light-tail simulator over one model future."""
from dataclasses import asdict
from experiments.hcsn_v9_followup_20261101.mechanisms import campaign as v9


def run(core, initial, tick, budget, physics, matrix, config, q, pool, start, index, root):
    obs=v9.old.Observation(**asdict(initial))
    stopped=False
    pending=None
    reads=correct=0
    states=[]
    codes={'STOP':0,'WAIT':1,'READ':2}
    for t in range(tick,config.ticks+1):
        if t>tick:
            if pending==t:
                if pool['service_uniform'][index,t]<q[t]:
                    probs=[0.]*config.classes;probs[int(pool['content'][index,t-start])]=1.
                    obs=v9.old.Observation(t*config.dt,float(pool['x'][index,t-start]),
                        float(pool['refractory_remaining'][index,t-start]),probs,True)
                pending=None
            if t in config.deadlines:
                p=v9.old.predict(core,obs,t*config.dt,physics,matrix)[0]
                correct+=int(p.argmax()==pool['content'][index,t-start])
        if t==config.ticks:break
        if stopped:
            action='STOP'
        elif t==tick:
            action=root
        else:
            action,_=v9.choose(core,'lightweight',obs,t,budget,physics,matrix,config,0,q,True)
        if action=='READ':
            if budget<=0 or pending is not None:raise ValueError('Invalid scalar READ')
            budget-=1;reads+=1;pending=t+1
        elif action=='STOP':stopped=True
        states.append({'action':codes[action],'budget':budget,'pending':-1 if pending is None else pending,
                       'x':obs.x,'time':obs.time,'remaining':obs.refractory_remaining,'content':obs.content_probs[:]})
    return {'units':25*correct-4*reads,'correct':correct,'reads':reads,'states':states}
