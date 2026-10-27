"""Real media/feedback integration on artificial pixels and untrained models.

No MNIST, registered source roles, pretrained checkpoint, or scientific outcome
is loaded. This verifies the data-path contract, not treatment effectiveness.
"""

import argparse
import copy
import gzip
import hashlib
import json
from pathlib import Path
import time
from unittest.mock import patch

import numpy as np
import torch

from ..v6.data import Observation, SourceCorpus, SourceSplit, Target
from ..v6.neural import NeuralPortfolio, parameter_hash
from ..v6.observer import Recognizer
from .feedback_bank import batches, build_bank, build_tree_batch, load_bank
from .feedback_media import MediaWriter, read_receipt
from .feedback_task import public_event, revise, score, start, verifier_review
from .native_stream import NativeStreamBridge, file_sha
from .runtime_controller import array_sha, fit_controllers, select
from .training_common import Journal
from . import feedback_rollout


def fixture(pairs=1):
    splits = {}
    for index, role in enumerate(("runtime_fit", "runtime_select")):
        rng = torch.Generator().manual_seed(271033+index)
        images = torch.randint(0, 256, (2*pairs, 1, 28, 28), generator=rng, dtype=torch.uint8)
        hashes = tuple(hashlib.sha256(row.numpy().tobytes()).hexdigest() for row in images)
        splits[role] = SourceSplit(images, (torch.arange(2*pairs)+index+1) % 10,
            tuple(f"artificial:{role}:{i}:{digest}" for i, digest in enumerate(hashes)), hashes)
    manifest = {"schema": "artificial-integration-fixture", "no_MNIST_or_registered_sources": True,
                "manifest_sha256": hashlib.sha256(b"artificial-v3-runtime-fixture-271033").hexdigest()}
    protocol = {"runtime": {"fit_pairs": pairs, "selection_pairs": pairs, "batch_size": pairs,
        "conditions": ["heavy_noise", "missing", "occlusion", "clean"]}}
    return SourceCorpus(splits, manifest), protocol


def expect_error(call):
    try:
        call()
    except (ValueError, TypeError):
        return
    raise AssertionError("Expected task/feedback boundary rejection")


def batching_witness():
    """Measure the raw Torch batching risk without opening any trained asset."""
    from ..field_bridge_20261027.task import _hard_output, public_features
    torch.manual_seed(271033)
    model = NeuralPortfolio(hidden=96).eval().requires_grad_(False)
    observer = Recognizer().eval().requires_grad_(False)
    rng = torch.Generator().manual_seed(271034)
    x = Observation(torch.rand((3, 1, 28, 56), generator=rng), torch.ones(3, 1, 28, 56),
                    torch.tensor([[1, 9, 12, 11, 13, 11, 2, 0]]).repeat(3, 1))
    noise = torch.randn((3, 96), generator=rng)
    with torch.inference_mode():
        grouped = model.decode(model.step(model.encode(x, noise), "couple"))
        grouped_features = public_features(x, grouped, observer, _hard_output(grouped))
        outputs, features = [], []
        for index in range(3):
            one = Observation(x.pixels[index:index+1], x.mask[index:index+1], x.text_tokens[index:index+1])
            output = model.decode(model.step(model.encode(one, noise[index:index+1]), "couple"))
            outputs.append(output)
            features.append(public_features(one, output, observer, _hard_output(output)))
        images, texts, single = torch.cat([o.image_logits for o in outputs]), torch.cat([o.text_logits for o in outputs]), torch.cat(features)
        return {"synthetic_only": True, "untrained_model_and_observer": True, "model_seed": 271033,
            "input_seed": 271034, "image_logit_max_abs_difference": float((images-grouped.image_logits).abs().max()),
            "text_logit_max_abs_difference": float((texts-grouped.text_logits).abs().max()),
            "public_feature_max_abs_difference": float((single-grouped_features).abs().max()),
            "different_public_feature_coordinates": int((single != grouped_features).sum()),
            "different_hard_pixels": int(((images.sigmoid()*255).round() != (grouped.image_logits.sigmoid()*255).round()).sum())}


def rollout_contract(model, observers, fitted, bridge, out):
    corpus, protocol = fixture(3)
    _, _, case_ids, batch = next(batches(corpus, "runtime_select", 17, protocol))
    case_ids = tuple("mixed-fixture-"+name for name in case_ids)
    with MediaWriter(out/"mixed-bank.h3m") as writer, Journal(out/"mixed-bank.jsonl.gz") as journal:
        events, values, _ = build_tree_batch(model, batch, observers["reward"], writer, journal, case_ids, "runtime_select")
    records = {}
    with gzip.open(out/"mixed-bank.jsonl.gz", "rt") as stream:
        for line in stream:
            row = json.loads(line)
            for case, media in zip(row["case_ids"], row["media"], strict=True):
                records[(case, row["node"])] = media["record_sha256"]
    policies = {"root_stop": {"kind": "fixed", "node": 0, "actions": []},
                "three_revisions": {"kind": "fixed", "node": 21, "actions": [1, 1, 1]},
                **fitted["models"], "mixed_actions": fitted["models"]["history"]}
    counts, checked_histories = {}, 0
    for arm, controller in policies.items():
        observed_histories = []

        def intercepted(policy, histories, **kwargs):
            assert isinstance(histories, np.ndarray) and histories.dtype != object
            assert not isinstance(histories, (Observation, Target))
            assert set(kwargs) <= {"bridge", "sessions"}
            observed_histories.append(histories.copy())
            if arm == "mixed_actions":
                chosen = np.asarray(([1, 2, 0], [0, 3], [4])[len(observed_histories)-1])
                assert len(chosen) == len(histories)
                return chosen, {"action_indices": chosen.tolist(), "round": histories.shape[1]-1,
                    "representation": "history", "target_accesses": 0, "future_events_accessed": 0,
                    "native_tick_calls": 0, "native_ns": 0, "select_wall_ns": 0, "select_python_cpu_ns": 0}
            return select(policy, histories, **kwargs)

        with MediaWriter(out/f"rollout-{arm}.h3m") as writer, Journal(out/f"rollout-{arm}.jsonl.gz") as journal, \
                patch.object(feedback_rollout, "select", side_effect=intercepted), \
                patch.object(model, "encode", wraps=model.encode) as encoder, \
                patch.object(model, "step", wraps=model.step) as transition, \
                patch.object(model, "decode", wraps=model.decode) as decoder:
            rows, cost = feedback_rollout.rollout_batch(model, batch, observers, controller, bridge,
                writer, journal, case_ids, "runtime_select", arm)
            encoder_sizes = [len(call.args[0].pixels) for call in encoder.call_args_list]
            transition_sizes = [len(call.args[0].h) for call in transition.call_args_list]
            decoder_sizes = [len(call.args[0].h) for call in decoder.call_args_list]
            assert all(size == 1 for size in encoder_sizes+transition_sizes+decoder_sizes)
            assert sum(encoder_sizes) == cost["encoder_examples"] == cost["encoder_batches"] == 3
            assert sum(transition_sizes) == cost["transition_examples"] == cost["transition_batches"]
            assert sum(decoder_sizes) == cost["decoder_examples"] == cost["decoder_batches"] == writer.records
        total_depth = 0
        for index, row in enumerate(rows):
            node = 0
            for action in row["actions"]:
                if action == 0:
                    break
                node = 4*node+action
            assert node == row["terminal_node"]
            assert row["scores"]["reward"]["net_utility"] == float(values[index, node])
            assert row["media"][-1]["record_sha256"] == records[(case_ids[index], node)]
            assert len(row["media"]) == row["depth"]+1 and row["unchosen_continuations_executed"] == 0
            total_depth += row["depth"]
        assert cost["transition_examples"] == cost["decoder_examples"] == 3+total_depth
        assert cost["unchosen_continuations_executed"] == 0
        assert cost["simulated_feedback_packets"] == sum(min(row["depth"], 2) for row in rows)
        assert cost["public_feature_observer_digit_examples"] == 2*(3+cost["simulated_feedback_packets"])
        assert cost["selection_rows"] == sum(min(row["depth"]+1, 3) for row in rows)
        assert cost["native_tick_calls"] == (2*cost["selection_rows"] if "native" in arm else 0)
        assert cost["reward_outcome_observer_digit_examples"] == cost["audit_outcome_observer_digit_examples"] == 6
        if arm == "mixed_actions":
            assert [row["terminal_node"] for row in rows] == [1, 48, 0]
            assert [row["actions"] for row in rows] == [[1, 0], [2, 3, 4], [0]]
            assert [h.shape for h in observed_histories] == [(3, 1, 16), (2, 2, 16), (1, 3, 16)]
            assert cost["transition_examples"] == cost["decoder_examples"] == 7
            assert cost["simulated_feedback_packets"] == 3
        # Reconstruct each active history from the complete tree using only the
        # actual prior actions, independently of evaluator history concatenation.
        for round_index, recorded in enumerate(observed_histories):
            expected = []
            for index, row in enumerate(rows):
                if len(row["actions"]) <= round_index:
                    continue
                ancestors, node = [0], 0
                for action in row["actions"][:round_index]:
                    assert action != 0
                    node = 4*node+action
                    ancestors.append(node)
                expected.append(events[index, ancestors])
            assert np.array_equal(recorded, np.asarray(expected))
            checked_histories += len(recorded)
        counts[arm] = {key: cost[key] for key in ("encoder_examples", "transition_examples", "decoder_examples",
            "simulated_feedback_packets", "selection_rows", "native_tick_calls", "unchosen_continuations_executed")}
    return {"episodes": 21, "full_tree_output_states": 255, "histories_checked": checked_histories,
            "mixed_action_terminal_nodes": [1, 48, 0], "canonical_arithmetic_model_batches": 1,
            "all_selected_values_and_media_match_tree": True, "resources_by_arm": counts}


def dedup_contract(model, corpus, observer, protocol, out):
    _, _, case_ids, batch = next(batches(corpus, "runtime_select", 17, protocol))
    with MediaWriter(out/"dedup.h3m") as writer, \
            patch.object(model, "encode", wraps=model.encode) as encoder, \
            patch.object(model, "step", wraps=model.step) as transition, \
            patch.object(model, "decode", wraps=model.decode) as decoder:
        first = start(model, batch.observation, observer, writer, case_ids)
        before = writer.bytes
        second = start(model, batch.observation, observer, writer, case_ids)
        assert encoder.call_count == transition.call_count == decoder.call_count == 2
        assert writer.records == 2 and writer.physical_records == 1 and writer.bytes == before
        a, b = first.hard.receipts[0], second.hard.receipts[0]
        assert a["offset"] == b["offset"] and a["record_sha256"] == b["record_sha256"]
        assert b["readback_monotonic_ns"] > a["readback_monotonic_ns"]
    pixels, caption, _ = read_receipt(out, b)
    assert np.array_equal(pixels, second.hard.pixels_u8[0, 0].numpy()) and caption == second.hard.captions[0]
    return {"logical_deliveries_read_back": 2, "unique_physical_records": 1,
            "actual_encoder_calls": 2, "actual_transition_calls": 2, "actual_decoder_calls": 2,
            "model_cache_used": False, "new_readback_receipt_for_each_delivery": True}


def run(library, out):
    started = time.perf_counter_ns()
    out.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    arithmetic_witness = batching_witness()
    torch.manual_seed(271033)
    model = NeuralPortfolio(hidden=16).eval().requires_grad_(False)
    observer = Recognizer().eval().requires_grad_(False)
    audit_observer = Recognizer().eval().requires_grad_(False)
    model_before, observer_before = parameter_hash(model), parameter_hash(observer)
    corpus, protocol = fixture()
    for role in ("runtime_fit", "runtime_select"):
        build_bank(model, corpus, observer, 17, "artificial", role, protocol, out/role,
            {"synthetic_only": True, "trained_assets_loaded": False})
    train, selection = load_bank(out/"runtime_fit", "runtime_fit"), load_bank(out/"runtime_select", "runtime_select")
    assert train["events"].shape == selection["events"].shape == (4, 21, 16)
    offline_records = {}
    with gzip.open(out/"runtime_select/evidence.jsonl.gz", "rt") as stream:
        for line in stream:
            row = json.loads(line)
            offline_records[(row["case_ids"][0], row["node"])] = row["media"][0]["record_sha256"]
    episode_count = feedback_count = decisions = output_records = 0
    rejection_checks = 0
    feature_path = out/"synthetic_fitted_features.npz"
    with NativeStreamBridge(library) as bridge:
        fitted = fit_controllers(train, selection, bridge, metadata={"synthetic_only": True}, feature_destination=feature_path)
        saved = np.load(feature_path, allow_pickle=False)
        integration_tick_start = bridge.tick_count
        for rep, selected_policy in fitted["models"].items():
            for forced in (False, True):
                controller = copy.deepcopy(selected_policy)
                if forced:
                    for head in controller["heads"]:
                        head["coefficient"] = np.zeros((89, 5)).tolist()
                        head["coefficient"][-1][1] = 1
                media_path = out/f"online-{rep}-{'forced' if forced else 'selected'}.h3m"
                with MediaWriter(media_path) as writer:
                    for index, (_, _, case_ids, batch) in enumerate(batches(corpus, "runtime_select", 17, protocol)):
                        delivered = start(model, batch.observation, observer, writer, case_ids)
                        expect_error(lambda: verifier_review(delivered, batch.target))
                        rejection_checks += 1
                        histories, node, packets = [], 0, None
                        session = bridge.open(case_ids[0]+f"-{rep}-{forced}") if "native" in rep else None
                        try:
                            for stage in range(3):
                                assert delivered.hard.receipts[0]["record_sha256"] == offline_records[(case_ids[0], node)]
                                event = public_event(delivered, packets)
                                assert np.array_equal(event[0], selection["events"][index, node])
                                histories.append(event[0])
                                kwargs = {"bridge": bridge, "sessions": [session]} if session is not None else {}
                                action, summary = select(controller, np.asarray(histories)[None], **kwargs)
                                cached = saved[f"{controller['transform']['name']}.{rep}.selection"][index, node][None]
                                assert summary["feature_matrix_sha256"] == array_sha(cached)
                                decisions += 1
                                action = int(action[0])
                                if forced:
                                    assert action == 1
                                if action == 0:
                                    break
                                delivered = revise(model, delivered, action, observer, writer)
                                node = 4*node+action
                                if stage < 2:
                                    packets = verifier_review(delivered, batch.target)
                                    assert len(packets[0]["public_feedback"]) == 4
                                    assert "label" not in packets[0] and "pixels" not in packets[0]
                                    feedback_count += 1
                                    bad = copy.deepcopy(packets)
                                    bad[0]["after_readback_monotonic_ns"] = delivered.hard.receipts[0]["readback_monotonic_ns"]-1
                                    expect_error(lambda: public_event(delivered, bad))
                                    rejection_checks += 1
                            measured = score(delivered, batch.target, observer)[0]["net_utility"]
                            assert measured == float(selection["terminal_values"][index, node])
                            assert delivered.hard.receipts[0]["record_sha256"] == offline_records[(case_ids[0], node)]
                            pixels, caption, _ = read_receipt(out, delivered.hard.receipts[0])
                            assert np.array_equal(pixels, delivered.hard.pixels_u8[0, 0].numpy())
                            assert caption == delivered.hard.captions[0]
                            if forced:
                                assert node == 21 and delivered.depth == 3
                                if session is not None:
                                    assert session.clock == 6
                                expect_error(lambda: verifier_review(delivered, batch.target))
                                expect_error(lambda: revise(model, delivered, 1, observer, writer))
                                rejection_checks += 2
                            episode_count += 1
                        finally:
                            if session is not None:
                                session.close()
                    output_records += writer.records
        native_ticks = bridge.tick_count-integration_tick_start
        rollout = rollout_contract(model, {"reward": observer, "audit": audit_observer}, fitted, bridge, out)
        dedup = dedup_contract(model, corpus, observer, protocol, out)
        assert bridge.library.hepta_stream_live_sessions() == 0
    assert parameter_hash(model) == model_before and parameter_hash(observer) == observer_before
    result = {"schema": "hepta.field-bridge-v3.runtime-media-integration-contract.v1", "passed": True,
        "synthetic_only": True, "MNIST_or_registered_sources_opened": False, "trained_assets_loaded": False,
        "offline_tree_base_cases": 8, "offline_logical_deliveries_read_back": 680,
        "offline_feedback_packets": 160, "selected_or_forced_live_episodes": episode_count,
        "live_decisions": decisions, "live_feedback_packets": feedback_count,
        "live_media_logical_deliveries_read_back": output_records, "live_native_ticks": native_ticks,
        "premature_or_exhausted_feedback_action_guards": rejection_checks,
        "offline_online_event_feature_value_media_exact": True,
        "raw_torch_batching_witness": arithmetic_witness, "selected_rollout_contract": rollout,
        "physical_media_deduplication_contract": dedup,
        "generator_and_observer_parameters_unchanged": True,
        "native_library_sha256": file_sha(library), "test_source_sha256": file_sha(__file__),
        "source_sha256": {name: file_sha(Path(__file__).with_name(name)) for name in
            ("feedback_bank.py", "feedback_task.py", "feedback_media.py", "feedback_rollout.py", "runtime_controller.py", "native_stream.py")},
        "wall_ns": time.perf_counter_ns()-started}
    (out/"RUNTIME_MEDIA_INTEGRATION_CONTRACT.json").write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.library, args.out), indent=2))
