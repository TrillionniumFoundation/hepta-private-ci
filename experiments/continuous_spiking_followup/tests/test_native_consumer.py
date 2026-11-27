"""True native consumption, cold replay, score-rounding and archived evidence."""

import hashlib
import json
import os
from pathlib import Path
import tarfile

import pytest
import torch

from experiments.continuous_spiking_followup.native_consumer import (
    NativeEpisodeConsumer,
)
from experiments.continuous_spiking_followup.streaming import StreamingClassifier
from experiments.continuous_spiking_network.models import SequenceClassifier


BINARY = Path(os.environ.get("HCSN_NATIVE_BINARY", "/nonexistent/hcsn-native-host"))
pytestmark = pytest.mark.skipif(
    not BINARY.is_file(), reason="requires exact original native host"
)


def fixtures(directory, mode="value"):
    model = SequenceClassifier(4, 2, 4, 1, "hcsn", 9239).eval()
    stream = StreamingClassifier(model).reset(1)
    x = torch.arange(12, dtype=torch.float32).reshape(3, 1, 4) / 12
    dt = torch.ones(3, 1)
    binding = {
        "input_sha256": hashlib.sha256(
            x.numpy().tobytes() + dt.numpy().tobytes()
        ).hexdigest(),
        "policy_sha256": hashlib.sha256(
            b"development-only-known-action-policy"
        ).hexdigest(),
        "snr": 0.5,
        "cost": 0.025,
        "horizon": 3,
    }
    consumer = NativeEpisodeConsumer(
        BINARY,
        directory,
        model_sha256=stream.model_sha256,
        objective_sha256=hashlib.sha256(b"development-objective").hexdigest(),
        policy_id=mode,
        episode_id="development.native.consumer",
        seed=9239,
        maximum_steps=3,
        task_binding=binding,
    )
    return stream, x, dt, consumer


def decision(terminal=False):
    return {
        "stop": terminal,
        "continue_score": -1.0 if terminal else 0.125,
        "score_kind": "value_model_advantage",
        "forced_terminal": terminal,
        "continuation_value": None if terminal else 0.75,
        "stopping_value": 0.625,
        "predicted_error_probability": 0.375,
    }


def test_real_consumer_restarts_native_and_restores_tensor_frontier(tmp_path):
    torch.set_num_threads(1)
    stream, x, dt, native = fixtures(tmp_path / "episode")
    _, aux = stream.step(x[0], dt[0])
    first = native.tick(
        decision=decision(),
        natural_margin=float(aux["margin"].mean()),
        event_activity=float(aux["event_probability"].mean()),
        episode_id="development.native.consumer",
        step=1,
    )
    assert not first["stop"] and not first["policy_disagreement"]
    reference = StreamingClassifier(stream.model).restore(stream.snapshot())
    recovered, resume = native.cold_resume(stream, 1, "development.native.consumer")
    assert resume["old_pid"] != resume["new_pid"]
    assert resume["restored_cursor"] == 1
    assert resume["native_resume"]["original_journal_replay_steps"] == 1
    for index in (1, 2):
        expected, _ = reference.step(x[index], dt[index])
        logits, aux = recovered.step(x[index], dt[index])
        assert torch.equal(logits, expected)
        receipt = native.tick(
            decision=decision(index == 2),
            natural_margin=float(aux["margin"].mean()),
            event_activity=float(aux["event_probability"].mean()),
            episode_id="development.native.consumer",
            step=index + 1,
        )
        assert receipt["stop"] == (index == 2)
    complete = native.finish()
    assert complete["terminal"] and complete["post_stop_native_rejected"]
    assert complete["policy_disagreements"] == 0
    assert len(complete["native_processes"]) == 2
    assert (
        sum(row["counters"]["owner_ticks"] for row in complete["native_processes"]) == 3
    )
    assert native.finish() == complete
    with tarfile.open(complete["archive"]["path"], "r:gz") as archive:
        assert sorted(archive.getnames()) == sorted(complete["archive"]["files"])
        for name, meta in complete["archive"]["files"].items():
            raw = archive.extractfile(name).read()
            assert len(raw) == meta["bytes"]
            assert hashlib.sha256(raw).hexdigest() == meta["sha256"]
    (tmp_path / "RESULT.json").write_text(json.dumps(complete, indent=2))


def test_native_q24_disagreement_is_used_and_reported(tmp_path):
    stream, x, dt, native = fixtures(tmp_path / "episode", "fixed")
    _, aux = stream.step(x[0], dt[0])
    current = {
        "stop": False,
        "continue_score": 2**-27,
        "score_kind": "threshold_confidence_advantage",
        "forced_terminal": False,
        "continuation_value": None,
        "stopping_value": None,
        "predicted_error_probability": 0.4,
    }
    result = native.tick(
        decision=current,
        natural_margin=float(aux["margin"].mean()),
        event_activity=float(aux["event_probability"].mean()),
        episode_id="development.native.consumer",
        step=1,
    )
    assert result["stop"] and result["policy_disagreement"]
    assert result["raw"]["readout"]["tie"]
    assert result["raw"]["readout"]["scores_q24"] == [0, -(8 << 24), 0]
    receipt = native.finish()
    assert receipt["policy_disagreements"] == 1
    assert receipt["post_stop_native_rejected"]


def test_cold_snapshot_rejects_wrong_cursor_before_native_mutation(tmp_path):
    stream, x, dt, native = fixtures(tmp_path / "episode")
    _, aux = stream.step(x[0], dt[0])
    native.tick(
        decision=decision(),
        natural_margin=float(aux["margin"].mean()),
        event_activity=float(aux["event_probability"].mean()),
        episode_id="development.native.consumer",
        step=1,
    )
    before = native.client.binding()
    with pytest.raises(ValueError, match="frontiers"):
        native.cold_resume(stream, 2, "development.native.consumer")
    assert native.client.binding() == before
    receipt = native.finish()
    assert not receipt["terminal"]
