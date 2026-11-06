"""Equivalent root-influence and classical AO*/interval-Bellman priorities.

Candidate: reverse differentiation of selected max branches on a Bellman tape.
Classical strong baseline: cached-DAG forward occupancy by Kahn propagation.
Both are O(E), use identical early certificates and incremental value bounds.
"""
from collections import deque
from fractions import Fraction as F
from .contract import ORDER,key


class Partial:
    def __init__(self,c,root=None):
        self.c=c;self.data={};self.parents={};self.work=0;self.expansions=[]
        self.ensure(root or c.root)

    def ensure(self,s):
        if s not in self.data:
            terminal=self.c.terminal(s)
            self.data[s]={'expanded':False,'L':max(terminal.values()),'U':self.c.upper(s),
                'terminal':terminal,'edges':{},'QL':dict(terminal),'QU':dict(terminal)}
            self.parents[s]=set();self.work+=2*len(self.c.world_accuracy)

    def backup(self,s):
        r=self.data[s];ql=dict(r['terminal']);qu=dict(r['terminal']);self.work+=1
        for a,edges in r['edges'].items():
            self.work+=len(edges)
            ql[a]=-self.c.cost(a)+sum((p*self.data[ch]['L'] for p,ch in edges),F(0))
            qu[a]=-self.c.cost(a)+sum((p*self.data[ch]['U'] for p,ch in edges),F(0))
        previous=r['L'],r['U'],r['QL'],r['QU']
        r.update(L=max(ql.values()),U=max(qu.values()),QL=ql,QU=qu)
        return previous!=(r['L'],r['U'],r['QL'],r['QU'])

    def expand(self,s):
        r=self.data[s]
        if r['expanded']:raise ValueError('A cached state cannot be paid twice')
        r['expanded']=True;self.expansions.append(s)
        for a in self.c.information_actions(s):
            edges=self.c.responses(s,a);r['edges'][a]=edges
            self.work+=len(edges)*len(self.c.world_accuracy)
            for _,child in edges:
                self.ensure(child);self.parents[child].add(s)
        # All changes move toward greater remaining clock; shared ancestors
        # are recomputed only when a child bound changes, not a full DP sweep.
        queue=deque([s]);queued={s}
        while queue:
            state=queue.popleft();queued.remove(state)
            if self.backup(state):
                for parent in sorted(self.parents[state]):
                    if parent not in queued:queue.append(parent);queued.add(parent)

    def optimistic_action(self,s):
        r=self.data[s]
        return max((a for a in ORDER if a in r['QU']),key=lambda a:r['QU'][a])

    def certificate(self,root):
        self.work+=1
        r=self.data[root]
        best=max((a for a in ORDER if a in r['QL']),key=lambda a:r['QL'][a])
        if not r['expanded']:
            return best if r['L']==r['U'] else None
        upper_other=max((v for a,v in r['QU'].items() if a!=best),default=r['QL'][best])
        return best if r['QL'][best]>=upper_other else None


def reverse_influence(view,root):
    # Reverse-mode adjoints on the selected Bellman tape. A fixed deterministic
    # active branch is used at max ties: this is a selected subgradient.
    tape=[];visited=set();edges_seen=0
    def visit(s):
        nonlocal edges_seen
        if s in visited:return
        visited.add(s)
        r=view.data[s]
        edges=r['edges'].get(view.optimistic_action(s),()) if r['expanded'] else ()
        for _,child in edges:
            edges_seen+=1;visit(child)
        tape.append((s,edges))
    visit(root)
    adjoint={root:F(1)};frontier={}
    for s,edges in reversed(tape):
        weight=adjoint.get(s,F(0))
        if not view.data[s]['expanded']:
            frontier[s]=weight
        for p,child in edges:adjoint[child]=adjoint.get(child,F(0))+weight*p
    view.work+=len(tape)+2*edges_seen
    return frontier


def classical_occupancy(view,root):
    # O(E) forward flow on the shared DAG, not an exponential path enumerator.
    adjacency={};indegree={root:0};todo=[root];seen=set();edge_count=0
    while todo:
        s=todo.pop()
        if s in seen:continue
        seen.add(s);r=view.data[s]
        edges=r['edges'].get(view.optimistic_action(s),()) if r['expanded'] else ()
        adjacency[s]=edges
        for _,child in edges:
            edge_count+=1;indegree[child]=indegree.get(child,0)+1;todo.append(child)
    queue=deque([s for s,d in indegree.items() if d==0]);mass={root:F(1)};frontier={}
    while queue:
        s=queue.popleft()
        if not view.data[s]['expanded']:frontier[s]=mass.get(s,F(0))
        for p,child in adjacency[s]:
            mass[child]=mass.get(child,F(0))+mass.get(s,F(0))*p
            indegree[child]-=1
            if indegree[child]==0:queue.append(child)
    view.work+=len(adjacency)+2*edge_count
    return frontier


def priorities(view,root,method):
    if method not in ('candidate','classical'):
        raise ValueError('Unknown scheduler')
    weights=(reverse_influence if method=='candidate' else classical_occupancy)(view,root)
    view.work+=len(weights)
    return {s:w*(view.data[s]['U']-view.data[s]['L'])/view.c.quote(s)
            for s,w in weights.items() if w and view.data[s]['U']>view.data[s]['L']}


def solve(view,root,method,max_expansions=1000):
    view.ensure(root);trace=[]
    for iteration in range(max_expansions+1):
        action=view.certificate(root)
        if action is not None:return {'action':action,'trace':trace,'certified':True}
        if iteration==max_expansions:
            raise ArithmeticError('Unfinished certificate under the computation cap')
        scores=priorities(view,root,method)
        if not scores:raise ArithmeticError('Uncertified root has no positive frontier priority')
        state=min(scores,key=lambda s:(-scores[s],key(s)))
        trace.append({'state':key(state),'priority':scores[state]})
        view.expand(state)
        if view.work*view.c.compute_time>view.c.compute_reserve:
            raise ArithmeticError('Declared planning-clock reserve exceeded')
    raise ArithmeticError('Unfinished certificate under the computation cap')
