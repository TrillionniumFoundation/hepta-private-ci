"""Nonfinancial chain checks; no H-X inputs, Torch, oracle, or candidate run."""
import json
from pathlib import Path
import unittest

import numpy as np

from two_layer_reference import MODES, compose_local, reverse_steps

CONFIG = dict(dt=.05, leak=.5, k_equity=.15, k_risk=.04, tau=.4,
              fraction=.03, coupling_gain=.2, conditioning_gain=.5)
C = {k: float(np.float32(v)) for k, v in CONFIG.items()}
BASE1 = np.linspace(.8, 1.2, 9)
BASE2 = np.linspace(.7, 1.1, 9)
RAW = np.linspace(-.12, .15, 18)
STATE = np.array([[.4, .01, .7, .02], [.3, .03, .8, .04]])


def artificial_fields(theta, asset):
    """Smooth arbitrary polynomial/affine fields, explicitly NOT finance."""
    w_b, w_e, w_f = np.linspace(.01, .03, 9), np.linspace(.02, .04, 9), np.linspace(.002, .005, 9)
    n = len(asset)
    b = 1.4 + theta @ w_b
    e = .1 * asset ** 2 + theta @ w_e + .03 * asset * theta[:, 0]
    f = .3 + .01 * asset + theta @ w_f + .005 * asset * theta[:, 1]
    values = np.stack((b, e, f, np.zeros(n), np.zeros(n)), axis=1)
    jac = np.zeros((n, 5, 10))
    jac[:, 0, :9] = w_b
    jac[:, 1, :9] = w_e; jac[:, 1, 0] += .03 * asset
    jac[:, 1, 9] = .2 * asset + .03 * theta[:, 0]
    jac[:, 2, :9] = w_f; jac[:, 2, 1] += .005 * asset
    jac[:, 2, 9] = .01 + .005 * theta[:, 1]
    return values, jac


def toy_step(state, raw, mode='full', frozen_link=None, return_locals=False):
    n = len(state)
    tanh1 = np.tanh(raw[:9]); theta1 = BASE1 * (1 + C['fraction'] * tanh1)
    asset1, asset2 = np.exp(state[:, 0]), np.exp(state[:, 2])
    r1, j1 = artificial_fields(np.broadcast_to(theta1, (n, 9)), asset1)
    link = np.log(asset1 / r1[:, 0])
    if frozen_link is None:
        frozen_link = link
    drive_link = link if mode in ('full', 'drive_only') else frozen_link
    condition_link = link if mode in ('full', 'conditioning_only') else frozen_link
    tanh2 = np.tanh(raw[9:][None] + C['conditioning_gain'] * condition_link[:, None])
    theta2 = BASE2 * (1 + C['fraction'] * tanh2)
    r2, j2 = artificial_fields(theta2, asset2)
    next_state = state.copy()
    for offset, fields, drive in ((0, r1, np.full(n, .02)), (2, r2, .03 + C['coupling_gain'] * drive_link)):
        q, risk = fields[:, 1] / fields[:, 0], 1 - (1 - fields[:, 2]) ** 2
        dz = drive - C['leak'] * (state[:, offset] - .5) - C['k_equity'] * q - C['k_risk'] * risk + state[:, offset + 1]
        da = (C['k_risk'] * risk - state[:, offset + 1]) / C['tau']
        next_state[:, offset] += C['dt'] * dz
        next_state[:, offset + 1] += C['dt'] * da
    if return_locals:
        return compose_local(raw1=r1, jac1=j1, asset1=asset1, raw2=r2, jac2=j2, asset2=asset2,
                             base1=BASE1, base2=BASE2, tanh1=tanh1, tanh2=tanh2, config=CONFIG, mode=mode), link
    return next_state


class SyntheticReferenceTests(unittest.TestCase):
    def test_all_four_modes_against_local_finite_differences(self):
        h = 1e-6
        for mode in MODES:
            local, anchor = toy_step(STATE, RAW, mode, return_locals=True)
            numerical_A = np.zeros_like(local['A']); numerical_B = np.zeros_like(local['B'])
            for j in range(4):
                plus, minus = STATE.copy(), STATE.copy(); plus[:, j] += h; minus[:, j] -= h
                numerical_A[:, :, j] = (toy_step(plus, RAW, mode, anchor) - toy_step(minus, RAW, mode, anchor)) / (2 * h)
            for j in range(18):
                plus, minus = RAW.copy(), RAW.copy(); plus[j] += h; minus[j] -= h
                numerical_B[:, :, j] = (toy_step(STATE, plus, mode, anchor) - toy_step(STATE, minus, mode, anchor)) / (2 * h)
            np.testing.assert_allclose(local['A'], numerical_A, rtol=0, atol=2e-10)
            np.testing.assert_allclose(local['B'], numerical_B, rtol=0, atol=2e-10)

    def test_mode_partition_and_explicit_boundary_components(self):
        locals_ = {m: toy_step(STATE, RAW, m, return_locals=True)[0] for m in MODES}
        full, drive, condition, detached = [locals_[m] for m in MODES]
        np.testing.assert_array_equal(full['B'][:, 2:, :9], full['boundary_raw1_drive'] + full['boundary_raw1_condition'])
        np.testing.assert_array_equal(detached['A'][:, 2:, :2], 0)
        np.testing.assert_array_equal(detached['B'][:, 2:, :9], 0)
        for mode, local in locals_.items():
            np.testing.assert_array_equal(toy_step(STATE, RAW, mode), toy_step(STATE, RAW, 'full'))
            np.testing.assert_array_equal(local['B'][:, :, 9:], full['B'][:, :, 9:])
        terminal = np.array([[0., 0., .3, -.2], [0., 0., -.4, .1]])
        vjps = {m: reverse_steps(np.repeat(v['A'][None], 3, axis=0), np.repeat(v['B'][None], 3, axis=0), terminal)['shared_raw'] for m, v in locals_.items()}
        np.testing.assert_allclose(vjps['full'][:9], vjps['drive_only'][:9] + vjps['conditioning_only'][:9], rtol=0, atol=1e-17)
        np.testing.assert_array_equal(vjps['both_detached'][:9], 0)
        for mode in MODES:
            np.testing.assert_array_equal(vjps[mode][9:], vjps['full'][9:])
        self.assertGreater(np.linalg.norm(vjps['conditioning_only'][:9]), 0)

    def test_reverse_against_forward_sensitivity(self):
        local, _ = toy_step(STATE, RAW, return_locals=True)
        A = np.stack([local['A'], .99 * local['A'], .98 * local['A']])
        B = np.stack([local['B'], 1.01 * local['B'], .97 * local['B']])
        terminal = np.array([[.1, -.2, .3, .4], [-.3, .2, -.1, .5]])
        P = np.broadcast_to(np.eye(4), (2, 4, 4)).copy(); S = np.zeros((2, 4, 18))
        for at, bt in zip(A, B):
            P = np.einsum('bij,bjk->bik', at, P)
            S = np.einsum('bij,bjk->bik', at, S) + bt
        reverse = reverse_steps(A, B, terminal)
        np.testing.assert_allclose(reverse['shared_raw'], np.einsum('bi,bij->j', terminal, S), rtol=0, atol=1e-17)
        np.testing.assert_allclose(reverse['state_adj'][0], np.einsum('bi,bij->bj', terminal, P), rtol=0, atol=2e-16)


if __name__ == '__main__':
    unittest.main(verbosity=2)
