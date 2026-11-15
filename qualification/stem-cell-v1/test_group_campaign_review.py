import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from group_campaign_review import ARMS, COMPOSITION_PROMPT, CORE_ARMS, review


class CampaignReviewTests(unittest.TestCase):
    def fixture(self, root):
        public, groups = {}, {}
        for i, name in enumerate(("train", "validation", "selection", "test", "long")):
            label, node = chr(65 + i), f"n{i + 1}"
            facts = [("link", "n0", node), ("label", node, label)]
            canonical = json.dumps(["dependency", ("follow", "n0"), sorted(facts)], separators=(",", ":"))
            source = hashlib.sha256(canonical.encode()).hexdigest()
            text = f"Start at n0 and follow every link. What is the endpoint class? Answer one of A B C D E F G H.\nn0 links to {node}.\n{node} has class {label}."
            public[name] = [dict(case_id=name, source_group=source, family="dependency", text=text)]
            groups[name] = [source]
        public["deleted"] = [dict(public["test"][0], text=public["test"][0]["text"].splitlines()[0])]
        groups["deleted"] = groups["test"]
        left = public["test"][0]
        right_text = "Which class satisfies every allowed-class constraint? Answer one of A B C D E F G H.\nConstraint 0 allows B."
        right_source = hashlib.sha256(json.dumps(["constraint", ["intersection"], [["allow", "0", ["B"]]]], separators=(",", ":")).encode()).hexdigest()
        canonical = ["composition", ["sum_mod", 8], [["test/" + left["source_group"][:20], left["source_group"]], ["test/" + right_source[:20], right_source]]]
        source = hashlib.sha256(json.dumps(canonical, separators=(",", ":")).encode()).hexdigest()
        public["composition"] = [dict(case_id="composed", source_group=source, family="composition",
                                       text=COMPOSITION_PROMPT + "\n[LEFT]\n" + left["text"] + "\n[RIGHT]\n" + right_text)]
        groups["composition"] = [source]
        protocol = dict(public_cases=public, source_groups=groups)
        rows, summaries = [], {}
        for cohort, target in (("selection", 2), ("test", 3), ("long", 4), ("deleted", 3), ("composition", 4)):
            for arm in (("fixed", "split") if cohort == "selection" else ARMS):
                case = public[cohort][0]
                rows.append(dict(cohort=cohort, arm=arm, case_id=case["case_id"],
                                 source_group=case["source_group"], family=case["family"], prediction=target,
                                 candidate_correct=True, valid_execution=True, success=True, status="done", steps=4, wall_ns=10, cpu_ns=8,
                                 search_formula_work=100, verifier_calls=4,
                                 model_sha256="core" if arm in CORE_ARMS else arm,
                                 feature_sha256=cohort))
                summaries[f"{cohort}.{arm}"] = dict(n=1, correct=1, verifier_calls=4, steps=4,
                    cpu_ns=8, wall_ns=10, observed_p50_ns=10, observed_p95_ns=10,
                    tail_quantiles_are_target_host_certification=False, statuses={"done": 1})
        digest = hashlib.sha256(json.dumps(protocol, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        report = dict(protocol_sha256=digest, summaries=summaries)
        for name, data in (("protocol", protocol), ("observations", rows), ("report", report)):
            (root / f"{name}.json").write_text(json.dumps(data))
        return rows

    def test_replays_original_truth_for_deleted_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            result = review(root)
            self.assertTrue(result["independent_symbolic_label_replay"])
            self.assertEqual(result["observation_rows"], 34)
            self.assertFalse(result["model_execution_independently_attested"])

    def test_tampered_prediction_success_missing_arm_and_duplicate_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = self.fixture(root)
            def bad_prediction(rows): rows[0]["prediction"] = 7
            def bad_success(rows): rows[0]["success"] = False
            def failed_execution(rows): rows[0]["status"] = "callback_failed"
            def changed_core(rows): rows[0]["model_sha256"] = "changed"
            def missing_work(rows): rows[0]["search_formula_work"] = 0
            def missing(rows): rows.pop()
            def duplicate(rows): rows.append(copy.deepcopy(rows[0]))
            for mutate in (bad_prediction, bad_success, failed_execution, changed_core, missing_work, missing, duplicate):
                rows = copy.deepcopy(original)
                mutate(rows)
                (root / "observations.json").write_text(json.dumps(rows))
                with self.subTest(mutation=mutate.__name__), self.assertRaises(ValueError):
                    review(root)


if __name__ == "__main__":
    unittest.main()
