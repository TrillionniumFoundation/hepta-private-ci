"""Independent CPU checks of reward flow, gradients and observation chronology."""

import math
import unittest

import numpy as np
from scipy.integrate import quad_vec
from scipy.linalg import expm
from scipy.optimize import brentq
import torch

from experiments.hcsn_distributional_v2 import distribution_kernel as finite
from .model import Classifier
from .operators import prepare_interval, reward_boundary, reward_operator, value_vectors


MEASUREMENTS = {}


def independent_generator(mu, sigma, boundary, reset, tau, *, cells=8, stages=2):
    """Assemble physical transitions directly, without the torch jump builder."""
    spacing = (boundary+2.)/cells
    centers = -2.+(np.arange(cells)+.5)*spacing
    diffusion = sigma*sigma/(2*spacing*spacing)
    up = diffusion+max(mu, 0.)/spacing
    down = diffusion+max(-mu, 0.)/spacing
    exit_rate = 2*diffusion+max(mu, 0.)/spacing
    size = cells+stages
    q, events = np.zeros((size, size)), np.zeros(size)
    for state in range(cells):
        if state:
            q[state, state-1] = down
        if state < cells-1:
            q[state, state+1] = up
        else:
            q[state, cells] = exit_rate
            events[state] = exit_rate
    for phase in range(stages-1):
        q[cells+phase, cells+phase+1] = stages/tau
    weights = np.maximum(0., 1.-np.abs(centers-reset)/spacing)
    weights /= weights.sum()
    q[-1, :cells] = stages/tau*weights
    q -= np.diag(q.sum(axis=1))
    return q, events, centers


def make_flow(parameters, slope):
    tensors = [torch.tensor(v, dtype=torch.float64) for v in parameters]
    grid = finite.Grid(cells=8, lower=-2., refractory_stages=2, fixed_rate=8.1,
                       fixed_terms=21, max_duration=.36, per_token_chunks=True)
    flow = finite.make_flow(*tensors, grid)
    flow['slope'] = torch.tensor(slope, dtype=torch.float64)
    return flow


def assert_state_close(test, a, b, *, atol=2e-12):
    if isinstance(a, dict):
        test.assertEqual(set(a), set(b))
        for key in a:
            assert_state_close(test, a[key], b[key], atol=atol)
    else:
        torch.testing.assert_close(a, b, atol=atol, rtol=atol)


class RewardFlowAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous_threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.previous_threads)

    def test_repeat_count_and_signed_running_integral_against_expm(self):
        parameters = (.6, .45, .8, -.1, .4)
        q, count, centers = independent_generator(*parameters)
        errors = []
        maximum_count = 0.
        for slope in (-.06, .04):
            flow = make_flow(parameters, slope)
            matrix = np.zeros((12, 12))
            matrix[:10, :10] = q
            matrix[:10, 10] = count
            matrix[:8, 11] = slope*centers
            for duration in (0., .037, .36, .361, 1.07, 12.37):
                transition, integral = reward_operator(flow, torch.tensor(duration, dtype=torch.float64))
                reference = expm(matrix*duration)
                observed = torch.cat((transition, integral), -1).detach().numpy()
                error = float(np.max(np.abs(observed-reference[:10])))
                errors.append(error)
                maximum_count = max(maximum_count, float(integral[:, 0].max()))
                self.assertLess(error, 5e-9)
                self.assertLess(float(np.max(np.abs(observed[:, :10].sum(1)-1))), 2e-12)
        self.assertGreater(maximum_count, 1.)
        MEASUREMENTS['expm'] = {'cases': len(errors), 'max_abs_error': max(errors),
                                'max_expected_repeat_count': maximum_count,
                                'absolute_tolerance': 5e-9}

    def test_own_policy_values_against_dense_solve_and_discounted_flow(self):
        parameters = (.17, .47, 1.2, -.13, .7)
        rho, cost, slope = .43, .52, -.035
        flow = make_flow(parameters, slope)
        values = value_vectors(flow, *[torch.tensor(v, dtype=torch.float64)
                                      for v in (rho, cost, slope)])
        q, count, centers = independent_generator(*parameters)
        running = np.r_[slope*centers, [0., 0.]]
        rhs = running+count*(parameters[2]-cost)
        discounted = q-rho*np.eye(10)
        reference = np.linalg.solve(-discounted, rhs)
        integral, estimate = quad_vec(lambda t: expm(discounted*t) @ rhs,
                                      0., 50., epsabs=1e-11, epsrel=1e-11)
        integral += expm(discounted*50.) @ reference
        self.assertLess(np.max(np.abs(integral-reference)), 2e-10)
        self.assertLess(np.max(np.abs(values['J'].detach().numpy()-reference)), 2e-12)
        expected_g = np.r_[centers-cost+reference[8], reference[8:]]
        self.assertLess(np.max(np.abs(values['G'].detach().numpy()-expected_g)), 2e-12)
        MEASUREMENTS['values'] = {
            'dense_solve_max_error': float(np.max(np.abs(values['J'].detach().numpy()-reference))),
            'discounted_flow_max_error': float(np.max(np.abs(integral-reference))),
            'quad_vec_estimate_not_bound': float(estimate)}

    def test_reward_boundary_all_seven_gradients_against_independent_root(self):
        def independent(vector):
            mu, sigma, rho, cost, reset, tau, slope = vector
            k = (math.sqrt(mu*mu+2*rho*sigma*sigma)-mu)/(sigma*sigma)
            delay = (1+rho*tau/2)**-2
            particular = slope*mu/(rho*rho)
            amplitude = 1-slope/rho
            effective_cost = (cost+particular-delay*(slope*reset/rho+particular))/amplitude
            function = lambda b: k*(b-effective_cost)-1+delay*math.exp(-k*(b-reset))
            return brentq(function, effective_cost, effective_cost+1/k,
                          xtol=1e-14, rtol=1e-14)

        records = []
        for vector in ((.1, .45, .45, .525, -.1, .75, -.0275),
                       (-.18, .6, .5, .6, -.2, .9, .04)):
            tensors = tuple(torch.tensor(v, dtype=torch.float64, requires_grad=True) for v in vector)
            result = reward_boundary(*tensors)
            derivatives = torch.autograd.grad(result, tensors)
            self.assertLess(abs(float(result.detach())-independent(vector)), 2e-12)
            for index, derivative in enumerate(derivatives):
                h = 1e-5
                plus, minus = list(vector), list(vector)
                plus[index] += h; minus[index] -= h
                fd = (independent(plus)-independent(minus))/(2*h)
                error = abs(float(derivative)-fd)
                self.assertLess(error, 2e-7*(1+abs(fd)))
                records.append({'parameter': index, 'autograd': float(derivative),
                                'independent_fd': fd, 'absolute_error': error})
        MEASUREMENTS['boundary_gradients'] = {'directions': records,
            'max_absolute_error': max(r['absolute_error'] for r in records)}

    def test_full_chunk_and_prefix_causality(self):
        model = Classifier(input_dim=5, output_dim=3, width=8, physical=1, seed=43).double()
        generator = torch.Generator().manual_seed(1801)
        x = torch.randn(2, 8, 5, generator=generator, dtype=torch.float64)
        dt = torch.rand(2, 8, generator=generator, dtype=torch.float64)*.5
        observed = torch.tensor([[1, 1, 0, 0, 1, 1, 0, 1], [0, 1, 1, 0, 1, 0, 1, 1]], dtype=torch.bool)
        with torch.no_grad():
            whole, aux = model(x, dt, observed, return_aux=True)
            first, first_aux = model(x[:, :3], dt[:, :3], observed[:, :3], return_aux=True)
            last, last_aux = model(x[:, 3:], dt[:, 3:], observed[:, 3:],
                                   state=first_aux['state'], return_aux=True)
            altered_x, altered_dt = x.clone(), dt.clone()
            altered_x[:, 4:] += 30.; altered_dt[:, 4:] *= 19.
            altered = model(altered_x, altered_dt, observed)
        chunked = torch.cat((first, last), 1)
        torch.testing.assert_close(chunked, whole, atol=3e-12, rtol=3e-12)
        assert_state_close(self, last_aux['state'], aux['state'], atol=3e-12)
        torch.testing.assert_close(altered[:, :4], whole[:, :4], atol=3e-12, rtol=3e-12)
        MEASUREMENTS['causality'] = {'chunk_logit_max_error': float((chunked-whole).abs().max()),
                                     'prefix_logit_max_error': float((altered[:, :4]-whole[:, :4]).abs().max())}

    def test_missing_observation_payload_cannot_change_output_or_state(self):
        model = Classifier(input_dim=5, output_dim=3, width=8, physical=1, seed=44).double()
        generator = torch.Generator().manual_seed(1802)
        x = torch.randn(2, 8, 5, generator=generator, dtype=torch.float64)
        dt = torch.rand(2, 8, generator=generator, dtype=torch.float64)*.5
        observed = torch.tensor([[0, 1, 0, 1, 0, 0, 1, 0], [1, 0, 0, 0, 1, 0, 0, 1]], dtype=torch.bool)
        changed = x.clone(); changed[~observed] = 1000.
        with torch.no_grad():
            original, original_aux = model(x, dt, observed, return_aux=True)
            other, other_aux = model(changed, dt, observed, return_aux=True)
        torch.testing.assert_close(original, other, atol=0., rtol=0.)
        assert_state_close(self, original_aux['state'], other_aux['state'], atol=0.)
        MEASUREMENTS['missing_payload'] = {'logits_bitwise_equal': bool(torch.equal(original, other)),
                                           'state_bitwise_equal': True}

    def test_split_unobserved_wait_keeps_the_same_recovery_and_content(self):
        model = Classifier(input_dim=5, output_dim=3, width=8, physical=1, seed=47).double()
        generator = torch.Generator().manual_seed(1803)
        x = torch.randn(2, 1, 5, generator=generator, dtype=torch.float64)
        with torch.no_grad():
            _, initial = model(x, torch.full((2, 1), .1, dtype=torch.float64), return_aux=True)
            whole, whole_aux = model(x, torch.full((2, 1), .8, dtype=torch.float64),
                observed=torch.zeros(2, 1, dtype=torch.bool), state=initial['state'], return_aux=True)
            split, split_aux = model(x.expand(-1, 2, -1),
                torch.tensor([[.3, .5], [.3, .5]], dtype=torch.float64),
                observed=torch.zeros(2, 2, dtype=torch.bool), state=initial['state'], return_aux=True)
        torch.testing.assert_close(whole[:, -1], split[:, -1], atol=3e-12, rtol=3e-12)
        assert_state_close(self, whole_aux['state'], split_aux['state'], atol=3e-11)
        torch.testing.assert_close(initial['state']['cell']['recovery'],
                                   split_aux['state']['cell']['recovery'], atol=0., rtol=0.)
        MEASUREMENTS['unobserved_wait'] = {'last_logit_error': float((whole[:, -1]-split[:, -1]).abs().max()),
                                          'recovery_held_exactly': True}

    def test_interval_cost_and_reward_use_old_then_new_parameters(self):
        old_values = dict(mu=.3, sigma=.45, boundary=1.3, r=-.1, tau=.7,
                          rho=.4, K=.2, slope=-.03)
        new_values = dict(mu=-.2, sigma=.55, boundary=.8, r=-.2, tau=.8,
                          rho=.6, K=.65, slope=-.02)
        previous = {key: torch.tensor(value, dtype=torch.float64) for key, value in old_values.items()}
        current = {key: torch.tensor(value, dtype=torch.float64) for key, value in new_values.items()}
        flow = make_flow(tuple(old_values[k] for k in ('mu', 'sigma', 'boundary', 'r', 'tau')),
                         old_values['slope'])
        q, count, centers = independent_generator(*(old_values[k] for k in ('mu', 'sigma', 'boundary', 'r', 'tau')))
        old_edges, new_edges = np.linspace(-2., 1.3, 9), np.linspace(-2., .8, 9)
        remap, jump, jump_reward = np.zeros((10, 10)), np.zeros(10), np.zeros(10)
        for row in range(8):
            width = old_edges[row+1]-old_edges[row]
            for column in range(8):
                remap[row, column] = max(0., min(old_edges[row+1], new_edges[column+1])
                                        - max(old_edges[row], new_edges[column]))/width
            left = max(old_edges[row], .8)
            jump[row] = max(0., old_edges[row+1]-left)/width
            jump_reward[row] = jump[row]*((left+old_edges[row+1])/2-.65)
            remap[row, 8] = jump[row]
        remap[8:, 8:] = np.eye(2)
        augmented = np.zeros((12, 12)); augmented[:10, :10] = q
        augmented[:10, 10] = count; augmented[:8, 11] = -.03*centers
        errors = []
        for duration in (0., .72):
            reference = expm(augmented*duration)
            transition, integrals = reference[:10, :10], reference[:10, 10:]
            expected = {
                'transition': transition @ remap,
                'events': integrals[:, 0]+transition @ jump,
                'cost': .2*integrals[:, 0]+.65*(transition @ jump),
                'reward': integrals[:, 1]+(1.3-.2)*integrals[:, 0]+transition @ jump_reward,
            }
            actual = prepare_interval(previous, current, torch.tensor(duration, dtype=torch.float64), flow['grid'])
            for name, wanted in expected.items():
                error = float(np.max(np.abs(actual[name].detach().numpy()-wanted)))
                errors.append(error)
                self.assertLess(error, 2e-10)
        MEASUREMENTS['old_new_chronology'] = {'max_error': max(errors),
            'durations': [0., .72], 'old_cost': .2, 'new_cost': .65}

    def test_fixed_boundary_differs_from_frozen_parameters_and_stopped_gradient(self):
        frozen = Classifier(input_dim=5, width=8, physical=1, seed=45).double()
        fixed = Classifier(input_dim=5, width=8, physical=1, seed=45, boundary='fixed').double()
        stopped = Classifier(input_dim=5, width=8, physical=1, seed=45, boundary='stop_gradient').double()
        frozen.freeze('boundary')
        signal = torch.tensor([[.2, -.1, .5, .8, -.3, .1, .6, -.7],
                               [-.8, .5, -.2, .1, .7, -.4, -.3, .2]], dtype=torch.float64)
        bf = frozen.cell.coefficients(signal)['boundary']
        bx = fixed.cell.coefficients(signal)['boundary']
        bs = stopped.cell.coefficients(signal)['boundary']
        self.assertGreater(float((bf[0]-bf[1]).detach().abs().max()), 1e-5)
        self.assertEqual(float((bx[0]-bx[1]).abs().max()), 0.)
        torch.testing.assert_close(bf, bs, atol=0., rtol=0.)
        self.assertTrue(bf.requires_grad)
        self.assertFalse(bs.requires_grad)
        bf.sum().backward()
        self.assertTrue(all(parameter.grad is None for _, parameter in frozen.parameter_groups()['boundary']))
        self.assertGreater(float(frozen.cell.drift_input.weight.grad.abs().max()), 1e-7)
        MEASUREMENTS['freeze_semantics'] = {'frozen_boundary_variation': float((bf[0]-bf[1]).detach().abs().max()),
            'fixed_boundary_variation': float((bx[0]-bx[1]).abs().max()),
            'stop_gradient_preserves_forward_boundary': True,
            'frozen_group_has_no_parameter_gradients': True,
            'boundary_still_depends_on_live_dynamics': True}


if __name__ == '__main__':
    import argparse
    import hashlib
    import io
    import json
    import pathlib
    import sys
    import time

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    arguments = parser.parse_args()
    arguments.output.mkdir(parents=True, exist_ok=True)
    stream = io.StringIO()
    started = time.perf_counter()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RewardFlowAuditTests)
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    source = pathlib.Path(__file__).parent
    receipt = {'passed': result.wasSuccessful(), 'tests_run': result.testsRun,
               'failure_count': len(result.failures), 'error_count': len(result.errors),
               'python': sys.version, 'torch': torch.__version__, 'numpy': np.__version__,
               'wall_seconds': time.perf_counter()-started, 'measurements': MEASUREMENTS,
               'source_sha256': {name: hashlib.sha256((source/name).read_bytes()).hexdigest()
                                 for name in ('operators.py', 'model.py', 'flow_audit_tests.py')}}
    (arguments.output/'flow_audit.log').write_text(stream.getvalue())
    (arguments.output/'flow_audit.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(stream.getvalue())
    print(json.dumps(receipt, indent=2))
    raise SystemExit(0 if result.wasSuccessful() else 1)
