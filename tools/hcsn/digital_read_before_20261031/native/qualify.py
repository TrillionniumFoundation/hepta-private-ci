#!/usr/bin/env python3
"""Development-only native parity, due-read, and acknowledged-recovery checks.

These forced qualification trajectories are excluded from formal experiment data.
Inputs must be untrained development policies from a fit outside the formal set.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))
from tools.hcsn.digital_read_before_20261031.deploy import Policy
from tools.hcsn.digital_read_before_20261031.task import legal, successor

FAMILIES = ("ordinary_base", "ordinary_bank", "clocked_bank", "first_passage_bank", "raw_history")


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False)+"\n")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def same_state(a, b):
    a, b = dict(a), dict(b)
    for key in ("elapsed", "charges"):
        assert abs(a.pop(key)-b.pop(key)) <= 2e-12, key
    assert a == b, (a, b)


class Audit:
    def __init__(self, args):
        self.args = args
        self.out = args.work_dir.resolve()
        self.out.mkdir(parents=True, exist_ok=False)
        self.rows = []
        self.calls = 0
        self.maximum_score_error = 0.
        self.source_digest = None
        self.original_public = json.loads(args.public.read_text())
        self.artifacts = {name: json.loads((args.policies/f"{name}.json").read_text()) for name in FAMILIES}
        self.reference = {name: Policy(value) for name, value in self.artifacts.items()}

    def world(self, name, mutation=None):
        folder = self.out/"worlds"/name
        folder.mkdir(parents=True)
        public = json.loads(json.dumps(self.original_public))
        public["read_delay"] = [2]*6
        public["read_delay"][3] = 1
        for packet in public["packets"]:
            shutil.copyfile(self.args.public.parent/packet, folder/packet)
        if mutation is not None:
            mutation(folder, public)
        save(folder/"public.json", public)
        return folder/"public.json", public

    def run(self, name, world, family="first_passage_bank", actions=None, controller="fixed",
            snapshot=None, ack=None, steps=7, success=True, policy=None, seed=818):
        self.calls += 1
        directory = self.out/"runs"/name
        directory.mkdir(parents=True)
        snapshot = snapshot or directory/"owner.json"
        command = [str(self.args.binary), "--public", str(world), "--content-model", str(self.args.content_model),
                   "--policy", str(policy or self.args.policies/f"{family}.json"),
                   "--controller", controller, "--snapshot", str(snapshot), "--seed", str(seed),
                   "--steps", str(len(actions) if actions is not None else steps), "--mode", "qualification"]
        if actions is not None:
            command += ["--forced-actions", ",".join(actions)]
        if ack is not None:
            command += ["--ack", ack]
        process = subprocess.run(command, capture_output=True, text=True, timeout=30)
        (directory/"stdout.json").write_text(process.stdout)
        (directory/"stderr.txt").write_text(process.stderr)
        row = dict(name=name, command=command, returncode=process.returncode,
                   stdout_sha256=hashlib.sha256(process.stdout.encode()).hexdigest(),
                   stderr_sha256=hashlib.sha256(process.stderr.encode()).hexdigest())
        self.rows.append(row)
        if not success:
            assert process.returncode != 0, row
            return None, snapshot
        assert process.returncode == 0, (row, process.stderr)
        result = json.loads(process.stdout)
        assert result["actual_native"] and not result["production_activation"]
        assert result["authority"] == "DENY_ALL" and result["mode"] == "qualification"
        assert result["cpu_nanos"] > 0 and result["wall_nanos"] > 0
        assert result["forced_control"] == (actions is not None)
        assert result["acknowledged_sha256"] == digest(snapshot)
        if self.source_digest is not None:
            assert result["source_digest"] == self.source_digest
        self.source_digest = result["source_digest"]
        public = json.loads(world.read_text())
        reference = self.reference[family]
        for receipt in result["receipts"]:
            before, after = receipt["before"], receipt["after"]
            scores = reference.predict(public, before, receipt["cell_before"]["index"])
            err = max(np.max(np.abs(np.asarray(scores["q"])-receipt["q"])),
                      abs(scores["belief"]-receipt["belief"]))
            self.maximum_score_error = max(self.maximum_score_error, float(err))
            assert err <= 5e-12, (name, err)
            assert legal(public, before)[receipt["action"]]
            same_state(after, successor(public, before, receipt["action"], receipt["completion"]))
            old_index, old_rng = receipt["cell_before"]["index"], int(receipt["cell_before"]["rng_hex"], 16)
            new_index, new_rng, event = old_index, old_rng, dict(sampled=False, event=False)
            if receipt["action"] not in (0, 4, 5):
                new_index, new_rng, event = reference.advance(public, before, old_index, old_rng)
            assert new_index == receipt["cell_after"]["index"]
            assert new_rng == int(receipt["cell_after"]["rng_hex"], 16)
            assert event["sampled"] == (receipt["draw"] is not None)
            assert event["event"] == receipt["cell_event"]
            audit = receipt["read_audit"]
            assert receipt["actual_content_calls"] == audit["model_executions"]
            assert len(receipt["opened_packet_paths"]) == audit["successful_opens"]
            assert len(receipt["attempted_packet_paths"]) == audit["open_attempts"]
            if receipt["due_source"] is None:
                assert audit == dict(open_attempts=0, successful_opens=0, bytes_read=0, model_executions=0)
            if receipt["action"] in (0, 4, 5):
                assert receipt["cell_before"] == receipt["cell_after"]
                assert receipt["duration"] == 0 and receipt["charges"] == 0
        expected_bytes = result["initial_persistence_bytes"] + sum(
            x["checkpoint_bytes"]+x["journal_bytes"]+x["witness_bytes"] for x in result["receipts"])
        assert result["persistence_bytes"] == expected_bytes
        return result, snapshot

    @staticmethod
    def hashes(snapshot):
        return {suffix: digest(str(snapshot)+suffix) for suffix in ("", ".journal", ".witness")}

    @staticmethod
    def clone(snapshot, destination):
        destination.parent.mkdir(parents=True)
        for suffix in ("", ".journal", ".witness"):
            shutil.copyfile(str(snapshot)+suffix, str(destination)+suffix)
        return destination

    def execute(self):
        world, public = self.world("valid_delay_two")
        for family in FAMILIES:
            for controller in ("fixed", "value"):
                self.run(f"autonomous_{family}_{controller}", world, family, controller=controller)
            actions = ["READ", "WAIT", "READ", "SUBMIT_1"]
            full, _ = self.run(f"continuous_{family}", world, family, actions=actions)
            assert [r["actual_content_calls"] for r in full["receipts"]] == [0, 1, 0, 0]
            assert [r["read_audit"]["open_attempts"] for r in full["receipts"]] == [0, 1, 0, 0]
            assert full["after"]["task"]["history"][0]["source_tick"] == 0
            assert len(full["after"]["task"]["history"]) == 1
            assert full["after"]["task"]["pending"] is None
            expected_draws = 0 if family == "raw_history" else 3
            assert full["after"]["cell"]["draws"] == expected_draws
            first, snapshot = self.run(f"partial_{family}", world, family, actions=["READ"])
            assert first["after"]["task"]["pending"] == dict(source_tick=0, due_tick=2)
            assert first["after"]["task"]["history"] == []
            restored, _ = self.run(f"restored_{family}", world, family, actions=actions[1:],
                                   snapshot=snapshot, ack=first["acknowledged_sha256"])
            assert restored["external_ack_verified"]
            for key in ("task", "cell", "content", "ledger"):
                assert full["after"][key] == restored["after"][key], (family, key)
            if family == "raw_history":
                assert restored["after"]["cell"] == dict(index=7, rng_hex=f"{818:016x}", draws=0, events=0)
        for action in ("STOP", "SUBMIT_0", "SUBMIT_1"):
            result, _ = self.run(f"pending_cancel_{action}", world, actions=["READ", action])
            assert all(r["read_audit"]["open_attempts"] == 0 for r in result["receipts"])
            assert not result["after"]["task"]["history"]
            assert result["after"]["task"]["budget"] == 2
            assert result["after"]["task"]["charges"] > 0
        mutants = {
            "missing": lambda folder, p: (folder/p["packets"][0]).unlink(),
            "digest_mismatch": lambda folder, p: (folder/p["packets"][0]).write_bytes(b"mutated bytes"),
            "oversize": lambda folder, p: (folder/p["packets"][0]).write_bytes(b"x"*40000),
        }
        def invalid_schema(folder, p):
            path = folder/p["packets"][0]
            path.write_text('{"schema":"invalid","symbols":[1,-1],"dt":[1,1]}')
            p["packet_sha256"][0] = digest(path)
        mutants["invalid_schema"] = invalid_schema
        def symlink(folder, p):
            path = folder/p["packets"][0]
            path.rename(folder/"real-payload.json")
            path.symlink_to("real-payload.json")
        mutants["symlink"] = symlink
        for name, mutation in mutants.items():
            mutant, _ = self.world(name, mutation)
            result, _ = self.run(f"failed_{name}", mutant, actions=["READ", "WAIT", "REPAIR", "READ", "SUBMIT_0"])
            failure = result["receipts"][1]
            assert failure["completion"] == {"failure": True}
            assert failure["after"]["broken"] and failure["actual_content_calls"] == 0
            assert failure["after"]["budget"] == 2
            assert failure["after"]["charges"] > 0
            assert failure["read_audit"]["open_attempts"] == 1
            assert not result["receipts"][2]["after"]["broken"]
            assert result["receipts"][3]["actual_content_calls"] == 1
            # Before the first due completion, both decisions are content independent.
            baseline, _ = self.run(f"counterfactual_valid_{name}", world, actions=["READ", "WAIT"])
            for a, b in zip(result["receipts"][:2], baseline["receipts"]):
                assert a["q"] == b["q"] and a["belief"] == b["belief"]
                assert a["public_features"] == b["public_features"]
                assert a["representation_features"] == b["representation_features"]
        first, snapshot = self.run("ack_seed", world, actions=["READ"])
        ack = first["acknowledged_sha256"]
        original_hashes = self.hashes(snapshot)
        self.run("no_ack", world, snapshot=snapshot, actions=["WAIT"], success=False)
        self.run("wrong_ack", world, snapshot=snapshot, ack="0"*64, actions=["WAIT"], success=False)
        self.run("illegal_pending_read", world, snapshot=snapshot, ack=ack, actions=["READ"], success=False)
        self.run("unknown_action", world, snapshot=snapshot, ack=ack, actions=["UNKNOWN"], success=False)
        assert self.hashes(snapshot) == original_hashes
        invalid_new = self.out/"illegal-new.json"
        self.run("illegal_genesis_repair", world, snapshot=invalid_new, actions=["REPAIR"], success=False)
        assert not invalid_new.exists() and not Path(str(invalid_new)+".journal").exists()
        pending = self.clone(snapshot, self.out/"incomplete"/"owner.json")
        Path(str(pending)+".pending").write_text("interrupted atomic write")
        self.run("incomplete_commit", world, snapshot=pending, ack=ack, actions=["WAIT"], success=False)
        rollback = self.clone(snapshot, self.out/"rollback"/"owner.json")
        self.run("advance_rollback", world, snapshot=rollback, ack=ack, actions=["WAIT"])
        shutil.copyfile(snapshot, rollback)
        self.run("stale_snapshot_frontier", world, snapshot=rollback, ack=ack, actions=["WAIT"], success=False)
        altered = json.loads(json.dumps(self.artifacts["first_passage_bank"]))
        altered["network"]["b2"][0] += 1e-6
        altered_path = self.out/"altered-policy.json"
        save(altered_path, altered)
        self.run("weight_identity_mismatch", world, snapshot=snapshot, ack=ack, actions=["WAIT"],
                 policy=altered_path, success=False)
        self.run("seed_identity_mismatch", world, snapshot=snapshot, ack=ack, actions=["WAIT"],
                 seed=819, success=False)
        assert self.hashes(snapshot) == original_hashes
        result = dict(schema="digital-read-before-native-qualification-v1", passed=True,
                      scope="untrained development only; all forced control excluded from confirmation",
                      fit_ids=sorted({a["fit"] for a in self.artifacts.values()}),
                      calls=self.calls, families=list(FAMILIES), source_digest=self.source_digest,
                      maximum_python_score_error=self.maximum_score_error,
                      checks=["all five families and both controllers execute actual native runtime",
                              "same exported NumPy scores, task transition and SplitMix64 hard successor",
                              "delay two completes only at due boundary; pre-completion decisions content independent",
                              "terminal actions cancel pending without read or RNG/time advance; sunk fees remain",
                              "missing, mutated, oversize, invalid-schema, symlink inputs fail charged; explicit repair",
                              "restart restores pending, cell, RNG, history, content receipt, elapsed and charges",
                              "missing/forged ACK, incomplete commit, stale frontier, changed weights/seed rejected",
                              "unknown/illegal forced actions publish no changed snapshot",
                              "reported persistent payload bytes equal actual checkpoint/journal/witness accounting"],
                      runs=self.rows)
        save(self.args.receipt, result)
        print(json.dumps({k: v for k, v in result.items() if k != "runs"}, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--content-model", type=Path, required=True)
    p.add_argument("--policies", type=Path, required=True)
    p.add_argument("--public", type=Path, required=True)
    p.add_argument("--work-dir", type=Path, required=True)
    p.add_argument("--receipt", type=Path, default=HERE/"evidence/NATIVE_QUALIFICATION.json")
    Audit(p.parse_args()).execute()
