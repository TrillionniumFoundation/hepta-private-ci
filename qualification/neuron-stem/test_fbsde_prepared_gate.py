"""Exact arithmetic, snapshot ownership and per-request context contracts."""
import copy
from dataclasses import FrozenInstanceError
import math
import random
import unittest
from unittest.mock import patch
from four_gate_common import digest
from fbsde_depth_data import numeric_inputs, construct
from fbsde_depth_policy import scalar_score
from fbsde_outcome_policy import execute
from fbsde_prepared_gate import PreparedOutcomeGate
from fbsde_tracking_control import PlanningBudgetError
from test_fbsde_depth import weights


class PreparedGateTests(unittest.TestCase):
    def setUp(self):
        self.ctx = dict(model=digest('model'), calibration=digest('cal'), scope='depth-research', generation=3)
        self.state = weights()
        rng = random.Random(913)
        for key, value in self.state.items():
            self.state[key] = [[rng.uniform(-2,2) for _ in row] for row in value] if key.endswith('weight') else [rng.uniform(-2,2) for _ in value]
        self.gate = PreparedOutcomeGate(self.state,.37,self.ctx)

    def test_exact_score_and_old_bundle_identity(self):
        rng = random.Random(977)
        for _ in range(80):
            x = [rng.uniform(-1,1) for _ in range(15)]
            self.assertEqual(self.gate.score(x),scalar_score(self.state,x))
        for row in numeric_inputs(953,5,'context'):
            p = construct(row,self.ctx['model'],self.ctx['calibration'])
            ctx = dict(source=digest(row),**self.ctx)
            expected = digest(dict(binding=p.binding,state=self.state,threshold=.37))
            self.assertEqual(self.gate.bind(p,ctx),expected)

    def test_caller_mutation_does_not_change_snapshot(self):
        before=self.gate.score([.3]*15); identity=self.gate.identity
        self.state['value.weight'][0][0]=999.; self.ctx['model']=digest('other')
        self.assertEqual(self.gate.score([.3]*15),before)
        self.assertEqual(self.gate.identity,identity)
        with self.assertRaises(FrozenInstanceError):self.gate.threshold=.9
        with self.assertRaises(TypeError):self.gate.layers[0][0][0][0]=7

    def test_bad_tensor_shape_nonfinite_and_extra_channel_reject(self):
        for value in (True,float('nan'),float('inf')):
            state=copy.deepcopy(self.state);state['out.bias'][0]=value
            with self.assertRaises(ValueError):PreparedOutcomeGate(state,.3,self.ctx)
        for key in ('future_label','value.weight'):
            state=copy.deepcopy(self.state);state[key]=[]
            with self.assertRaises(ValueError):PreparedOutcomeGate(state,.3,self.ctx)
        for threshold in (True,-.01,1.02,float('nan')):
            with self.assertRaises(ValueError):PreparedOutcomeGate(self.state,threshold,self.ctx)

    def test_bad_features_and_confidence_law(self):
        gate=PreparedOutcomeGate(None,.7,self.ctx,kind='confidence')
        self.assertEqual(gate.score([.81]*15),1-.81)
        self.assertEqual(gate.score([math.nextafter(1.,math.inf)]+[0.]*14),
                         1-math.nextafter(1.,math.inf))
        for x in ([0.]*14,[float('inf')]*15,[True]*15):
            with self.assertRaises(ValueError):self.gate.score(x)
        with self.assertRaises(ValueError):PreparedOutcomeGate(self.state,.7,self.ctx,kind='confidence')

    def test_cross_model_calibration_scope_generation_and_source_reject(self):
        row=numeric_inputs(953,1,'context')[0];p=construct(row,self.ctx['model'],self.ctx['calibration'])
        ctx=dict(source=digest(row),**self.ctx)
        for key in ctx:
            changed=dict(ctx);changed[key]=4 if key=='generation' else digest('wrong')
            with self.assertRaises(ValueError):self.gate.bind(p,changed)

    def test_threshold_ties_preserve_exact_route_predicate(self):
        x=[.07]*15;t=scalar_score(self.state,x)
        for threshold in (t,math.nextafter(t,math.inf),math.nextafter(t,-math.inf)):
            gate=PreparedOutcomeGate(self.state,threshold,self.ctx)
            self.assertEqual(gate.score(x)>=gate.threshold,scalar_score(self.state,x)>=threshold)

    def test_runtime_full_conditional_path_matches_original(self):
        def semantic(value):
            if isinstance(value,dict):return {k:semantic(v) for k,v in value.items() if k!='cpu_ns'}
            if isinstance(value,(tuple,list)):return [semantic(x) for x in value]
            return value
        for row in numeric_inputs(941,12,'runtime'):
            p=construct(row,self.ctx['model'],self.ctx['calibration'])
            ctx=dict(source=digest(row),**self.ctx)
            truth=p.worlds[0][1]
            reveal=lambda event:truth[p.groups[event]]
            bundle=dict(binding=p.binding,state=self.state,threshold=.37)
            a=execute(p,'outcome_outcome',reveal,bundle)
            b=execute(p,'outcome_outcome',reveal,prepared=self.gate,context=ctx)
            self.assertEqual(semantic(a),semantic(b))

    def test_prepared_binding_fails_before_any_revelation(self):
        row=numeric_inputs(953,1,'context')[0];p=construct(row,self.ctx['model'],self.ctx['calibration'])
        called=[];ctx=dict(source=digest('wrong'),**self.ctx)
        with self.assertRaises(ValueError):execute(p,'outcome_outcome',called.append,prepared=self.gate,context=ctx)
        self.assertEqual(called,[])
        with self.assertRaises(ValueError):execute(p,'confidence_outcome',called.append,prepared=self.gate,context=ctx)

    def test_original_cpu_limit_still_rejects_compiled_use(self):
        row=numeric_inputs(953,1,'context')[0];p=construct(row,self.ctx['model'],self.ctx['calibration'])
        clock=[0]
        def now():clock[0]+=40_000_000;return clock[0]
        with patch('time.process_time_ns',side_effect=now):
            with self.assertRaises(PlanningBudgetError):
                execute(p,'outcome_outcome',lambda _:0,prepared=self.gate,context=dict(source=digest(row),**self.ctx))

if __name__=='__main__':unittest.main()
