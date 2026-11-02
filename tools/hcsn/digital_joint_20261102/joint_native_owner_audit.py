"""Independent semantic/privacy audit of the real joint native owner records.

This reads excluded engineering fixtures only, never scientific confirmation
worlds. It replays Python task semantics, checks score/mass/history identities,
independently decodes each successful packet once, and inspects persisted ACK
generations. It does not prove every crash point or external exactly-once IO.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from . import joint_task as task
from .joint_deploy import NumpyPolicy
from .joint_law import IndependentLaw
from .joint_task_audit import fixture

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def same_state(actual, expected):
    a, b = deepcopy(actual), deepcopy(expected)
    error = max(abs(a.pop(k)-b.pop(k)) for k in ("charges", "elapsed"))
    if a != b or error > 2e-12:
        raise AssertionError("task/history/clock state mismatch")
    return error


def validate_generation(directory):
    ack = read(directory/"CURRENT.json")["ack"]
    committed = directory/"generations"/ack; manifest = read(committed/"manifest.json")
    assert sha(committed/"manifest.json") == ack
    assert {p.name: sha(p) for p in (committed/"payload").iterdir()} == manifest["payload"]
    result = read(committed/"result.json")
    assert sha(committed/"result.json") == manifest["result_sha256"]
    assert result["acknowledged_sha256"] == sha(committed/"payload/owner.json")
    return manifest, result


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True); args = parser.parse_args()
    root = args.qualification.resolve(); summary = read(root/"SUMMARY.json")
    wall, cpu = time.perf_counter(), time.process_time(); adapter = task.ContentAdapter()
    publics = {sha(p): (read(p), p.parent) for p in root.glob("engineering_*/public.json")}
    artifacts = {sha(p): read(p) for p in (root/"models").glob("*.json")}
    decoded, rows, attempts, successes, failures, pending, cancellation = {}, 0, 0, 0, 0, 0, 0
    score_error = task_error = 0.; cases = []
    for path in sorted(root.glob("*.evidence.json")):
        evidence = read(path); full, prefix, resumed = [evidence[k] for k in ("full", "prefix", "resumed")]
        identity = full["before"]["identity"]
        public, folder = publics[identity["public_sha256"]]
        policy = NumpyPolicy(artifacts[identity["policy_sha256"]])
        assert full["actual_native"] and not full["production_activation"] and full["authority"] == "DENY_ALL"
        assert not full["forced_control"] and identity["mode"] == "qualification"
        assert full["after"] == resumed["after"] and full["acknowledged_sha256"] == resumed["acknowledged_sha256"]
        assert resumed["before"] == prefix["after"] and resumed["external_ack_verified"]
        pending += int(prefix["after"]["task"]["pending"] is not None)
        state = task.initial(public); task_error = max(task_error, same_state(full["before"]["task"], state))
        ledger = []
        for receipt in full["receipts"]:
            rows += 1; task_error = max(task_error, same_state(receipt["before"], state))
            scores = policy.predict(public, state); mask = task.legal(public, state)
            action = task.fixed_action(state, mask, scores["belief"]) if identity["controller"] == "fixed" else int(np.argmax(np.where(mask, scores["q"], -np.inf)))
            assert action == receipt["action"] and receipt["legal"] == mask
            assert receipt["public_features"] == task.public_features(public, state).tolist()
            for actual, expected in ((receipt["q"], scores["q"]), (receipt["cell_before"]["mass"], scores["mass"]), (receipt["cell_before"]["bank"], scores["bank"])):
                score_error = max(score_error, float(np.max(np.abs(np.asarray(actual)-expected))))
            score_error = max(score_error, abs(receipt["belief"]-scores["belief"]))
            due = task.due_request(public, state, action); completion = receipt["completion"]
            assert receipt["due_source"] == (None if due is None else due-1)
            if due is None:
                assert completion is None and receipt["actual_content_calls"] == 0 and not receipt["attempted_packet_paths"]
                cancellation += int(action in (0, 4, 5) and state["pending"] is not None)
            else:
                attempts += 1; packet = folder/public["packets"][due-1]
                assert completion["observation_tick"] == due
                assert receipt["attempted_packet_paths"] == [str(packet)]
                if completion.get("failure", False):
                    assert not packet.exists() and receipt["actual_content_calls"] == 0
                    failures += 1
                else:
                    digest = sha(packet); assert digest == public["packet_sha256"][due-1]
                    if digest not in decoded:
                        decoded[digest] = adapter.read(packet)
                    actual = decoded[digest]
                    assert actual["observation"] == completion["observation"] == receipt["content"]["observation"]
                    assert receipt["content"]["payload_sha256"] == digest and receipt["actual_content_calls"] == 1
                    successes += 1
            after = task.successor(public, state, action, completion)
            task_error = max(task_error, same_state(receipt["after"], after))
            mass, bank, _ = policy.represent(public, after)
            score_error = max(score_error, float(np.max(abs(np.asarray(receipt["cell_after"]["mass"])-mass))),
                              float(np.max(abs(np.asarray(receipt["cell_after"]["bank"])-bank))))
            ledger.append(dict(action=action, forced_control=False, completion=completion, content=receipt["content"]))
            state = after
        assert state["terminal"] and full["after"]["ledger"] == ledger
        task_error = max(task_error, same_state(full["after"]["task"], state))
        assert full["after"]["content"]["completed_reads"] == len(state["history"])
        rawdir = root/(path.name.removesuffix(".evidence.json")+"_raw")
        assert sha(rawdir/"full.json") == full["acknowledged_sha256"]
        assert sha(rawdir/"resume.json") == resumed["acknowledged_sha256"]
        cases.append(dict(name=path.name, actions=len(full["receipts"]), family=identity["controller"]))
    assert len(cases) == summary["paired_episodes"] == 48 and successes == summary["actual_content_calls"]
    assert pending == summary["pending_cold_resumes"] and score_error < 5e-12
    faults = []
    for row in summary["fault_cases"]:
        fi = 3 if row["missing"] else 2
        baseline = root/f"normal_transaction_{row['family']}_{fi}"
        fault = root/f"fault_{row['family']}_{fi}_{row['fault']}"
        baseline_manifest, normal = validate_generation(baseline)
        fault_manifest, recovered = validate_generation(fault)
        assert normal["after"] == recovered["after"]
        assert baseline_manifest["request_id"] == fault_manifest["request_id"] == "due"
        assert fault_manifest["parent_ack"] is not None and fault_manifest["steps"] == 1
        faults.append(dict(family=row["family"], missing=row["missing"], fault=row["fault"], exact_published_state=True))
    assert len(faults) == summary["transaction_crash_cases"] == 48

    # Model-law diagnostic only: no new world/cohort or empirical utility claim.
    protocol = read(HERE/"joint_protocol.json"); law = IndependentLaw(protocol["truth_raw"])
    public = fixture(); public.update(duration=[.25]*6, drive=[1, -1, 1, -1, 1, -1],
            read_delay=[1]*6, reliability=[.85]*6, read_price=[.03]*6,
            latency_price=.025, failure_probability=0.)
    confusion = np.array([[.97, .03], [.04, .96]]); prior_cases = []
    for distance in (.125, .375, .75):
        public["prior_distance"] = distance; oracle = task.Oracle(public, law, confusion)
        state = task.initial(public); initial_target = oracle.posterior(state)
        q = oracle.q(state); no_read = abs(2*initial_target-1)
        initial_mass = law.initial_mass(distance)
        assert initial_mass[law.positive].sum() == .5 and np.count_nonzero(initial_mass) == 2
        center_atom = float(oracle.future_mass(state)[law.n_grid//2])
        passive = deepcopy(state)
        for _ in range(6):
            passive = task.successor(public, passive, 1)
            assert abs(oracle.posterior(passive)-initial_target) < 3e-13
        assert max(q) > no_read+.1 and 0.01 < initial_target < .99
        prior_cases.append(dict(prior_distance=distance, initial_sign_probability=.5,
             deadline_probability=initial_target, no_read_utility=no_read,
             declared_model_dp_value=float(max(q)), center_grid_atom_label0=center_atom))
    result = dict(schema="joint-native-owner-independent-audit-v1", passed=True,
          qualification_sha256=sha(root/"SUMMARY.json"), paired_episodes=len(cases), actions=rows,
          max_q_mass_bank_error=score_error, max_task_time_fee_error=task_error,
          attempts=attempts, successes=successes, failures=failures,
          unique_successful_packets_independently_decoded=len(decoded),
          pending_cold_resumes=pending, pending_cancellations=cancellation,
          exact_published_transaction_recoveries=len(faults),
          protocol_semantic_diagnostic=prior_cases, formal_worlds_generated=0,
          privacy_static_review="policy/DecisionPort take public43, learned artifact and completed task history; no folder, evaluator, target label, true law, teacher posterior or Q enters prediction",
          scope="bounded excluded engineering fixtures; finite CTMC center atom retained as label0; no scientific efficacy, universal crash safety, or external physical exactly-once claim",
          source_sha256={n:sha(HERE/n) for n in ("joint_native_owner_audit.py", "joint_task.py", "joint_deploy.py", "joint_native_task.rs", "joint_native_policy.rs", "joint_native_full_build.py", "joint_native_owner.py")},
          wall_seconds=time.perf_counter()-wall, cpu_seconds=time.process_time()-cpu)
    args.out.parent.mkdir(parents=True, exist_ok=True); args.out.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
