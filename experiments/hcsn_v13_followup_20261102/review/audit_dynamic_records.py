"""Independent stdlib accounting/path audit of frozen historical dynamic output.

Does not import the executor, model, author evaluator, Torch, NumPy or new data.
It checks saved forward-state bindings, not an independent neural implementation.
"""

import argparse
from collections import defaultdict
import gzip
import hashlib
import itertools
import json
import math
from pathlib import Path
import statistics


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse(identity):
    return [part.split(":") for part in identity.split("/")]


def public_outcome(parts, now, deadline):
    t, issued, accepted = now, 0, []
    for step in parts:
        if t >= deadline:
            break
        if step[0] == "WAIT":
            t = min(deadline, t + float(step[1]))
        else:
            issued += 1
            completion = max(t, int(step[2])) + .001
            t = min(completion, deadline)
            if completion > deadline:
                break
            accepted.append(step)
    return accepted, t-now, issued


def alternatives(levels, requested):
    result, frontier = [], [()]
    for _ in range(2):
        new = []
        for prefix in frontier:
            local = dict(levels)
            for step in prefix:
                if step[0] == "READ":
                    local[step[1]] = int(step[2])
            nexts = [("READ", m, str(local[m]+1)) for m in ("audio", "video") if local[m] < 3]
            if not prefix or prefix[-1][0] != "WAIT":
                nexts.append(("WAIT", "0.25"))
            for step in nexts:
                path = prefix+(step,)
                reads = sum(s[0] == "READ" for s in path)
                if requested+reads <= 6:
                    result.append("/".join(":".join(s) for s in path))
                    new.append(path)
        frontier = new
    return result


def audit(root, run):
    checks, failures, max_error = 0, [], defaultdict(float)

    def check(ok, label):
        nonlocal checks
        checks += 1
        if not ok and len(failures) < 50:
            failures.append(label)

    def close(actual, expected, label, tolerance=2e-12):
        error = abs(actual-expected)
        max_error[label] = max(error, max_error[label])
        check(math.isfinite(actual) and error <= tolerance, label)

    output = run/"evaluation"
    summary = json.loads((output/"SUMMARY.json").read_text())
    seal = json.loads((run/"CANDIDATES.json").read_text())
    plan = json.loads((run/"PLAN.json").read_text())
    gate = json.loads((output/"BEFORE_TEST_GATE.json").read_text())
    identities = json.loads((output/"TEST_IDENTITIES.json").read_text())
    check(seal["plan_sha256"] == digest(run/"PLAN.json") and not seal["test_opened"], "candidate plan and untouched TEST flag")
    check(gate["gate_passed_before_test_loader"] and gate["candidates_sha256"] == digest(run/"CANDIDATES.json"), "actual pre-TEST gate")
    check(gate["remote_head"] == summary["remote_candidate_head"] and not gate["scientific_confirmation"], "published candidate head and development scope")
    check(summary["trace_sha256"] == digest(output/"TRACES.jsonl.gz"), "trace bytes")
    check(summary["test_identities_sha256"] == digest(output/"TEST_IDENTITIES.json"), "TEST identity bytes")
    for task, identity in identities.items():
        check(identity["materialized_packet_sha256"] == digest(output/(task+"-historical-TEST.npz")), "actual materialized historical TEST packet bytes")
    for path, sha in plan["source_sha256"].items():
        check(digest(root/path) == sha, "frozen actual control source bytes")
    metadata = {}
    for item in seal["models"]:
        key = item["task"], item["family"], item["seed"]
        check(key not in metadata, "unique frozen reader candidate")
        directory = run/item["directory"]
        for name, sha in item["files"].items():
            check(digest(directory/name) == sha, "frozen reader candidate bytes")
        meta = json.loads((directory/"CANDIDATE.json").read_text())
        metadata[key] = meta
    rows, keys, labels = [], set(), {}
    expected = {(t, f, s, i, p) for t, f, s in metadata for i in range(len(identities[t]["ids"])) for p in ("fixed", "light", "value")}
    summary_rows = {(r["task"], r["family"], r["seed"], r["index"], r["policy"]): r for r in summary["rows"]}
    raw_content = {}
    with gzip.open(output/"TRACES.jsonl.gz", "rt") as stream:
        for line in stream:
            row = json.loads(line)
            key = row["task"], row["family"], row["seed"], row["index"], row["policy"]
            check(key not in keys and key in expected, "unique expected dynamic episode")
            keys.add(key)
            check(all(row[k] == v for k, v in summary_rows[key].items()), "summary is exact trace projection")
            task, family, seed, index, policy = key
            meta, execution = metadata[key[:3]], row["execution"]
            label_key = task, index
            labels.setdefault(label_key, row["label_for_scoring_only"])
            check(labels[label_key] == row["label_for_scoring_only"], "paired actual object label")
            check(execution["clock"] == "LogicalClock" and execution["source_monotonic_ns"] is None and execution["output_flush_monotonic_ns"] is None, "simulated historical clock scope")
            check("raw decoding and original feature preparation excluded" in execution["service_mode"], "honest historical service mode")
            check(execution["deadline_seconds"] == 4 and not execution["scientific_confirmation"], "fixed deadline and development scope")
            events, updates, source = execution["events"], row["updates"], execution["source_window_updates"]
            levels, time, requested, cursor, accepted = {"audio": 0, "video": 0}, 0., 0, 0, 0
            current_p, current_fp, model_rows = meta["train_prior"], None, []

            def consume_read(step, mandatory=False):
                nonlocal time, requested, cursor, accepted, current_p, current_fp
                event = events[cursor]; cursor += 1; requested += 1
                modality, endpoint = step[1], int(step[2])
                check(event["kind"] == "read" and event["action"] == ":".join(step) and event["request"] == requested and event["mandatory"] is mandatory, "actual requested path")
                check(endpoint == levels[modality]+1 <= 3, "no skipped/repeated source prefix")
                close(event["requested_at"], time, "actual request time")
                if current_fp is not None:
                    check(event["before"] == current_fp, "accepted content chain")
                completion = max(time, endpoint)+.001
                time = min(4., completion)
                if completion > 4:
                    check(event["status"] == "timed_out" and event["after"] == event["before"], "late request excluded from content")
                    close(event["observed_at"], time, "timeout clock")
                    return
                check(event["status"] == "accepted", "primary replay accepted actual read")
                close(event["completed_at"], completion, "actual prepared completion")
                close(event["accepted_at"], time, "actual acceptance clock")
                prior_global = max(levels.values()); levels[modality] = endpoint
                increment = max(levels.values())-prior_global
                update, source_update = updates[accepted], source[accepted]; accepted += 1
                check(update["event_id"] == "prepared-"+str(requested) == source_update["accepted_event_id"], "accepted update event identity")
                check(update["source_time"] == endpoint and update["global_source_increment"] == increment, "late modality uses correct source axis")
                check(source_update == {"modality": modality, "modality_prefix_increment": 1, "global_source_increment": increment, "global_source_time": max(levels.values()), "accepted_event_id": update["event_id"]}, "full source-clock update")
                raw = update["raw_row"]
                check(len(raw) == len(update["model_row"]) == 55, "common accepted input width")
                check(raw[32:35] == [levels["audio"]/3, levels["video"]/3, increment] and raw[51:54] == [float(modality == "audio"), float(modality == "video"), endpoint/3], "protected source row controls")
                check(raw[54] in (0., 1.), "fresh-window flag")
                for m, start in (("audio", 0), ("video", 16)):
                    content_key = task, index, m, levels[m], "cache"
                    raw_content.setdefault(content_key, raw[start:start+16])
                    check(raw_content[content_key] == raw[start:start+16], "same accepted modality cache across candidates")
                fresh_key = task, index, modality, endpoint, "fresh"
                raw_content.setdefault(fresh_key, raw[35:51]+raw[54:55])
                check(raw_content[fresh_key] == raw[35:51]+raw[54:55], "new window evidence invariant to model/order")
                current_fp = event["after"]
                check(current_fp == update["content_fingerprint"], "holder binds accepted cache")
                current_p = update["probabilities"]
                check(len(current_p) == (6 if task == "async_av" else 2) and all(math.isfinite(p) and 0 <= p <= 1 for p in current_p), "finite new class-head probabilities")
                close(sum(current_p), 1., "class probability mass")
                model_rows.append(update["model_row"])
                payload = [current_fp, model_rows, update["state"], current_p]
                bound = hashlib.sha256(json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()).digest()
                check(update["digest"] == list(map(float, bound)), "actual stored state/history/head digest")

            consume_read(["READ", "audio", "1"], True)
            for decision in execution["decisions"]:
                check(decision["content_fingerprint"] == current_fp, "decision sees current accepted cache")
                stop = meta["stop_calibration"]["rates"][min(int(max(current_p)*5), 4)]
                selected = decision["selected"]
                if policy == "value":
                    close(decision["stop_score"], stop, "current calibrated STOP target")
                    check(decision["reader_id"] == meta["head_id"]+"-value" and decision["backend"] == "core", "new exact-head future reader")
                    check([p["plan"] for p in decision["plans"]] == alternatives(levels, requested), "complete bounded public alternatives")
                    for scored in decision["plans"]:
                        steps = parse(scored["plan"])
                        future, elapsed, issued = public_outcome(steps, time, 4.)
                        check(scored["requested_reads"] == sum(s[0] == "READ" for s in steps) and scored["expected_requested_reads"] == issued, "planned versus actually issuable fee")
                        close(scored["expected_seconds"], elapsed, "public deadline-truncated duration")
                        check(scored["deadline_miss_probability"] == 0, "declared timely-output risk")
                        if not future:
                            close(scored["correctness"], stop, "no accepted read retains STOP target")
                        else:
                            check(scored["correctness"] in meta["future_calibration"]["rates"], "frozen calibrated future target range")
                        value = scored["correctness"]-.02*issued-.005*elapsed
                        close(scored["score"], value, "single plan fee deduction")
                        close(scored["increment_over_stop"], value-stop, "same-target advantage")
                    best = max(decision["plans"], key=lambda p: (p["score"], p["plan"]), default=None)
                    check(selected == (best["plan"] if best is not None and best["score"] > stop else None), "STOP tie and lexical best action")
                else:
                    check(decision["mode"] == "fixed", "fixed/light explicit schedule mode")
                    if policy == "fixed":
                        check(selected == "READ:video:1/READ:audio:2/READ:video:2/READ:audio:3/READ:video:3", "common complete fixed schedule")
                    else:
                        options = [(levels[m]+1, m) for m in ("audio", "video") if levels[m] < 3]
                        expected_light = None if stop >= .8 or not options else "READ:"+min(options)[1]+":"+str(min(options)[0])
                        check(selected == expected_light, "frozen light threshold and public tie rule")
                if selected is None:
                    break
                for step in parse(selected):
                    if time >= 4:
                        break
                    if step[0] == "READ":
                        consume_read(step)
                    else:
                        event = events[cursor]; cursor += 1
                        check(event["kind"] == "wait" and event["before"] == event["after"] == current_fp and event["core_unchanged"], "WAIT leaves source state unchanged")
                        close(event["started_at"], time, "WAIT start")
                        time = min(4., time+float(step[1]))
                        close(event["ended_at"], time, "WAIT truncation")
            check(cursor == len(events) and accepted == len(updates) == len(source), "all actual service/model updates accounted once")
            check(requested == execution["requested_observations"] == row["requests"], "actual request count")
            final = execution["output"]
            check(final["head_id"] == meta["head_id"] and final["probabilities"] == current_p and final["content_fingerprint"] == current_fp, "final new head/state binding")
            check(final["accepted_event_ids"] == [u["event_id"] for u in updates], "final accepted observations only")
            check(final["predicted_class"] == max(range(len(current_p)), key=current_p.__getitem__), "actual raw argmax")
            check(row["correct"] == int(final["predicted_class"] == row["label_for_scoring_only"]), "actual object correctness")
            serialized = (json.dumps(final, sort_keys=True, separators=(",", ":"), allow_nan=False)+"\n").encode()
            check(hashlib.sha256(serialized).hexdigest() == execution["serialized_output_sha256"], "actual frozen serialized output bytes")
            close(execution["output_elapsed_seconds"], time, "frozen output time")
            close(execution["observation_fee"], .02*requested, "actual observation fee")
            close(execution["latency_fee"], .005*time, "actual latency fee")
            check(execution["deadline_penalty"] == int(time > 4) and execution["timely_output"] == (time <= 4), "actual deadline outcome")
            utility = row["correct"]-.02*requested-.005*time-int(time > 4)
            close(row["utility"], utility, "utility reconstructed from actual result")
            check(execution["cache_storage"]["retained_event_count"] == accepted, "retained metadata count")
            rows.append({**{k: row[k] for k in ("task", "family", "seed", "index", "policy", "correct", "requests", "utility")}, "elapsed": time})
    check(keys == expected and len(rows) == summary["executions"] == 1944, "complete prespecified 1944 paired executions")
    buckets = defaultdict(list)
    for row in rows:
        buckets[row["task"], row["family"], row["policy"]].append(row)
    metrics = ("correct", "requests", "utility", "elapsed")
    means = [{"task": t, "family": f, "policy": p, "episodes": len(group), **{m: statistics.mean(r[m] for r in group) for m in metrics}} for (t, f, p), group in sorted(buckets.items())]
    lookup = {(r["task"], r["family"], r["seed"], r["index"], r["policy"]): r for r in rows}
    contrasts = []
    for task in sorted(identities):
        for ordinary in ("hx_margin", "ordinary_gate", "gru", "ssm", "history"):
            differences = defaultdict(list)
            for seed, index in itertools.product((13301, 13303, 13307), range(len(identities[task]["ids"]))):
                a, b, c, d = [lookup[task, family, seed, index, policy] for family, policy in ((ordinary, "fixed"), (ordinary, "value"), ("hx_full", "fixed"), ("hx_full", "value"))]
                for metric in metrics:
                    for label, value in (("B-A", b[metric]-a[metric]), ("D-C", d[metric]-c[metric]), ("C-A", c[metric]-a[metric]), ("D-B", d[metric]-b[metric]), ("interaction", (d[metric]-c[metric])-(b[metric]-a[metric]))):
                        differences[label, metric].append(value)
            contrasts.append({"task": task, "ordinary": ordinary, "paired_units": len(identities[task]["ids"])*3, "differences": {label: {metric: statistics.mean(differences[label, metric]) for metric in metrics} for label in ("B-A", "D-C", "C-A", "D-B", "interaction")}})
    return {"schema": "hcsn-v13-independent-dynamic-stdlib-audit.v1", "checks": checks, "all_checks_passed": not failures, "failed_examples": failures, "executions": len(rows), "candidates": len(metadata), "maximum_absolute_errors": dict(max_error), "means": means, "ordinary_fixed_value_four_grid": contrasts, "gate": gate, "scope": "Independent stdlib path/time/source-clock/scoring/fees and saved state binding, no author evaluator imports or independent neural kernel; correlated historical objects, no model selection or confidence claim"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.root, args.run)
    with args.out.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("means", "ordinary_fixed_value_four_grid")}))
    raise SystemExit(0 if result["all_checks_passed"] else 1)
