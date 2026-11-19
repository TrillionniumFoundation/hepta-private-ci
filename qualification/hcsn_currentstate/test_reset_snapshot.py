"""Event-time reset snapshots remain immutable while their autograd path survives."""

from fractions import Fraction as F
import math
import unittest

import torch

from .differentiable import Atom, Flux, Physics, advance, initial, intervene


def observe(kind):
    rate = 1.7
    reset = torch.nn.Parameter(torch.tensor([.25,.75],dtype=torch.float64))
    def law(target):
        scalar = target.new_tensor
        return Physics(scalar([[-rate,0.],[0.,0.]]),scalar([rate,0.]),scalar([0.,0.]),
                       target,scalar([0.,0.]),scalar(0.),scalar(1.),scalar(.15))
    def emit(p):
        state = initial(p.lower.new_tensor([[1.,0.],[-.3,0.]]))
        return (intervene(state,p,p.lower.new_tensor([1.,0.])) if kind == 'atom'
                else advance(state,p,F(1,10)))
    current = law(reset)
    state = emit(current)
    reference = emit(law(reset.detach().clone()))
    packet = next(p for p in state.pending if isinstance(p,Atom if kind == 'atom' else Flux))
    original = packet.reset.detach().clone()
    aliases_parameter = packet.reset.data_ptr() == reset.data_ptr()
    with torch.no_grad():
        reset.copy_(reset.new_tensor([.8,.2]))
    packet_gradient, = torch.autograd.grad((packet.reset*reset.new_tensor([1.,2.])).sum(),reset,retain_graph=True)
    end = F(1,5) if kind == 'atom' else F(3,10)
    actual, expected = advance(state,current,end),advance(reference,current,end)
    future_gradient, = torch.autograd.grad((actual.active[0]*reset.new_tensor([1.,2.])).sum(),reset)
    expected_gradient = ([1.,2.] if kind == 'atom' else
                         [rate*.1*math.exp(-rate*.1),2*(-math.expm1(-rate*.1))])
    return {'kind':kind,'aliases_parameter':aliases_parameter,'emitted_reset':original.tolist(),
            'updated_parameter':reset.detach().tolist(),'retained_reset_after_update':packet.reset.detach().tolist(),
            'actual_active':actual.active.detach().tolist(),'reference_active':expected.active.detach().tolist(),
            'max_active_error':float((actual.active-expected.active).detach().abs().max()),
            'packet_reset_gradient':packet_gradient.detach().tolist(),'future_active_score_gradient':future_gradient.detach().tolist(),
            'independent_future_gradient':expected_gradient,
            'future_gradient_max_error':max(abs(a-b) for a,b in zip(future_gradient.detach().tolist(),expected_gradient))}


class ResetSnapshotTests(unittest.TestCase):
    def check_snapshot(self,kind):
        result = observe(kind)
        self.assertFalse(result['aliases_parameter'])
        self.assertEqual(result['retained_reset_after_update'],result['emitted_reset'])
        self.assertLess(result['max_active_error'],2e-13)
        self.assertEqual(result['packet_reset_gradient'],[1.,2.])
        self.assertLess(result['future_gradient_max_error'],2e-13)

    def test_atom_retains_event_reset_after_parameter_update(self):
        self.check_snapshot('atom')

    def test_flux_retains_event_reset_after_parameter_update(self):
        self.check_snapshot('flux')


if __name__ == '__main__':
    unittest.main()
