"""Local opportunity controls; no independent business-task qualification."""

import secrets
import unittest
from unittest import mock

from . import test_treatment as fixtures
from .checker_effects import CheckerSpec
from .check_opportunities import CheckOpportunityJournal
from .contracts import digest
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


if __name__ == "__main__":
    unittest.main()
