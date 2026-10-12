"""Independent forward-world and source arithmetic; no runtime belief or planner."""
from itertools import permutations,product
import math
import hashlib
from pathlib import Path
import re
from four_gate_common import digest,require,strict_loads,canonical
from fbsde_effect_data import generate,SEED,FRAMES,STRATA

OPS=tuple(permutations(range(3)));SWAPS=(1,2,5);ALL=tuple(range(6))
ARMS=('swap_two','swap_probe','expand_two','expand_audit','permutation_one','permutation_two','permutation_probe','event_probe','exact')


def actual(public):
    names=public['names'];held=list(range(3));effects=[];name=r'([A-Z][a-z]+)'
    patterns=(rf'{name} exchanges parcels with {name}; {name} keeps their parcel\.',
        rf'{name}, {name}, and {name} keep their parcels without any exchange\.',
        rf'{name} gives to {name}, \2 gives to {name}, and \3 gives to \1\.',
        rf'{name} exchanges with {name} only if \1 currently holds amber; {name} keeps theirs\.',
        rf'{name} copies the parcel held by {name}; {name} keeps theirs\.')
    for text in public['events']:
        matched=[(i,re.fullmatch(p,text)) for i,p in enumerate(patterns) if re.fullmatch(p,text)]
        require(len(matched)==1,'independent source grammar');kind,m=matched[0]
        a,b,c=[names.index(x) for x in m.groups()];p=list(range(3))
        if kind==0 or kind==3 and held[a]==0:p[a],p[b]=b,a
        elif kind==2:p[a],p[b],p[c]=c,a,b
        elif kind==4:p[a]=b
        effects.append(tuple(p));held=[held[j] for j in p]
    return effects,held[public['query']]


class Reference:
    def __init__(self,public,grouping,supports,revision):
        self.public=public;names=public['names'];keys=[];emissions=[]
        for i,text in enumerate(public['events']):
            tokens=re.split('([A-Z][a-z]+)',text);ordered=list(dict.fromkeys(t for t in tokens if t in names))
            ordered.extend(n for n in names if n not in ordered)
            canonical=''.join('{R'+str(ordered.index(t))+'}' if t in names else t for t in tokens)
            key=digest(['verified_role_program_v1',canonical]);keys.append(key if grouping=='frame' else digest([key,i]))
            roles=[names.index(n) for n in ordered];em=[]
            for op in OPS:em.append(OPS.index(tuple(roles[op[roles.index(j)]] for j in range(3))))
            emissions.append(em)
        unique=list(dict.fromkeys(keys));self.groups=[unique.index(k) for k in keys]
        self.reps=[keys.index(k) for k in unique];self.emissions=emissions
        self.supports=supports or [list(SWAPS) for _ in unique];self.grouping=grouping;self.revision=revision
        require(math.prod(map(len,self.supports))<=8192,'reference world bound')
        binding=digest(dict(source=digest(public),model='effect_family_revision_v1',calibration='uniform-assumed',scope='effect-family-research',generation=1))
        self.identity=digest([binding,grouping,self.supports,revision,emissions]);self.cache={};self.values={}

    def conflict(self,h):
        obs={}
        for e,o in sorted(h):
            g=self.groups[e];r=self.emissions[e].index(o)
            if g in obs and obs[g]!=r:return 'frame_conflict',obs
            obs[g]=r
        return ('outside_effect_family' if any(r not in self.supports[g] for g,r in obs.items()) else None),obs

    def state(self,h):
        if h in self.cache:return self.cache[h]
        kind,obs=self.conflict(h);require(kind is None,'reference unsupported history')
        rows=[]
        for choices in product(*self.supports):
            if any(choices[g]!=r for g,r in obs.items()):continue
            held=list(range(3))
            for e,g in enumerate(self.groups):held=[held[j] for j in OPS[self.emissions[e][choices[g]]]]
            rows.append((choices,held[self.public['query']]))
        p=[sum(v==j for _,v in rows)/len(rows) for j in range(3)]
        available=[e for g,e in enumerate(self.reps) if g not in obs]
        laws={e:[sum(self.emissions[e][c[self.groups[e]]]==j for c,_ in rows)/len(rows) for j in ALL] for e in available}
        self.cache[h]=(p,available,laws);return self.cache[h]

    def choose(self,h,depth):
        if (h,depth) in self.values:return self.values[h,depth]
        p,available,laws=self.state(h);label=max(range(3),key=lambda j:(p[j],-j));value=max(0.,2*p[label]-1)
        action='abstain' if value==0 else f'answer:{label}'
        if depth and available and value<1-.02-1e-12:
            for e in available:
                v=math.fsum(q*self.choose(tuple(sorted(h+((e,j),))),depth-1)[0] for j,q in enumerate(laws[e]) if q>0)-.02
                if v>value+1e-12:value,action=v,f'verify:{e}'
        self.values[h,depth]=(value,action);return value,action


def audit(root):
    root=Path(root)
    def read(n):
        p=root/(n+'.json');require(p.is_file() and not p.is_symlink() and p.stat().st_size<=64*1024*1024,'bounded artifact')
        return strict_loads(p.read_bytes())
    def ns(n):require(type(n) is int and n>=0,'nonnegative CPU');return n
    require(not (root/'failure.json').exists(),'incomplete study')
    rows=read('inputs');design=read('design');result=read('results');outputs={a:read(a) for a in ARMS};targets={}
    require(rows==generate() and digest(rows)==design['input_sha256'] and design['arms']==list(ARMS) and
        (design['seed'],design['checks'],design['nodes'],design['cpu_ns'],design['worlds'])==(SEED,2,20000,100_000_000,8192), 'frozen design')
    require(all([r['source_id'] for r in out]==[r['public']['source_id'] for r in rows] for out in outputs.values()),'complete ordered outputs')
    require(design['profile']==result['profile']=='effect_family_revision_v1' and design['frames']==list(FRAMES) and
            result['production_promotion_permitted'] is False and result['independent_risk_certified'] is False, 'scope and design identity')
    streams=read('streams');require(set(streams)==set(ARMS),'complete original streams');payload=0
    for arm,records in outputs.items():
        raw=(root/(arm+'.json')).read_bytes();meta=streams[arm];size=sum(len(canonical(v)) for v in records)
        require(meta==dict(file_sha256=hashlib.sha256(raw).hexdigest(),rows=len(records),serialized_payload_bytes=size,native_durability_claimed=False), 'original record bytes')
        payload+=size
    require(payload==result['record_payload_bytes']<=256*1024*1024,'record allocation total')
    summary={s:{a:dict(cases=0,correct=0,answered=0,checks=0,revisions=0,cpu_ns=0) for a in ARMS} for s in STRATA}
    for index,row in enumerate(rows):
        public=row['public'];effects,truth=actual(public);targets[public['source_id']]=truth
        for arm in ARMS:
            r=outputs[arm][index];h=();used=0;ri=0;p=None;holder=None;reason=None
            require(r['arm']==arm and r['semantic_certificate'] is False and r['production_promotion_permitted'] is False,'non-authorizing identity')
            if arm=='exact':
                holder=truth;reason='exact_registered_simulator';require(not r['checks'] and not r['revisions'] and not r['decisions'],'exact independent execution')
            else:
                grouping='event' if arm=='event_probe' else 'frame';ref=Reference(public,grouping,None,0)
                if arm.startswith('permutation') or arm=='event_probe':ref=Reference(public,grouping,[ALL]*len(ref.supports),0)
                require(ref.identity==r['initial_sha256'],'initial family binding')
                for turn,d in enumerate(r['decisions']):
                    p,available,_=ref.state(h);unqueried=[i for i in range(len(effects)) if i not in dict(h)]
                    forced=turn==0 and arm in ('swap_probe','expand_two','expand_audit')
                    repeat=arm=='expand_audit' and turn==1 and any(ref.groups[i]==ref.groups[r['checks'][0]['event']] for i in unqueried)
                    if forced:action='verify:0'
                    elif repeat:action='verify:'+str(next(i for i in reversed(unqueried) if ref.groups[i]==ref.groups[r['checks'][0]['event']]))
                    elif arm.endswith('probe'):
                        support=[j for j,x in enumerate(p) if x>0];action=f'answer:{support[0]}' if len(support)==1 else f'verify:{available[0]}' if available and used<2 else 'abstain'
                    else:
                        value,action=ref.choose(h,min(2-used,1 if arm=='permutation_one' else 2))
                        require(d['plan']['action']==action and abs(d['plan']['value']-value)<1e-10,'original Bellman objective')
                    require(d['action']==action and d['known']==[list(x) for x in h] and d['probabilities']==p and d['forced']==forced and d['repeat_audit']==repeat and
                        d['problem_sha256']==ref.identity and ns(d['cpu_ns'])<=100_000_000 and 0<=ns(d['nodes'])<=20000,'public action and budget')
                    if not action.startswith('verify:'):
                        holder=None if action=='abstain' else int(action.split(':')[1]);reason='insufficient_support' if holder is None else 'family_conditional_answer';break
                    e=int(action.split(':')[1]);require(e in unqueried and used<2,'no phantom verification')
                    check=r['checks'][used];used+=1;ns(check['cpu_ns'])
                    require(check['event']==e and check['known_before']==[list(x) for x in h] and check['receipt']==dict(effect=list(effects[e]),source_sha256=digest(public),
                        event_sha256=digest(public['events'][e]),known_sha256=digest(h)),'selected complete evidence')
                    if effects[e] not in OPS:reason='unsupported_nonbijective_effect';p=None;break
                    nxt=tuple(sorted(h+((e,OPS.index(effects[e])),)));kind,obs=ref.conflict(nxt)
                    if kind:
                        if arm not in ('expand_two','expand_audit') or kind=='frame_conflict' and arm!='expand_audit':reason=kind;p=None;break
                        rev=r['revisions'][ri];ri+=1
                        grouping='event' if kind=='frame_conflict' else ref.grouping
                        supports=[ALL]*len(effects) if kind=='frame_conflict' else [ALL if g in obs and obs[g] not in s else s for g,s in enumerate(ref.supports)]
                        new=Reference(public,grouping,supports,ref.revision+1);new.state(nxt)
                        require(rev==dict(reason=kind,from_sha256=ref.identity,to_sha256=new.identity,history_sha256=digest(nxt),supports=[list(s) for s in supports],
                            grouping=grouping,revision=new.revision,remaining_checks=2-used,cpu_ns=ns(rev['cpu_ns'])) and rev['cpu_ns']<=100_000_000,'revision preserves evidence and budget')
                        ref=new
                    h=nxt
                else:raise ValueError('unfinished reference policy')
                require(turn==len(r['decisions'])-1 and used==len(r['checks']) and ri==len(r['revisions']) and r['final_known']==[list(x) for x in h] and r['final_sha256']==ref.identity and r['probabilities']==p,'terminal revision trace')
                require(ns(r['build_cpu_ns'])>=sum(v['cpu_ns'] for v in r['revisions']),'unpaid revision')
            require((r['holder'],r['reason'],r['text'])==(holder,reason,'Insufficient evidence; abstain.' if holder is None else ('amber','blue','coral')[holder]),'rendered outcome')
            require(ns(r['cpu_ns'])>=sum(d['cpu_ns'] for d in r['decisions'])+sum(d['cpu_ns'] for d in r['checks'])+sum(d['cpu_ns'] for d in r['revisions']),'physical envelope')
            s=summary[row['stratum']][arm];s['cases']+=1;s['correct']+=holder==truth;s['answered']+=holder is not None;s['checks']+=len(r['checks']);s['revisions']+=len(r['revisions']);s['cpu_ns']+=r['cpu_ns']
    for group in summary.values():
        for s in group.values():s['conditional_utility']=(2*s['correct']-s['answered']-.02*s['checks'])/s['cases']
    require(read('targets')==targets and result['summary']==summary,'original outcomes and cost sums')
    return dict(outputs_recomputed=len(rows)*len(ARMS),families_assumed_not_authenticated=True,production_promotion_permitted=False)
