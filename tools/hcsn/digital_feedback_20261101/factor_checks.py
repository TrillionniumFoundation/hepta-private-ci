"""Discriminating checks for separated mechanisms and execution agreement."""
import json

import numpy as np
import torch

from ..digital_read_before_20261031.task import initial
from .factors import FactorPolicy, FactorRuntime, candidates


def fixture():
    public = dict(schema="digital-read-before-public-v1", id="factor-check", deadline=6,
                  initial_budget=3, duration=[.5] * 6, reliability=[.85] * 6,
                  read_price=[.03] * 6, read_delay=[1] * 6, latency_price=.025,
                  repair_price=.03, failure_probability=.08,
                  packets=[f"packet_{i}.json" for i in range(6)], packet_sha256=["0" * 64] * 6)
    state = initial(public)
    state.update(tick=1, budget=2, elapsed=.5, last_symbol=1., last_reliability=.85,
                 history=[dict(source_tick=0, observation=1, reliability=.85)])
    context = dict(dt=.5, symbol=1., reliability=.85,
                   injection_symbol=-1., injection_reliability=.85)
    return public, state, context


def run_checks():
    torch.set_num_threads(1)
    public, state, context = fixture()
    policies = {s["id"]: FactorPolicy.from_spec(s, 1231) for s in candidates()}
    for policy in policies.values():
        if policy.cell is not None:
            with torch.no_grad():
                policy.cell.raw[4:].copy_(policy.cell.raw.new_tensor([.7, -.4, .2]))
    base = policies["fpt_base_multi"]
    with torch.no_grad():
        transition, events = base.transition_for_context(context)
        inputs = base.latent_inputs(public, state)
        bank_transition, bank_events = policies["fpt_neutral_bank"].transition_for_context(context)
        assert torch.equal(transition, bank_transition) and torch.equal(events, bank_events)
        assert not torch.equal(inputs, policies["fpt_neutral_bank"].latent_inputs(public, state))
        assert torch.equal(inputs, policies["fpt_neutral_drift"].latent_inputs(public, state))
        assert not torch.equal(transition, policies["fpt_neutral_drift"].transition_for_context(context)[0])
        pooled = policies["fpt_pooled_sign"]
        assert torch.equal(transition, pooled.transition_for_context(context)[0])
        pooled_inputs = pooled.latent_inputs(public, state)
        assert torch.equal(inputs[:15], pooled_inputs[:15])
        assert torch.equal(pooled_inputs[15], pooled_inputs[16])
        assert not torch.equal(inputs[15], inputs[16])
        common = policies["fpt_common_reset"]
        common_transition, common_events = common.transition_for_context(context)
        assert torch.equal(events, common_events)
        assert torch.equal(transition[:15], common_transition[:15])
        assert torch.equal(transition[15:, 15:], common_transition[15:, 15:])
        assert not torch.equal(transition[15:, :15], common_transition[15:, :15])
        assert torch.allclose(common_transition[15, :15], common_transition[16, :15], atol=1e-15, rtol=0)
        assert torch.equal(inputs, common.latent_inputs(public, state))
        # The fixed completion impulse remains present for neutral-drift cells.
        neutral = policies["fpt_neutral_both"]
        no_injection = dict(context, injection_symbol=0., injection_reliability=.5)
        assert not torch.equal(neutral.transition_for_context(context)[0],
                               neutral.transition_for_context(no_injection)[0])
    maximum_mass_error = 0.
    maximum_runtime_error = 0.
    checked = 0
    for policy in policies.values():
        if policy.cell is not None:
            policy.cell.raw.requires_grad_(False)
        restored = FactorPolicy.from_export(policy.export())
        assert restored.export() == policy.export()
        runtime = FactorRuntime(restored)
        with torch.no_grad():
            expected = restored(restored.latent_inputs(public, state))
            for index in range(len(expected)):
                actual = runtime.predict(public, state, index)
                error = float(np.max(np.abs(np.asarray(actual["q"]) - expected[index, :6].numpy())))
                maximum_runtime_error = max(maximum_runtime_error, error)
                assert error < 2e-15
                assert abs(actual["belief"] - float(torch.sigmoid(expected[index, 6]))) < 2e-15
            for dt in (0., .25, .5, 1., 1.5, 2.):
                for symbol in (-1., 0., 1.):
                    current = dict(context, dt=dt, symbol=symbol)
                    matrix, event = policy.transition_for_context(current)
                    assert bool(torch.isfinite(matrix).all())
                    assert float(matrix.min()) >= -2e-11
                    maximum_mass_error = max(maximum_mass_error, float((matrix.sum(-1) - 1).abs().max()))
                    assert maximum_mass_error < 2e-10
                    assert bool(((event >= -2e-11) & (event <= 1 + 2e-11)).all())
                    checked += 1
            prefix = [context, dict(context, dt=1., symbol=-1.)]
            explicit = policy.initial_mass()
            for current in prefix:
                explicit = explicit @ policy.transition_for_context(current)[0]
            assert torch.equal(explicit, policy.prefix_mass(prefix))
    return dict(schema="digital-feedback-factor-checks-v1", passed=True,
                transition_cases=checked, maximum_mass_error=maximum_mass_error,
                maximum_runtime_error=maximum_runtime_error,
                isolated_factors=["drift", "bank_driver", "event_sign_readout", "reset"],
                scope="factor invariance, finite mass, checkpoint and numerical head agreement; not efficacy")


if __name__ == "__main__":
    print(json.dumps(run_checks(), sort_keys=True))
