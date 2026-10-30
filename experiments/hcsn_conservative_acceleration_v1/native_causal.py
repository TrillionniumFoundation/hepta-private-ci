"""A value-message intervention in the actual pinned native owner.

Calibration uses a fixed, unlabeled synthetic input panel and selects extrema
only to exercise both sides of an engineering threshold. This is not heldout
evaluation, a learned task policy, or a claim about useful neural decisions.
"""

import hashlib
import math
from pathlib import Path

import numpy as np
import torch

from experiments.hcsn_distributional_v2.runtime_eval import numeric_state
from experiments.hcsn_free_boundary_v1.native_bridge import NativeSession, Signals, UPSTREAM
from experiments.hcsn_free_boundary_v1.training import save_weights
from .runtime import DEFAULT_CONFIG, _model, digest, execution_sources, write_json


PANEL_SEED = 730017
PANEL_LENGTH = 32


def state_digest(state):
    value = hashlib.sha256()
    for key, array in sorted(numeric_state(state).items()):
        value.update(key.encode())
        value.update(str(array.shape).encode())
        value.update(str(array.dtype).encode())
        value.update(array.tobytes())
    return value.hexdigest()


def value_record(aux):
    continuation = float(aux["continuation"].mean())
    intervention = float(aux["intervention"].mean())
    return dict(continuation=continuation, intervention=intervention,
                value_difference=float((aux["continuation"]-aux["intervention"]).mean()))


def causal_check(output, backend, binary, profile="stable", config=None, checkpoint=None):
    output, config = Path(output), dict(DEFAULT_CONFIG if config is None else config)
    output.mkdir(parents=True, exist_ok=False)
    sources = execution_sources()
    protocol = dict(schema="hcsn-native-value-causal-protocol.v1", config=config,
        backend=backend, profile=profile, seed=PANEL_SEED, observations=PANEL_LENGTH,
        input_law="Independent standard normal x; dt=0.1+4*Uniform(0,1); no labels",
        state_selection="First argmin and first argmax of actual mean(J-G) on the fixed panel",
        threshold="Arithmetic midpoint of those two values; fixed for every native case",
        external_budget=0.0, external_read_fee=0.0,
        message="continuation=0.05+0.9*tanh(sent_value-fixed_threshold)",
        auxiliary_message_fields=dict(margin=0.0, risk=0.0, activity=0.0),
        native_profile="continuation_only", shared_prefix_continuation=.75,
        minimum_q24_separation_from_threshold=16,
        cases=["natural_low", "natural_high", "high_state_frozen_low_value",
               "low_state_counterfactual_high_value"],
        calibration_is_heldout=False, learned_task_value_policy=False,
        trained_weights=checkpoint is not None,
        original_checkpoint_sha256=digest(checkpoint) if checkpoint else None,
        sources=sources)
    write_json(output / "PROTOCOL.json", protocol)
    model = _model(config, backend, profile, checkpoint).eval()
    save_weights(output / "weights.npz", model)
    weights_sha = digest(output / "weights.npz")
    generator = torch.Generator().manual_seed(PANEL_SEED)
    inputs = torch.randn(1, PANEL_LENGTH, config["input_dim"], generator=generator)
    durations = .1+4*torch.rand(1, PANEL_LENGTH, generator=generator)
    np.savez_compressed(output / "panel.npz", x=inputs.numpy(), dt=durations.numpy())
    state, records, states = None, [], []
    with torch.inference_mode():
        for index in range(PANEL_LENGTH):
            logits, state, aux = model.step(inputs[:, index], durations[:, index], state)
            records.append(dict(index=index, logits=logits.tolist(), state_sha256=state_digest(state),
                                **value_record(aux)))
            states.append(numeric_state(state))
    low = min(range(PANEL_LENGTH), key=lambda i: records[i]["value_difference"])
    high = max(range(PANEL_LENGTH), key=lambda i: records[i]["value_difference"])
    low_value, high_value = (records[i]["value_difference"] for i in (low, high))
    threshold = .5*(low_value+high_value)

    def message(value):
        return .05+.9*math.tanh(value-threshold)

    center_q24 = UPSTREAM.quantize(.05)
    low_q24, high_q24 = UPSTREAM.quantize(message(low_value)), UPSTREAM.quantize(message(high_value))
    calibration = dict(records=records, low_index=low, high_index=high,
        low_value=low_value, high_value=high_value, threshold=threshold,
        low_message=message(low_value), high_message=message(high_value),
        low_message_q24=low_q24, high_message_q24=high_q24, threshold_q24=center_q24,
        weights_sha256=weights_sha, panel_sha256=digest(output / "panel.npz"),
        protocol_sha256=digest(output / "PROTOCOL.json"))
    write_json(output / "CALIBRATION.json", calibration)
    if not (center_q24-low_q24>=16 and high_q24-center_q24>=16):
        raise AssertionError("Fixed unlabeled panel did not yield distinct resolvable value messages")
    for name, index in (("low", low), ("high", high)):
        np.savez_compressed(output / f"{name}_state.npz", **states[index])

    outcomes = []
    cases = [("natural_low", low, low_value, "stop"),
             ("natural_high", high, high_value, "keep"),
             ("high_state_frozen_low_value", high, low_value, "stop"),
             ("low_state_counterfactual_high_value", low, high_value, "keep")]
    for name, index, sent_value, expected in cases:
        # Recreate the actual neural state from the same immutable weights and
        # panel, instead of constructing a synthetic J/G pair in the test.
        probe = _model(config, backend, profile, output / "weights.npz").eval()
        probe_state = None
        with torch.inference_mode():
            for step in range(index+1):
                logits, probe_state, aux = probe.step(inputs[:, step], durations[:, step], probe_state)
        actual = value_record(aux)
        if (actual["value_difference"] != records[index]["value_difference"] or
                state_digest(probe_state) != records[index]["state_sha256"] or
                logits.tolist() != records[index]["logits"]):
            raise AssertionError("Selected real neural state failed exact replay")
        session = NativeSession(output / name, binary=binary, policy="continuation_only",
            model_digest=weights_sha, case="acceleration-value-causal-v1", seed=PANEL_SEED)
        try:
            common = session.tick(Signals(.75, 0., 0., 0.), context=dict(
                kind="identical_causal_prefix", external_budget=0., external_read_fee=0.,
                threshold=threshold))
            if common["native"]["effective_action"] != "keep":
                raise AssertionError("Shared native prefix did not remain active")
            prefix = dict(session.bridge.current)
            signals = Signals(message(sent_value), 0., 0., 0.)
            # Context and all non-value input fields are the same in every
            # case; only this single continuation coordinate is intervened on.
            row = session.tick(signals, context=dict(kind="causal_value_message",
                external_budget=0., external_read_fee=0., threshold=threshold))
            retry = session.verify_retry()
            terminal_guard = session.verify_terminal() if session.terminal else None
            outcome = dict(case=name, neural_index=index, neural_replay_steps=index+1,
                actual_neural_values=actual, sent_value=sent_value,
                intervention=sent_value != actual["value_difference"],
                state_sha256=state_digest(probe_state), logits=logits.tolist(),
                prefix=prefix, common_native_event=common, native_event=row,
                expected_action=expected, actual_action=row["native"]["effective_action"],
                retry=retry, terminal_guard=terminal_guard)
        finally:
            cost = session.close()
        outcome["native_execution"] = cost
        outcomes.append(outcome)
        write_json(output / f"{name}_RESULT.json", outcome)

    same_prefix = all(row["prefix"]==outcomes[0]["prefix"] for row in outcomes)
    actions = {row["case"]: row["actual_action"] for row in outcomes}
    expected_actions = {name: expected for name, _, _, expected in cases}
    changed = [path for path, expected in sources.items()
               if digest(Path(__file__).resolve().parents[2] / path) != expected]
    result = dict(schema="hcsn-native-value-causal-result.v1", cases=outcomes,
        backend=backend, profile=profile, config=config, threshold=threshold,
        weights_sha256=weights_sha, original_checkpoint_sha256=protocol["original_checkpoint_sha256"],
        random_weights=checkpoint is None, trained_weights=checkpoint is not None,
        exact_same_native_prefix=same_prefix, fixed_external_budget=0., fixed_external_read_fee=0.,
        actions=actions, expected_actions=expected_actions, source_changed=changed,
        natural_state_action_changes=actions["natural_low"]!=actions["natural_high"],
        high_state_value_freeze_changes_action=actions["natural_high"]!=actions["high_state_frozen_low_value"],
        low_state_value_intervention_changes_action=actions["natural_low"]!=actions["low_state_counterfactual_high_value"],
        actual_native_processes=4, python_mock_native=False, owner_authority="DENY_ALL",
        scope="Causal engineering test of the value-to-action route; selected extrema on an unlabeled calibration panel, not task quality or policy optimality",
        cost_scope="Individual actual native children are recorded; complete Python/calibration/replay cost requires the external worker wait4 receipt")
    write_json(output / "RESULT.json", result)
    if not same_prefix or actions!=expected_actions or changed:
        raise AssertionError("Value-message causal acceptance failed; complete evidence retained")
    return result
