"""Finite Bellman System-2 *control baseline*, not a stochastic FBSDE solver.

All rewards are *pre-boundary forecasts* in signed micro-utility. The terminal
labels and independent truth never enter the planner. A full FBSDE candidate must
beat this cheap deterministic baseline on subsequent blind task outcomes/cost.
"""
from __future__ import annotations

from fractions import Fraction
from functools import lru_cache

MAX_NODES = 32
MAX_ACTIONS = 5
ONE = 1_000_000


def need(flag, reason):
    if not flag:
        raise ValueError(reason)


def validate_graph(graph):
    need(type(graph) is dict and 1 <= len(graph) <= MAX_NODES, 'bounded node catalog')
    for key, actions in graph.items():
        need(type(key) is str and 0 < len(key) <= 64 and
             type(actions) is list and 1 <= len(actions) <= MAX_ACTIONS,
             'invalid public state')
        seen=set()
        for a in actions:
            need(type(a) is dict and set(a)=={'name','cost','forecast_utility','children'},
                 'unknown future/authority field')
            name=a['name']
            need(type(name) is str and 0 < len(name) <= 32 and name not in seen,
                 'invalid action identity')
            seen.add(name)
            need(type(a['cost']) is int and 0 <= a['cost'] <= 10_000 and
                 type(a['forecast_utility']) is int and
                 -ONE <= a['forecast_utility'] <= ONE, 'invalid registered forecast/cost')
            kids=a['children']
            need(type(kids) is list and len(kids) <= 3, 'oversize branch')
            if kids:
                need(all(type(c) is list and len(c)==2 and
                         type(c[0]) is str and c[0] in graph and
                         type(c[1]) is int and 0 < c[1] <= ONE for c in kids),
                     'bad child identity/probability')
                need(len({c[0] for c in kids})==len(kids) and
                     sum(c[1] for c in kids)==ONE, 'invalid probability mass')
            if name=='stop':
                need(a['cost']==0 and a['forecast_utility']==0 and not kids,
                     'stop must be legal no-op')
        need('stop' in seen,'missing abstain/stop action')
    # Structural cycles can cause a planner to fake extra depth or cost reuse.
    colors={}
    def visit(u):
        need(colors.get(u,0)!=1,'cyclic decision graph')
        if colors.get(u,0)==2:
            return
        colors[u]=1
        for a in graph[u]:
            for v,_ in a['children']:
                visit(v)
        colors[u]=2
    for node in graph:
        visit(node)


def solve(graph, start, *, budget, horizon=3, price_ppm=0, discount_ppm=900_000):
    validate_graph(graph)
    need(start in graph and type(budget) is int and 0 <= budget <= 10_000,
         'invalid subject/budget')
    need(type(horizon) is int and 0 <= horizon <= 4 and
         type(price_ppm) is int and 0 <= price_ppm <= ONE and
         type(discount_ppm) is int and 0 <= discount_ppm <= ONE,
         'invalid horizon/cost policy')
    visits=[0]
    gamma=Fraction(discount_ppm,ONE)
    price=Fraction(price_ppm,ONE)
    @lru_cache(maxsize=4096)
    def rec(node, remain, steps):
        visits[0]+=1
        need(visits[0] <= 4096,'search budget exhausted')
        # stop is sorted first and wins utility ties, reducing gratuitous work.
        best=(Fraction(0),'stop',0)
        if steps==0:
            return best
        for act in graph[node]:
            if act['name']=='stop' or act['cost'] > remain:
                continue
            score=Fraction(act['forecast_utility'],ONE)-price*act['cost']
            if act['children']:
                future=sum((Fraction(p,ONE)*rec(child,remain-act['cost'],steps-1)[0]
                            for child,p in act['children']),Fraction(0))
                score+=gamma*future
            if score>best[0]:
                best=(score,act['name'],act['cost'])
        return best
    best=rec(start,budget,horizon)
    return {'chosen_action':best[1], 'estimated_utility':float(best[0]),
            'first_action_cost':best[2], 'visited_bellman_states':visits[0],
            'horizon':horizon,'budget':budget,'oracle_outcomes_used':False,
            'continuous_fbsde_certified':False,'production_authorized':False,
            'authority':'DENY_ALL','disposition':'HOLD_NO_GO'}
