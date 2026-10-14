"""Synthetic contract regressions; FakeLocalEncoder is never evidence of real weights."""
from __future__ import annotations

from copy import deepcopy
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import torch

from multimodal_alignment_contract import canonical, sha
from multimodal_bridge import ContractError
from multimodal_candidate_gate import PLAN, evaluate, validate_plan
from multimodal_head import StateGatedCellHead
from multimodal_pinned_candidate import (
    SCHEMA, _candidate, _head, _restore_head, _validate_examples,
    host_identity, predict, text_input_digest, train,
)
from multimodal_real_encoder import PROFILE_SCHEMA


def pin(v):
    return sha(v.encode())


class FakeLocalEncoder:
    """Controlled fixture only, never an actual checkpoint verifier."""
    simulated = True

    def __init__(self, profile):
        self.identity = sha(canonical(profile["snapshot"]))
        self.forward_calls = 0
        self.closed = False

    def encode(self, texts):
        self.forward_calls += 1
        return torch.tensor([
            [((sum(word.encode()) + i * 11) % 19 - 9) / 10 for i in range(16)]
            for word in texts
        ], dtype=torch.float32)

    def close(self):
        self.closed = True


class WrongForward(FakeLocalEncoder):
    def encode(self, texts):
        self.forward_calls += 1
        return torch.full((len(texts), 16), float("nan"))


def fixture():
    profiles = {}
    for label in ("granite_97m", "mmbert_small"):
        profiles[label] = {"schema": PROFILE_SCHEMA, "candidate": label,
                           "snapshot": {"revision": "f" * 40, "kind": "encoder",
                                        "files": {"model.safetensors": pin("model:"+label)}},
                           "expected_width": 16, "maximum_tokens": 64, "batch_size": 5,
                           "pooling": "attention-mask-mean", "normalization": "none"}
    train_rows = [
        {"case_id": f"t{i:02}", "group_id": f"train_group_{i//2}", "scope": "cell_S",
         "observed_at": i + 1, "split": "train", "text": f"training sample {i}",
         "state": [float(i % 3)] * 64, "label": i % 2}
        for i in range(16)]
    future_rows = []
    future_labels = []
    for i in range(16):
        txt = f"unseen sample {i}"
        state = [float((i+1) % 3)] * 64
        input_sha = text_input_digest("cell_S", txt, state)
        future_rows.append({"case_id": f"f{i:02}", "group_id": f"future_group_{i//2}",
                            "scope": "cell_S", "observed_at": 201+i, "split": "future",
                            "text": txt, "state": state, "input_sha256": input_sha})
        future_labels.append({"case_id": f"f{i:02}", "group_id": f"future_group_{i//2}",
                              "scope": "cell_S", "observed_at": 201+i,
                              "input_sha256": input_sha, "label": i%2})
    forward_meta = [{k:r[k] for k in ("case_id", "group_id", "scope", "observed_at", "input_sha256")}
                    for r in future_rows]
    candidates = ([{"name": "no_change", "profile_sha256": pin("baseline-p"),
                    "snapshot_sha256": pin("baseline-w")}] + [
                   {"name": k, "profile_sha256": sha(canonical(v)),
                    "snapshot_sha256": sha(canonical(v["snapshot"]))}
                   for k,v in profiles.items()])
    head_params = StateGatedCellHead(16,64,8,2).parameter_count()
    host = {"hardware_sha256": pin("hardware"), "environment_sha256": pin("env")}
    plan = {"schema": PLAN, "scope": "cell_S",
            "train_sha256": sha(b"".join(canonical(x) for x in train_rows)),
            "future_source_sha256": sha(b"".join(canonical(x) for x in forward_meta)),
            "future_targets_sha256": sha(b"".join(canonical(x) for x in future_labels)),
            "train_group_sha256s": sorted({pin(r["group_id"]) for r in train_rows}),
            "train_cutoff": 100, "future_start": 200, "future_end": 300,
            "classes": 2, "train_steps": 4, "head_parameters": head_params,
            "seed": 42, "hardware_sha256": host["hardware_sha256"],
            "environment_sha256": host["environment_sha256"],
            "candidates": sorted(candidates, key=lambda x:x["name"])}
    validate_plan(plan)
    return plan, profiles, train_rows, future_rows, future_labels, host


class FrozenCandidateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        # Resolve lazy TorchDynamo initialization before replacing the fixture's
        # isolated execution module for negative owner tests.
        torch.manual_seed(0)

    def setUp(self):
        (self.plan, self.profiles, self.train_rows,
         self.future_rows, self.truth, self.host) = fixture()
        self.profile = self.profiles["granite_97m"]
        self.p_sha = sha(canonical(self.plan))
        self.profile_sha = sha(canonical(self.profile))

    def mock_owner(self):
        # Patch only inside fixture tests. Production _material continues to
        # require the exact physical LocalEncoder class and snapshot identity.
        def fixture_owner(backend, identity):
            if not isinstance(backend, FakeLocalEncoder) or backend.identity != identity:
                raise ContractError("wrong fixture identity")
        return patch("multimodal_pinned_candidate._material", fixture_owner)

    def build(self, name="granite_97m"):
        profile = self.profiles[name]
        profile_sha = sha(canonical(profile))
        with self.mock_owner():
            raw, receipt = train(self.plan, self.p_sha, profile, profile_sha, name,
                                 self.train_rows, self.plan["train_sha256"],
                                 FakeLocalEncoder(profile), self.host)
            result, proof = predict(self.plan, self.p_sha, profile, profile_sha, name,
                                    receipt, sha(canonical(receipt)), raw, self.future_rows,
                                    FakeLocalEncoder(profile), self.host)
        return raw, receipt, result, proof

    def test_cls_pooling_propagates_to_train_and_predict_receipts(self):
        """Granite-style CLS must not be re-labelled masked-mean after fitting."""
        profile = dict(self.profile, pooling="cls-first-token", normalization="unit_l2")
        self.plan["candidates"] = [
            ({**v, "profile_sha256": sha(canonical(profile))}
             if v["name"] == "granite_97m" else v)
            for v in self.plan["candidates"]
        ]
        self.p_sha = sha(canonical(self.plan))
        profile_sha = sha(canonical(profile))

        class CLSFixtureEncoder(FakeLocalEncoder):
            def encode(self, texts, *, pooling="attention-mask-mean"):
                if pooling != "cls-first-token":
                    raise ContractError("CLS-only fixture received mean pooling")
                return super().encode(texts)

        with self.mock_owner():
            raw, receipt = train(self.plan, self.p_sha, profile, profile_sha,
                                 "granite_97m", self.train_rows,
                                 self.plan["train_sha256"], CLSFixtureEncoder(profile), self.host)
            self.assertEqual(receipt["pooling"], "cls-first-token")
            self.assertEqual(receipt["normalization"], "unit_l2")
            result, _ = predict(self.plan, self.p_sha, profile, profile_sha,
                                "granite_97m", receipt, sha(canonical(receipt)),
                                raw, self.future_rows, CLSFixtureEncoder(profile), self.host)
            self.assertEqual(result["candidate"], "granite_97m")
            for field, wrong in (("pooling", "attention-mask-mean"),
                                 ("normalization", "none")):
                tampered = {**receipt, field: wrong}
                with self.subTest(field=field), self.assertRaisesRegex(
                        ContractError, "Head training receipt"):
                    predict(self.plan, self.p_sha, profile, profile_sha,
                            "granite_97m", tampered, sha(canonical(tampered)),
                            raw, self.future_rows, CLSFixtureEncoder(profile), self.host)

    def test_model_param_count_is_real_and_equal_to_frozen_plan(self):
        self.assertEqual(self.plan["head_parameters"], _head(self.plan, 16).parameter_count())
        with self.assertRaises(ContractError):
            _head(self.plan, 384)

    def test_train_and_source_only_predict_bind_exact_complete_candidate(self):
        raw, receipt, result, proof = self.build()
        self.assertEqual(receipt["schema"], SCHEMA)
        self.assertEqual(receipt["model_forwards"], 4)
        self.assertEqual(result["execution"]["physical_forwards"], 8)
        self.assertEqual(len(result["predictions"]), 16)
        self.assertEqual(result["execution"]["publisher_authenticated"], False)
        self.assertFalse(proof["independent_attestation"])
        self.assertFalse(receipt["actual_pretrained_model_proven"])
        self.assertNotIn("label", result["predictions"][0])
        self.assertNotIn("text", result["predictions"][0])
        self.assertEqual(proof["candidate_result_sha256"], sha(canonical(result)))
        self.assertIsInstance(_restore_head(self.plan, receipt, raw, 16), StateGatedCellHead)

    def test_reproducible_train_with_same_seed_and_source(self):
        a = self.build()
        b = self.build()
        self.assertEqual(a[0], b[0])
        self.assertEqual(a[2]["predictions"], b[2]["predictions"])

    def test_real_backend_gate_rejects_unpatched_fake(self):
        # The fake may not issue a real-material receipt outside isolated patch.
        fake = FakeLocalEncoder(self.profile)
        with self.assertRaises((ContractError, ModuleNotFoundError)):
            train(self.plan, self.p_sha, self.profile, self.profile_sha, "granite_97m",
                  self.train_rows, self.plan["train_sha256"], fake, self.host)

    def test_fake_nonfinite_forward_and_counter_drift_rejected(self):
        with self.mock_owner():
            with self.assertRaises(ContractError):
                train(self.plan, self.p_sha, self.profile, self.profile_sha, "granite_97m",
                      self.train_rows, self.plan["train_sha256"],
                      WrongForward(self.profile), self.host)
            original = FakeLocalEncoder.encode
            def no_forward(self, texts):
                value = original(self, texts)
                self.forward_calls -= 1
                return value
            with patch.object(FakeLocalEncoder, "encode", no_forward):
                with self.assertRaises(ContractError):
                    train(self.plan, self.p_sha, self.profile, self.profile_sha,
                          "granite_97m", self.train_rows, self.plan["train_sha256"],
                          FakeLocalEncoder(self.profile), self.host)

    def test_frozen_training_scope_group_and_time_gates(self):
        for change in (lambda rows: rows[0].update(label=True),
                       lambda rows: rows[0].update(observed_at=101),
                       lambda rows: rows[0].update(scope="other"),
                       lambda rows: rows[0].update(group_id="unlisted"),
                       lambda rows: rows[0].update(extra=1),
                       lambda rows: rows[0].update(case_id="t01"),
                       lambda rows: rows[0].update(state=[float("nan")]*64)):
            rows=deepcopy(self.train_rows);change(rows)
            with self.subTest(change=change),self.assertRaises(ContractError):
                _validate_examples(self.plan, rows, "train")

    def test_future_input_label_content_group_and_time_leaks_rejected(self):
        train_texts = {sha(x["text"].encode()) for x in self.train_rows}
        for change in (lambda rows: rows[0].update(label=1),
                       lambda rows: rows[0].update(target_text="secret"),
                       lambda rows: rows[0].update(group_id="train_group_0"),
                       lambda rows: rows[0].update(observed_at=100),
                       lambda rows: rows[0].update(text="training sample 0"),
                       lambda rows: rows[0].update(state=[0.]*64),
                       lambda rows: rows[0].update(input_sha256=pin("altered")),
                       lambda rows: rows.pop()):
            rows=deepcopy(self.future_rows);change(rows)
            with self.subTest(change=change),self.assertRaises(ContractError):
                _validate_examples(self.plan, rows, "future", train_texts)

    def test_reject_tampered_head_receipt_and_plan_drift(self):
        raw, receipt, _, _=self.build()
        altered = deepcopy(receipt); altered["train_steps"] = 5
        with self.mock_owner(),self.assertRaises(ContractError):
            predict(self.plan, self.p_sha, self.profile, self.profile_sha,
                    "granite_97m", altered, sha(canonical(altered)), raw,
                    self.future_rows, FakeLocalEncoder(self.profile), self.host)
        with self.assertRaises(ContractError):
            _restore_head(self.plan, receipt, raw[:-1]+bytes([raw[-1]^1]), 16)
        drift = deepcopy(self.plan);drift["seed"] = 12
        with self.mock_owner(),self.assertRaises(ContractError):
            train(drift, self.p_sha, self.profile, self.profile_sha,"granite_97m",
                  self.train_rows, drift["train_sha256"],FakeLocalEncoder(self.profile),self.host)

    def test_fail_closed_unmatched_budget_or_unrecognized_baseline(self):
        changed = deepcopy(self.plan); changed["head_parameters"] += 1
        with self.assertRaises(ContractError):
            _head(changed,16)
        with self.assertRaises(ContractError):
            _candidate(self.plan,"no_change",self.profile,self.profile_sha)

    def test_host_profile_is_frozen_and_must_match(self):
        changed=deepcopy(self.host);changed["hardware_sha256"]=pin("alternate")
        with self.mock_owner(),self.assertRaises(ContractError):
            train(self.plan,self.p_sha,self.profile,self.profile_sha,"granite_97m",
                  self.train_rows,self.plan["train_sha256"],FakeLocalEncoder(self.profile),changed)

    def test_source_only_result_matches_independent_v4_readout(self):
        _,_,granite,_=self.build("granite_97m")
        _,_,mmbert,_=self.build("mmbert_small")
        source_fields=("case_id","group_id","scope","observed_at","input_sha256")
        baseline={**granite, "candidate":"no_change",
                  "profile_sha256":next(x["profile_sha256"] for x in self.plan["candidates"] if x["name"]=="no_change"),
                  "snapshot_sha256":next(x["snapshot_sha256"] for x in self.plan["candidates"] if x["name"]=="no_change"),
                  "train_steps":0,"head_parameters":0,
                  "predictions":[{**{k:r[k] for k in source_fields},"probabilities":[.5,.5]}
                                 for r in self.future_rows]}
        # The baseline is an invented *test fixture*, not an execution result.
        reports = [(r,sha(canonical(r))) for r in (baseline, granite, mmbert)]
        output=evaluate(self.plan,self.truth,reports,self.p_sha)
        self.assertEqual(set(output["candidate_results"]),
                         {"no_change","granite_97m","mmbert_small"})
        self.assertIsNone(output["winner"])
        self.assertFalse(output["production_accepted"])


if __name__ == "__main__":
    unittest.main()
