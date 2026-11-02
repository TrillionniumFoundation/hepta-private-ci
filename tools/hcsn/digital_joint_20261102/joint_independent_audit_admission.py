"""Independent formal fitting/source/input/full-worker CPU accounting audit."""
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import traceback

import numpy as np
from scipy.linalg import expm
from . import joint_task as task

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[2]


def read(path):
    path = Path(path)
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit(root):
    protocol = read(HERE/"joint_protocol.json")
    assert protocol["status"] == "frozen" and len(protocol["families"]) == 4 and len(protocol["fits"]) == 5
    assert set(protocol["train_domain"]["drives"]) == {-1, 0, 1}
    sources, results, heads = None, [], []
    maximum_expm_error, input_files, missing_files, trajectory_decisions = 0., 0, 0, 0
    adapter, decoded = task.ContentAdapter(), {}
    def check_episode(episode, data_root):
        nonlocal trajectory_decisions
        folder = data_root/episode["world"]
        public = read(folder/"public.json")
        state = task.initial(public)
        decisions = episode.get("decisions", [dict(action=r["action"], receipt=r) for r in episode.get("receipts", [])])
        for decision in decisions:
            receipt, action = decision["receipt"], decision["action"]
            assert receipt["before"] == state and receipt["action"] == action and task.legal(public, state)[action]
            due = task.due_request(public, state, action)
            assert receipt["source_opened"] == (None if due is None else due-1)
            if due is not None:
                packet = folder/public["packets"][due-1]
                if receipt["completion"].get("failure", False):
                    assert not packet.exists()
                else:
                    if str(packet) not in decoded:
                        decoded[str(packet)] = adapter.read(packet)
                    result = decoded[str(packet)]
                    assert result["observation"] == receipt["content"]["observation"] == receipt["completion"]["observation"]
                    assert result["payload_sha256"] == receipt["content"]["payload_sha256"] == public["packet_sha256"][due-1]
            state = task.successor(public, state, action, receipt["completion"])
            assert state == receipt["after"]
            trajectory_decisions += 1
        assert task.evaluate_terminal(state, read(folder/"evaluator.json")["label"]) == episode["outcome"]
    for fit in protocol["fits"]:
        folder = root/f"fit_{fit}"
        admission = read(folder/"FIT_ADMISSION.json")
        assert admission["admitted"] and admission["matching"]["matched"]
        prepared_path = folder/f"data/fit_{fit}_data.json"
        prepared = read(prepared_path)
        assert prepared["fit"] == fit and prepared["environment_law"]["raw"] == protocol["truth_raw"]
        data_root = prepared_path.parent
        for episode in prepared["train"]["episodes"]+prepared["validation"]["episodes"]:
            check_episode(episode, data_root)
        for split in ("train", "validation"):
            cohort = prepared[split+"_cohort"]
            assert len(cohort["records"]) == protocol[split+"_worlds"]
            assert all(sha(data_root/p) == h for p, h in cohort["files"].items())
            assert all(not (data_root/p).exists() for p in cohort["expected_missing"])
            input_files += len(cohort["files"])
            missing_files += len(cohort["expected_missing"])
        prep_receipt = folder/"preparation_budget/RECEIPT.json"
        preparation = read(prep_receipt)
        assert preparation["admissible"] and preparation["launched"]
        common = preparation["standalone_cpu_seconds"]
        assert common == preparation["worker_cpu_seconds"]
        worker_cpu, standalone, amortized, monitors, fit_heads, model_records = [], [], [], [], set(), []
        for family in protocol["families"]:
            budget = read(folder/f"budget_{family}/RECEIPT.json")
            complete = read(folder/f"model_{family}/COMPLETE.json")
            training = read(folder/f"model_{family}/TRAINING.json.gz")
            model_path = folder/f"model_{family}/model.json"
            model = read(model_path)
            assert budget["admissible"] and budget["launched"] and budget["returncode"] == 0
            assert budget["actual_cpu_in_match_band"] and budget["spec"] == protocol["budget"]
            assert budget["source_sha256"] == sha(HERE/"joint_budget.py")
            assert budget["shared_receipt_sha256"] == sha(prep_receipt)
            assert budget["shared_cpu_seconds"] == common and budget["consumers"] == 4
            identity = budget["pid_identity"]
            worker_limit = 60*1.02-common
            assert abs(identity["scientific_worker_cpu_limit_seconds"]-worker_limit) < 1e-10
            assert identity["cpu_backstop_multiplier"] == protocol["budget"]["cpu_backstop_multiplier"] == 2.
            soft = math.ceil(2*worker_limit)
            assert identity["configured_rlimit_cpu_seconds"] == identity["actual_rlimit_cpu_seconds"] == [soft, soft+1]
            total = common+budget["worker_cpu_seconds"]
            assert abs(total-budget["standalone_cpu_seconds"]) < 1e-10
            assert total <= 60*1.02 and abs(total-60) <= 6 and budget["wall_seconds"] <= 600
            assert complete["all_rounds_complete"] and complete["actual_updates"] > 0
            assert complete["family"] == model["family"] == family and complete["fit"] == model["fit"] == fit
            assert complete["data_sha256"] == sha(prepared_path)
            assert complete["protocol_sha256"] == sha(HERE/"joint_protocol.json")
            assert complete["model"]["sha256"] == sha(model_path)
            current_sources = complete["source_sha256"]
            assert all(sha(REPOSITORY/p) == h for p, h in current_sources.items())
            sources = current_sources if sources is None else sources
            assert sources == current_sources
            assert all(prepared[s+"_cohort"]["published_source_commit"] == complete["published_source_commit"] for s in ("train", "validation"))
            fit_heads.add(complete["initial_head_sha256"])
            initial = len(prepared["train"]["rows"])
            assert training["initial_behavior_rows"] == initial
            assert len(training["rounds"]) == protocol["policy_feedback_rounds"] == 4
            cumulative, updates, collection_episodes = initial, [], 0
            for number, one_round in enumerate(training["rounds"]):
                assert one_round["round"] == number and one_round["complete"]
                expected_ids = [r["id"] for r in prepared["train_cohort"]["records"]]
                assert [e["world"] for e in one_round["episodes"]] == expected_ids
                for episode in one_round["episodes"]:
                    check_episode(episode, data_root)
                added = sum(len(e["decisions"]) for e in one_round["episodes"])
                assert added == one_round["added_rows"]
                cumulative += added
                assert cumulative == one_round["total_rows"]
                matching = [u for u in training["updates"] if u["round"] == number]
                assert len(matching) == one_round["updates"]
                for update in matching:
                    assert len(update["minibatch_indices"]) == protocol["batch_states"]
                    assert all(0 <= i < cumulative for i in update["minibatch_indices"])
                    assert np.isfinite(update["loss"]) and np.isfinite(update["gradient_norm_before_clip"])
                    assert update["max_mass_defect"] < 1e-8
                updates += matching
                collection_episodes += len(one_round["episodes"])
            assert [u["step"] for u in updates] == list(range(1, complete["actual_updates"]+1))
            assert collection_episodes == complete["actual_collection_episodes"] == 256
            assert cumulative-initial == complete["actual_collection_visits"]
            core = model["core"]
            if family != "gru":
                q = {int(d): np.asarray(matrix) for d, matrix in core["generators"].items()}
                for matrix in q.values():
                    off = matrix.copy()
                    np.fill_diagonal(off, 0.)
                    assert off.min() >= -1e-12 and np.max(abs(matrix.sum(-1))) < 1e-8
                if family == "affine_markov":
                    assert np.max(abs(q[0]-(q[-1]+q[1])/2)) < 1e-10
                for table in core["tables"]:
                    matrix = np.asarray(table["matrix"])
                    assert matrix.min() >= -1e-10 and np.max(abs(matrix.sum(-1)-1)) < 1e-8
                    error = float(np.max(abs(matrix-expm(table["dt"]*q[table["drive"]]))))
                    maximum_expm_error = max(maximum_expm_error, error)
            worker_cpu.append(budget["worker_cpu_seconds"])
            standalone.append(total)
            amortized.append(budget["amortized_cpu_seconds"])
            monitors.append(budget["supervisor_cpu_before_receipt_seconds"])
            model_records.append(dict(family=family, model_sha256=sha(model_path), actual_updates=len(updates),
                                      standalone_cpu_seconds=total, round_updates=[r["updates"] for r in training["rounds"]],
                                      actual_collection_visits=cumulative-initial))
        assert len(fit_heads) == 1
        heads.append(next(iter(fit_heads)))
        assert max(standalone)-min(standalone) <= 6
        ledger = admission["ledger"]
        assert max(abs(np.asarray(amortized)-(np.asarray(worker_cpu)+common/4))) < 1e-10
        assert abs(ledger["physical_worker_plus_shared_cpu_seconds"]-(common+sum(worker_cpu))) < 1e-8
        assert abs(admission["full_master_cpu_since_exec"]["waited_child_cpu_seconds"]-(common+sum(worker_cpu))) < 1e-8
        assert admission["full_master_cpu_since_exec"]["self_cpu_seconds"] >= sum(monitors)
        results.append(dict(fit=fit, models=model_records, shared_cpu_seconds=common,
                            paired_actual_cpu_gap=max(standalone)-min(standalone), ledger=ledger))
    assert len(set(heads)) == 5 and maximum_expm_error < 1e-9
    return dict(passed=True, fits=results, models=20, source_sha256=sources,
                verified_input_files=input_files, verified_absent_packets=missing_files,
                verified_trajectory_decisions=trajectory_decisions, unique_packets_independently_redecoded=len(decoded),
                max_exported_table_scipy_expm_error=maximum_expm_error,
                scope="All formal fits and complete standalone/amortized worker CPU; not a bit-exact optimizer rerun, efficacy or lifecycle-cost gate")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = audit(args.root)
    except Exception:
        result = dict(passed=False, error=traceback.format_exc())
    result.update(schema="joint-formal-admission-independent-audit-v1", audit_source_sha256=sha(__file__))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+"\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("fits", "source_sha256")}, sort_keys=True))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
