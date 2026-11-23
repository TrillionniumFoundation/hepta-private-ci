"""Independent enumeration and causal finite-state controls for paid terminal READ.

A query ends at STOP or READ. A free WAIT advances to the next observed audio
prefix and costs running utility. A second paid acquisition has no transition
in this intervention design. Scoring receives paid ranks and hidden gold
answers. The frozen policy receives only the current free score margin and
prefix index. All comparisons weight independent source groups equally.
"""

from dataclasses import dataclass
import math

import numpy as np


STOP, READ, WAIT = range(3)
TOL = 1e-12


def _array(s, key, fallback=None):
    value = s.get(key) if key in s else s.get(fallback)
    if value is None:
        raise ValueError(f"missing {key}")
    return np.asarray(value)


def _material(s):
    f = _array(s, "scores")
    p = _array(s, "read_scores")
    label = _array(s, "target")
    dt = _array(s, "dt")
    groups = _array(s, "group", "source").astype(str)
    source = _array(s, "source", "group").astype(str)
    identities = _array(s, "query_id").astype(str)
    n = len(f)
    if (f.shape != (n,6,2) or n < 1 or p.shape != f.shape or dt.shape != f.shape[:2]
            or label.shape != (n,) or not np.isin(label,[0,1]).all()
            or groups.shape != (n,) or source.shape != (n,) or identities.shape != (n,)
            or not all(len(k) for k in (*groups,*source,*identities)) or len(np.unique(identities)) != n
            or not all(np.isfinite(a).all() for a in (f,p,dt)) or (dt<=0).any()):
        raise ValueError("invalid or duplicated six-prefix two-alternative query")
    # Multiple queries from the same source must not become independent groups.
    if any(len(set(groups[source==k]))!=1 for k in set(source)):
        raise ValueError("one recording source assigned to different groups")
    correct = np.stack((f.argmax(-1)==label[:,None],p.argmax(-1)==label[:,None]),-1)
    return f,dt,groups,identities,correct


def _law(price,rate,rho):
    if not all(math.isfinite(v) and v>=0 for v in (price,rate,rho)):
        raise ValueError("fees and discount must be finite and nonnegative")


def _running(t,rate,rho):
    return -rate*t if rho==0 else rate*np.expm1(-rho*t)/rho


def _utility(dt,correct,price,rate,rho):
    _law(price,rate,rho)
    time=dt.cumsum(1)-dt[:,:1]
    return (np.exp(-rho*time)[:,:,None]*(correct.astype(float)-np.array([0.,price]))
            +_running(time,rate,rho)[:,:,None])


def _means(values,groups):
    return {str(g):float(np.mean(values[groups==g])) for g in np.unique(groups)}


def _macro(values):
    return float(np.mean(list(values.values())))


def _diagnostic_counts(a,v):
    return {"corrected":int((~a&v).sum()),"broken":int((a&~v).sum()),
            "both_correct":int((a&v).sum()),"neither_correct":int((~a&~v).sum())}


def verify_disjoint(partitions):
    """Check roster identities without touching any FREE/READ scores or labels.

    Accept metadata-only partitions; a TEST roster can be checked while its
    outcomes remain sealed. Provenance for aliases must already be resolved by
    the caller into canonical creator/master IDs.
    """
    scopes={}
    for name,s in partitions.items():
        ids=_array(s,"query_id").astype(str)
        groups=_array(s,"group","source").astype(str)
        sources=_array(s,"source","group").astype(str)
        if ids.ndim!=1 or len(ids)!=len(set(ids)) or groups.shape!=ids.shape or sources.shape!=ids.shape:
            raise ValueError(f"invalid source roster {name}")
        here={"query":set(ids),"creator":set(groups),"source":set(sources)}
        for earlier,old in scopes.items():
            for key in here:
                if here[key]&old[key]:
                    raise ValueError(f"{key} crosses {earlier} and {name}")
        scopes[name]=here
    return {name:{k:len(x) for k,x in value.items()} for name,value in scopes.items()}


def opportunity(s, *, price=.30, rate=.40, rho=.20):
    """Enumerate all twelve potential terminal interventions per query.

    Paid gain compares joint clairvoyance with equally clairvoyant FREE stopping.
    WAIT gain compares joint clairvoyance with per-query best immediate action.
    Neither contrast is an estimate of deployable policy performance.
    """
    _,dt,group,ids,c=_material(s)
    u=_utility(dt,c,price,rate,rho)
    # argmax resolves a tie by earliest prefix, then lower cost STOP first.
    best=u.reshape(len(c),-1).argmax(1)
    joint=u.reshape(len(c),-1).max(1)
    paid=joint-u[:,:,STOP].max(1)
    wait=joint-u[:,0,:].max(1)
    paid_group,wait_group=_means(paid,group),_means(wait,group)
    paid_mean,wait_mean=_macro(paid_group),_macro(wait_group)
    p_count=sum(v>TOL for v in paid_group.values())
    w_count=sum(v>TOL for v in wait_group.values())
    paid_ok=paid_mean>=.03-TOL and p_count>=2
    wait_ok=wait_mean>=.015-TOL and w_count>=2
    return dict(eligible=paid_ok,paid_gate_pass=paid_ok,wait_gate_pass=wait_ok,
                paid_gain_mean=paid_mean,wait_gain_mean=wait_mean,
                paid_positive_groups=p_count,wait_positive_groups=w_count,
                paid_gain_by_source=paid_group,wait_gain_by_source=wait_group,
                paid_gain_by_query=dict(zip(ids,paid.tolist())),wait_gain_by_query=dict(zip(ids,wait.tolist())),
                n_queries=len(c),n_groups=len(paid_group),n_paid_positive_queries=int((paid>TOL).sum()),
                n_wait_positive_queries=int((wait>TOL).sum()),oracle_reads=int((best%2==1).sum()),
                oracle_waits=int((best//2>0).sum()),oracle_read_after_wait=int(((best%2==1)&(best//2>0)).sum()),
                oracle_joint_macro=_macro(_means(joint,group)),
                free_oracle_macro=_macro(_means(u[:,:,0].max(1),group)),
                immediate_joint_oracle_macro=_macro(_means(u[:,0].max(1),group)),
                free_at_first_macro=_macro(_means(u[:,0,0],group)),
                per_prefix_change=[_diagnostic_counts(c[:,t,0],c[:,t,1]) for t in range(6)],
                per_prefix_read_minus_free_utility=[_macro(_means(u[:,t,1]-u[:,t,0],group)) for t in range(6)],
                waiting_gates_open_test=False,repeated_paid_read_observed=False)


def outcome(s, times, actions, *, price=.30, rate=.40, rho=.20):
    """Score committed per-query terminal prefixes/actions by direct enumeration."""
    _,dt,groups,ids,c=_material(s)
    n=len(c)
    t=np.asarray(times)
    a=np.asarray(actions)
    if (t.shape!=(n,) or a.shape!=(n,) or t.dtype.kind not in "iu" or a.dtype.kind not in "iu"
            or not np.isin(a,[STOP,READ]).all() or not np.isin(t,range(6)).all()):
        raise ValueError("expected one legal terminal prefix and binary action per query")
    idx=np.arange(n)
    u=_utility(dt,c,price,rate,rho)[idx,t,a]
    hit=c[idx,t,a]
    uv,acc=_means(u,groups),_means(hit,groups)
    bought=a==READ
    switched=_diagnostic_counts(c[idx[bought],t[bought],0],c[idx[bought],t[bought],1])
    return dict(utility=_macro(uv),r1=_macro(acc),per_source=uv,per_source_r1=acc,
                episode_utility=u.tolist(),episode_hit=hit.astype(int).tolist(),query_ids=ids.tolist(),
                exit_prefix=t.tolist(),terminal_action=a.tolist(),reads=int(bought.sum()),
                read_after_wait=int((bought&(t>0)).sum()),waiting_queries=int((t>0).sum()),
                wait_steps=int(t.sum()),reads_change_at_same_prefix=switched)


def _margin(scores):
    if scores.ndim!=3 or scores.shape[1:]!=(6,2) or not np.isfinite(scores).all():
        raise ValueError("expected finite free scores [N,6,2]")
    return np.abs(scores[:,:,0]-scores[:,:,1])


def _table(edges,scores,dt,correct,groups,price,rate,rho,allow_read):
    """Train expected STOP/READ and WAIT return under the next learned policy.

    Use source-balanced example weights, four margin bins and shrink each
    bin toward the same-prefix unconditional mean by one average-weight row.
    The next action comes from the next fitted table. Its *realized return*
    supplies the current WAIT target, not the best future answer in hindsight.
    """
    bins=np.searchsorted(edges,_margin(scores))
    q=np.empty((6,4,3),dtype=float)
    n=len(scores)
    weights=np.empty(n)
    for g in np.unique(groups):
        take=groups==g
        weights[take]=n/(len(np.unique(groups))*take.sum())
    realized=np.zeros(n)
    for t in reversed(range(6)):
        rewards=np.empty((n,3))
        rewards[:,STOP]=correct[:,t,0]
        rewards[:,READ]=correct[:,t,1].astype(float)-price
        if t<5:
            h=dt[:,t+1]
            rewards[:,WAIT]=np.exp(-rho*h)*realized+_running(h,rate,rho)
        else:
            rewards[:,WAIT]=rewards[:,STOP]
        prior=np.average(rewards,axis=0,weights=weights)
        for b in range(4):
            at=bins[:,t]==b
            q[t,b]=(weights[at]@rewards[at]+prior)/(weights[at].sum()+1)
        current=q[t,bins[:,t]].copy()
        if not allow_read:
            current[:,READ]=-np.inf
        if t==5:
            current[:,WAIT]=-np.inf
        realized=rewards[np.arange(n),current.argmax(1)]
    return q


@dataclass
class CausalChooser:
    edges: np.ndarray
    q: np.ndarray
    q_no_read: np.ndarray
    price: float
    rate: float
    rho: float

    def state_dict(self):
        return dict(edges=self.edges.tolist(),q=self.q.tolist(),q_no_read=self.q_no_read.tolist(),
                    price=self.price,rate=self.rate,rho=self.rho)

    @classmethod
    def from_state_dict(cls,state):
        edges,q,qn=(np.asarray(state[k],dtype=float) for k in ("edges","q","q_no_read"))
        if (edges.shape!=(3,) or q.shape!=(6,4,3) or qn.shape!=q.shape
                or (np.diff(edges)<0).any() or not all(np.isfinite(a).all() for a in (edges,q,qn))):
            raise ValueError("invalid table payload")
        _law(state["price"],state["rate"],state["rho"])
        return cls(edges,q,qn,state["price"],state["rate"],state["rho"])

    def acts(self, free_scores, restricted=None):
        if restricted not in (None,"mask_read","refit_no_read","immediate","always_stop","always_read"):
            raise ValueError("unknown policy restriction")
        free=np.asarray(free_scores)
        bins=np.searchsorted(self.edges,_margin(free))
        n=len(free)
        if restricted in ("always_stop","always_read"):
            return np.zeros(n,dtype=int),np.full(n,int(restricted=="always_read"),dtype=int)
        tables=self.q_no_read if restricted=="refit_no_read" else self.q
        # Lookup of a given prefix uses only its own free score. Future lookups
        # in this vector implementation cannot influence an earlier decision.
        score=tables[np.arange(6)[None,:],bins].copy()
        if restricted in ("mask_read","refit_no_read"):
            score[:,:,READ]=-np.inf
        if restricted=="immediate":
            score[:,:,WAIT]=-np.inf
        score[:,-1,WAIT]=-np.inf
        acts=score.argmax(-1)
        times=(acts!=WAIT).argmax(1)
        return times,acts[np.arange(n),times]


def fit_causal(train, *, price=.30, rate=.40, rho=.20):
    _law(price,rate,rho)
    f,dt,groups,_,c=_material(train)
    edges=np.quantile(_margin(f),[.25,.50,.75])
    inputs=(edges,f,dt,c,groups,price,rate,rho)
    return CausalChooser(edges,_table(*inputs,True),_table(*inputs,False),price,rate,rho)


def _contrast(a,b,confidence):
    ax,bx=a["per_source"],b["per_source"]
    if set(ax)!=set(bx):
        raise ValueError("unpaired source roster")
    diffs={k:ax[k]-bx[k] for k in ax}
    n=len(diffs); vals=sorted(diffs.values())
    k=sum(d>TOL for d in vals); ties=sum(abs(d)<=TOL for d in vals)
    # Count ties as non-wins. The exact binomial tail tests P(group gain>0)>.5
    # under independent groups, conservatively for data with an atom at zero.
    p=sum(math.comb(n,i) for i in range(k,n+1))/(2**n)
    alpha=1-confidence
    allowed=[i for i in range(n) if sum(math.comb(n,j) for j in range(i+1))/(2**n)<=alpha]
    lower=vals[max(allowed)] if allowed else None
    return dict(mean_paired_source_gain=_macro(diffs),per_source=diffs,n=n,positive=k,ties=ties,
                negative=n-k-ties,exact_one_sided_sign_p=p,
                one_sided_median_lower=lower,confidence=confidence)


FRONTENDS = ("handwritten_visual", "trained_visual", "imagenet_visual", "imagenet_fusion")
IMMEDIATE = ("immediate", "always_stop", "always_read")


def evaluate(chooser, s, *, stage="development", immediate_baseline=None, confidence=.95):
    if not .5<confidence<1 or stage not in ("development","confirmation"):
        raise ValueError("invalid confidence or stage")
    if stage=="confirmation" and immediate_baseline not in IMMEDIATE:
        raise ValueError("confirmation requires the one immediate baseline already locked on DEV")
    f=_array(s,"scores")
    policies={}
    for key in ("full","mask_read","refit_no_read",*IMMEDIATE):
        t,a=chooser.acts(f,None if key=="full" else key)
        policies[key]=outcome(s,t,a,price=chooser.price,rate=chooser.rate,rho=chooser.rho)
    # The twelve unconditional exits are fixed descriptive controls; validation
    # or confirmation does not select one as a deployable common rule.
    n=len(f)
    fixed={}
    for prefix in range(6):
        for action in (STOP,READ):
            t=np.full(n,prefix,dtype=int)
            a=np.full(n,action,dtype=int)
            obs=outcome(s,t,a,price=chooser.price,rate=chooser.rate,rho=chooser.rho)
            name=f"{'stop' if action==STOP else 'read'}_at_{prefix}"
            fixed[name]={k:obs[k] for k in ("utility","r1","per_source","reads_change_at_same_prefix")}
    if stage=="development":
        immediate_baseline=max(IMMEDIATE,key=lambda k:policies[k]["utility"])
    primary=("refit_no_read",immediate_baseline)
    adjusted=1-(1-confidence)/len(primary)
    gains={k:_contrast(policies["full"],policies[k],adjusted if k in primary else confidence)
           for k in ("refit_no_read",*IMMEDIATE,"mask_read")}
    positive=all(gains[k]["mean_paired_source_gain"]>TOL for k in primary)
    support=positive and all(gains[k]["exact_one_sided_sign_p"]<=1-adjusted+TOL for k in primary)
    return dict(stage=stage,policies=policies,fixed_exits=fixed,contrasts=gains,primary_comparators=list(primary),
                immediate_baseline=immediate_baseline,development_practical_pass=positive,
                confirmatory_pass=(support if stage=="confirmation" else None),
                inference="Exact one-sided source sign tests assume independent groups and assess a typical-group directional effect. Paired macro means are descriptive. Bonferroni across two primary contrasts; other contrasts descriptive.")


def select_frontend(panels, *, max_candidates=4):
    """Read TRAIN/DEV only. Rank all prospectively eligible vision frontends once."""
    if not 1<=len(panels)<=max_candidates or not set(panels)<=set(FRONTENDS):
        raise ValueError("frontend roster absent, unknown or exceeds the frozen cap")
    qualified=[k for k,v in panels.items()
               if v.get("available",True) and v["train"]["eligible"] and v["dev"]["eligible"]]
    def ordering(k):
        r=panels[k]["dev_policy"]
        if r["stage"]!="development":
            raise ValueError("only the frozen development policy may rank a frontend")
        lower=min(r["contrasts"][name]["mean_paired_source_gain"] for name in r["primary_comparators"])
        return (lower<=TOL,-lower,-r["policies"]["full"]["utility"],FRONTENDS.index(k))
    return min(qualified,key=ordering) if qualified else None
