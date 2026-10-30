"""Post-run independent trace arithmetic and descriptive on-policy diagnosis."""
from collections import Counter
import json
import time
import numpy as np
from scipy.stats import t as student_t
from identity import HERE, protocol, save, sha, verify
from oracle import Bellman


def audit():
    start, cpu = time.perf_counter(), time.process_time()
    verify()
    result = json.loads((HERE / "confirmation.json").read_text())
    manifest = json.loads((HERE / "heldout_manifest.json").read_text())
    records = {r["id"]: r for r in manifest["records"]}
    for relative, digest in manifest["files"].items():
        assert sha(HERE / relative) == digest, relative
    names = ("STOP", "SKIP", "READ", "FIRE")
    diagnostics, counts = [], Counter()
    for row in result["rows"]:
        trace = json.loads((HERE / row["trace"]).read_text())
        assert sha(HERE / row["trace"]) == row["trace_sha256"]
        folder = HERE / records[row["session"]]["folder"]
        meta = json.loads((folder / "public.json").read_text())
        confusion = np.asarray(trace["confusion"])
        calibration = json.loads((HERE / "calibration" / f"seed{row['seed']}.json").read_text())
        assert np.array_equal(confusion, calibration["confusion"])
        assert trace["public_sha256"] == sha(folder / "public.json")
        dp = Bellman(meta, confusion, trace["multiplier"])
        job, tick, budget, posterior, terminal = 0, 0, meta["budget"], .5, False
        charged, answers, event_counts, regrets = 0., [], Counter(), []
        for event in trace["events"]:
            assert not terminal
            assert (job, tick, budget) == (event["job"], event["tick"], event["budget_before"])
            assert abs(posterior-event["posterior_before"]) < 1e-12
            selected = event["action"]
            valid = [True, tick+1 < meta["deadline"], budget > 0 and tick+1 < meta["deadline"], True]
            assert job < 2 and tick < meta["deadline"] and valid[names.index(selected)]
            q = np.asarray(dp.q(job, tick, budget, posterior))
            regrets.append(float(max(q)-q[names.index(selected)]))
            event_counts[selected] += 1
            if selected == "STOP":
                terminal = True
            elif selected == "SKIP":
                assert "payload_sha256" not in event and "packet" not in event
                tick += 1
            elif selected == "READ":
                packet = folder / meta["packets"][job][tick]
                assert sha(packet) == event["payload_sha256"]
                assert packet.stat().st_size == event["payload_bytes"]
                assert event["observation"] == int(np.argmax(event["logits"][:2]))
                reliability, observation = meta["reliability"][job][tick], event["observation"]
                law = reliability*confusion+(1-reliability)*confusion[::-1]
                numerator = posterior*law[1, observation]
                posterior = numerator/(numerator+(1-posterior)*law[0, observation])
                charged += trace["multiplier"]*meta["price"][job][tick]
                tick, budget = tick+1, budget-1
            else:
                answer = dict(job=job, prediction=int(posterior >= .5))
                assert all(event["answer"][k] == v for k, v in answer.items())
                answers.append(answer)
                job, tick, posterior = job+1, tick+2, .5
            terminal = terminal or job >= 2 or tick >= meta["deadline"]
            assert (job, tick, budget, terminal) == (event["next_job"], event["next_tick"], event["budget_after"], event["terminal"])
            assert abs(posterior-event["posterior_after"]) < 1e-12
        assert terminal and trace["terminal"]
        assert all(event_counts[name] == row["counts"][name] == trace["counts"][name] for name in names)
        assert event_counts["READ"] == row["counts"]["content_invocations"] == row["counts"]["packet_file_reads"]
        labels = json.loads((folder / "evaluator_labels.json").read_text())["labels"]
        correct = sum(a["prediction"] == labels[a["job"]] for a in answers)
        utility = 2*correct-len(answers)-charged
        assert abs(charged-row["charged_cost"]) < 1e-12 and abs(utility-row["utility"]) < 1e-12
        assert correct == row["correct_jobs"] and len(answers) == row["completed_jobs"]
        counts.update(event_counts)
        diagnostics.append(dict(session=row["session"], seed=row["seed"], family=row["family"],
            decisions=len(regrets), accumulated_model_regret=sum(regrets),
            initial_decision_model_regret=regrets[0], maximum_decision_model_regret=max(regrets)))
    differences = []
    for seed in protocol()["seeds"]:
        values = {name: np.mean([r["utility"] for r in result["rows"] if r["seed"] == seed and r["family"] == name])
                  for name in ("full_value", "ordinary_boundary")}
        differences.append(float(values["full_value"]-values["ordinary_boundary"]))
    mean = float(np.mean(differences))
    radius = float(student_t.ppf(.975, 4)*np.std(differences, ddof=1)/np.sqrt(5))
    assert np.allclose([mean-radius, mean+radius], result["primary"]["interval95"], atol=1e-15, rtol=0.)
    summaries = []
    for family in protocol()["families"]+["model_dp"]:
        group = [r for r in diagnostics if r["family"] == family]
        summaries.append(dict(family=family,
            mean_accumulated_model_regret=float(np.mean([r["accumulated_model_regret"] for r in group])),
            mean_initial_decision_model_regret=float(np.mean([r["initial_decision_model_regret"] for r in group])),
            per_decision_model_regret=sum(r["accumulated_model_regret"] for r in group)/sum(r["decisions"] for r in group)))
    save(HERE / "delivery_audit.json", dict(passed=True, heldout_files_verified=len(manifest["files"]),
        traces_verified=len(result["rows"]), counts=dict(counts),
        independently_recomputed_primary=dict(mean=mean, interval95=[mean-radius, mean+radius]),
        original_scientific_results_unchanged=True, audit_wall_seconds=time.perf_counter()-start,
        audit_cpu_seconds=time.process_time()-cpu,
        posthoc_diagnosis=dict(description="Descriptive model-based regrets along saved trajectories, added after results. No new streams, fits, choices or endpoint changes. Conditional fitted DP values, not true-law regret.", summaries=summaries, rows=diagnostics),
        input_sha256={name: sha(HERE / name) for name in ("confirmation.json", "heldout_manifest.json", "freeze.json")}))
    print(json.dumps(dict(passed=True, files=len(manifest["files"]), traces=len(result["rows"]), counts=dict(counts), diagnostic_summaries=summaries), indent=2))


if __name__ == "__main__":
    audit()
