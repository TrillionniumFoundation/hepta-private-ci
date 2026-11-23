"""Synthetic source-owner and native transport fixtures, with real SQLite and OS leases."""

import concurrent.futures
import contextlib
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

from . import data, paired_intake as intake, paired_observation, paired_people
from .test_prospective_exposure import FREEZE, SNAPSHOT, artificial

STUDY = data.digest("fictional private study")
PRINCIPAL = data.digest("fictional principal")
SOURCE = Path(__file__).resolve().parents[1]


def shell_cli(args, *, handles=False):
    cmd = [sys.executable, "-m", "cell_experiments.paired_intake", *map(str, args)]
    if handles:
        cmd = [
            "/bin/sh",
            "-c",
            'exec 3</dev/null 4</dev/null; exec "$@"',
            "fixture",
            *cmd,
        ]
    return subprocess.run(
        cmd,
        env={**os.environ, "PYTHONPATH": str(SOURCE), "HF_HUB_OFFLINE": "1"},
        text=True,
        capture_output=True,
        timeout=90,
    )


@unittest.skipUnless(sys.platform == "linux", "requires Linux private issuer transport")
class IntakeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / "journal"
        self.inbox = self.root / "owner"
        self.inbox.mkdir(mode=0o700)
        self.native = self.root / "fixture-native"
        # This executable replies only with the fixture the simulated owner provided.
        self.native.write_text(
            "#!/usr/bin/python3\nimport json,sys\n"
            "case=json.load(open(sys.argv[3]))\n"
            'if json.load(sys.stdin)!=case["expected"]: sys.exit(1)\n'
            'print(json.dumps(case["native_reply"]))\n'
        )
        self.native.chmod(0o700)
        self.anchor = dict(
            schema="hepta.paired-intake.freeze-observation.v1",
            sequence=8,
            study_sha256=STUDY,
            freeze_sha256=FREEZE,
        )
        self.put(self.inbox / "freeze.json", self.anchor)
        self.install_options = SimpleNamespace(
            home=self.home,
            scope="engineering_fixture",
            snapshot=SNAPSHOT,
            study=STUDY,
            freeze=FREEZE,
            inbox=self.inbox,
            native=self.native,
            native_sha256=hashlib.sha256(self.native.read_bytes()).hexdigest(),
        )
        intake.install(self.install_options)
        self.record = artificial(13137)

    @staticmethod
    def put(path, item):
        path.write_bytes(data.canonical(item))
        path.chmod(0o600)

    def event(self, record, seq=9):
        row_hash = data.record_digest(record)
        delivery = data.digest(["mock-consent", seq])
        arrival = data.digest(["mock-arrival", seq])
        event = dict(
            schema="hepta.paired-intake.first-observation.v1",
            study_sha256=STUDY,
            freeze_sha256=FREEZE,
            sequence=seq,
            arrival_id=arrival,
            record_sha256=row_hash,
            consent_delivery_id=delivery,
            study_principal_sha256=PRINCIPAL,
        )
        text = (
            f"Hepta paired learning consent v1\nStudy SHA-256: {STUDY}\n"
            f"I authorize Hepta to evaluate the frozen pair on this task. Training on this task is prohibited.\n"
            f"Pair freeze SHA-256: {FREEZE}\nTask SHA-256: {row_hash}"
        )
        expected = dict(
            study_sha256=STUDY,
            delivery_id=delivery,
            scope=dict(use="evaluate_only", freeze=FREEZE, task=row_hash),
        )
        reply = dict(
            schema="hepta.paired-learning.consent-readback.v1",
            study_sha256=STUDY,
            delivery_id=delivery,
            use="evaluate_only",
            consent_text_sha256=intake.sha(text.encode()),
            study_principal_sha256=PRINCIPAL,
        )
        route = self.root / f"mock-route-{seq}.json"
        self.put(route, dict(expected=expected, native_reply=reply))
        self.put(self.inbox / (arrival + ".json"), event)
        task = self.root / f"fixture-{seq}.json"
        self.put(task, [record])
        return event, [
            self.home,
            "admit",
            arrival,
            SNAPSHOT,
            SNAPSHOT.parent,
            task,
            "1",
            "unused",
            route,
        ]

    def count(self):
        with contextlib.closing(intake.open_database(self.home)) as db:
            return db.execute("SELECT count(*) FROM admissions").fetchone()[0]

    def test_untrusted_source_directory_and_changed_anchor_rejected(self):
        _, cmd = self.event(self.record)
        self.inbox.chmod(0o770)
        self.assertIn("permits other writers", shell_cli(cmd, handles=True).stderr)
        self.inbox.chmod(0o700)
        self.put(self.inbox / "freeze.json", {**self.anchor, "sequence": 4})
        self.assertIn("freeze observation changed", shell_cli(cmd, handles=True).stderr)
        self.assertEqual(self.count(), 0)

    def test_wrong_order_and_wrong_owner_fail_before_private_data_read(self):
        event, cmd = self.event(self.record, seq=7)
        cmd[5] = self.root / "unread-private-record"
        self.assertIn("not witnessed after freeze", shell_cli(cmd, handles=True).stderr)
        self.put(
            self.inbox / (event["arrival_id"] + ".json"),
            {
                **event,
                "sequence": 9,
                "study_principal_sha256": data.digest("someone else"),
            },
        )
        self.assertIn(
            "principal or signed statement", shell_cli(cmd, handles=True).stderr
        )
        self.assertEqual(self.count(), 0)

    def test_owner_stream_emits_write_once_events_and_rejects_wrong_order(self):
        folder = self.root / "other-owner"
        folder.mkdir(mode=0o700)
        pin = paired_observation.observe(folder, STUDY, FREEZE, 8)
        self.assertEqual(pin, data.digest(self.anchor))
        self.assertEqual(pin, paired_observation.observe(folder, STUDY, FREEZE, 8))
        with self.assertRaisesRegex(ValueError, "different contents"):
            paired_observation.observe(folder, STUDY, FREEZE, 9)
        event, _ = self.event(self.record)
        args = dict(
            arrival=event["arrival_id"],
            record=event["record_sha256"],
            delivery=event["consent_delivery_id"],
            principal=PRINCIPAL,
        )
        with self.assertRaisesRegex(ValueError, "follow"):
            paired_observation.observe(folder, STUDY, FREEZE, 7, **args)
        self.assertEqual(
            paired_observation.observe(folder, STUDY, FREEZE, 9, **args),
            data.digest(event),
        )

    def test_native_binary_pin_and_inherited_handles(self):
        _, cmd = self.event(self.record)
        self.assertNotEqual(shell_cli(cmd).returncode, 0)
        self.native.write_text(self.native.read_text() + "# modified\n")
        self.assertIn("native executable changed", shell_cli(cmd, handles=True).stderr)
        self.assertEqual(self.count(), 0)

    def test_source_directory_replacement_refused(self):
        _, cmd = self.event(self.record)
        moved = self.root / "original"
        os.rename(self.inbox, moved)
        shutil.copytree(moved, self.inbox)
        self.assertIn("owner or directory changed", shell_cli(cmd, handles=True).stderr)

    @unittest.skipUnless(
        importlib.util.find_spec("transformers"), "requires the frozen tokenizer"
    )
    def test_real_assembly_dedup_parallel_reopen_and_process_death(self):
        _, cmd = self.event(self.record)
        first = shell_cli(cmd, handles=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        admission = first.stdout.strip()
        again = shell_cli(cmd, handles=True)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(again.stdout.strip(), admission)
        clone = copy.deepcopy(self.record)
        clone["record_id"] += "-renumbered"
        clone["task_id"] += "-renumbered"
        _, duplicate = self.event(clone, seq=10)
        self.assertIn("UNIQUE constraint", shell_cli(duplicate, handles=True).stderr)
        self.assertEqual(self.count(), 1)
        # Exit the real process after directory publication and before SQLite completion.
        script = """
import os,sys
from pathlib import Path
from cell_experiments import paired_intake as lib
rename = os.rename
def crash_after_publish(src,dst):
    rename(src,dst)
    os._exit(19)
lib.os.rename=crash_after_publish
lib.release(Path(sys.argv[1]),sys.argv[2])
"""
        stopped = subprocess.run(
            [sys.executable, "-c", script, str(self.home), admission],
            env={**os.environ, "PYTHONPATH": str(SOURCE)},
        )
        self.assertEqual(stopped.returncode, 19)
        with contextlib.closing(intake.open_database(self.home)) as db:
            self.assertEqual(
                db.execute("SELECT state FROM admissions").fetchone(), ("publishing",)
            )
        result_path = self.home / admission / "release.json"
        inode = result_path.stat().st_ino
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            jobs = list(
                pool.map(
                    lambda _: shell_cli([self.home, "release", admission]), range(3)
                )
            )
        self.assertTrue(all(j.returncode == 0 for j in jobs))
        self.assertEqual(len({j.stdout for j in jobs}), 1)
        self.assertEqual(result_path.stat().st_ino, inode)
        receipt = json.loads(jobs[0].stdout)
        delivered = json.loads((self.home / admission / "paired.json").read_bytes())
        self.assertEqual(data.digest(delivered), receipt["request_sha256"])
        self.assertEqual(delivered["future"], [self.record])
        self.assertEqual(receipt["scope"], "engineering_fixture")
        status = intake.people_status(self.home, admission)
        self.assertFalse(status["site_attested_distinct_people"])
        self.assertFalse(status["original_enrollment_bindings_checked"])
        with contextlib.closing(intake.open_database(self.home)) as db:
            self.assertEqual(
                db.execute("SELECT state FROM admissions").fetchone(), ("released",)
            )
        shutil.rmtree(self.home / admission)
        with self.assertRaisesRegex(ValueError, "released request is missing"):
            intake.release(self.home, admission)

    def test_site_pair_requires_original_material_same_registry_and_both_grants(self):
        event, cli_args = self.event(self.record)
        b_owner = json.loads(Path(cli_args[-1]).read_bytes())["native_reply"]
        run = self.root / "training-run"
        run.mkdir()
        candidate = data.digest(json.loads(SNAPSHOT.read_bytes())["candidate"])
        request_sha = data.digest("mock exact request")
        fields = {
            k: data.digest(k)
            for k in (
                "failure_sha256",
                "correction_sha256",
                "source_plan_sha256",
                "parent_sha256",
            )
        }
        a_scope = (
            f"Hepta paired learning consent v1\nStudy SHA-256: {STUDY}\n"
            "I authorize Hepta to train the study candidate using only these records.\n"
            f"Failure SHA-256: {fields['failure_sha256']}\nCorrection SHA-256: {fields['correction_sha256']}"
        )
        a_owner = dict(
            schema="hepta.paired-learning.consent-readback.v1",
            study_sha256=STUDY,
            use="train",
            consent_text_sha256=intake.sha(a_scope.encode()),
            study_principal_sha256=data.digest("fictional A principal"),
            delivery_id=data.digest("fictional A consent"),
        )
        completion = dict(
            schema="hepta.paired-learning.source-completion.v1",
            scope="engineering_fixture",
            study_sha256=STUDY,
            freeze_sha256=FREEZE,
            candidate_sha256=candidate,
            owner_receipt_sha256=data.digest(a_owner),
            **fields,
        )
        self.put(run / "OWNER.json", a_owner)
        self.put(run / "COMPLETED.json", completion)
        common = dict(
            study_sha256=STUDY,
            freeze_sha256=FREEZE,
            authority_sha256=data.digest("fictional directory owner"),
        )
        a = dict(
            **common,
            schema="hepta.paired-intake.training-person.v1",
            sequence=8,
            consent_delivery_id=a_owner["delivery_id"],
            study_principal_sha256=a_owner["study_principal_sha256"],
            person_sha256=data.digest("fictional A person"),
            source_completion_sha256=data.digest(completion),
        )
        b = dict(
            **common,
            schema="hepta.paired-intake.evaluation-person.v1",
            sequence=10,
            consent_delivery_id=b_owner["delivery_id"],
            study_principal_sha256=b_owner["study_principal_sha256"],
            person_sha256=data.digest("fictional B person"),
            arrival_id=event["arrival_id"],
            record_sha256=event["record_sha256"],
            request_sha256=request_sha,
        )
        for item, body in (
            (a, b"fixture enrollment of A"),
            (b, b"fixture enrollment of B"),
        ):
            item["enrollment_receipt_sha256"] = intake.sha(body)
            (self.inbox / ("enrollment-" + intake.sha(body) + ".bin")).write_bytes(body)
        self.put(self.inbox / "training-person.json", a)
        b_path = self.inbox / ("person-" + event["arrival_id"] + ".json")
        self.put(b_path, b)
        with contextlib.closing(intake.open_database(self.home)) as db:
            config = json.loads(db.execute("SELECT value FROM settings").fetchone()[0])

        def check():
            return paired_people.check(
                config, event, b_owner, request_sha, candidate, run
            )

        self.assertEqual(check()["source_completion_sha256"], data.digest(completion))
        for change in (
            dict(person_sha256=a["person_sha256"]),
            dict(authority_sha256=data.digest("other authority")),
            dict(request_sha256=data.digest("another request")),
            dict(study_principal_sha256=a["study_principal_sha256"]),
        ):
            self.put(b_path, {**b, **change})
            with self.assertRaises(ValueError):
                check()
        self.put(b_path, b)
        (
            self.inbox / ("enrollment-" + b["enrollment_receipt_sha256"] + ".bin")
        ).write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "original enrollment material"):
            check()

    def test_training_readback_binds_failed_and_corrected_record(self):
        failure, correction, delivery = [
            data.digest(v) for v in ("failed", "corrected", "consent")
        ]
        text = (
            f"Hepta paired learning consent v1\nStudy SHA-256: {STUDY}\n"
            "I authorize Hepta to train the study candidate using only these records.\n"
            f"Failure SHA-256: {failure}\nCorrection SHA-256: {correction}"
        )
        scope = dict(use="train", failure=failure, correction=correction)
        req = dict(study_sha256=STUDY, delivery_id=delivery, scope=scope)
        reply = dict(
            schema="hepta.paired-learning.consent-readback.v1",
            study_sha256=STUDY,
            delivery_id=delivery,
            use="train",
            consent_text_sha256=intake.sha(text.encode()),
            study_principal_sha256=PRINCIPAL,
        )
        path = self.root / "training.json"
        self.put(path, dict(expected=req, native_reply=reply))
        script = """exec 3</dev/null 4</dev/null; exec "$@" """
        program = (
            "import sys,json; from cell_experiments.paired_intake import verify_live;"
            "native,sha,study,delivery,scope,route=sys.argv[1:];"
            "print(json.dumps(verify_live(native,sha,study,delivery,json.loads(scope),['1','unused',route])))"
        )
        run = subprocess.run(
            [
                "sh",
                "-c",
                script,
                "test",
                sys.executable,
                "-c",
                program,
                str(self.native),
                self.install_options.native_sha256,
                STUDY,
                delivery,
                json.dumps(scope),
                str(path),
            ],
            env={**os.environ, "PYTHONPATH": str(SOURCE)},
            text=True,
            capture_output=True,
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout), reply)
