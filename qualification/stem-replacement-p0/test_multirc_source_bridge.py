"""Synthetic reproduction of upstream P0 shape; no genuine source/human score."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import gate
import matched_head
import multirc_source_bridge as b
import physical_feature_bank


def sha(x):
    return hashlib.sha256(x).hexdigest()


def fixture():
    fit, blind = [], []
    for split,n in b.SOURCE_COUNTS.items():
        for passage_idx in range(n):
            state = ("The original human-annotated passage describes the status of the "
                     + str(split) + " shipment " + str(passage_idx) + ". "
                     + "The warehouse log is a separate source of evidence and the "
                     + "summary must only use the words in the original message.")
            source = sha(state.encode())
            group = sha(" ".join(state.split()).casefold().encode())
            for question_idx in range(2):
                for answer_idx in range(2):
                    orig_question = f"What did the passage report about shipment {passage_idx}?"
                    candidate = f"candidate option {answer_idx} for question {question_idx}"
                    prompt = ("Is the proposed answer supported by the original passage? Question: "
                              + json.dumps(orig_question, ensure_ascii=False) +
                              " Candidate answer: " + json.dumps(candidate, ensure_ascii=False))
                    for condition in ("original", "no_evidence"):
                        view = {"state": state if condition == "original" else
                                "(no passage evidence available)",
                                "question": prompt,
                                "options": ["not_supported", "supported"]}
                        row = {"case_id": sha(f"{split}:{passage_idx}:{question_idx}:{answer_idx}:{condition}".encode())[:32],
                               "source_id": source, "source_group": group, "split": split,
                               "question_id": sha(f"{source}:{question_idx}".encode())[:32],
                               "answer_id": sha(f"{source}:{question_idx}:{answer_idx}".encode())[:32],
                               "condition": condition, "candidate_text": candidate,
                               "original_question_text": orig_question,
                               "joint_input": view, "view_sha256": sha(b._json(view))}
                        if split != "test":
                            row["label"] = ((passage_idx + answer_idx + question_idx) % 2
                                            if condition == "original" else None)
                            fit.append(row)
                        else:
                            blind.append(row)
    base = {"schema": b.SOURCE_SCHEMA, "repo": b.SOURCE_REPO,
            "revision": b.SOURCE_REVISION, "train_sha256": "a"*64,
            "validation_sha256": "b"*64, "selection_rule": b.SOURCE_RULE,
            "source_passages_by_split": dict(b.SOURCE_COUNTS),
            "training_license_independently_approved": False,
            "contamination_ruled_out": False, "temporal_future_windows_verified": False,
            "authority": "DENY_ALL", "production_promotion_permitted": False}
    meta = dict(base, panel_id=sha(b._json({"base": base, "fit": fit, "blind": blind})))
    return {"metadata": meta, "cases": fit}, {"metadata": meta, "cases": blind}


def rehash_source(fit, blind):
    base = {k:v for k,v in fit["metadata"].items() if k!="panel_id"}
    fit["metadata"]["panel_id"] = sha(b._json({"base":base,"fit":fit["cases"],"blind":blind["cases"]}))
    blind["metadata"] = copy.deepcopy(fit["metadata"])


class P0MultiRCBridgeTests(unittest.TestCase):
    def test_success_label_blind_48_case_real_shape(self):
        fit, blind = fixture()
        panel, views, ledger, receipt = b.convert(fit, blind)
        self.assertEqual(len(panel["cases"]), 48)
        self.assertEqual((receipt["fit_count"],receipt["cal_count"],receipt["test_count"]), (24,8,16))
        self.assertEqual(receipt["number_source_groups"], 24)
        self.assertEqual(len(ledger["targets"]),24)
        self.assertEqual(panel["budget"]["head_trainable_params"],4161)
        self.assertEqual(panel["budget"]["head_steps"],40)
        self.assertFalse(ledger["production_authorized"])
        self.assertFalse(receipt["cal_or_test_labels_exported"])
        for doc in (panel,views):
            self.assertNotIn("label", json.dumps(doc).lower())
        self.assertFalse(receipt["cal_or_test_labels_exported"])
        self.assertEqual(gate.validate_panel(panel)["test_count"],16)
        self.assertEqual(len(physical_feature_bank.manifest_views(panel,views)),48)
        self.assertEqual(len(matched_head.validate_fit(panel,ledger)),24)

    def test_label_mutation_changes_only_private_fit_target_not_selection(self):
        fit, blind = fixture()
        panel1,views1,ledger1,_ = b.convert(fit,blind)
        c=next(r for r in fit["cases"] if r["split"]=="train" and r["condition"]=="original")
        c["label"] ^= 1
        rehash_source(fit,blind)
        panel2,views2,ledger2,_ = b.convert(fit,blind)
        self.assertEqual([r["case_id"] for r in panel1["cases"]],
                         [r["case_id"] for r in panel2["cases"]])
        self.assertEqual([r["question"] for r in views1["cases"]],
                         [r["question"] for r in views2["cases"]])
        self.assertNotEqual(panel1["source_material_sha256"],panel2["source_material_sha256"])
        self.assertNotEqual(ledger1["source_label_owner_sha256"],ledger2["source_label_owner_sha256"])

    def test_hidden_heldout_label_denied(self):
        fit,blind=fixture()
        blind["cases"][0]["label"]=1
        rehash_source(fit,blind)
        with self.assertRaises(gate.Denied):b.convert(fit,blind)

    def test_missing_original_pair_denied(self):
        fit,blind=fixture();fit["cases"].pop()
        rehash_source(fit,blind)
        with self.assertRaisesRegex(gate.Denied,"missing or oversized"):b.convert(fit,blind)

    def test_counterfactual_never_human_labeled(self):
        fit,blind=fixture()
        c=next(x for x in fit["cases"] if x["condition"]=="no_evidence")
        c["label"]=0;rehash_source(fit,blind)
        with self.assertRaises(gate.Denied):b.convert(fit,blind)

    def test_cross_split_same_group_rejected(self):
        fit,blind=fixture()
        train_group=next(x["source_group"] for x in fit["cases"] if x["split"]=="train")
        for item in blind["cases"][:8]:
            item["source_group"] = train_group
        rehash_source(fit,blind)
        with self.assertRaises(gate.Denied):b.convert(fit,blind)

    def test_changed_question_with_self_consistent_view_hash_denied(self):
        fit,blind=fixture()
        case=next(x for x in fit["cases"] if x["condition"]=="original")
        case["joint_input"]["question"] = "Does this original source allow a false claim?"
        case["view_sha256"] = sha(b._json(case["joint_input"]))
        rehash_source(fit,blind)
        with self.assertRaises(gate.Denied):b.convert(fit,blind)

    def test_reordered_options_denied(self):
        fit,blind=fixture()
        item=fit["cases"][0]
        item["joint_input"]["options"].reverse()
        item["view_sha256"] = sha(b._json(item["joint_input"]))
        rehash_source(fit,blind)
        with self.assertRaises(gate.Denied):b.convert(fit,blind)

    def test_upstream_panel_id_drift_denied(self):
        fit,blind=fixture()
        fit["cases"][0]["label"] ^= 1
        with self.assertRaisesRegex(gate.Denied,"panel digest"):b.convert(fit,blind)

    def test_unauthorized_source_claim_denied(self):
        fit,blind=fixture()
        fit["metadata"]["training_license_independently_approved"] = True
        blind["metadata"]["training_license_independently_approved"] = True
        rehash_source(fit,blind)
        with self.assertRaises(gate.Denied):b.convert(fit,blind)

    def test_unknown_source_field_denied(self):
        fit,blind=fixture();fit["cases"][0]["gold"] = 1
        rehash_source(fit,blind)
        with self.assertRaises(gate.Denied):b.convert(fit,blind)

    def test_fit_label_support_required(self):
        fit,blind=fixture()
        for c in fit["cases"]:
            if c["split"]=="train" and c["condition"]=="original": c["label"]=0
        rehash_source(fit,blind)
        with self.assertRaises(gate.Denied):b.convert(fit,blind)

    def test_separate_private_and_public_cli_files(self):
        fit,blind=fixture()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/"source-fit.json").write_bytes(b._json(fit))
            (root/"source-blind.json").write_bytes(b._json(blind))
            (root/"private").mkdir(mode=0o700)
            b.main(["--fit",str(root/"source-fit.json"),"--blind",str(root/"source-blind.json"),
                    "--public-out",str(root/"public"),"--fit-labels-out",str(root/"private"/"fit-only.json")])
            public_files={p.name for p in (root/"public").iterdir()}
            self.assertEqual(public_files,{"panel.json","views.json","source-receipt.json"})
            for filename in public_files:
                self.assertFalse(any(k in json.loads((root/"public"/filename).read_text())
                                     for k in ("targets","gold","labels")))
                self.assertEqual((root/"public"/filename).stat().st_mode & 0o777,0o600)
            self.assertEqual((root/"private"/"fit-only.json").stat().st_mode & 0o777,0o600)
            self.assertEqual(len(json.loads((root/"private"/"fit-only.json").read_text())["targets"]),24)
            with self.assertRaises(gate.Denied):
                b.main(["--fit",str(root/"source-fit.json"),"--blind",str(root/"source-blind.json"),
                        "--public-out",str(root/"public"),"--fit-labels-out",str(root/"private"/"fit-only.json")])

    def test_same_public_private_directory_denied(self):
        fit,blind=fixture()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/"fit.json").write_bytes(b._json(fit))
            (root/"blind.json").write_bytes(b._json(blind))
            with self.assertRaises(gate.Denied):
                b.main(["--fit",str(root/"fit.json"),"--blind",str(root/"blind.json"),
                        "--public-out",str(root/"public"),"--fit-labels-out",str(root/"fit-only.json")])

    def test_tampered_original_group_hash_even_with_rehashed_docs_denied(self):
        fit,blind=fixture()
        for row in fit["cases"][:8]:
            row["source_group"] = "e"*64
        rehash_source(fit,blind)
        with self.assertRaisesRegex(gate.Denied,"group bytes"):
            b.convert(fit,blind)

    def test_missing_source_group_fail_closed(self):
        fit,blind=fixture()
        group=fit["cases"][0]["source_group"]
        fit["cases"]=[r for r in fit["cases"] if r["source_group"]!=group]
        rehash_source(fit,blind)
        with self.assertRaises(gate.Denied):b.convert(fit,blind)

    def test_counterfactual_question_mutation_denied(self):
        fit,blind=fixture()
        row=next(x for x in fit["cases"] if x["condition"]=="no_evidence")
        row["joint_input"]["question"] += " changed"
        row["view_sha256"]=sha(b._json(row["joint_input"]))
        rehash_source(fit,blind)
        with self.assertRaises(gate.Denied):b.convert(fit,blind)

    def test_fixed_original_revision_required(self):
        fit,blind=fixture()
        fit["metadata"]["revision"] = blind["metadata"]["revision"] = "0"*40
        rehash_source(fit,blind)
        with self.assertRaises(gate.Denied):b.convert(fit,blind)


if __name__=="__main__":unittest.main()
