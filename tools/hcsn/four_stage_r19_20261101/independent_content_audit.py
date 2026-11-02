"""Root-team independent raw record/statistic audit; imports no candidate code."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np
from scipy.stats import beta

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CANDIDATE = ROOT / "experiments/hcsn_unknown_generator_r19_20261101"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    start = time.process_time()
    checks = 0
    allowed = os.sched_getaffinity(0)
    os.sched_setaffinity(0, allowed & set(range(7)))
    spec = json.loads((CANDIDATE / "protocol.json").read_text())
    assert spec["risk_limit"] == .1 and spec["panels"] == ["confirm", "reverse", "lag2"]
    source = json.loads((CANDIDATE / "SOURCE_FREEZE.json").read_text())
    for name, digest in source["files"].items():
        assert sha(CANDIDATE / name) == digest
        checks += 1
    dependency = json.loads((CANDIDATE / "DEPENDENCY_IDENTITIES.json").read_text())
    for name, record in dependency["exact_dependencies"].items():
        data = (CANDIDATE.parent / "hcsn_unknown_generator_r18_20261101" / name).read_bytes()
        assert hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest() == record["git_blob_sha"]
        assert hashlib.sha256(data).hexdigest() == record["sha256"]
        checks += 2
    replay = json.loads((CANDIDATE / "EXACT_DEPENDENCY_PREPARATION_REPLAY.json").read_text())
    for name, matched in replay["files"].items():
        assert matched and (CANDIDATE / name).read_bytes() == (CANDIDATE / "ENGINEERING_PREPARE_V1" / name).read_bytes()
        checks += 1
    remote = json.loads((HERE / "CONTENT_REMOTE_FREEZE_READBACK.json").read_text())
    for row in remote:
        data = (CANDIDATE / row["path"]).read_bytes()
        assert hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest() == row["git_blob"]
        checks += 1
    for freeze in ["SOURCE_FREEZE.json", "POSTCALIBRATION_FREEZE.json"]:
        for name, digest in json.loads((CANDIDATE / freeze).read_text())["files"].items():
            assert sha(CANDIDATE / name) == digest
            checks += 1

    def load(directory):
        nonlocal checks
        rows = []
        for record in json.loads((CANDIDATE / directory / "ARCHIVES.json").read_text()):
            data = (CANDIDATE / record["path"]).read_bytes()
            raw = gzip.decompress(data)
            assert hashlib.sha256(data).hexdigest() == record["sha256"]
            assert hashlib.sha256(raw).hexdigest() == record["raw_sha256"]
            value = json.loads(raw)
            assert len(value) == record["records"]
            checks += 3
            if "training" not in record["path"]:
                rows.extend(value)
        return rows

    prepared, confirmed = load("prepare_01"), load("confirm_01")
    calibration = json.loads((CANDIDATE / "prepare_01/CALIBRATION.json").read_text())
    summary = json.loads((CANDIDATE / "confirm_01/SUMMARY.json").read_text())
    fees, reads = 0., 0
    for row in prepared + confirmed:
        public = row["public"]
        events, prefix = np.array(public["owner_events"]), np.array(public["prefix"])
        mask = np.array(public["observed"], dtype=bool)
        assert np.array_equal(events[mask], prefix[mask]) and not prefix[~mask].any()
        alias = int(np.argmax(public["query"][19:23]))
        key = next(int(np.argmax(b[:4])) for b in public["bridges"] if b[19 + alias] == 1)
        writes = [e for e in events if e[12] == 1]
        assert len(writes) == 6
        target = int(np.argmax([e for e in writes if e[key] == 1][-1][4:8]))
        assert target == row["target"]
        for name, thresholds in row["predictions"].items():
            for threshold, record in thresholds.items():
                assert not record["invalid"]
                p, before = np.array(record["probability"]), np.array(record["before"])
                assert np.isfinite(p).all() and min(p) >= 0 and abs(sum(p)-1) < 2e-12
                assert np.isfinite(before).all() and min(before) >= 0 and abs(sum(before)-1) < 2e-12
                assert record["accepted"] == bool(record["admitted"] and max(p) >= float(threshold))
                assert record["fractional"] == bool(max(p) < 1-1e-9)
                assert record["correct"] == int(p.argmax() == target)
                assert abs(record["confidence"] - max(p)) < 1e-12
                assert abs(record["true_probability"] - p[target]) < 1e-12
                index = record["read_index"]
                if index is not None:
                    assert not mask[index] and record["actual_read"] == public["owner_events"][index]
                    assert record["fee"] == row["price"]
                else:
                    assert record["actual_read"] is None and record["fee"] == 0
                expected = (2*record["correct"]-1 if record["accepted"] else 0)-record["fee"]
                stop = int(before.argmax() == target)
                no_read = 2*stop-1 if record["admitted"] and max(before) >= float(threshold) else 0
                assert abs(record["payoff"]-expected) < 1e-12 and record["no_read_payoff"] == no_read
                onehot = np.eye(4)[target]
                assert abs(record["brier"]-sum((p-onehot)**2)) < 1e-12
                assert abs(record["before_brier"]-sum((before-onehot)**2)) < 1e-12
                fees += record["fee"]
                reads += index is not None
                checks += 14

    assert len(prepared) == 2048 and len(confirmed) == 3072
    for model in spec["models"]:
        passing = []
        for threshold in spec["thresholds"]:
            r = [x["predictions"][model][str(threshold)] for x in prepared]
            accepted = [x for x in r if x["accepted"]]
            fractional = [x for x in accepted if x["fractional"]]
            counts = [len(accepted), sum(not x["correct"] for x in accepted),
                      len(fractional), sum(not x["correct"] for x in fractional)]
            stored = calibration["grid"][model][str(threshold)]
            assert counts == [stored[k] for k in ["accepted", "errors", "fractional", "fractional_errors"]]
            upper = [1. if not n or e == n else float(beta.ppf(1-.05/16,e+1,n-e))
                     for n,e in [(counts[0],counts[1]),(counts[2],counts[3])]]
            assert abs(upper[0]-stored["upper_error"]) < 1e-12
            assert abs(upper[1]-stored["upper_fractional_error"]) < 1e-12
            passed = max(upper) <= .1 and counts[2] >= 20
            assert passed == stored["passed"]
            if passed:
                passing.append((counts[2],-threshold,threshold))
            checks += 8
        assert calibration["selected"][model] == dict(calibration_gate_passed=bool(passing), threshold=max(passing)[2] if passing else 1-1e-12)

    panels = {}
    for panel in spec["panels"]:
        rows = [r for r in confirmed if r["panel"] == panel]
        assert {(r["generator"],r["index"]) for r in rows} == {(g,i) for g in range(256) for i in range(4)}
        bootstrap = np.random.default_rng(1905513).integers(256,size=(4096,256))
        grouped = {}
        for model in spec["models"]:
            values = np.zeros((256,9))
            for row in rows:
                p = next(iter(row["predictions"][model].values()))
                a, f, e = p["accepted"], p["accepted"] and p["fractional"], not p["correct"]
                values[row["generator"]] += [a,a and e,f,f and e,p["payoff"],p["before_brier"],
                    p["true_probability"] <= 0,p["read_index"] is not None,p["payoff"]-p["no_read_payoff"]]
            total, draws = values.sum(0), values[bootstrap].sum(1)
            fractional = np.divide(draws[:,3],draws[:,2],out=np.ones(4096),where=draws[:,2]>0)
            overall = np.divide(draws[:,1],draws[:,0],out=np.ones(4096),where=draws[:,0]>0)
            stored = summary["models"][panel+":"+model]["quality"]
            for index, field in enumerate(["accepted","errors","fractional","fractional_errors"]):
                assert total[index] == stored[field]
            assert abs(total[4]/1024-stored["payoff"]) < 1e-12
            assert abs(total[5]/1024-stored["before_brier"]) < 1e-12
            assert total[6] == stored["support_losses"] and total[7] == stored["reads"]
            assert abs(total[8]/1024-stored["read_net_effect"]) < 1e-12
            u, v = float(np.quantile(fractional,.95)),float(np.quantile(overall,.95))
            assert abs(u-stored["upper95_fractional"]) < 1e-12 and abs(v-stored["upper95_overall"]) < 1e-12
            gate = calibration["selected"][model]["calibration_gate_passed"] and not total[6] and total[2]>=32 and max(u,v)<=.1
            assert stored["gate"] == gate
            grouped[model] = values/4
            checks += 13
        for col, sign, field, interval in [(4,1,"payoff_difference","payoff_ci95"),(5,-1,"before_brier_improvement","before_brier_ci95")]:
            d = sign*(grouped["full_transition"][:,col]-grouped["restricted_markov"][:,col])
            assert abs(d.mean()-summary[panel+":paired"][field]) < 1e-12
            assert np.max(np.abs(np.quantile(d[bootstrap].mean(1),[.025,.975])-summary[panel+":paired"][interval])) < 1e-12
            checks += 2
        panels[panel] = {m:summary["models"][panel+":"+m]["quality"] for m in spec["models"]}
    assert summary["unseen_family_gate"] == all(panels[p]["full_transition"]["gate"] for p in ["reverse","lag2"])
    result = dict(passed=True, source_review="no hidden owner target enters infer/choose; only selected paid indexed token enters acquire before scoring; family labels absent from fitting/inference", risk_limit=.1,
        panel_units="256 distinct generators x4 worlds independently for each panel; no pooling",
        frozen_remote_model_readbacks=len(remote), exact_preparation_replay_files=len(replay["files"]),
        calibration_worlds=len(prepared), confirmation_worlds=len(confirmed), checked_prediction_records=2048*2*4+3072*2,
        checks=checks, all_prediction_fees_sum=fees, all_prediction_reads=reads,
        panels=panels, unseen_family_gate=summary["unseen_family_gate"],
        caveat="Cluster bootstrap intervals are empirical; no finite-sample coverage guarantee. Both models ordinary finite references; no analytic D-B or production claim.",
        process_cpu_seconds=time.process_time()-start)
    (HERE/"INDEPENDENT_CONTENT_REVIEW.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({k:v for k,v in result.items() if k != "panels"}))


if __name__ == "__main__":
    main()
