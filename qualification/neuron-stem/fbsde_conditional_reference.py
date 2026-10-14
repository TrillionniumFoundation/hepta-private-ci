"""Independent finite-state transition tables; imports no runtime belief/planner."""
from itertools import permutations, product
import math
import re
from four_gate_common import digest, require

OPS=tuple(permutations(range(3)))
RULES=tuple((-1,-1,e) for e in range(6))+tuple((r,c,e) for r in range(3) for c in range(3)
    for e,p in enumerate(OPS) if sum(i!=p[i] for i in range(3))==2)


def actual(public):
    held=list(range(3));effects=[]
    name=r'([A-Z][a-z]+)'
    for k,text in enumerate(public['events']):
        effect=list(range(3));n=public['names']
        conditional=re.fullmatch(name+r' exchanges with '+name+r' if '+name+r' holds (amber|blue|coral); '+name+r' waits\.',text)
        constant=re.fullmatch(name+r' and '+name+r' exchange items while '+name+r' waits\.',text)
        time_rule=re.fullmatch(name+r' and '+name+r' exchange on even numbered events; '+name+r' waits\.',text)
        copy=re.fullmatch(name+r' takes a copy of the item of '+name+r'; '+name+r' waits\.',text)
        if conditional:
            a,b,g,colour,c=conditional.groups(); active=held[n.index(g)]==('amber','blue','coral').index(colour)
        elif constant or time_rule:
            a,b,c=(constant or time_rule).groups();active=bool(constant) or (k+1)%2==0
        elif copy:
            a,b,c=copy.groups();active=False;effect[n.index(a)]=n.index(b)
        else:raise ValueError('unrecognized independent source')
        require(len({a,b,c})==3 and set((a,b,c))==set(n),'source roles')
        if active: effect[n.index(a)],effect[n.index(b)]=n.index(b),n.index(a)
        effects.append(tuple(effect));held=[held[j] for j in effect]
    return effects,held[public['query']]


class Reference:
    def __init__(self, public, family='conditional', initial=(0,1,2)):
        self.public=public; rules=RULES[:6] if family=='constant' else RULES
        keys=[];coords=[];names=public['names']
        for text in public['events']:
            pattern=r'\b(?:'+'|'.join(map(re.escape,names))+r')\b'
            order=list(dict.fromkeys(re.findall(pattern,text)));order += [n for n in names if n not in order]
            frame=re.sub(pattern,lambda m:'{R'+str(order.index(m[0]))+'}',text)
            keys.append(digest(['verified_role_program_v1',frame]));coords.append([names.index(n) for n in order])
        unique=list(dict.fromkeys(keys));groups=[unique.index(k) for k in keys];self.groups=groups
        require(len(rules)**len(unique)<=8192,'reference capacity')
        binding=digest(dict(source=digest(public),initial=initial,model='conditional_program_induction_v1',
            calibration='uniform-program-assumption',scope='conditional-program-research',generation=1))
        self.identity=digest([binding,family,rules,keys,groups]);self.rows=[];self.states={};self.values={}
        # Compile all possible predecessor states, rather than calling transition().
        tables=[]
        for roles in coords:
            event={}
            for state in OPS:
                options=[]
                for guard,colour,effect in rules:
                    mapping=tuple(roles[OPS[effect][roles.index(j)]] for j in range(3))
                    if guard!=-1 and state[roles[guard]]!=colour:mapping=(0,1,2)
                    options.append((OPS.index(mapping),tuple(state[j] for j in mapping)))
                event[state]=options
            tables.append(event)
        for assigned in product(range(len(rules)),repeat=len(unique)):
            state=initial;effects=[]
            for i,g in enumerate(groups):
                effect,state=tables[i][state][assigned[g]];effects.append(effect)
            self.rows.append((assigned,tuple(effects),state[public['query']]))

    def state(self,h):
        h=tuple(sorted(h))
        if h in self.states:return self.states[h]
        rows=[r for r in self.rows if all(r[1][e]==o for e,o in h)]
        require(rows,'outside reference family')
        p=[sum(r[2]==j for r in rows)/len(rows) for j in range(3)];laws={}
        for e in range(len(self.groups)):
            if e in dict(h):continue
            counts=[sum(r[1][e]==j for r in rows) for j in range(6)]
            if sum(x>0 for x in counts)>1:laws[e]=[v/len(rows) for v in counts]
        support=[sorted({r[0][g] for r in rows}) for g in range(max(self.groups)+1)]
        posterior=dict(history_sha256=digest(h),compatible_worlds=len(rows),program_support=support,
            program_set_identified=all(len(s)==1 for s in support),semantic_certificate=False)
        self.states[h]=(p,list(laws),laws,posterior);return self.states[h]

    def choose(self,h,depth):
        if (h,depth) in self.values:return self.values[h,depth]
        p,available,laws,_=self.state(h);label=max(range(3),key=lambda j:(p[j],-j));value=max(0.,2*p[label]-1)
        action='abstain' if value==0 else f'answer:{label}'
        if depth and available and value<1-.02-1e-12:
            for e in available:
                v=math.fsum(q*self.choose(tuple(sorted(h+((e,o),))),depth-1)[0]
                           for o,q in enumerate(laws[e]) if q>0)-.02
                if v>value+1e-12:value,action=v,f'verify:{e}'
        self.values[h,depth]=(value,action);return value,action
