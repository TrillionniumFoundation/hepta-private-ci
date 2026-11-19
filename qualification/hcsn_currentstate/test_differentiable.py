"""Independent renewal/DDE references and derivatives of the complete state."""

from fractions import Fraction as F
import io
import unittest
from dataclasses import replace

import numpy as np
from scipy.integrate import quad, solve_ivp
from scipy.special import gammainc
import torch

from .differentiable import Physics, Work, advance, initial, intervene, refractory


torch.set_num_threads(1)


def physics(rates=None, reset=None):
    rates = torch.tensor([.7, .3, .6, .2, .05, .08], dtype=torch.float64) if rates is None else rates
    a, b, lo, hi = rates[0], rates[1], rates[2:4], rates[4:6]
    q = torch.stack((torch.stack((-a-lo[0]-hi[0], a)), torch.stack((b, -b-lo[1]-hi[1]))))
    reset = rates.new_tensor([.25, .75]) if reset is None else reset
    return Physics(q, lo, hi, reset, rates.new_tensor([.4, .7]), rates.new_tensor(.5),
                   rates.new_tensor(.8), rates.new_tensor(.15))


def dde_reference(laws, ends, active):
    """Method-of-steps ODE oracle; no matrix exponential or candidate imports."""
    delay = float(laws[0].delay)
    c, n = active.shape
    y = np.zeros((c, n + 5)); y[:, :n] = active
    histories = []
    knots = {0., float(ends[-1])}
    for edge in [0., *map(float, ends)]:
        for cycle in range(int(float(ends[-1]) / delay) + 2):
            t = edge + cycle * delay
            if 0 < t < float(ends[-1]):
                knots.add(t)
    knots = sorted(knots)
    for left, right in zip(knots, knots[1:]):
        index = next(i for i, end in enumerate(ends) if left < float(end))
        p = laws[index]
        q, lower, upper, reset, reward = [x.detach().numpy() for x in
            (p.generator, p.lower, p.upper, p.reset, p.reward)]
        discount, hit, escape = map(float, (p.discount, p.spike_reward, p.escape_reward))

        def rhs(t, flat):
            z = flat.reshape(c, n + 5)
            pending = np.zeros((c, n))
            past = t - delay
            if past >= 0:
                for start, end, dense, old_lower, old_reset in reversed(histories):
                    if start <= past <= end:
                        flux = dense(past).reshape(c, n + 5)[:, :n] @ old_lower
                        pending = flux[:, None] * old_reset
                        break
            derivative = np.zeros_like(z)
            derivative[:, :n] = z[:, :n] @ q + pending
            derivative[:, n] = z[:, :n] @ upper
            flux = z[:, :n] @ lower
            derivative[:, n+1] = flux
            derivative[:, n+2] = z[:, :n].sum(1) + z[:, n]
            derivative[:, n+3] = np.exp(-discount*t) * flux
            derivative[:, n+4] = np.exp(-discount*t) * (z[:, :n] @ reward + escape*z[:, n] + hit*flux)
            return derivative.ravel()

        solution = solve_ivp(rhs, (left, right), y.ravel(), method="DOP853",
                             rtol=2e-12, atol=2e-14, dense_output=True, max_step=delay/10)
        if not solution.success:
            raise RuntimeError(solution.message)
        y = solution.y[:, -1].reshape(c, n + 5)
        histories.append((left, right, solution.sol, lower, reset))
    return y


class DifferentiableCurrentStateTests(unittest.TestCase):
    def test_five_excursions_against_independent_gamma_renewal(self):
        rate, discount, t, delay = 3., .15, 1.07, .2
        scalar = lambda x: torch.tensor(x, dtype=torch.float64)
        p = Physics(scalar([[-rate]]), scalar([rate]), scalar([0.]), scalar([1.]),
                    scalar([.4]), scalar(.4), scalar(1.), scalar(discount))
        state = advance(initial(scalar([[1.], [-.7], [.3]])), p, F(107, 100))
        def hit_count(time):
            return sum(gammainc(k, rate*(time-(k-1)*delay)) for k in range(1, 7)
                       if time > (k-1)*delay)
        def waiting(time):
            return sum(gammainc(k, rate*(time-(k-1)*delay)) -
                       (gammainc(k, rate*(time-k*delay)) if time > k*delay else 0.)
                       for k in range(1, 7) if time > (k-1)*delay)
        h = sum(np.exp(-discount*(k-1)*delay)*(rate/(rate+discount))**k *
                gammainc(k, (rate+discount)*(t-(k-1)*delay))
                for k in range(1, 7) if t > (k-1)*delay)
        integral = quad(lambda s: 1-waiting(s), 0, t, points=[.2,.4,.6,.8,1.], epsabs=1e-12)[0]
        value = .4*quad(lambda s: np.exp(-discount*s)*(1-waiting(s)), 0, t,
                       points=[.2,.4,.6,.8,1.], epsabs=1e-12)[0] + h
        expected = np.array([1-waiting(t), hit_count(t), h, integral, value, waiting(t)])
        actual = torch.stack((state.active[:, 0], state.hits, state.discounted_hits,
                              state.occupation, state.value, refractory(state)), 1).detach().numpy()
        np.testing.assert_allclose(actual, np.array([1.,-.7,.3])[:,None]*expected,
                                   atol=2e-12, rtol=2e-12)

    def test_input_changes_and_signed_content_against_dde(self):
        p1 = physics(); p2 = physics(p1.lower.new_tensor([.2,.9,.1,.8,.03,.02]),
                                    p1.lower.new_tensor([.8,.2]))
        active = torch.tensor([[.65,.35], [-.4,.9], [.3,-.8]], dtype=torch.float64)
        state = advance(initial(active), p1, F(3,20))
        state = advance(state, p2, F(17,20))
        reference = dde_reference([p1,p2], [F(3,20),F(17,20)], active.numpy())
        actual = torch.cat((state.active, state.upper[:,None], state.hits[:,None],
                            state.occupation[:,None], state.discounted_hits[:,None], state.value[:,None]),1)
        np.testing.assert_allclose(actual.detach().numpy(), reference, atol=3e-10, rtol=3e-10)
        total = state.active.sum(1)+state.upper+refractory(state)
        torch.testing.assert_close(total, active.sum(1), atol=4e-13, rtol=4e-13)

    def test_partition_checkpoint_and_boundary_sweep(self):
        p = physics(); active = p.lower.new_tensor([[.6,.4],[-.3,.8]])
        start = initial(active)
        swept = intervene(start, p, p.lower.new_tensor([1.,.25]))
        torch.testing.assert_close(swept.active.sum(1)+refractory(swept), active.sum(1))
        direct = advance(swept, p, F(71,100))
        first = advance(swept, p, F(23,100))
        buffer = io.BytesIO(); torch.save(first, buffer); buffer.seek(0)
        restored = torch.load(buffer, weights_only=False)
        continued = advance(restored, p, F(71,100))
        fields = ('active','upper','hits','discounted_hits','occupation','value','discount_factor')
        for name in fields:
            torch.testing.assert_close(getattr(continued,name), getattr(direct,name), atol=2e-12, rtol=2e-12)
        torch.testing.assert_close(refractory(continued), refractory(direct), atol=2e-12, rtol=2e-12)
        self.assertGreater(continued.tensor_bytes(), 8*active.numel())

    def test_full_state_gradients_match_finite_differences(self):
        rates = torch.tensor([.7,.3,.6,.2,.05,.08], dtype=torch.float64, requires_grad=True)
        reset_logit = torch.tensor([-.3,.3], dtype=torch.float64, requires_grad=True)
        active = torch.tensor([[.6,.4],[-.3,.8]], dtype=torch.float64, requires_grad=True)
        def run(r, logits, a):
            p = physics(r, torch.softmax(logits,0))
            s = advance(initial(a), p, F(13,100))
            s = advance(s, physics(r*1.2, p.reset), F(63,100))
            return torch.cat((s.active.flatten(), s.upper, s.hits, s.value, refractory(s)))
        self.assertTrue(torch.autograd.gradcheck(run, (rates,reset_logit,active), eps=1e-6,
                                                atol=3e-7, rtol=3e-5))

    def test_explicit_work_limits_do_not_prune_state(self):
        p = physics(); start = initial(p.lower.new_tensor([[.6,.4]]))
        with self.assertRaises(RuntimeError):
            advance(start, p, F(3,5), Work(max_dimension=4))
        self.assertEqual(start.time, F(0))
        self.assertEqual(start.pending, ())
        first = intervene(start, p, p.lower.new_zeros(2), Work(max_packets=1))
        with self.assertRaises(RuntimeError):
            intervene(first, p, p.lower.new_zeros(2), Work(max_packets=1))
        second = intervene(first, p, p.lower.new_zeros(2), Work(max_packets=2))
        with self.assertRaises(RuntimeError):
            advance(second, p, F(0), Work(max_packets=1))
        with self.assertRaises(RuntimeError):
            refractory(second, Work(max_packets=1))
        huge = initial(torch.tensor([[1.,0.],[3e38,0.]], dtype=torch.float32))
        p32 = Physics(*[getattr(p,name).float() for name in
                       ('generator','lower','upper','reset','reward','escape_reward','spike_reward','discount')])
        with self.assertRaises(FloatingPointError):
            intervene(huge, replace(p32, spike_reward=torch.tensor(2.)), torch.ones(2))

    def test_two_layer_flux_and_content_backpropagation(self):
        rates = torch.tensor([.7,.3,.6,.2,.05,.08], dtype=torch.float64, requires_grad=True)
        def network(r):
            upstream = advance(initial(r.new_tensor([[.6,.4],[-.3,.8]])), physics(r), F(31,100))
            outgoing_flux, outgoing_content = upstream.hits.unbind()
            distribution = r.new_tensor([.25,.75])
            downstream = initial(torch.stack((distribution, outgoing_content*distribution)))
            downstream = advance(downstream, physics(r.new_tensor([.7,.3,.6,.2,.05,.08]) *
                                                     (1 + outgoing_flux)), F(47,100))
            return downstream.value + downstream.hits + refractory(downstream)
        gradient, = torch.autograd.grad(network(rates).sum(), (rates,))
        self.assertGreater(float(gradient.norm()), 1e-4)
        self.assertTrue(torch.autograd.gradcheck(network, (rates,), eps=1e-6, atol=3e-7, rtol=3e-5))


if __name__ == '__main__':
    unittest.main()
