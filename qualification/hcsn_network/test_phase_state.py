"""Full Erlang forward state, independent value flow, and cold continuation."""

from dataclasses import replace
from fractions import Fraction
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from scipy.integrate import solve_ivp
import torch

from qualification.hcsn_currentstate.differentiable import Physics
from .network import FlowNetwork
from .phase_approximation import (PHYSICS_FIELDS, phase_forward, phase_state_from_record,
                                  phase_state_to_record)
from .task_physics import task_physics


torch.set_num_threads(1)


def law():
    return task_physics(torch.tensor([-.2, .55, .3, 1.2, .8, .25, .15], dtype=torch.float64)).physics


def cold_child(source, destination):
    data = torch.load(source, weights_only=True)
    net = FlowNetwork(1, 2, layers=2).double()
    net.load_state_dict(data["model"])
    p = Physics(*[data["physics"][name] for name in PHYSICS_FIELDS], Fraction(*data["delay"]))
    with torch.no_grad():
        output, state, _ = phase_forward(net, data["future"], (p, p), 4, phase_state_from_record(data["state"]))
    torch.save({"output": output, "state": phase_state_to_record(state)}, destination)


class PhaseStateTests(unittest.TestCase):
    def test_all_accumulators_against_independent_ode_and_perpetual_value(self):
        p = law(); stages, n, batch = 4, p.lower.numel(), 2
        net = FlowNetwork(1, 2, layers=1).double()
        with torch.no_grad():
            net.writers[0].weight.copy_(torch.tensor([[.7], [-.4]], dtype=torch.float64))
        sequence = torch.zeros(6, batch, 1, dtype=torch.float64)
        sequence[0, :, 0] = torch.tensor([.5, -.9])
        _, state, _ = phase_forward(net, sequence, (p,), stages)
        d = n+stages+1
        q = np.zeros((d, d)); q[:n, :n] = p.generator.numpy()
        q[:n, n] = p.lower.numpy(); q[:n, -1] = p.upper.numpy()
        rate = stages/float(p.delay)
        for j in range(stages):
            q[n+j, n+j] = -rate
            if j+1 < stages:
                q[n+j, n+j+1] = rate
            else:
                q[n+j, :n] = rate*p.reset.numpy()
        event = np.r_[p.lower.numpy(), np.zeros(stages+1)]
        occupation = np.r_[np.ones(n), np.zeros(stages), 1.]
        reward = np.r_[p.reward.numpy(), np.zeros(stages), float(p.escape_reward)]
        rho, spike = float(p.discount), float(p.spike_reward)
        marks = net.writers[0](sequence[0]).tanh().detach().numpy().ravel()
        start = np.zeros((1+batch*2, d+4))
        start[0, :n] = p.reset.numpy()
        start[1:, :n] = marks[:, None]*p.reset.numpy()[None]
        def rhs(t, flat):
            x = flat.reshape(1+batch*2, d+4)[:, :d]
            hit = x @ event
            return np.column_stack((x @ q, hit, np.exp(-rho*t)*hit, x @ occupation,
                                    np.exp(-rho*t)*(x @ reward + spike*hit))).ravel()
        reference = solve_ivp(rhs, (0., .6), start.ravel(), method="DOP853", rtol=2e-12, atol=2e-14)
        self.assertTrue(reference.success)
        actual = torch.cat((state.density[0], state.hits[0][:, None], state.discounted_hits[0][:, None],
                            state.occupation[0][:, None], state.value[0][:, None]), 1).detach().numpy()
        np.testing.assert_allclose(actual, reference.y[:, -1].reshape(actual.shape), atol=3e-12, rtol=3e-10)
        perpetual = np.linalg.solve(rho*np.eye(d)-q, reward+spike*event)
        np.testing.assert_allclose(state.value[0].detach().numpy() + float(state.discount_factor[0]) *
                                   (state.density[0].detach().numpy() @ perpetual), start[:, :d] @ perpetual,
                                   atol=3e-12, rtol=3e-11)
        torch.testing.assert_close(state.balances()[0], torch.zeros_like(state.balances()[0]), atol=3e-12, rtol=0)

    def test_split_whole_gradients_and_fresh_process_complete_record(self):
        torch.manual_seed(37)
        net = FlowNetwork(1, 2, layers=2).double(); p = law()
        sequence = torch.linspace(-1, 1, 12, dtype=torch.float64).reshape(6, 2, 1).requires_grad_()
        full, final, _ = phase_forward(net, sequence, (p, p), 4)
        prefix, middle, _ = phase_forward(net, sequence[:3], (p, p), 4)
        warm, last, _ = phase_forward(net, sequence[3:], (p, p), 4, middle)
        torch.testing.assert_close(torch.cat((prefix, warm)), full, atol=0, rtol=0)
        for a, b in zip(last.tensors(), final.tensors()):
            torch.testing.assert_close(a, b, atol=0, rtol=0)
        args = (sequence, *net.parameters())
        a = torch.autograd.grad(full.square().sum()+sum(t.sum() for t in final.value), args, retain_graph=True)
        b = torch.autograd.grad(torch.cat((prefix, warm)).square().sum()+sum(t.sum() for t in last.value), args)
        for left, right in zip(a, b):
            torch.testing.assert_close(left, right, atol=2e-12, rtol=2e-11)
        with tempfile.TemporaryDirectory() as directory:
            source, destination = Path(directory)/"input.pt", Path(directory)/"cold.pt"
            torch.save({"model": net.state_dict(), "future": sequence[3:].detach(),
                        "physics": {name: getattr(p, name) for name in PHYSICS_FIELDS},
                        "delay": [p.delay.numerator, p.delay.denominator],
                        "state": phase_state_to_record(middle)}, source)
            child = subprocess.run([sys.executable, "-m", "qualification.hcsn_network.test_phase_state",
                                    "--cold", str(source), str(destination)],
                                   cwd=Path(__file__).resolve().parents[2], timeout=60, capture_output=True,
                                   env={**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"})
            self.assertEqual(child.returncode, 0, child.stderr.decode())
            record = torch.load(destination, weights_only=True)
            cold = phase_state_from_record(record["state"])
            torch.testing.assert_close(record["output"], warm, atol=0, rtol=0)
            for left, right in zip(cold.tensors(), last.tensors()):
                self.assertEqual(left.contiguous().numpy().tobytes(), right.detach().contiguous().numpy().tobytes())
            self.assertEqual(cold.time, Fraction(3, 5))
            self.assertEqual(cold.law_digests, last.law_digests)
            self.assertEqual(cold.batch_size, 2)
            self.assertEqual(cold.tensor_bytes(), last.tensor_bytes())
            self.assertTrue(all(not t.requires_grad for t in cold.tensors()))

    def test_changed_law_or_contract_is_rejected_before_continuation(self):
        net = FlowNetwork(1, 2, layers=2).double(); p = law()
        sequence = torch.zeros(1, 2, 1, dtype=torch.float64)
        _, state, _ = phase_forward(net, sequence, (p, p), 4)
        for changed in (replace(p, reset=p.reset.flip(0)), replace(p, delay=Fraction(2, 5)),
                        replace(p, discount=p.discount+.1)):
            with self.assertRaisesRegex(ValueError, "identical frozen law"):
                phase_forward(net, sequence, (changed, p), 4, state)
        with self.assertRaisesRegex(ValueError, "identical frozen law"):
            phase_forward(net, sequence, (p, p), 5, state)
        net.dt = Fraction(1, 20)
        with self.assertRaisesRegex(ValueError, "identical frozen law"):
            phase_forward(net, sequence, (p, p), 4, state)
        buffer = io.BytesIO(); torch.save(phase_state_to_record(state), buffer); buffer.seek(0)
        saved = torch.load(buffer, weights_only=True)
        saved["batch_size"] = 3
        with self.assertRaisesRegex(ValueError, "tensor shape"):
            phase_state_from_record(saved)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--cold":
        cold_child(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        unittest.main()
