"""Synthetic causal planning contracts, independently reconstructed targets.

Uses no corpus, generator, observer or scientific outcome. These artificial tree
values test accounting/causality, never establish empirical control benefit.
"""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import time
from unittest.mock import patch

import numpy as np

from .native_stream import NativeStreamBridge, file_sha
from . import runtime_controller as runtime


def digest(values):
    return hashlib.sha256(np.asarray(values, dtype="<f8").tobytes()).hexdigest()


def path(node):
    result = []
    while node:
        result.append(node)
        node = (node-1)//4
    return [0]+result[::-1]


def fixture(role, count, seed):
    rng = np.random.default_rng(seed)
    events = rng.uniform(-1, 1, (count, 21, 16))
    events[:, 0, 8:] = 0
    for node in range(1, 21):
        events[:, node, 8] = 1
        events[:, node, 9:11] = rng.choice([-1., 1.], size=(count, 2))
        events[:, node, 12:] = 0
        events[:, node, 12+(node-1) % 4] = 1
    # Independent random terminal values make clairvoyant future choices differ
    # from a finite readout's actual future policy for many reached states.
    values = rng.uniform(-.9, .9, (count, 85))
    return {"role": role, "events": events, "terminal_values": values,
            "source_ids": np.asarray([[f"synthetic:{role}:{i}:L", f"synthetic:{role}:{i}:R"] for i in range(count)], dtype=str)}


def actions(head, features):
    z = (features-np.asarray(head["normalizer"]["mean"]))/np.asarray(head["normalizer"]["scale"])
    return np.c_[z, np.ones(len(z))].dot(np.asarray(head["coefficient"])).argmax(1)


def follow(heads, features, values, row, node):
    while node < 21:
        stage = len(path(node))-1
        action = int(actions(heads[stage], features[row, node][None])[0])
        if action == 0:
            break
        node = 4*node+action
    return values[row, node], node


def expect_error(call):
    try:
        call()
    except (ValueError, TypeError):
        return
    raise AssertionError("Expected causal/fitting boundary rejection")


def run(library, out):
    started = time.perf_counter_ns()
    out.mkdir(parents=True, exist_ok=False)
    train, selection = fixture("runtime_fit", 12, 271033), fixture("runtime_select", 9, 271034)
    before_train, before_select = digest(train["events"]), digest(selection["terminal_values"])
    evidence = out/"synthetic_features.npz"
    with NativeStreamBridge(library) as bridge:
        fitted = runtime.fit_controllers(train, selection, bridge, metadata={"synthetic_only": True}, feature_destination=evidence)
        assert fitted["candidate_policies"] == 48 and fitted["stage_head_fits"] == 144
        assert fitted["native_tick_calls"] == 336*(len(train["events"])+len(selection["events"]))
        features = np.load(evidence, allow_pickle=False)
        assert len(features.files) == 32
        target_checks, rollout_checks, nonoracle_targets = 0, 0, 0
        for candidate in fitted["candidates"]:
            policy = candidate["controller"]
            rep, transform = policy["representation"], policy["transform"]["name"]
            assert len(policy["heads"]) == 3 and policy["head_coefficients"] == 1335
            tx = features[f"{transform}.{rep}.train"]
            for stage, nodes in enumerate(([0], range(1, 5), range(5, 21))):
                expected = []
                for row in range(len(tx)):
                    for node in nodes:
                        values = [train["terminal_values"][row, node]]
                        for action in range(1, 5):
                            child = 4*node+action
                            actual, _ = follow(policy["heads"], tx, train["terminal_values"], row, child)
                            values.append(actual)
                            if stage == 1:
                                oracle = max(train["terminal_values"][row, child],
                                             *train["terminal_values"][row, 4*child+1:4*child+5])
                                nonoracle_targets += int(actual < oracle)
                        expected.append(values)
                assert digest(expected) == policy["heads"][stage]["targets_sha256"]
                target_checks += 1
            for bank, label in ((train, "train"), (selection, "selection")):
                x = features[f"{transform}.{rep}.{label}"]
                actual = [follow(policy["heads"], x, bank["terminal_values"], row, 0) for row in range(len(x))]
                field = "training" if label == "train" else "selection"
                assert [node for _, node in actual] == candidate[field+"_terminal_nodes"]
                assert np.mean([value for value, _ in actual]) == candidate[field+"_mean_value"]
                rollout_checks += len(actual)
        assert nonoracle_targets > 0

        changed = copy.deepcopy(selection)
        changed["events"][:, :, :8] *= -1
        changed["terminal_values"] *= -1
        refitted = runtime.fit_controllers(train, changed, bridge, metadata={"synthetic_only": True})
        for old, new in zip(fitted["candidates"], refitted["candidates"], strict=True):
            a, b = old["controller"], new["controller"]
            assert a["heads"] == b["heads"] and a["transform"] == b["transform"] and a["fourier"] == b["fourier"]
        assert digest(train["events"]) == before_train and digest(selection["terminal_values"]) == before_select
        assert fitted["fixed_policy"]["node"] == int(selection["terminal_values"].mean(0).argmax())

        batch_split_checks = 0
        for rep in ("current", "history"):
            controller = fitted["models"][rep]
            cached = features[f"{controller['transform']['name']}.{rep}.selection"]
            for node in range(21):
                histories = selection["events"][:, path(node)]
                whole, summary = runtime.select(controller, histories)
                assert summary["feature_matrix_sha256"] == digest(cached[:, node])
                divided = []
                for row in range(len(histories)):
                    chosen, part = runtime.select(controller, histories[row:row+1])
                    assert part["feature_matrix_sha256"] == digest(cached[row:row+1, node])
                    divided.append(int(chosen[0]))
                    batch_split_checks += 1
                assert np.array_equal(whole, divided)
        deployed_rows = native_rows = 0
        with patch.object(runtime, "_ridge", side_effect=AssertionError("Deployment attempted fitting")), \
                patch.object(runtime, "_normalizer", side_effect=AssertionError("Deployment attempted normalization fitting")):
            for rep, controller in fitted["models"].items():
                restored = json.loads(json.dumps(controller))
                assert restored == controller
                nodes = np.zeros(len(selection["events"]), dtype=int)
                active = list(range(len(nodes)))
                sessions = {i: bridge.open(f"synthetic-deploy-{rep}-{i}") for i in active} if "native" in rep else {}
                try:
                    for stage in range(3):
                        if not active:
                            break
                        histories = np.stack([selection["events"][i, path(int(nodes[i]))] for i in active])
                        kwargs = {"bridge": bridge, "sessions": [sessions[i] for i in active]} if sessions else {}
                        selected, summary = runtime.select(restored, histories, **kwargs)
                        expected_features = features[f"{controller['transform']['name']}.{rep}.selection"][active, nodes[active]]
                        expected = actions(controller["heads"][stage], expected_features)
                        assert np.array_equal(selected, expected)
                        assert summary["feature_matrix_sha256"] == digest(expected_features)
                        assert summary["target_accesses"] == summary["future_events_accessed"] == 0
                        native_rows += summary["native_tick_calls"]//2
                        deployed_rows += len(active)
                        next_active = []
                        for row, action in zip(active, selected, strict=True):
                            if action:
                                nodes[row] = 4*nodes[row]+action
                                next_active.append(row)
                        active = next_active
                    candidate = next(c for c in fitted["candidates"] if c["representation"] == rep and
                                     c["candidate_index"] == controller["candidate_index"])
                    assert nodes.tolist() == candidate["selection_terminal_nodes"]
                finally:
                    for session in sessions.values():
                        session.close()

        # The current-only representation must discard earlier public events;
        # the full-history control must preserve those same causal coordinates.
        original_history = selection["events"][:1, [0, 1, 5]]
        alternate_history = original_history.copy()
        alternate_history[:, :2, :8] *= -1
        current_a = runtime.select(fitted["models"]["current"], original_history)[1]
        current_b = runtime.select(fitted["models"]["current"], alternate_history)[1]
        history_a = runtime.select(fitted["models"]["history"], original_history)[1]
        history_b = runtime.select(fitted["models"]["history"], alternate_history)[1]
        assert current_a["feature_matrix_sha256"] == current_b["feature_matrix_sha256"]
        assert history_a["feature_matrix_sha256"] != history_b["feature_matrix_sha256"]
        guards = 0
        for role in ("runtime_audit", "primary", "retention"):
            invalid = dict(train, role=role)
            expect_error(lambda: runtime.fit_controllers(invalid, selection, bridge))
            guards += 1
        overlap = dict(selection, source_ids=selection["source_ids"][:])
        overlap["source_ids"][0] = train["source_ids"][0]
        expect_error(lambda: runtime.fit_controllers(train, overlap, bridge))
        guards += 1
        inconsistent = copy.deepcopy(train)
        inconsistent["events"][0, 1, 12:] = [0, 1, 0, 0]
        expect_error(lambda: runtime.fit_controllers(inconsistent, selection, bridge))
        guards += 1

        controller = copy.deepcopy(fitted["models"]["native"])
        for head in controller["heads"]:
            head["coefficient"] = np.zeros((89, 5)).tolist()
            head["coefficient"][-1][1] = 1
        with bridge.open("causality-guards") as session:
            h0 = selection["events"][:1, [0]]
            selected, _ = runtime.select(controller, h0, bridge=bridge, sessions=[session])
            assert selected.tolist() == [1] and session.clock == 2
            h1 = selection["events"][:1, [0, 1]]
            rewritten = h1.copy()
            rewritten[0, 0, 0] = -rewritten[0, 0, 0]
            expect_error(lambda: runtime.select(controller, rewritten, bridge=bridge, sessions=[session]))
            wrong_action = h1.copy()
            wrong_action[0, -1, 12:] = [0, 1, 0, 0]
            expect_error(lambda: runtime.select(controller, wrong_action, bridge=bridge, sessions=[session]))
            expect_error(lambda: runtime.select(controller, h0, bridge=bridge, sessions=[session]))
            altered = copy.deepcopy(controller)
            altered["heads"][2]["coefficient"][-1][1] = 2
            expect_error(lambda: runtime.select(altered, h1, bridge=bridge, sessions=[session]))
            expect_error(lambda: runtime.select(controller, np.repeat(h1, 2, axis=0), bridge=bridge, sessions=[session, session]))
            assert session.clock == 2
            guards += 5
            with session.fork() as forked:
                a, sa = runtime.select(controller, h1, bridge=bridge, sessions=[session])
                b, sb = runtime.select(controller, h1, bridge=bridge, sessions=[forked])
                assert a.tolist() == b.tolist() == [1]
                assert sa["feature_matrix_sha256"] == sb["feature_matrix_sha256"]
            with bridge.open("fresh-next-round") as fresh:
                expect_error(lambda: runtime.select(controller, h1, bridge=bridge, sessions=[fresh]))
                guards += 1
            pathfile = out/"occupied-receipt.jsonl"
            pathfile.write_text("preserved\n")
            h2 = selection["events"][:1, [0, 1, 5]]
            expect_error(lambda: runtime.select(controller, h2, bridge=bridge, sessions=[session], receipt_path=pathfile))
            assert pathfile.read_text() == "preserved\n" and session.clock == 4
            guards += 1
        assert bridge.library.hepta_stream_live_sessions() == 0
        total_ticks = bridge.tick_count
    result = {"schema": "hepta.field-bridge-v3.runtime-controller-contract.v1", "passed": True,
        "synthetic_only": True, "corpus_or_generator_accessed": False, "candidates_per_fit": 48,
        "head_fits_per_fit": 144, "independent_stage_target_hash_checks": target_checks,
        "independent_candidate_rollout_rows": rollout_checks, "nonoracle_tail_targets_witnessed": nonoracle_targets,
        "selection_perturbation_changed_no_fitted_head": True, "serialized_selected_policy_live_decision_rows": deployed_rows,
        "native_selected_live_decision_rows": native_rows, "fitting_and_causality_rejection_guards": guards,
        "deployment_fitting_forbidden": True, "native_ticks_executed": total_ticks,
        "current_only_history_ablation_verified": True,
        "batch_splitting_bitwise_feature_and_action_checks": batch_split_checks,
        "controller_source_sha256": file_sha(runtime.__file__), "test_source_sha256": file_sha(__file__),
        "native_library_sha256": file_sha(library), "synthetic_features_sha256": file_sha(evidence),
        "authority": "DENY_ALL", "native_owner_integration": False, "wall_ns": time.perf_counter_ns()-started}
    (out/"RUNTIME_CONTROLLER_CONTRACT.json").write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.library, args.out), indent=2))
