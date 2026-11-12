"""Local journal controls; no new business task, evaluator or trust key."""

from dataclasses import asdict, replace
import json
import os
import queue
import secrets
import sqlite3
import subprocess
import sys
import threading
import unittest
from unittest import mock

from . import test_treatment as fixtures
from .checker_effects import CheckerSpec
from .check_opportunities import CheckOpportunityJournal
from .contracts import canonical_json, digest
from .prospective import FrozenAttempt, ShadowJournal
from .shadow_risk import Target
from .treatment import TreatmentJournal


class OpportunityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.TreatmentTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.source = self.fixture.journal
        with self.source.shadow._transaction() as connection:
            manifest = self.source.shadow._read(connection)[0]
        self.other_configuration = {
            key: value for key, value in manifest.items() if key != "schema"
        }
        self.other_configuration.update(
            target=Target(**manifest["target"]),
            roster=tuple(FrozenAttempt(**row) for row in manifest["roster"]),
            scheduler_sha256=digest("other-policy"),
        )
        self.other = self.other_journal("other", self.fixture.checkers)
        self.configuration = dict(
            policies={
                "source": self.source.shadow.manifest_sha256,
                "other": self.other.shadow.manifest_sha256,
            },
            frontier=0,
            checker_id="readback",
            offer_numerator=1,
            offer_denominator=2,
            free_view_schema_sha256=digest("all-free-acks"),
            mandatory_contract_sha256=digest("original-gates"),
            evaluation_spec_sha256=digest("frozen-analysis"),
        )
        self.opportunities = CheckOpportunityJournal.create(
            self.source, **self.configuration
        )
        self.free_sha = digest("original-free-evidence")

    def other_journal(self, name, checkers):
        shadow = ShadowJournal.create(
            self.fixture.path.with_name(name + ".sqlite"), **self.other_configuration
        )
        return TreatmentJournal.create(shadow, checkers)

    def reserve(self, draw=0, **changes):
        self.source.shadow.record(self.fixture.predictions[0])
        args = dict(eligible=True, eligibility_evidence_sha256=digest("eligible"))
        args.update(changes)
        with mock.patch("secrets.randbelow", return_value=draw) as random:
            ticket = self.opportunities.reserve("0", self.free_sha, **args)
            self.assertEqual(random.call_count, int(args["eligible"]))
        return ticket

    def choose(self, treatment):
        return treatment.choose(
            self.fixture.predictions[0],
            self.fixture.effects,
            (),
            ("accept", "reject"),
            ((0, 100), (5, 5)),
            1,
            hard_checks_complete=True,
        )

    def test_real_draw_freezes_once_and_recovery_keeps_missing_denominator(self):
        self.source.shadow.record(self.fixture.predictions[0])
        with mock.patch("secrets.randbelow", wraps=secrets.randbelow) as random:
            ticket = self.opportunities.reserve(
                "0",
                self.free_sha,
                eligible=True,
                eligibility_evidence_sha256=digest("original-eligibility"),
            )
            self.assertEqual(random.call_count, 1)
            with self.assertRaisesRegex(ValueError, "already attempted"):
                self.opportunities.reserve(
                    "0",
                    self.free_sha,
                    eligible=True,
                    eligibility_evidence_sha256=digest("original-eligibility"),
                )
            self.assertEqual(random.call_count, 1)
        report = self.opportunities.report()
        recovered = CheckOpportunityJournal(
            TreatmentJournal(ShadowJournal(self.fixture.path)),
            expected_manifest_sha256=report["manifest_sha256"],
            expected_ledger_sha256=report["ledger_sha256"],
        )
        self.assertEqual(recovered.report(), report)
        self.assertEqual(
            (ticket["offered"], report["missing_opportunity_ids"]),
            (ticket["draw"] == 0, ["1", "2", "3"]),
        )

    def test_entropy_exception_retains_unknown_intent_and_forbids_redraw(self):
        self.source.shadow.record(self.fixture.predictions[0])
        with mock.patch(
            "secrets.randbelow", side_effect=OSError("entropy unavailable")
        ):
            with self.assertRaises(OSError):
                self.opportunities.reserve(
                    "0",
                    self.free_sha,
                    eligible=True,
                    eligibility_evidence_sha256=digest("eligible"),
                )
        report = self.opportunities.report()
        self.assertEqual(
            (
                report["tickets"],
                report["pending_opportunity_ids"],
                report["unstarted_opportunity_ids"],
            ),
            ({}, ["0"], ["1", "2", "3"]),
        )
        recovered = CheckOpportunityJournal(
            self.source, expected_ledger_sha256=report["ledger_sha256"]
        )
        with mock.patch("secrets.randbelow", wraps=secrets.randbelow) as random:
            with self.assertRaisesRegex(ValueError, "never redraw"):
                recovered.reserve(
                    "0",
                    self.free_sha,
                    eligible=True,
                    eligibility_evidence_sha256=digest("eligible"),
                )
            self.assertEqual(random.call_count, 0)

    def test_actual_process_death_after_real_draw_cannot_reroll(self):
        self.source.shadow.record(self.fixture.predictions[0])
        script = """
import json, secrets, sys
from experiments.verification_cell_verify1.check_opportunities import CheckOpportunityJournal
from experiments.verification_cell_verify1.prospective import ShadowJournal
from experiments.verification_cell_verify1.treatment import TreatmentJournal
original_draw = secrets.randbelow
def stop_after_real_draw(bound):
    value = original_draw(bound)
    print(json.dumps({'stage': 'actual_entropy_draw_before_commit', 'draw': value}), flush=True)
    sys.stdin.buffer.read(1)
    return value
secrets.randbelow = stop_after_real_draw
journal = CheckOpportunityJournal(TreatmentJournal(ShadowJournal(sys.argv[1])))
journal.reserve('0', sys.argv[2], eligible=True, eligibility_evidence_sha256=sys.argv[3])
"""
        process = subprocess.Popen(
            [
                sys.executable,
                "-B",
                "-c",
                script,
                str(self.fixture.path),
                self.free_sha,
                digest("eligible"),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        ready = queue.Queue()
        reader = threading.Thread(
            target=lambda: ready.put(process.stdout.readline()), daemon=True
        )
        reader.start()
        try:
            marker = json.loads(ready.get(timeout=10))
            self.assertEqual(marker["stage"], "actual_entropy_draw_before_commit")
            self.assertIn(marker["draw"], (0, 1))
            process.kill()
            returncode = process.wait(timeout=10)
            self.assertNotEqual(returncode, 0)
            print(
                "ACTUAL_DRAW_PROCESS_DEATH",
                json.dumps(dict(marker, returncode=returncode)),
            )
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
            reader.join(timeout=10)
        recovered = CheckOpportunityJournal(
            TreatmentJournal(ShadowJournal(self.fixture.path))
        )
        report = recovered.report()
        self.assertEqual(
            (
                report["tickets"],
                report["pending_opportunity_ids"],
                report["pending_draw_status"],
            ),
            ({}, ["0"], "UNKNOWN"),
        )
        self.assertEqual(report["missing_opportunity_ids"], ["0", "1", "2", "3"])
        with mock.patch("secrets.randbelow", wraps=secrets.randbelow) as random:
            with self.assertRaisesRegex(ValueError, "never redraw"):
                recovered.reserve(
                    "0",
                    self.free_sha,
                    eligible=True,
                    eligibility_evidence_sha256=digest("eligible"),
                )
            self.assertEqual(random.call_count, 0)

    def test_shared_free_consumption_runs_original_pending_and_unknown_path(self):
        ticket = self.reserve()
        self.other.shadow.record(self.fixture.predictions[0])
        self.opportunities.bind_policy(
            self.other, "0", free_evidence_sha256=self.free_sha
        )
        choice = self.choose(self.other)
        self.opportunities.start_optional(
            self.other, choice["record_sha256"], "original-read"
        )
        with self.assertRaises(ValueError):
            self.opportunities.start_optional(
                self.other, choice["record_sha256"], "retry"
            )
        with self.assertRaises(ValueError):
            self.other.record_disposition(
                "0",
                "accept",
                hard_checks_complete=True,
                gate_evidence_sha256=digest("gate"),
            )
        self.other.complete(
            "original-read",
            "unknown",
            digest("original-timeout"),
            dict(wall_seconds=0.1, cpu_seconds=None, energy_joules=None),
        )
        audit = self.opportunities.audit_treatment(self.other)
        self.assertEqual(audit["consumed_trajectory_ids"], ["0"])
        self.assertEqual(
            ticket["free_snapshot_sha256"],
            digest(asdict(self.fixture.predictions[0].snapshot)),
        )

    def test_unoffered_optional_check_refuses_and_cannot_replace_mandatory_gate(self):
        self.reserve(draw=1)
        choice = self.choose(self.source)
        with self.assertRaisesRegex(ValueError, "unavailable"):
            self.opportunities.start_optional(
                self.source, choice["record_sha256"], "forbidden-read"
            )
        with self.assertRaises(ValueError):
            self.source.record_disposition(
                "0",
                "accept",
                hard_checks_complete=False,
                gate_evidence_sha256=digest("gate"),
            )
        self.source.record_disposition(
            "0",
            "accept",
            hard_checks_complete=True,
            gate_evidence_sha256=digest("gate"),
        )
        self.opportunities.audit_treatment(self.source)

    def test_original_start_bypass_is_visible_to_audit(self):
        self.reserve(draw=1)
        choice = self.choose(self.source)
        self.source.start(choice["record_sha256"], "bypassed-opportunity")
        with self.assertRaisesRegex(ValueError, "unoffered"):
            self.opportunities.audit_treatment(self.source)

    def test_late_binding_and_choice_without_binding_refuse(self):
        self.reserve()
        self.other.shadow.record(self.fixture.predictions[0])
        self.choose(self.other)
        with self.assertRaisesRegex(ValueError, "precede"):
            self.opportunities.bind_policy(
                self.other, "0", free_evidence_sha256=self.free_sha
            )
        with self.assertRaisesRegex(ValueError, "did not consume"):
            self.opportunities.audit_treatment(self.other)

    def test_changed_free_snapshot_and_original_evidence_are_not_shared_controls(self):
        self.reserve()
        self.other.shadow.record(self.fixture.predictions[0])
        with self.assertRaisesRegex(ValueError, "identical free view"):
            self.opportunities.bind_policy(
                self.other, "0", free_evidence_sha256=digest("paid-observation")
            )
        altered = self.other_journal("paid-view", self.fixture.checkers)
        altered.shadow.record(
            replace(
                self.fixture.predictions[0],
                snapshot=replace(self.fixture.predictions[0].snapshot, features=(0,)),
            )
        )
        with self.assertRaisesRegex(ValueError, "identical free view"):
            self.opportunities.bind_policy(
                altered, "0", free_evidence_sha256=self.free_sha
            )

    def test_same_checker_name_different_version_cannot_consume_or_start(self):
        self.reserve()
        changed = self.other_journal(
            "other-checker",
            (CheckerSpec("readback", digest("different-checker"), 0.1),),
        )
        changed.shadow.record(self.fixture.predictions[0])
        self.assertEqual(
            changed.shadow.manifest_sha256, self.other.shadow.manifest_sha256
        )
        with self.assertRaisesRegex(ValueError, "checker version"):
            self.opportunities.bind_policy(
                changed, "0", free_evidence_sha256=self.free_sha
            )
        with self.assertRaisesRegex(ValueError, "checker version"):
            self.opportunities.audit_treatment(changed)

    def test_reserve_after_choice_and_wrong_frontier_refuse(self):
        self.source.shadow.record(self.fixture.predictions[0])
        self.choose(self.source)
        with self.assertRaisesRegex(ValueError, "precede"):
            self.opportunities.reserve(
                "0",
                self.free_sha,
                eligible=True,
                eligibility_evidence_sha256=digest("eligible"),
            )
        self.source.shadow.record(
            replace(
                self.fixture.predictions[1],
                snapshot=replace(self.fixture.predictions[1].snapshot, observed_step=2),
            )
        )
        with self.assertRaisesRegex(ValueError, "planned frontier"):
            self.opportunities.reserve(
                "1",
                self.free_sha,
                eligible=True,
                eligibility_evidence_sha256=digest("eligible"),
            )

    def test_ineligible_is_explicit_and_never_drawn(self):
        ticket = self.reserve(
            eligible=False, ineligible_reason="original host denies optional read"
        )
        self.assertEqual(
            (ticket["offered"], ticket["draw"], ticket["offer_propensity"]),
            (False, None, {"numerator": 0, "denominator": 1}),
        )
        self.assertEqual(self.opportunities.report()["tickets"]["0"], ticket)

    def test_rehashed_reroll_refuses_external_original_root(self):
        self.reserve()
        before = self.opportunities.report()
        with self.source.shadow._transaction() as connection:
            body = json.loads(
                connection.execute("SELECT body FROM opportunity_tickets").fetchone()[0]
            )
            body.update(draw=1, offered=False)
            connection.execute(
                "UPDATE opportunity_tickets SET body=?, sha=?",
                (canonical_json(body), digest(body)),
            )
        with self.assertRaisesRegex(ValueError, "opportunity ledger changed"):
            CheckOpportunityJournal(
                self.source,
                expected_manifest_sha256=before["manifest_sha256"],
                expected_ledger_sha256=before["ledger_sha256"],
            )
        with self.assertRaisesRegex(ValueError, "consumption"):
            self.opportunities.audit_treatment(self.source)

    def test_create_and_rebind_are_never_implicit_recovery(self):
        self.reserve()
        with self.assertRaises(ValueError):
            CheckOpportunityJournal.create(self.source, **self.configuration)
        with self.assertRaises(sqlite3.IntegrityError):
            self.opportunities.bind_policy(
                self.source, "0", free_evidence_sha256=self.free_sha
            )

    def test_physical_journal_alias_refuses_before_nested_lock(self):
        alias = self.fixture.path.with_name("source-hardlink.sqlite")
        os.link(self.fixture.path, alias)
        aliased = TreatmentJournal(ShadowJournal(alias))
        with self.assertRaisesRegex(ValueError, "same physical journal"):
            self.opportunities.audit_treatment(aliased)


if __name__ == "__main__":
    unittest.main()
