"""Synthetic development checks before the separate native003 code/data freeze."""

import argparse
import hashlib
import itertools
from pathlib import Path
import shutil
import traceback

import torch

from .model import HCSNClassifier
from .native003_common import PACKAGE, read_json, write_new
from .native003_eval import LearnedNativeSession, run_episode
from .native003_heads import FAMILIES, StopHead, Q, hard_decisions, observed_features, soft_utility
from .native003_train import priced_bank, train_candidate
from .native_bridge import Signals, UPSTREAM, restored_binary
from .run_native_live import model_identity


def checks(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    snapshots = output / "source_snapshot"
    snapshots.mkdir()
    for path in PACKAGE.glob("native003_*.py"):
        shutil.copyfile(path, snapshots / path.name)
    shutil.copyfile(PACKAGE / "NATIVE003_PROTOCOL.json", snapshots / "NATIVE003_PROTOCOL.json")
    write_new(output / "REQUEST.json", {"scope": "synthetic development only; no fresh or original real-data predictions",
                                         "source_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in snapshots.iterdir()}})
    try:
        torch.set_num_threads(1)
        scores = torch.tensor([[0.17, -0.11, 0.3]], dtype=torch.float64, requires_grad=True)
        rewards = torch.tensor([[0.0, 1.0, 0.0]], dtype=torch.float64)
        prices = torch.tensor([0.02], dtype=torch.float64)
        utility, mass = soft_utility(scores, rewards, prices, 0.1)
        p = torch.sigmoid(-scores.detach()[0] / 0.1)
        exact_mass = torch.tensor([p[0], (1-p[0])*p[1], (1-p[0])*(1-p[1])])
        assert torch.allclose(mass[0], exact_mass, rtol=1e-12, atol=1e-12)
        assert abs(float(mass.sum()) - 1) < 1e-12
        utility.sum().backward()
        assert torch.isfinite(scores.grad).all() and scores.grad[0, -1] == 0
        hard = hard_decisions(torch.tensor([[1., -1., 2.], [1., 2., 3.]]),
                              torch.tensor([[0., 1., 0.], [0., 0., 1.]]), torch.tensor([.02, .05]))
        assert hard["reads"].tolist() == [2, 3]
        model = HCSNClassifier(3, 2, width=4, seed=177).eval()
        generator = torch.Generator().manual_seed(381)
        x, dt = torch.randn(2, 4, 3, generator=generator), torch.full((2, 4), .7)
        with torch.no_grad():
            logits, aux = model(x, dt, return_sequence=True)
            batched = observed_features(logits, aux, dt.cumsum(1))
            state, sequential = None, []
            for t in range(4):
                z, state, a = model.step(x[:, t], dt[:, t], state)
                sequential.append(observed_features(z[:, None], a, state["elapsed"][:, None])[:, 0])
            sequential = torch.stack(sequential, 1)
        assert batched.shape == (2, 4, 5)
        torch.testing.assert_close(batched, sequential, atol=1e-6, rtol=1e-6)
        for family, count in zip(FAMILIES, [33, 33, 2], strict=True):
            head = StopHead(family, torch.zeros(6), torch.ones(6))
            assert head.parameter_count() == count
            features = torch.randn(32, 6, generator=generator)
            features[:, 2] = features[:, 2].sigmoid()
            features[:, 5] = features[:, 5].sigmoid() * .05
            head(features).square().mean().backward()
            assert all(p.grad is not None and torch.isfinite(p.grad).all() for p in head.parameters())
        # A small synthetic candidate checks gradients, checkpoint selection and
        # numeric saving for every family without reading any actual task data.
        protocol = read_json(PACKAGE / "NATIVE003_PROTOCOL.json")
        protocol["optimization"] = {**protocol["optimization"], "updates_per_learning_rate": 4,
                                     "checkpoints": [2, 4], "batch_size": 8}
        observed = torch.randn(12, 4, 5, generator=generator)
        observed[..., 2] = observed[..., 2].sigmoid()
        correct = (torch.rand(12, 4, generator=generator) > .5).float()
        bank = priced_bank(observed, correct, protocol["execution"]["read_prices"])
        candidate_results = {}
        for family in FAMILIES:
            candidate_results[family] = train_candidate(family, .003, bank, bank,
                {"mean": [0.] * 6, "std": [1.] * 6}, protocol, output / "toy_training" / family)
        binary = restored_binary()
        quantization = []
        for index, value in enumerate((0.0, 0.5/Q, 1.0/Q, -1.0/Q, .2, -.2)):
            session = LearnedNativeSession(output / "q24" / str(index), binary=binary,
                family="ordinary_mlp", model_digest=UPSTREAM.digest("native003-development-quantization"),
                case="quantization", seed=index)
            result = session.tick(Signals(value, 0, 0, 0), context={"scope": "development"})
            expected = "keep" if UPSTREAM.quantize(value) > 0 else "stop"
            assert result["native"]["effective_action"] == expected
            guard = session.verify_terminal() if session.terminal else None
            quantization.append({"score": value, "q24": UPSTREAM.quantize(value), "action": expected,
                                 "guard": guard, "cost": session.close()})
        write_new(output / "QUANTIZATION.json", quantization)
        # Explicitly constant KEEP in this fixture ensures recovery is exercised.
        head = StopHead("ordinary_mlp", torch.zeros(6), torch.ones(6)).eval()
        with torch.no_grad():
            head.readout.weight.zero_()
            head.readout.bias.fill_(1.)
        selection = {"selected_checkpoint_sha256": model_identity(head)[0]}
        identity = {"backbone_checkpoint_sha256": model_identity(model)[0],
                    "fresh_dataset_sha256": UPSTREAM.digest("synthetic-development-only"),
                    "protocol_sha256": UPSTREAM.digest("synthetic-development-protocol")}

        def reload_objects():
            rebuilt = HCSNClassifier(**model.config).eval()
            rebuilt.load_state_dict(model.state_dict())
            rebuilt_head = StopHead("ordinary_mlp", torch.zeros(6), torch.ones(6)).eval()
            rebuilt_head.load_state_dict(head.state_dict())
            return rebuilt, rebuilt_head

        uninterrupted = run_episode(model, head, "ordinary_mlp", selection, x[0], dt[0], 0,
                                    "synthetic-development", 0, .005, output / "uninterrupted", binary, identity)
        recovered = run_episode(model, head, "ordinary_mlp", selection, x[0], dt[0], 0,
                                "synthetic-development", 0, .005, output / "recovered", binary, identity,
                                recover=True, reload_objects=reload_objects)
        for first, second in zip(uninterrupted["events"], recovered["events"], strict=True):
            for key in ("features", "score", "score_q24", "prediction"):
                assert first[key] == second[key]
            for key in ("checkpoint_before", "checkpoint_after", "readout", "activation_q24", "effective_action"):
                assert first["native"][key] == second["native"][key]
        assert len(recovered["recoveries"]) == 1
        result = {"status": "passed", "scope": "synthetic development only",
                  "soft_mass_and_expected_utility_checked": True, "forced_horizon_and_first_read_checked": True,
                  "batch_vs_stream_features_max_abs_error": float((batched-sequential).abs().max()),
                  "head_parameter_counts": {family: row["parameters"] for family, row in candidate_results.items()},
                  "all_three_toy_candidates_completed": True, "q24_cases": len(quantization),
                  "recovery_full_native_digests_and_neural_features_equal": True,
                  "fresh_holdout_inference_performed": False}
        write_new(output / "SUMMARY.json", result)
        return result
    except Exception as error:
        write_new(output / "FAILURE.json", {"error_type": type(error).__name__, "error": str(error),
                                           "traceback": traceback.format_exc(), "partial_results_preserved": True})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    import json
    print(json.dumps(checks(args.output), sort_keys=True))
