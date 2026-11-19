"""Independent dynamic Bellman identity on actual joint delayed flow."""

from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path('/workspace/scratch/c06d659c1e72')
sys.path[:0] = [str(ROOT / p) for p in ('spatial', 'joint-dde', 'hcsn-repair')]
from qualification.hcsn_joint_dde.model import JointModel, Packet
from qualification.hcsn_boundary_audit.spatial_generator import KilledSpatialGenerator
from review_coupled import active_reference


def identity(path):
    value = Path(path).read_bytes()
    return {'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()}


def main(output):
    started = time.perf_counter()
    paths = [Path(sys.modules[c.__module__].__file__) for c in (JointModel, Packet, KilledSpatialGenerator)]
    paths += [Path(__file__), Path(__file__).with_name('review_coupled.py'), Path(__file__).with_name('phase_type_reference.py')]
    before = {str(p): identity(p) for p in paths}
    model = JointModel(KilledSpatialGenerator(32,2.,-.12,.35), .5,.2,.15)
    transient, lower, upper, reset = model.ingredients()
    p = np.zeros(33); p[8]=1
    values, reset_value = model.perpetual()
    cases=[]
    for name, active, packets in (
        ('active_point',p,()),
        ('phase_atom',p*0,(Packet('atom',Fraction(7,100),Fraction(7,100),1,(2,-3)),)),
    ):
        qtimes=[0.,.052,.07,.173,.27,.417,.83,1.]
        result=model.solve(qtimes,active,np.column_stack((2*active,-3*active)),packets,
                           rtol=2e-11,atol=2e-13,max_step=.01)
        expected_initial=float(active@values)+sum(float(packet.mass)*math.exp(-model.discount*float(packet.start))*reset_value for packet in packets)
        initial=np.array([1.,2.,-3.])*expected_initial
        checks=[]
        for row in result['rows']:
            terminal=row['active'].T@values[1:-1]+row['upper']*model.active_reward/model.discount
            terminal+=row['discounted_remaining_phase']*reset_value
            accrued=model.active_reward*row['discounted_active_time']+model.hit_reward*row['discounted_events']
            actual=accrued+math.exp(-model.discount*row['time'])*terminal
            checks.append({'time':row['time'],'identity_value':actual.tolist(),
                           'initial_value':initial.tolist(),'absolute_error':abs(actual-initial).tolist()})
        last=result['rows'][-1]
        if name=='active_point':
            reference=active_reference(transient,lower,upper,p[1:-1],reset,1.,.2,.15)
        else:
            reference=active_reference(transient,lower,upper,reset,reset,.93,.2,.15)
            reference[[1,3]]*=math.exp(-.15*.07)
        actual=np.array([last['events'][0],last['discounted_events'][0],last['refractory'][0],last['discounted_active_time'][0]])
        cases.append({'case':name,'checks':checks,'maximum_identity_error':float(max(max(c['absolute_error']) for c in checks)),
                      'independent_serial_reference_M_H_R_A':reference.tolist(),'final_actual_M_H_R_A':actual.tolist(),
                      'independent_serial_absolute_error':abs(actual-reference).tolist(),'internal_steps':result['internal_steps']})
    after={str(p):identity(p) for p in paths}
    if before!=after:raise RuntimeError('executing source changed')
    report={'schema':'hcsn-independent-dynamic-value-flow-review-v1','sources':before,'source_unchanged':True,
            'cases':cases,'wall_seconds':time.perf_counter()-started,'scientific_admission':'HOLD_NO_GO',
            'limits':'one finite CTMC law with point/phase-atom initial states; no old posterior flow migration or complete trained-network gradient qualification'}
    with Path(output).open('x') as stream:
        json.dump(report,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')
    print(json.dumps(report,sort_keys=True,allow_nan=False))


if __name__=='__main__':main(sys.argv[1])
