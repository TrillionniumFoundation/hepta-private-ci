#!/usr/bin/env python3
"""Zero-training, label-blind grammar baseline for the frozen HPCA development content.
Stdin is JSON with exact text from TASKS.json, TRAIN_FEEDBACK.json, PLAN.json.
EVAL_LABELS.json must not be supplied, loaded, or used before candidates freeze.
"""
import hashlib
import json
import re
import resource
import sys
import time

PATTERNS = [
    re.compile(r"Record: (?P<who>[A-Za-z]+) has (?P<slot>color|shape) (?P<actual>[a-z]+)\. Does (?P=who) have (?P=slot) (?P<asked>[a-z]+)\?"),
    re.compile(r"The (?P<slot>color|shape) assigned to (?P<who>[A-Za-z]+) is (?P<actual>[a-z]+)\. Is the statement '(?P=who) has (?P=slot) (?P<asked>[a-z]+)' true\?"),
    re.compile(r"Read this fact: (?P<who>[A-Za-z]+)'s (?P<slot>color|shape) is (?P<actual>[a-z]+)\. According to the fact, does (?P=who) have (?P=slot) (?P<asked>[a-z]+)\?"),
]
DOMAINS = {0: ("color", {"red", "blue"}), 1: ("shape", {"circle", "square"})}


def digest(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def predict(prompt, group):
    if type(group) is not int or group not in DOMAINS or type(prompt) is not str:
        raise ValueError("invalid group or prompt")
    found = [m for p in PATTERNS if (m := p.fullmatch(prompt))]
    if len(found) != 1:
        raise ValueError("unrecognized/ambiguous prompt")
    m = found[0]
    slot, allowed = DOMAINS[group]
    if m["slot"] != slot or m["actual"] not in allowed or m["asked"] not in allowed:
        raise ValueError("out-of-domain fact")
    return "yes" if m["actual"] == m["asked"] else "no"


def adversarial_tests():
    assert predict("Record: Lumoa has color red. Does Lumoa have color red?", 0) == "yes"
    assert predict("The shape assigned to Neria is square. Is the statement 'Neria has shape circle' true?", 1) == "no"
    assert predict("Read this fact: Nerib's color is blue. According to the fact, does Nerib have color red?", 0) == "no"
    invalid = (
        ("Record: A has color red. Does B have color red?", 0),
        ("Record: A has color red. Does A have color red?", 1),
        ("Record: A has color purple. Does A have color red?", 0),
        ("Record: A has color red. Does A have color red? yes", 0),
    )
    for p, g in invalid:
        try:
            predict(p, g)
        except ValueError:
            continue
        raise AssertionError("unsafe prompt accepted")
    return 7


def run(bundle):
    t0 = time.perf_counter()
    if not isinstance(bundle, dict) or set(bundle) != {"tasks", "train", "plan"}:
        raise ValueError("only three frozen source texts allowed; no evaluation labels")
    if any(type(v) is not str for v in bundle.values()):
        raise ValueError("unbound text")
    plan = json.loads(bundle["plan"])
    if plan.get("decision") != "HOLD_NO_GO" or plan.get("independent_future_B") is not False:
        raise ValueError("not a held development source")
    for key, name in (("tasks", "TASKS.json"), ("train", "TRAIN_FEEDBACK.json")):
        if digest(bundle[key]) != plan["data_sha256"][name]:
            raise ValueError("source hash mismatch: " + name)
    rows = json.loads(bundle["tasks"])["tasks"]
    labels = json.loads(bundle["train"])
    if len(rows) != 160 or len({r["id"] for r in rows}) != 160:
        raise ValueError("wrong source roster")
    train = [r for r in rows if r["split"] == "train"]
    content = [r for r in rows if r["split"] == "content"]
    retention = [r for r in rows if r["split"] == "retention"]
    if (len(train), len(content), len(retention)) != (64, 64, 32):
        raise ValueError("wrong split")
    if set(labels) != {r["id"] for r in train}:
        raise ValueError("wrong training truth roster")
    training_predictions = {r["id"]: predict(r["question"], r["group"]) for r in train}
    content_predictions = {r["id"]: predict(r["question"], r["group"]) for r in content}
    correct = sum(training_predictions[k] == v for k, v in labels.items())
    canonical = json.dumps(content_predictions, sort_keys=True, separators=(",", ":"))
    u = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "schema": "HPCA-CONTENT-RULE-CONTROL-V1",
        "source_commit": "b0ea141de2d5218869823b2d9e075db6d7b215dd",
        "source_tree": "132da19ad5829e38a3e96f304c061c0c4c96becf",
        "input_sha256": {key: digest(value) for key, value in bundle.items()},
        "adversarial_cases_passed": adversarial_tests(),
        "train_correct": correct, "train_total": 64,
        "content_predictions": content_predictions,
        "content_prediction_sha256": digest(canonical),
        "content_count": 64,
        "content_yes": sum(v == "yes" for v in content_predictions.values()),
        "retention_count_not_scored": 32,
        "evaluation_labels_loaded": False,
        "model_forwards": 0, "optimizer_updates": 0,
        "grammar_matches": 128,
        "cpu_user_seconds_process": u.ru_utime,
        "cpu_system_seconds_process": u.ru_stime,
        "peak_rss_kib_process": u.ru_maxrss,
        "wall_seconds_inside_script": time.perf_counter() - t0,
        "scope": "explicit operator-authored contextual content grammar; not general intelligence",
        "decision": "HOLD_NO_GO",
    }


if __name__ == "__main__":
    print(json.dumps(run(json.loads(sys.stdin.read())), indent=2, sort_keys=True))
