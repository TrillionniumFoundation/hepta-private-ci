"""Independent absolute-time, unnormalized-mass solver for the frozen 18 cells.

This intentionally does not use the package's kernel, posterior update,
branches, planner recursion, or conditional-value timing implementation.
Package functions are imported only to compare final outputs.
"""
from fractions import Fraction as F
from functools import lru_cache
from pathlib import Path
import hashlib,json,math,sys
from .model import Task,planner,evaluate

LAWS={
 'fast':[
  {('0',1):F(63,100),('1',1):F(27,100),('failure',2):F(1,10)},
  {('0',1):F(27,100),('1',1):F(63,100),('failure',2):F(1,10)}],
 'slow':[
  {('0',3):F(441,500),('1',3):F(9,500),('failure',4):F(1,10)},
  {('0',3):F(9,500),('1',3):F(441,500),('failure',4):F(1,10)}],
 'joint':[
  {('0',1):F(2,5),('1',1):F(1,20),('0',3):F(1,20),('1',3):F(2,5),('failure',2):F(1,10)},
  {('0',1):F(1,20),('1',1):F(2,5),('0',3):F(2,5),('1',3):F(1,20),('failure',2):F(1,10)}]
}

def independent(task):
 @lru_cache(None)
 def value(m0,m1,elapsed,probes):
  terminal=math.exp(-task.rho*elapsed)*float(max(m0,m1))
  best=terminal
  if elapsed==task.deadline or probes==0:return best
  for q, pair in LAWS.items():
   for cap in range(1,task.deadline-elapsed+1):
    obs={}
    for h,law in enumerate(pair):
     for (label,duration),prob in law.items():
      event=(label,duration) if duration<=cap else ('timeout',cap)
      obs.setdefault(event,[F(0),F(0)])[h]+=prob
    branch_values=[]
    for (_,duration),(p0,p1) in obs.items():
     branch_values.append(value(m0*p0,m1*p1,elapsed+duration,probes-1))
    action=-float(m0+m1)*task.fee*math.exp(-task.rho*elapsed)+math.fsum(branch_values)
    best=max(best,action)
  return best
 return value(F(1,2),F(1,2),0,task.max_probes),value.cache_info().currsize

def run():
 directory=Path(__file__).parent
 protocol=json.loads((directory/'protocol.json').read_text())
 rows=[]
 for deadline in protocol['deadline_grid']:
  for fee in protocol['launch_fee_grid']:
   t=Task(deadline=deadline,fee=fee,rho=protocol['rho'],max_probes=protocol['max_probes'])
   ref,n=independent(t)
   pol,sol=planner(t)
   got=sol(F(1,2),deadline,t.max_probes)[0]
   env=evaluate(t,pol,keep_leaves=False)['utility']
   rows.append({'deadline':deadline,'fee':fee,'independent_absolute_time_value':ref,'package_dp_value':got,'package_enumeration_value':env,'abs_error':max(abs(ref-got),abs(ref-env)),'independent_states':n})
 max_error=max(x['abs_error'] for x in rows)
 if max_error>2e-13:raise AssertionError(max_error)
 # Correlated label/time informativeness, computed directly from the manual table.
 j=LAWS['joint'];kl=sum(float(p)*math.log(float(p/j[1][event])) for event,p in j[0].items())
 payload={'review_scope':'independent second implementation for the frozen bounded model; not external institutional review','source_sha256':{x:hashlib.sha256((directory/x).read_bytes()).hexdigest() for x in ['model.py','study.py','README.md','protocol.json']},'case_count':len(rows),'max_abs_value_error':max_error,'manual_joint_kl':kl,'analytic_joint_kl':.7*math.log(8),'rows':rows}
 out=directory/'evidence/independent_model_review.json'
 out.write_text(json.dumps(payload,indent=2)+'\n')
 print(json.dumps({'cases':len(rows),'max_error':max_error,'joint_kl':kl,'output':str(out)}))
if __name__=='__main__':run()
