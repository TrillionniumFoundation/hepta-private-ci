"""Real original-owner lifecycle checks; no substitute native implementation."""

import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from experiments.continuous_spiking_followup.bridge import (
    NATIVE_BINARY_SHA256,
    NativeClient,
    Q,
    make_profile,
    signals,
)


BINARY = Path(os.environ.get("HCSN_NATIVE_BINARY", "/nonexistent/hcsn-native-host"))
MODEL = hashlib.sha256(b"development-only-model").hexdigest()
OBJECTIVE = hashlib.sha256(b"development-only-task-objective").hexdigest()
EVIDENCE = hashlib.sha256(b"development-only-causal-observation").hexdigest()


def client(root, model=MODEL):
    return NativeClient(
        BINARY,
        root,
        model_sha256=model,
        objective_sha256=OBJECTIVE,
        arm_id="hcsn-bridge-development",
        score_kind="value_model_advantage",
        maximum_ticks=12,
    )


def observation(continuation=0.75, stopping=0.5):
    return signals(
        continuation - stopping,
        score_kind="value_model_advantage",
        continuation_value=continuation,
        stopping_value=stopping,
        natural_margin=-0.25,
        task_risk=0.125,
        activity=0.375,
    )


def test_typed_probabilities_and_q24_domain_are_not_silently_clipped():
    for kwargs in (
        {"task_risk": 2},
        {"task_risk": float("nan")},
        {"activity": 1.01},
        {"activity": float("nan")},
        {"natural_margin": 9},
    ):
        fields = dict(natural_margin=0.5, task_risk=0.25, activity=0.5)
        fields.update(kwargs)
        with pytest.raises(ValueError):
            signals(0.1, score_kind="threshold_confidence_advantage", **fields)
    with pytest.raises(ValueError):
        make_profile("0" * 64, OBJECTIVE, "bad-model", "value_model_advantage")
    with pytest.raises(ValueError, match="not task"):
        signals(
            0.1,
            score_kind="threshold_confidence_advantage",
            natural_margin=0,
            task_risk=0.2,
            activity=0.3,
            continuation_value=0.5,
            stopping_value=0.4,
        )
    terminal = signals(
        -1,
        score_kind="value_model_advantage",
        natural_margin=0,
        task_risk=0.2,
        activity=0.3,
        continuation_value=None,
        stopping_value=0.8,
        forced_terminal=True,
    )
    assert terminal["semantics"]["continuation_value"] is None


@pytest.mark.skipif(
    not BINARY.is_file(), reason="requires the exact original #4157 native host"
)
class TestActualNativeOwner:
    @pytest.mark.parametrize(
        "score_kind", ["value_model_advantage", "threshold_confidence_advantage"]
    )
    def test_declared_score_kind_and_explicit_terminal_constraint(
        self, tmp_path, score_kind
    ):
        with NativeClient(
            BINARY,
            tmp_path / "owner",
            model_sha256=MODEL,
            objective_sha256=OBJECTIVE,
            arm_id="typed-score-check",
            score_kind=score_kind,
            maximum_ticks=3,
        ) as native:
            native.open("development.terminal", 9127)
            values = (
                dict(continuation_value=0.75, stopping_value=0.5)
                if score_kind == "value_model_advantage"
                else {}
            )
            first = signals(
                0.25,
                score_kind=score_kind,
                natural_margin=0.3,
                task_risk=0.2,
                activity=0.1,
                **values,
            )
            assert (
                native.tick(first, evidence_digest=EVIDENCE)["effective_action"]
                == "keep"
            )
            terminal = signals(
                -1,
                score_kind=score_kind,
                natural_margin=0.2,
                task_risk=0.1,
                activity=0.2,
                forced_terminal=True,
                stopping_value=0.9 if score_kind == "value_model_advantage" else None,
            )
            receipt = native.tick(terminal, evidence_digest=EVIDENCE)
            assert receipt["effective_action"] == "stop"
            assert receipt["readout"]["scores_q24"] == [-Q, -8 * Q, 0]

    def test_typed_auxiliary_channels_reach_native_state_without_value_relabeling(
        self, tmp_path
    ):
        with client(tmp_path / "owner") as native:
            first = observation()["features"]
            second = signals(
                0.25,
                score_kind="value_model_advantage",
                continuation_value=0.75,
                stopping_value=0.5,
                natural_margin=0.75,
                task_risk=0.8,
                activity=0.9,
            )["features"]
            result = native.native.kernel_batch(
                native.profile_sha256, [[first], [second]]
            )
            left, right = (row[0] for row in result["sequences"])
            assert (
                left["activation_q24"]
                == right["activation_q24"]
                == [Q // 4, 0, 0, 0, 0]
            )
            assert left["temporal_digest"] != right["temporal_digest"]
            assert result["actual_kernel_calls"] == 2
            assert not result["durable_owner_execution"]

    def test_actual_activations_values_retry_and_terminal_guard(self, tmp_path):
        with client(tmp_path / "owner") as native:
            native.open("development.values", 9131)
            first = native.tick(observation(), evidence_digest=EVIDENCE)
            assert first["effective_action"] == "keep"
            assert first["native_transition_executed"]
            assert first["readout"]["scores_q24"] == [Q // 4, -8 * Q, 0]
            assert first["activation_q24"] == [Q // 4, 0, 0, 0, 0]
            before = native.status()
            retry = native.native.rpc(native.last_request)
            assert retry["duplicate_event_ignored"]
            assert not retry["native_transition_executed"]
            assert native.status() == before
            stop = native.tick(observation(-0.25, 0.5), evidence_digest=EVIDENCE)
            assert stop["readout"]["scores_q24"] == [-3 * Q // 4, -8 * Q, 0]
            assert stop["effective_action"] == "stop"
            before = native.status()
            probe = copy.deepcopy(native.last_request)
            probe["observation"].update(
                event_id="development.after-stop",
                step=3,
                checkpoint=before["checkpoint"],
            )
            rejected = native.native.rpc(probe, allow_error=True)
            assert not rejected["ok"] and "Terminal episode" in rejected["error"]
            assert native.status() == before
            receipt = native.close()
        assert receipt["counters"]["owner_ticks"] == 2
        assert receipt["identity"]["binary_sha256"] == NATIVE_BINARY_SHA256
        assert receipt["counters"]["total_native_ndu_calls"] == 2
        assert receipt["counters"]["request_bytes"] > 0
        (tmp_path / "RECEIPT.json").write_text(json.dumps(receipt, indent=2))

    def test_cold_process_restore_identity_and_frontier(self, tmp_path):
        root = tmp_path / "owner"
        with client(root) as first:
            first.open("development.resume", 9133)
            first.tick(observation(), evidence_digest=EVIDENCE)
            binding = first.binding()
            old_pid = first.process_id
        with client(root) as second:
            restored = second.open("development.resume", 9133, resume=True)
            assert second.process_id != old_pid
            assert restored["original_journal_replay_steps"] == 1
            second.verify_binding(binding)
            wrong = copy.deepcopy(binding)
            wrong["model_sha256"] = hashlib.sha256(b"wrong-model").hexdigest()
            with pytest.raises(ValueError, match="frontier"):
                second.verify_binding(wrong)
            second.tick(observation(0.5, 0.5), evidence_digest=EVIDENCE)
            assert second.status()["terminal"]
            receipt = second.close()
        assert receipt["counters"]["original_journal_replay_steps"] == 1
        assert receipt["counters"]["event_validation_kernel_steps"] == 1
        (tmp_path / "RECEIPT.json").write_text(json.dumps(receipt, indent=2))
        with client(root, hashlib.sha256(b"another-model").hexdigest()) as wrong:
            with pytest.raises(RuntimeError, match="identity/profile/seed"):
                wrong.open("development.resume", 9133, resume=True)

    def test_bad_observation_fails_without_advancing_owner(self, tmp_path):
        with client(tmp_path / "owner") as native:
            native.open("development.invalid", 9137)
            before = native.status()
            malformed = observation()["features"]
            malformed["continuous"]["risk_q24"] = Q + 1
            with pytest.raises(RuntimeError, match="domain"):
                native.native.rpc(
                    {
                        "command": "Tick",
                        "observation": {
                            "event_id": "development.invalid.probe",
                            "step": 1,
                            "checkpoint": before["checkpoint"],
                            "features": malformed,
                            "evidence_digest": EVIDENCE,
                        },
                    }
                )
            assert native.status() == before
            native.tick(observation(), evidence_digest=EVIDENCE)
            assert native.status()["step"] == 1

    def test_stream_and_native_frontiers_resume_together(self, tmp_path):
        import torch

        from experiments.continuous_spiking_network.models import SequenceClassifier
        from experiments.continuous_spiking_followup.streaming import (
            StreamingClassifier,
        )

        torch.set_num_threads(1)
        model = SequenceClassifier(4, 2, 4, 1, "hcsn", 9221).eval()
        stream = StreamingClassifier(model).reset(1)
        inputs = torch.arange(12, dtype=torch.float32).reshape(3, 1, 4) / 16
        root = tmp_path / "owner"
        with client(root, stream.model_sha256) as first:
            first.open("development.tensor-resume", 9221)
            _, aux = stream.step(inputs[0], torch.ones(1))
            values = signals(
                0.25,
                score_kind="value_model_advantage",
                continuation_value=0.75,
                stopping_value=0.5,
                natural_margin=float(aux["margin"].mean()),
                task_risk=0.25,
                activity=float(aux["event_probability"].mean()),
            )
            first.tick(values, evidence_digest=EVIDENCE)
            binding = first.binding()
            assert binding["status"]["step"] == stream.steps == 1
            state = stream.save_state(tmp_path / "stream")
        expected, _ = stream.step(inputs[1], torch.ones(1))
        recovered = StreamingClassifier(model).load_state(tmp_path / "stream")
        with client(root, recovered.model_sha256) as second:
            second.open("development.tensor-resume", 9221, resume=True)
            second.verify_binding(binding)
            actual, aux = recovered.step(inputs[1], torch.ones(1))
            assert torch.equal(actual, expected)
            values = signals(
                -0.25,
                score_kind="value_model_advantage",
                continuation_value=0.25,
                stopping_value=0.5,
                natural_margin=float(aux["margin"].mean()),
                task_risk=float(1 - actual.softmax(-1).max()),
                activity=float(aux["event_probability"].mean()),
            )
            result = second.tick(values, evidence_digest=EVIDENCE)
            assert result["effective_action"] == "stop"
            assert result["step"] == recovered.steps == 2
        assert state["serialized_bytes"] > 0
