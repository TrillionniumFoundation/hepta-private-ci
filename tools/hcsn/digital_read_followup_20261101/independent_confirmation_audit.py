"""Reconstruct every confirmation trajectory and paired-fit interval.

Post-hoc verification only: this module changes no model, optimizer, cohort or
selection. It recomputes neural predictions through the archived torch-free
deployment code and terminal projection independently of control_campaign.
"""
import argparse
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from scipy.stats import t as student_t

from ..digital_read_before_20261031 import data, deploy, task

HERE = Path(__file__).resolve().parent
BASE = HERE.parent/"digital_read_before_20261031"


def read(path):
    path = Path(path)
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_inputs(confirmation, protocol):
    old = read(BASE/"protocol.json")
    old["confirmation_seed_base"] = protocol["confirmation_seed_base"]
    files, absent, worlds = {}, [], {}
    with TemporaryDirectory(prefix="digital-cohort-audit-") as temporary:
        for fit in protocol["fits"]:
            for split in ("iid", "ood"):
                cohort = data.cohort(temporary, split, fit, protocol["confirmation_worlds_per_split_fit"], old)
                worlds[(fit, split)] = [record["id"] for record in cohort["records"]]
                for relative, expected in cohort["files"].items():
                    path = confirmation/relative
                    assert sha(path) == expected
                    files[relative] = dict(sha256=expected, bytes=path.stat().st_size)
                for record in cohort["records"]:
                    folder = confirmation/record["id"]
                    public, evaluator = read(folder/"public.json"), read(folder/"evaluator.json")
                    for source, missing in enumerate(evaluator["injected_missing"]):
                        if missing:
                            path = folder/public["packets"][source]
                            assert not path.exists()
                            absent.append(dict(path=str(path.relative_to(confirmation)), expected_sha256=public["packet_sha256"][source]))
    assert {str(p.relative_to(confirmation)) for p in confirmation.glob("*_fit*/*") if p.is_file()} == set(files)
    return worlds, dict(schema="digital-confirmation-input-manifest-v1", regenerated_from_frozen_seeds=True, files=files, intentionally_absent=absent)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--confirmation", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    frozen = read(args.train/"MODEL_FREEZE.json")
    summary = read(args.confirmation/"SUMMARY.json")
    started = read(args.confirmation/"STARTED.json")
    assert started["model_freeze_sha256"] == sha(args.train/"MODEL_FREEZE.json")
    assert len(summary["published_freeze_commit"]) == 40
    assert summary["published_freeze_commit"] == started["published_freeze_commit"]
    protocol = started["protocol"]
    assert protocol == read(HERE/"control_protocol.json")
    assert all(sha(args.train/p) == h for p, h in frozen["models"].items())
    assert all(sha(BASE/p) == h for p, h in frozen["old_models"].items())
    repository = HERE.parent.parent.parent
    assert all(sha(repository/p) == h for p, h in frozen["sources"].items())
    training_payloads = {h for fit in frozen["fits"].values() for cohort in fit["cohorts"].values()
                         for h in cohort["payload_sha256"]}
    confirmation_payloads = [sha(path) for path in args.confirmation.glob("*_fit*/packet_*.json")]
    assert len(confirmation_payloads) == len(set(confirmation_payloads))
    assert set(confirmation_payloads).isdisjoint(training_payloads)
    worlds, input_manifest = verify_inputs(args.confirmation, protocol)
    groups, oracle_cache = set(), {}
    adapter = task.ContentAdapter()
    cached_content, file_hashes, aggregates = {}, {}, {}
    episodes_checked = decisions_checked = actual_calls = successful_decodes = 0
    maximum_score_error = maximum_metric_error = 0.
    for path in sorted(args.confirmation.glob("fit_*_*.json.gz")):
        record = read(path)
        fit, split, family, arm = (record[k] for k in ("fit", "split", "family", "arm"))
        group = (fit, split, family, arm)
        assert group not in groups
        groups.add(group)
        assert [episode["world"] for episode in record["episodes"]] == worlds[(fit, split)]
        artifact = read(args.train/f"fit_{fit}/{family}.json" if arm.startswith("repaired") else BASE/f"checkpoints/fit_{fit}/{family}.json.gz")
        policy = deploy.Policy(artifact)
        structured = arm in ("terminal_only", "repaired_fixed", "repaired_value")
        metrics = []
        for episode_index, episode in enumerate(record["episodes"]):
            folder = args.confirmation/episode["world"]
            public = read(folder/"public.json")
            state, index, rng = task.initial(public), 7, (971000+fit*10000+episode_index) & deploy.MASK64
            confusion = frozen["fits"][str(fit)]["confusion"]
            oracle_key = (sha(folder/"public.json"), json.dumps(confusion, sort_keys=True))
            if oracle_key not in oracle_cache:
                oracle_cache[oracle_key] = task.Oracle(public, confusion)
            oracle = oracle_cache[oracle_key]
            for decision in episode["decisions"]:
                receipt, action = decision["receipt"], decision["action"]
                assert receipt["before"] == state and receipt["action"] == action
                scores = policy.predict(public, state, index)
                q = np.asarray(scores["q"])
                belief = scores["belief"]
                if structured:
                    q[[0, 4, 5]] = [0., 1-2*belief, 2*belief-1]
                maximum_score_error = max(maximum_score_error, abs(belief-decision["belief"]), float(abs(q-decision["q"]).max()))
                mask = task.legal(public, state)
                expected = task.fixed_action(state, mask, belief) if arm.endswith("fixed") else int(np.argmax(np.where(mask, q, -np.inf)))
                assert action == expected and mask[action]
                source = task.due_request(public, state, action)
                assert source == receipt["source_opened"]
                if source is not None:
                    actual_calls += 1
                    packet = folder/public["packets"][source]
                    if receipt["completion"].get("failure", False):
                        assert not packet.exists(), "generated confirmations fail only through injected missing packets"
                    else:
                        successful_decodes += 1
                        key = str(packet)
                        if key not in cached_content:
                            cached_content[key] = adapter.read(packet)
                            file_hashes[str(packet.relative_to(args.confirmation))] = sha(packet)
                        actual = cached_content[key]
                        assert actual["observation"] == receipt["completion"]["observation"]
                        assert actual["payload_sha256"] == public["packet_sha256"][source] == receipt["content"]["payload_sha256"]
                event = dict(event=False, recovery=False)
                if action not in (0, 4, 5):
                    index, rng, event = policy.advance(public, state, index, rng)
                assert event == decision["event"]
                after = task.successor(public, state, action, receipt["completion"])
                assert after == receipt["after"]
                assert abs(decision["teacher_regret"]-(max(oracle.q(state))-oracle.q(state)[action])) < 1e-12
                assert abs(decision["chosen_q"]-q[action]) < 1e-10
                state = after
                decisions_checked += 1
            assert state == episode["final_state"] and state["terminal"]
            label = read(folder/"evaluator.json")["label"]
            computed = task.evaluate_terminal(state, label)
            computed["belief_brier"] = float(np.mean([(d["belief"]-label)**2 for d in episode["decisions"]]))
            computed["chosen_q_return_mse"] = float(np.mean([(d["chosen_q"]-(computed["reward"]-state["charges"]+d["charges_before"]))**2 for d in episode["decisions"]]))
            computed["teacher_regret"] = float(np.mean([d["teacher_regret"] for d in episode["decisions"]]))
            computed["events"] = sum(d["event"]["event"] for d in episode["decisions"])
            computed["recoveries"] = sum(d["event"]["recovery"] for d in episode["decisions"])
            computed["content_calls"] = sum(d["receipt"]["source_opened"] is not None for d in episode["decisions"])
            for timing in ("wall_seconds", "cpu_seconds"):
                computed["execution_"+timing] = sum(d["control_"+timing]+d["receipt"][timing] for d in episode["decisions"])
            for key, value in computed.items():
                maximum_metric_error = max(maximum_metric_error, abs(float(value)-float(episode["outcome"][key])))
            for key in ("wall_seconds", "cpu_seconds", "execution_wall_seconds", "execution_cpu_seconds"):
                assert np.isfinite(episode["outcome"][key]) and episode["outcome"][key] >= 0
            metrics.append(episode["outcome"])
            episodes_checked += 1
        means = {key: float(np.mean([row[key] for row in metrics])) for key in metrics[0]}
        assert max(abs(means[k]-record["means"][k]) for k in means) < 1e-12
        key = f"{split}/{family}/{arm}"
        matched = [r for r in summary["fit_means"][key] if r["fit"] == fit]
        assert len(matched) == 1 and max(abs(means[k]-matched[0][k]) for k in means) < 1e-12
        aggregates.setdefault(key, {})[fit] = means
    assert maximum_score_error < 1e-10 and maximum_metric_error < 1e-12
    critical = student_t.ppf(1-.05/(2*14), 4)
    contrast_errors = []
    for name, reported in summary["contrasts"].items():
        split, contrast = name.split("/")
        if contrast.endswith(":value-fixed"):
            family = contrast.split(":")[0]
            positive, negative = f"{family}/repaired_value", f"{family}/repaired_fixed"
        elif contrast == "first_passage_increment":
            positive, negative = "first_passage_bank/repaired_value", "ordinary_bank/repaired_value"
        elif contrast == "bank_increment":
            positive, negative = "ordinary_bank/repaired_value", "ordinary_base/repaired_value"
        else:
            raise AssertionError("unregistered contrast")
        positive, negative = aggregates[f"{split}/{positive}"], aggregates[f"{split}/{negative}"]
        assert set(positive) == set(negative) == {11, 23, 37, 53, 71}
        difference = np.array([positive[f]["utility"]-negative[f]["utility"] for f in sorted(positive)])
        mean, half = difference.mean(), critical*difference.std(ddof=1)/np.sqrt(5)
        for key, value in (("mean", mean), ("lower", mean-half), ("upper", mean+half)):
            contrast_errors.append(abs(value-reported[key]))
        assert np.max(abs(difference-reported["fit_differences"])) < 1e-12
        assert bool(mean-half > .02) == reported["passed"]
    assert len(contrast_errors) == 42 and max(contrast_errors) < 1e-12
    assert episodes_checked == sum(summary["counts"].values()) == 10000
    assert groups == {(fit, split, family, arm) for fit in protocol["fits"] for split in ("iid", "ood") for family in protocol["families"] for arm in protocol["arms"]}
    input_path = args.out.with_name("input_manifest.json")
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(json.dumps(input_manifest, indent=2, sort_keys=True)+"\n")
    result = dict(schema="digital-independent-confirmation-audit-v1", passed=True,
                  episodes=episodes_checked, decisions=decisions_checked, recorded_content_calls=actual_calls,
                  recorded_due_read_attempts=actual_calls, recorded_successful_content_decodes=successful_decodes,
                  recorded_failed_due_reads=actual_calls-successful_decodes,
                  unique_packets_independently_rerun_fullhx=len(cached_content),
                  max_score_error=maximum_score_error, max_outcome_metric_error=maximum_metric_error,
                  primary_intervals_recomputed=14, max_contrast_error=float(max(contrast_errors)),
                  unique_confirmation_packet_files=len(confirmation_payloads),
                  confirmation_packet_bytes_disjoint_from_train_and_validation=True,
                  input_manifest_sha256=sha(input_path), cohort_groups=len(groups),
                  independent_teacher_caches=len(oracle_cache),
                  model_freeze_sha256=sha(args.train/"MODEL_FREEZE.json"),
                  confirmation_summary_sha256=sha(args.confirmation/"SUMMARY.json"),
                  packet_sha256=file_hashes, audit_source_sha256=sha(Path(__file__)),
                  scope="Python actual-content campaign only; no native, energy, or continuous-core task efficacy claim")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+"\n")
    print(json.dumps({key: value for key, value in result.items() if key != "packet_sha256"}, sort_keys=True))


if __name__ == "__main__":
    main()
