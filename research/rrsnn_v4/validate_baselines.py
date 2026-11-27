"""Independent ODE/event checks of v4 comparator paths and causal semantics."""

import json
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp
import torch

from .baselines import make_encoder


def independent_ode(encoder, current, initial, horizon):
    """Adaptive DOP853 with continuous threshold events, not the encoder root."""
    v, adaptation, trace, ref = initial
    time, events = 0., []
    beta = encoder.adaptation_strength if encoder.variant == "alif" else 0.
    threshold = encoder.threshold
    while time < horizon:
        if ref > 0:
            wait = min(ref, horizon-time)
            trace *= np.exp(-wait/encoder.trace_tau)
            adaptation *= np.exp(-wait/encoder.adaptation_tau)
            ref -= wait
            time += wait
            if time >= horizon:
                break

        def flow(_t, y):
            return [(current-y[0])/encoder.membrane_tau,
                    -y[1]/encoder.adaptation_tau, -y[2]/encoder.trace_tau]

        def crossing(_t, y):
            return y[0]-threshold-beta*y[1]

        crossing.terminal, crossing.direction = True, 1
        solution = solve_ivp(flow, (time, horizon), [v, adaptation, trace],
                             events=crossing, method="DOP853", rtol=1e-11,
                             atol=1e-12, max_step=.025)
        v, adaptation, trace = solution.y[:, -1]
        time = float(solution.t[-1])
        if not len(solution.t_events[0]):
            break
        events.append(time)
        v, trace = 0., trace+1.
        if encoder.variant == "alif":
            adaptation += 1.
        ref = encoder.refractory
    return {"voltage": float(v), "adaptation_trace": float(adaptation),
            "spike_trace": float(trace), "refractory_remaining": float(ref)}, events


def validate():
    torch.set_num_threads(1)
    torch.manual_seed(8401)
    rng = np.random.default_rng(8401)
    checks = []

    def record(name, **values):
        checks.append({"name": name, "passed": True, **values})

    largest_state, largest_time, total_events = 0., 0., 0
    for variant in ("lif", "alif", "resource_lif"):
        encoder = make_encoder(variant, hidden_size=1).double()
        for _ in range(24):
            current = float(rng.uniform(-.4, 1.3))
            adaptation = float(rng.uniform(0., 2.)) if variant == "alif" else 0.
            ref = float(rng.choice([0., .04, .13]))
            voltage = 0. if ref else float(rng.uniform(-.3, .6))
            trace, horizon = float(rng.uniform(0., 1.)), float(rng.uniform(.1, 8.))
            state = encoder.initial_state(1, dtype=torch.float64)
            state["voltage"].fill_(voltage)
            state["context"].fill_(np.arctanh(current/encoder.current_scale))
            state["refractory_remaining"].fill_(ref)
            state["spike_trace"].fill_(trace)
            if variant == "alif":
                state["adaptation_trace"].fill_(adaptation)
            with torch.no_grad():
                actual, output = encoder.step(state, None, horizon, False, True)
            reference, events = independent_ode(encoder, current,
                                                (voltage, adaptation, trace, ref), horizon)
            assert len(output["spike_times"]) == len(events)
            assert int(output["actual_counts"].sum()) == len(events)
            for key, expected in reference.items():
                if key in actual:
                    error = abs(float(actual[key][0, 0])-expected)
                    largest_state = max(largest_state, error)
                    assert error < 2e-8, (variant, key, error)
            for actual_event, expected in zip(output["spike_times"], events):
                error = abs(actual_event["time"]-expected)
                largest_time = max(largest_time, error)
                assert error < 2e-8, (variant, error)
            if len(events) > 1:
                assert np.diff(events).min() >= encoder.refractory-1e-10
            total_events += len(events)
    record("independent_adaptive_ode_event_paths", cases=72, physical_events=total_events,
           maximum_state_error=largest_state, maximum_event_time_error=largest_time)

    metadata, maximum_split_error = {}, 0.
    for variant in ("lif", "alif", "alif_held", "resource_lif", "ctrnn", "ctrnn_matched"):
        encoder = make_encoder(variant).double()
        state = encoder.initial_state(3, dtype=torch.float64)
        obs = torch.randn(3, 22, dtype=torch.float64)
        obs[:, 4] = .5
        with torch.no_grad():
            initial, out0 = encoder.step(state, obs, 0., True, True)
            # Every main architecture has an initially zero common readout.
            assert torch.equal(out0["latent"], torch.zeros_like(out0["latent"]))
            whole, whole_out = encoder.step(initial, None, 5.7, False, True)
            split, part1 = encoder.step(initial, None, 1.37, False, True)
            split, part2 = encoder.step(split, None, 4.33, False, True)
            for key in whole:
                error = float((whole[key]-split[key]).abs().max())
                maximum_split_error = max(maximum_split_error, error)
                assert error < 2e-10, (variant, key, error)
            assert int(whole_out["actual_counts"].sum()) == int(part1["actual_counts"].sum()+part2["actual_counts"].sum())
            next_obs = torch.randn(3, 22, dtype=torch.float64)
            direct, _ = encoder.step(initial, next_obs, .73, True)
            causal, _ = encoder.step(initial, None, .73, False)
            causal, _ = encoder.step(causal, next_obs, 0., True)
            for key in direct:
                assert torch.allclose(direct[key], causal[key], rtol=0, atol=1e-12)
        meta = encoder.metadata()
        state32 = encoder.initial_state(1, dtype=torch.float32)
        allocated = sum(x.numel()*x.element_size() for x in state32.values())
        assert allocated == meta["persistent_state_bytes_float32"]
        metadata[variant] = {"encoder_parameters": sum(p.numel() for p in encoder.parameters()),
                             "actual_float32_state_bytes": allocated,
                             "shared_constant_buffer_bytes": meta["shared_constant_buffer_bytes"]}
    record("no_observation_time_split_and_causal_input_order", variants=6,
           maximum_state_error=maximum_split_error)
    record("measured_tensor_state_accounting", variants=metadata)

    continuous = make_encoder("alif", hidden_size=1).double()
    held = make_encoder("alif_held", hidden_size=1).double()
    states = [e.initial_state(1, dtype=torch.float64) for e in (continuous, held)]
    for state in states:
        state["context"].fill_(np.arctanh(.9/continuous.current_scale))
        state["adaptation_trace"].fill_(1.)
    states[1]["held_threshold"].fill_(.95)
    with torch.no_grad():
        _, dynamic = continuous.step(states[0], None, 8., False, True)
        _, static = held.step(states[1], None, 8., False, True)
    assert int(dynamic["actual_counts"].sum()) > 0
    assert int(static["actual_counts"].sum()) == 0
    record("continuously_decaying_alif_not_held_threshold", continuous_spikes=len(dynamic["spike_times"]))

    gradient_details = {}
    for variant in ("lif", "alif", "resource_lif", "ctrnn", "ctrnn_matched"):
        encoder = make_encoder(variant).double()
        x = torch.randn(4, 8, 22, dtype=torch.float64)
        dt = torch.tensor([[0., .25, .5, .5, .75, .25, .5, .75]]*4, dtype=torch.float64)
        output = encoder(x, dt)
        loss = (output["latent"]*torch.randn_like(output["latent"])).sum()
        loss.backward()
        assert all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in encoder.parameters())
        gradient_details[variant] = float(sum(p.grad.square().sum() for p in encoder.parameters()).sqrt())
    record("training_gradients_finite", norms=gradient_details,
           qualification="Spiking count gradients are declared biased surrogates, not finite-difference-exact event-count derivatives")

    rejected = []
    for variant in ("lif", "alif", "ctrnn"):
        encoder = make_encoder(variant)
        for value in (-.1, float("nan"), float("inf")):
            try:
                encoder.step(encoder.initial_state(1), None, value, False)
            except ValueError:
                rejected.append((variant, str(value)))
            else:
                raise AssertionError("invalid elapsed interval accepted")
    record("nonfinite_or_negative_intervals_rejected", cases=len(rejected))
    return {"schema": "rr-v4-baseline-validation-1", "checks": checks,
            "allPassed": True, "reference": "independent scipy DOP853 with event roots; no Euler comparison",
            "scope": {"taskUtilityAcceptance": False, "fullLSNNReproduction": False,
                      "spikingGradientUnbiased": False}}


if __name__ == "__main__":
    result = validate()
    destination = Path(__file__).with_name("baseline_validation_results.json")
    destination.write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result, indent=2))
