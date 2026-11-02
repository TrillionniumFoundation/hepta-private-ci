"""Environment-only worlds and labels; no scoring fields enter client/provider."""

import numpy as np
from experiments.hcsn_missing_answers_20261101 import campaign as old

PRIMARY=("base","missing","long_tokens_128","missing_tokens_128")
SECONDARY=("two_erased","shifted_order_values")
TASK_ID={"mqar":1,"selective":2,"binding":3}


def query_keys(x):
    aliases={}
    for event in x[:-4]:
        if event[15]:aliases[int(event[19:23].argmax())]=int(event[:4].argmax())
    return [aliases[int(e[19:23].argmax())] if e[19:23].sum() else int(e[:4].argmax()) for e in x[-4:]]


def batch(task,n,seed,split,condition):
    if condition in PRIMARY:
        partial=old.batch(task,n,seed,split,condition)
        full=old.batch(task,n,seed,split,"long_tokens_128" if "128" in condition else "base")
    elif condition in SECONDARY:
        full=old.batch(task,n,seed,split,"base")
        full={k:v.copy() for k,v in full.items()}
        rng=np.random.default_rng(np.random.SeedSequence([seed,TASK_ID[task],571 if split=="dev" else 577]))
        if condition=="shifted_order_values":
            for row in range(n):
                prelude=full["x"].shape[1]-4
                events=full["x"][row,:prelude].copy()
                for event in events:
                    if event[12] or event[14]:
                        event[4:12]=0;event[4+int(rng.integers(8))]=1
                full["x"][row,:prelude]=events[rng.permutation(prelude)]
                state={}
                for event in full["x"][row,:prelude]:
                    if event[12]:state[int(event[:4].argmax())]=int(event[4:12].argmax())
                full["y"][row,-4:]=[state[k] for k in query_keys(full["x"][row])]
        partial={k:v.copy() for k,v in full.items()}
        for row in range(n):
            writes=np.flatnonzero(full["x"][row,:,12])
            erased=rng.choice(writes,2 if condition=="two_erased" else 1,replace=False)
            partial["x"][row,erased]=0;partial["observed"][row,erased]=False
    else:raise ValueError("Unknown prospective condition")
    # Evaluation-only dependency accounting. Neither client nor provider receives it.
    available=np.zeros_like(partial["observed"])
    for row in range(n):
        last={}
        for t,event in enumerate(full["x"][row,:-4]):
            if event[12]:last[int(event[:4].argmax())]=t
        for j,key in enumerate(query_keys(full["x"][row])):
            available[row,-4+j]=partial["observed"][row,last[key]]
    partial["target_available"]=available
    price_rng=np.random.default_rng(np.random.SeedSequence([seed,TASK_ID[task],919]))
    prices=price_rng.choice(np.array([.02,.08,.16,.32,.64]),n)
    assert np.array_equal(full["dt"],partial["dt"])
    assert np.array_equal(full["y"],partial["y"])
    return full,partial,prices
