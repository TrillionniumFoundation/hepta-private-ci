"""Synthetic file-record forgery checks for stdlib independent campaign review."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from group_attention_campaign_review import ARMS, COHORTS, _digest, review
from group_campaign_review import COMPOSITION_PROMPT, _parse


def _case(family, query, facts, prefix):
    source = hashlib.sha256(json.dumps([family, query, sorted(facts)],
                                        separators=(",", ":")).encode()).hexdigest()
    if family == "dependency":
        prompt = f"Start at {query[1]} and follow every link. What is the endpoint class? Answer one of A B C D E F G H."
        lines = [f"{a} links to {b}." if kind == "link" else f"{a} has class {b}."
                 for kind, a, b in facts]
    elif family == "constraint":
        prompt = "Which class satisfies every allowed-class constraint? Answer one of A B C D E F G H."
        lines = [f"Constraint {i} allows {' '.join(values)}." for _, i, values in facts]
    else:
        prompt = f"What is the class of the last event for {query[1]} by time? Answer one of A B C D E F G H."
        lines = [f"At time {time}, {entity} has class {label}."
                 for entity, time, label in facts]
    return dict(case_id=prefix + "/" + source[:20], source_group=source,
                family=family, text="\n".join([prompt, *lines]))


def fixture(directory):
    train = _case("dependency", ("follow", "n0"),
                  [("link", "n0", "n9"), ("label", "n9", "A")], "train")
    first = _case("dependency", ("follow", "n0"),
                  [("link", "n0", "n2"), ("label", "n2", "B")], "test")
    second = _case("constraint", ("intersection",), [("allow", "0", ("C",))], "test")
    long = _case("temporal", ("latest", "sensor0"), [("sensor0", 10, "D")], "test")
    pair = [[c["case_id"], c["source_group"]] for c in (first, second)]
    composed_source = hashlib.sha256(json.dumps(
        ["composition", ("sum_mod", 8), pair], separators=(",", ":")).encode()).hexdigest()
    composition = dict(case_id="composition/" + composed_source[:20],
        source_group=composed_source, family="composition",
        text=COMPOSITION_PROMPT + "\n[LEFT]\n" + first["text"]
        + "\n[RIGHT]\n" + second["text"])
    deleted = [dict(c, text=c["text"].splitlines()[0]) for c in (first, second)]
    cases = dict(train=[train], test=[first, second], long=[long],
                 deleted=deleted, composition=[composition])
    protocol = dict(schema="hepta.group.paired-step-campaign.v1",
        frozen_candidate_arms=list(ARMS), evaluation_cohorts=list(COHORTS),
        train_source_groups=[train["source_group"]], public_cases=cases,
        steps=3, seed=17)
    teacher = dict(source_groups_sha256=_digest([train["source_group"]]),
        authority="DENY_ALL", train_only=True, supervised_steps=2,
        tokenizer_calls=1, teacher_tensor_sha256="a" * 64)
    encoder = dict(actual_forward_calls=8)
    training = {}
    for arm in ARMS:
        training[arm] = dict(status="completed", completed_steps=3, seed=17,
            cpu_ns=100, wall_ns=100, parameter_count=112,
            sample_and_depth_sha256="b" * 64,
            attention_supervision_enabled=arm == "attention",
            attention_target_sha256="a" * 64 if arm == "attention" else None)
    rows, summaries = [], {}
    for cohort in COHORTS:
        for arm in ARMS:
            group_rows = []
            for case in cases[cohort]:
                correct, _, _ = _parse(case, missing=cohort == "deleted")
                row = dict(cohort=cohort, arm=arm, case_id=case["case_id"],
                    source_group=case["source_group"],
                    feature_sha256=hashlib.sha256(
                        (cohort + case["text"]).encode()).hexdigest(),
                    model_sha256=hashlib.sha256(arm.encode()).hexdigest(),
                    prediction=0 if correct is None else correct,
                    evidence_supported=correct is not None,
                    success=correct is not None, unsupported_attempt=correct is None,
                    wall_ns=20, cpu_ns=10)
                rows.append(row)
                group_rows.append(row)
            summaries[f"{cohort}.{arm}"] = dict(n=len(group_rows),
                correct=sum(r["success"] for r in group_rows),
                unsupported_attempts=sum(r["unsupported_attempt"] for r in group_rows),
                cpu_ns=sum(r["cpu_ns"] for r in group_rows),
                wall_ns=sum(r["wall_ns"] for r in group_rows),
                p50_ns=20, p95_ns=20)
    report = dict(schema="hepta.group.paired-step-observation.v1",
        protocol_sha256=_digest(protocol), authority="DENY_ALL",
        production_authorized=False, natural_future_win_established=False,
        equal_actual_training_work=False, teacher=teacher,
        encoder_cost=encoder, training=training, summaries=summaries)
    for name, data in (("protocol", protocol), ("teacher", teacher),
                       ("encoder", encoder), ("observations", rows), ("report", report)):
        (directory / (name + ".json")).write_text(json.dumps(data))
    return {name: copy.deepcopy(value) for name, value in
            (("protocol", protocol), ("teacher", teacher), ("encoder", encoder),
             ("observations", rows), ("report", report))}


class PairedReviewTests(unittest.TestCase):
    def test_independent_symbolic_replay_no_promotion(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = review_fixture = fixture(Path(tmp))
            reviewed = review(tmp)
            self.assertTrue(reviewed["complete_group_replay"])
            self.assertFalse(reviewed["future_task_efficacy_proved"])
            self.assertFalse(reviewed["real_host_execution_independently_attested"])

    def test_reject_prediction_cost_binding_and_missing_arm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = fixture(root)
            for mutation in (
                lambda r: r[0].update(success=False),
                lambda r: r[0].update(cpu_ns=0),
                lambda r: r[0].update(feature_sha256="0" * 64),
                lambda r: r.pop(),
                lambda r: r.append(copy.deepcopy(r[0])),
            ):
                rows = copy.deepcopy(files["observations"])
                mutation(rows)
                (root / "observations.json").write_text(json.dumps(rows))
                with self.subTest(mutation=repr(mutation)), self.assertRaises(ValueError):
                    review(root)

    def test_reject_teacher_and_unequal_schedule_forgery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = fixture(root)
            changed = copy.deepcopy(files["report"])
            changed["training"]["attention"]["sample_and_depth_sha256"] = "c" * 64
            (root / "report.json").write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, "schedule"):
                review(root)
            (root / "report.json").write_text(json.dumps(files["report"]))
            changed = copy.deepcopy(files["teacher"])
            changed["source_groups_sha256"] = "d" * 64
            (root / "teacher.json").write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, "teacher"):
                review(root)

    def test_reject_damaged_public_evidence_and_protocol(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = fixture(root)
            changed = copy.deepcopy(files["protocol"])
            changed["public_cases"]["test"][0]["text"] = "injected, no evidence"
            (root / "protocol.json").write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                review(root)


if __name__ == "__main__":
    unittest.main()
