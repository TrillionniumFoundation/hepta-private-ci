"""Engineering fixture with synthetic people and real persisted GPT-2 weights."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

from . import coding_sft, data, paired_consumer as owner, paired_freeze, paired_intake, paired_observation
from .test_paired_cold import fixture

ROOT = Path(__file__).resolve().parents[1]
NATIVE = """#!/usr/bin/python3
import json,sys
request=json.load(sys.stdin)
if sys.argv[1:] == ['--print-statement']:
    sys.stdout.write('Fixture statement '+json.dumps(request,sort_keys=True,separators=(',',':')))
else:
    case=json.load(open(sys.argv[3]))
    if request != case['request']: sys.exit(8)
    print(json.dumps(case['receipt']))
"""


def put(path, value):
    path.write_bytes(data.canonical(value))
    path.chmod(0o600)


class ScopeTests(unittest.TestCase):
    def test_changes_to_operation_pair_task_candidate_or_output_bind_different_statements(self):
        d = data.digest
        release = dict(request_sha256=d("pair"), candidate_sha256=d("child"))
        scope = owner.request_scope(d("A and B"), release, d("later task"), d("cold selection"))
        for admission, pair, model, task in [
            ("C and D", "pair", "child", "later task"),
            ("A and B", "other pair", "child", "later task"),
            ("A and B", "pair", "parent", "later task"),
            ("A and B", "pair", "child", "initial B task"),
        ]:
            other = owner.request_scope(d(admission), dict(request_sha256=d(pair), candidate_sha256=d(model)), d(task), d("cold selection"))
            self.assertNotEqual(other["operation"], scope["operation"])
        a = owner.outcome_scope(scope, {"output_sha256": d("x")}, d("business material"), "accepted")
        b = owner.outcome_scope(scope, {"output_sha256": d("y")}, d("business material"), "rejected")
        self.assertNotEqual(a["run_receipt"], b["run_receipt"])
        with self.assertRaises(ValueError):
            owner.outcome_scope(scope, {"output_sha256": d("x")}, d("material"), "unknown")

    def test_unfinished_one_use_operation_cannot_generate_again(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            put(path / "STARTED.json", {"engineering": True})
            with self.assertRaisesRegex(ValueError, "prior execution uncertain"):
                owner.execute(path, {}, {}, {}, "", {}, path)


NUMERICAL = all(importlib.util.find_spec(lib) for lib in ("torch", "transformers", "peft", "tokenizers"))


@unittest.skipUnless(sys.platform == "linux" and NUMERICAL, "Linux pinned coding_sft CPU profile required")
class LocalUseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.models = self.root / "materials"
        req = fixture(self.models)
        self.home, self.inbox = self.root / "intake", self.root / "site"
        self.inbox.mkdir(mode=0o700)
        self.exe = self.root / "simulated-native"
        self.exe.write_text(NATIVE)
        self.exe.chmod(0o700)
        self.route = self.root / "fixture-route.json"
        self.study = data.digest("fictional subsequent consumer study")
        self.b = data.digest("fixture principal for B")
        self.evaluate_delivery = data.digest("fixture original evaluation delivery")
        self.snapshot = self.root / "FROZEN.json"
        snapshot = {"schema": paired_freeze.FREEZE_SCHEMA, **{k: req[k] for k in paired_freeze.FIELDS}}
        put(self.snapshot, snapshot)
        freeze = data.digest(snapshot)
        paired_observation.observe(self.inbox, self.study, freeze, 10)
        paired_intake.install(SimpleNamespace(home=self.home, study=self.study, freeze=freeze,
                              scope="engineering_fixture", snapshot=self.snapshot, inbox=self.inbox,
                              native=self.exe, native_sha256=coding_sft.file_hash(self.exe)))
        future = req["future"][0]
        future.update(origin_kind="authorized_agent_run", exposure="unexposed", trajectory=[])
        future["authorization"]["rights_basis"] = "synthetic engineering only"
        task = data.digest(future)
        origin = data.digest("fixture arrival 11")
        paired_observation.observe(self.inbox, self.study, freeze, 11, arrival=origin, record=task,
                                   delivery=self.evaluate_delivery, principal=self.b)
        base = dict(study_sha256=self.study, delivery_id=self.evaluate_delivery)
        scope = dict(use="evaluate_only", freeze=freeze, task=task)
        statement = (f"Hepta paired learning consent v1\nStudy SHA-256: {self.study}\n"
                     "I authorize Hepta to evaluate the frozen pair on this task. Training on this task is prohibited.\n"
                     f"Pair freeze SHA-256: {freeze}\nTask SHA-256: {task}")
        put(self.route, dict(request=dict(base, scope=scope),
                             receipt=dict(base, schema="hepta.paired-learning.consent-readback.v1", use=scope["use"],
                                          consent_text_sha256=paired_intake.sha(statement.encode()), study_principal_sha256=self.b)))
        received = self.root / "future.json"
        put(received, [future])
        r = self.call("paired_intake", self.home, "admit", origin, self.snapshot, self.models,
                      received, "fixture-pid", "unused", self.route)
        self.admission = r.stdout.strip()
        paired_intake.release(self.home, self.admission)
        self.local("select")

    def call(self, module, *args, good=True):
        # Empty fixture descriptors exercise transport shape only; no actual human or Root event.
        cmd = ["/bin/sh", "-c", 'exec 3</dev/null 4</dev/null; exec "$@"', "fixture",
               sys.executable, "-m", "cell_experiments." + module, *map(str, args)]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=250,
                           env={**os.environ, "PYTHONPATH": str(ROOT), "HF_HUB_OFFLINE": "1"})
        if good:
            self.assertEqual(0, p.returncode, p.stderr)
        else:
            self.assertNotEqual(0, p.returncode)
        return p

    def local(self, *args, good=True):
        r = self.call("paired_consumer", self.home, self.admission, self.models, *args, good=good)
        return json.loads(r.stdout) if good else r.stderr

    def event(self, input_, delivery, principal=None):
        p = subprocess.run([self.exe, "--print-statement"], input=data.canonical(input_), capture_output=True, check=True)
        receipt = dict(schema="hepta.paired-learning.consumer-statement-readback.v1", study_sha256=self.study,
                       delivery_id=delivery, use=input_["scope"]["use"], statement_sha256=hashlib.sha256(p.stdout).hexdigest(),
                       study_principal_sha256=principal or self.b)
        put(self.route, dict(request=dict(input_, delivery_id=delivery), receipt=receipt))

    def test_real_later_output_signed_decisions_and_independent_readback(self):
        launch = ("fixture-pid", "unused", self.route)
        for decision, prompt in (("accepted", "train later"), ("rejected", "later later")):
            with self.subTest(decision=decision):
                task = {"input": prompt}
                td = data.digest(task)
                want = self.local("request-scope", td)
                request_id = data.digest([decision, "request"])
                self.event(want, request_id, data.digest("different fictional participant"))
                # No subsequent private task file exists while rejecting a different participant.
                self.assertIn("original B", self.local("run", td, request_id, *launch, good=False))
                put(self.inbox / f"consumer-task-{td}.json", task)
                self.event(want, request_id)
                r = self.local("run", td, request_id, *launch)
                self.assertEqual(r, self.local("run", td, request_id, *launch))
                self.assertEqual(r["run_receipt"], self.local("verify-request", td, *launch)["run_receipt"])
                path = self.home / self.admission / "consumer" / r["operation"]
                answer = (path / "answer.utf8").read_bytes()
                self.assertEqual(answer, b"1")
                self.assertEqual(r["output"], paired_intake.sha(answer))
                raw = json.loads((path / "worker-output.json").read_bytes())
                run = json.loads((path / "RUN.json").read_bytes())
                self.assertEqual(raw["prediction"]["pid"], run["local_child_pid"])
                self.assertEqual(raw["prediction"]["loaded_model_digest"], want["scope"]["candidate"])
                material = ("simulated downstream decision " + decision).encode()
                effect = paired_intake.sha(material)
                (self.inbox / f"consumer-effect-{effect}.bin").write_bytes(material)
                summary = self.local("outcome-scope", td, effect, decision)
                delivery = data.digest([decision, "report"])
                self.event(summary, delivery)
                receipt = self.local("report", td, effect, decision, delivery, *launch)
                self.assertEqual(receipt, self.local("verify", td, *launch))
                self.assertEqual(receipt["scope"]["outcome"], decision)
                self.assertEqual(receipt["evidence_scope"], "engineering_fixture")
                self.assertFalse(receipt["payment_authorized"])
                self.assertFalse(receipt["independently_verified_business_effect"])
                (path / "answer.utf8").write_bytes(b"altered")
                self.assertIn("delivered bytes differ", self.local("verify", td, *launch, good=False))
                (path / "answer.utf8").write_bytes(answer)
                (self.inbox / f"consumer-effect-{effect}.bin").write_bytes(b"other")
                self.assertIn("outcome material differs", self.local("verify", td, *launch, good=False))
        repeat = {"input": "later"}
        td = data.digest(repeat)
        put(self.inbox / f"consumer-task-{td}.json", repeat)
        want = self.local("request-scope", td)
        delivery = data.digest("fixture repeat")
        self.event(want, delivery)
        self.assertIn("known prompt or effective input", self.local("run", td, delivery, *launch, good=False))
        # A model-file replacement must be rejected even when the old decision survived.
        (self.models / "candidate-checkpoint/model.safetensors").write_bytes(
            (self.models / "parent-checkpoint/model.safetensors").read_bytes())
        self.assertIn("model artifact identity mismatch", self.local("select", good=False))


if __name__ == "__main__":
    unittest.main()
