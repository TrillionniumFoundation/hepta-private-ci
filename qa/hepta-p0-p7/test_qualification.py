"""Contract tests, intentionally synthetic: never constitute model evidence."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from qualification import (ARMS, EvidenceError, cvar90, digest, read_json,
                           report_status, validate_episode, validate_protocol,
                           validate_sources, verify_artifact)


def state(n):
    return digest(f"state:{n}".encode())


def generate_fixture(root):
    (root / "inputs").mkdir()
    (root / "outputs").mkdir()
    finished = b"an actual decoded toy artifact, not external model output"
    (root / "outputs" / "final.bin").write_bytes(finished)
    model_sha = digest(b"encoder-pinned")
    sources = []
    for role, count in (("train",1),("dev",1),("calibration",1),("test",128)):
        for i in range(count):
            sid = f"{role}:{i}"
            payload = f"registered-source:{sid}".encode()
            path = f"inputs/{sid.replace(':','_')}.bin"
            (root / path).write_bytes(payload)
            sources.append(dict(source_id=sid,split=role,original_group=sid,
                                source_sha256=digest(payload),path=path,
                                modalities=["text","image","audio","video"]))
    source_index = {s["source_id"]:s for s in sources}
    protocol = dict(schema="hepta.p0-p7.research.v1", seeds=[7,17,29],
                    arms=list(ARMS), episode_budget_us=20_000,
                    encoder_digest=model_sha, encoder_generation=1,
                    paired_noise_protocol="common-random-numbers-v1")
    records = []
    for s in sources:
        if s["split"] != "test":
            continue
        for seed in protocol["seeds"]:
            for arm in ARMS:
                actions = (["DECOMPOSE","ROUTE","RECALL","VERIFY","REVISE",
                            "BACKTRACK","VERIFY","STOP"] if arm == "ndu" else
                           ["ROUTE","STOP"] if arm == "ndu_no_cov" else ["STOP"])
                if arm == "ndu_no_cov":
                    actions = ["ROUTE","RECALL"]
                previous = state(0)
                trace = []
                for i,action in enumerate(actions):
                    after = state(i+1)
                    trace.append(dict(action=action,pre_state_sha256=previous,
                                      post_state_sha256=after,evidence_sha256=state(100+i),
                                      cost_us=50))
                    previous = after
                action_sha = digest(b"hepta.group.actions.v1\0"+
                                    json.dumps(actions,separators=(",", ":")).encode())
                trace_sha = digest(b"hepta.group.trace.v1\0" +
                                   json.dumps(trace,sort_keys=True,separators=(",", ":")).encode())
                score = .95 if arm=="ndu" else .8 if arm=="ndu_no_cov" else .75
                records.append(dict(arm=arm,source_id=s["source_id"],
                    source_sha256=s["source_sha256"],seed=seed,
                    noise_digest=digest(f"noise:{s['source_id']}:{seed}".encode()),
                    owner=dict(encoder_digest=model_sha,generation=1,forward_calls=1,
                        feature_digest=state(500),cells=[dict(cell_id="C:1",feature_digest=state(500))]),
                    cost_us=dict(encoder=1000,head=2000,controller=500,verifier=1500,
                                 decoder=3000,io=2000),total_us=10000,
                    valid=True,covered=True,severe=False,quality=score,
                    output_path="outputs/final.bin",output_sha256=digest(finished),
                    actual_steps=len(trace),decisions=trace,action_digest=action_sha,
                    trace_sha256=trace_sha,risk_weight=.5 if arm=="ndu" else 0.0))
    return protocol, {"sources":sources}, {"source_sha256":[]}, source_index, records


class QualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        (cls.protocol, cls.sources, cls.history, cls.by_id,
         cls.records) = generate_fixture(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_replayable_synthetic_mechanism_but_never_promoted(self):
        by_id, counts = validate_sources(self.root, self.sources, self.history)
        self.assertEqual(counts["test"],128)
        for r in self.records:
            validate_episode(self.root,r,by_id,self.protocol)
        receipt = report_status(by_id,self.protocol,self.records)
        self.assertEqual(receipt["episode_count"],3456)
        self.assertTrue(all(receipt["mechanism_checks"].values()))
        self.assertFalse(receipt["model_promotion_authorized"])
        self.assertEqual(set(receipt["stage_status"].values()), {"HOLD_NO_GO"})

    def test_source_leakage_fails(self):
        sources = {"sources":[dict(x) for x in self.sources["sources"]]}
        sources["sources"][-1]["source_sha256"] = sources["sources"][0]["source_sha256"]
        with self.assertRaises(EvidenceError):
            validate_sources(self.root,sources,self.history)

    def test_duplicate_episode_and_missing_arm_denied(self):
        with self.assertRaisesRegex(EvidenceError,"duplicate source/seed/arm"):
            report_status(self.by_id,self.protocol,self.records+[self.records[-1]])
        with self.assertRaisesRegex(EvidenceError,"incomplete heldout"):
            report_status(self.by_id,self.protocol,self.records[:-1])

    def test_risk_zero_and_short_ndu_denied(self):
        row = next(dict(x) for x in self.records if x["arm"]=="ndu")
        row["risk_weight"] = 0
        with self.assertRaisesRegex(EvidenceError,"risk term"):
            validate_episode(self.root,row,self.by_id,self.protocol)
        row["risk_weight"] = .5
        row["decisions"] = row["decisions"][:2]
        row["actual_steps"] = 2
        with self.assertRaisesRegex(EvidenceError,"fewer than 8"):
            validate_episode(self.root,row,self.by_id,self.protocol)

    def test_false_action_binding_denied(self):
        row = dict(self.records[0])
        row["action_digest"] = state(33)
        with self.assertRaisesRegex(EvidenceError,"action digest"):
            validate_episode(self.root,row,self.by_id,self.protocol)

    def test_trace_hash_binds_state_and_measured_cost(self):
        row = dict(self.records[0])
        row["decisions"] = [dict(x) for x in row["decisions"]]
        row["decisions"][0]["cost_us"] = 60
        with self.assertRaisesRegex(EvidenceError,"trace digest"):
            validate_episode(self.root,row,self.by_id,self.protocol)

    def test_covariance_requires_distinct_actions_not_merely_hashes(self):
        rows = [dict(r) for r in self.records]
        by_key = {(r["source_id"],r["seed"],r["arm"]):r for r in rows}
        for r in rows:
            if r["arm"] == "ndu_no_cov":
                target = by_key[(r["source_id"],r["seed"],"ndu")]
                r["decisions"] = target["decisions"]
                r["action_digest"] = target["action_digest"]
                r["trace_sha256"] = target["trace_sha256"]
        receipt = report_status(self.by_id,self.protocol,rows)
        self.assertFalse(receipt["mechanism_checks"]["ndu_covariance_changes_action"])

    def test_wrong_source_and_output_hash_denied(self):
        row = dict(self.records[0]); row["source_sha256"] = state(0)
        with self.assertRaisesRegex(EvidenceError,"source or common-noise"):
            validate_episode(self.root,row,self.by_id,self.protocol)
        row = dict(self.records[0]); row["output_sha256"] = state(0)
        with self.assertRaisesRegex(EvidenceError,"SHA256 mismatch"):
            validate_episode(self.root,row,self.by_id,self.protocol)

    def test_hard_cost_and_failed_output_counting(self):
        row = dict(self.records[0]); row["total_us"] = 20001
        with self.assertRaisesRegex(EvidenceError,"physical cost"):
            validate_episode(self.root,row,self.by_id,self.protocol)
        row = dict(self.records[0]); row["valid"] = False
        with self.assertRaisesRegex(EvidenceError,"wrongly rewarded"):
            validate_episode(self.root,row,self.by_id,self.protocol)

    def test_paired_draw_identity_denied(self):
        rows = [dict(r) for r in self.records]
        rows[0]["noise_digest"] = state(999)
        with self.assertRaisesRegex(EvidenceError,"unmatched stochastic"):
            report_status(self.by_id,self.protocol,rows)

    def test_path_escape_and_symlink_denied(self):
        with self.assertRaises(EvidenceError):
            verify_artifact(self.root,"../outside",state(0))
        (self.root/"inputs"/"linked.bin").symlink_to(self.root/"outputs"/"final.bin")
        with self.assertRaises(EvidenceError):
            verify_artifact(self.root,"inputs/linked.bin",digest(b"an actual decoded toy artifact, not external model output"))

    def test_duplicate_json_and_nan_denied(self):
        p = self.root/"invalid.json"
        p.write_text('{"seeds": [], "seeds": [7]}')
        with self.assertRaises(EvidenceError): read_json(p)
        p.write_text('{"a":NaN}')
        with self.assertRaises(EvidenceError): read_json(p)

    def test_protocol_sha_required(self):
        p = self.root/"policy.json"
        data = json.dumps(self.protocol).encode(); p.write_bytes(data)
        validate_protocol(self.protocol,p,digest(data))
        with self.assertRaises(EvidenceError):
            validate_protocol(self.protocol,p,state(99))

    def test_fractional_cvar(self):
        self.assertAlmostEqual(cvar90([1,0,0,0,0,0,0,0,0,0,0]), 10/11)


if __name__ == "__main__":
    unittest.main()
