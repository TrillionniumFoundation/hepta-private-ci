"""Independent trace accounting, Bellman identities and actual owner causality."""
import json
import shutil
import time
import numpy as np
from common import HERE, ACTIONS, save, sha, verify, protocol
from adapter import ContentAdapter
from oracle import Bellman, likelihood, outcomes
from owner import Owner


def fixture(adapter, confusion):
    folder = HERE / "causality_fixtures"
    folder.mkdir(exist_ok=True)
    rows = json.loads((HERE / "data" / "calibration_seed61" / "labels_train_only.json").read_text())
    for symbol in (0, 1):
        source = HERE / next(r["path"] for r in rows if r["symbol"] == symbol)
        shutil.copyfile(source, folder / f"symbol{symbol}.json")
    public = dict(id="causality_only", deadline=8, budget=4,
                  reliability=[[.9]*8, [.9]*8], price=[[.02]*8, [.02]*8],
                  packets=[["symbol0.json"]*8, ["symbol1.json"]*8])
    save(folder / "public.json", public)
    untouched = Owner(folder, adapter, confusion, 1.)
    untouched.act("SKIP")
    before_stop = json.loads(json.dumps(untouched.snapshot()))
    untouched.act("STOP")
    stopped = json.loads(json.dumps(untouched.snapshot()))
    # Remove every actual packet and prove SKIP/STOP still execute without a read.
    (folder / "symbol0.json").rename(folder / "parked0.json")
    (folder / "symbol1.json").rename(folder / "parked1.json")
    no_payload = Owner(folder, adapter, confusion, 1.)
    no_payload.act("SKIP")
    no_payload.act("STOP")
    assert no_payload.counts["packet_file_reads"] == no_payload.counts["content_invocations"] == 0
    assert no_payload.posterior == stopped["posterior"] and no_payload.answers == stopped["answers"]
    terminal_rejected = False
    try:
        no_payload.act("READ")
    except RuntimeError:
        terminal_rejected = True
    assert terminal_rejected
    (folder / "parked0.json").rename(folder / "symbol0.json")
    (folder / "parked1.json").rename(folder / "symbol1.json")
    zero, one = adapter.read(folder / "symbol0.json"), adapter.read(folder / "symbol1.json")
    logit_difference = float(np.max(np.abs(np.asarray(zero["logits"])-one["logits"])))
    assert logit_difference > 1e-6 and zero["observation"] != one["observation"]
    original = Owner(folder, adapter, confusion, 1.)
    original.act("READ")
    original.act("SKIP")
    save(folder / "recovery.json", original.snapshot())
    restored = Owner(folder, adapter, confusion, 1.)
    restored.restore(json.loads((folder / "recovery.json").read_text()))
    for action in ("FIRE", "READ", "FIRE"):
        original.act(action)
        restored.act(action)
    keys = ("job", "tick", "budget", "posterior", "terminal", "reads_in_job", "charged_cost", "answers", "counts")
    assert all(getattr(original, k) == getattr(restored, k) for k in keys)
    assert original.answers[1]["job"] == 1
    save(folder / "uninterrupted_final.json", original.snapshot())
    save(folder / "recovered_final.json", restored.snapshot())
    return dict(passed=True, skip_without_packets=True, stop_terminal_rejected=terminal_rejected,
                no_unread_payload_dependency=True, read_payload_logit_change=logit_difference,
                decoder_observation_changed=True, recovered_final_state_and_answers_match=True,
                post_reset_second_job_executed=True, frozen_content_adapter=True)


def math_checks():
    confusion = np.array([[.9, .1], [.1, .9]])
    meta = dict(deadline=2, budget=1, reliability=[[.8]*2]*2, price=[[.05]*2]*2)
    q = Bellman(meta, confusion, 1.).q(0, 0, 1, .5)
    expected = 2*(.8*.9+.2*.1)-1-.05
    assert abs(q[2]-expected) < 1e-12
    assert q[0] == q[1] == q[3] == 0.
    longer = dict(deadline=8, budget=3, reliability=[[.9]*8]*2, price=[[.02]*8]*2)
    full = Bellman(longer, confusion, 1.).q(0, 0, 3, .9)
    first = Bellman(longer, confusion, 1., future=False).q(0, 0, 3, .9)
    assert full[3] > first[3] + .1
    # Law of total probability: the Bayesian posterior is a martingale under its own observation law.
    worst = 0.
    for posterior in (.01, .2, .5, .9, .99):
        prob, belief = outcomes(posterior, likelihood(confusion, .74))
        worst = max(worst, abs(float(prob @ belief)-posterior))
    assert worst < 1e-12
    return dict(passed=True, one_read_value=q[2], independently_enumerated_value=expected,
                full_fire_value=full[3], first_event_fire_value=first[3],
                post_reset_continuation=full[3]-first[3], posterior_martingale_error=worst)


def run():
    start = time.perf_counter()
    verify()
    p = protocol()
    result = json.loads((HERE / "results.json").read_text())
    assert result["complete"]
    manifest = json.loads((HERE / "data_manifest.json").read_text())
    for path, digest in manifest["files"].items():
        assert sha(HERE / path) == digest, path
    seen, invocations = set(), 0
    for row in result["rows"]:
        key = (row["session"], row["policy"], row["multiplier"])
        assert key not in seen
        seen.add(key)
        assert sha(HERE / row["trace"]) == row["trace_sha256"]
        trace = json.loads((HERE / row["trace"]).read_text())
        assert trace["terminal"] and row["label_access_after_terminal"]
        counts = {action: sum(e["action"] == action for e in trace["events"]) for action in ACTIONS}
        assert all(counts[k] == trace["counts"][k] for k in ACTIONS)
        assert counts["READ"] == trace["counts"]["packet_file_reads"] == trace["counts"]["content_invocations"]
        assert counts["FIRE"] == len(trace["answers"]) == row["completed_jobs"]
        assert all(not e["terminal"] for e in trace["events"][:-1])
        labels = json.loads((HERE / "data" / row["session"] / "evaluator_labels.json").read_text())["labels"]
        correct = sum(a["prediction"] == labels[a["job"]] for a in trace["answers"])
        assert correct == row["correct_jobs"]
        assert abs(2*correct-len(trace["answers"])-trace["charged_cost"]-row["utility"]) < 1e-12
        invocations += counts["READ"]
    expected = len(p["seeds"])*p["test_sessions_per_seed"]*len(p["cost_multipliers"])*len(p["policies"])
    assert len(seen) == expected
    for seed in p["seeds"]:
        selection = json.loads((HERE / "fits" / f"seed{seed}" / "selection.json").read_text())
        assert len(selection["candidates"]) == 9
        for candidate in selection["candidates"]:
            assert sha(HERE / candidate["checkpoint"]) == candidate["checkpoint_sha256"]
        for split in ("train", "validation"):
            provenance = json.loads((HERE / "fits" / f"seed{seed}" / f"{split}_provenance.json").read_text())
            assert all(row[0].startswith(split+"_") for row in provenance)
    calibration = json.loads((HERE / "fits" / "calibration_seed61.json").read_text())
    adapter = ContentAdapter()
    receipt = dict(integrity_passed=True, causal=fixture(adapter, calibration["confusion"]),
                   mathematics=math_checks(), policy_sessions_verified=expected,
                   actual_test_content_invocations_verified=invocations,
                   data_files_verified=len(manifest["files"]), results_sha256=sha(HERE / "results.json"),
                   scientific_freeze_sha256=sha(HERE / "freeze.json"),
                   primary_scientific_gate_passed=result["analysis"]["primary_gate_passed"],
                   audit_wall_seconds=time.perf_counter()-start,
                   scope="Local Python owner and frozen inherited decoder; no native Hepta Rust deployment claim")
    save(HERE / "audit.json", receipt)
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    run()
