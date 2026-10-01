from dataclasses import asdict, replace
import unittest

from control_engineering_v2.deployment_evidence import (
    BackupRecoveryReceipt,
    OperatorAcceptanceReceipt,
    RollbackRehearsalReceipt,
    TargetDeploymentReceipt,
    verify_production_acceptance_evidence,
)
from control_engineering_v2 import HmacTrustStore, semantic_digest


class DeploymentEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_000_000
        self.trust = HmacTrustStore(
            {
                ("target_deployment_observer", "deploy-key"): b"deploy",
                ("backup_recovery_observer", "recovery-key"): b"recover",
                ("rollback_rehearsal_observer", "rollback-key"): b"rollback",
                ("operator_acceptance_authority", "operator-key"): b"operator",
            }
        )

    def signed(self, value):
        return replace(
            value,
            signature=self.trust.sign(
                value, value.issuer, value.signing_identity
            ),
        )

    def evidence(self):
        snapshot = "d" * 64
        deployment = self.signed(
            TargetDeploymentReceipt(
                "target-a",
                "staging",
                "a" * 40,
                "b" * 40,
                "c" * 64,
                snapshot,
                True,
                "target_deployment_observer",
                "deploy-key",
                self.now,
                self.now + 1000,
            )
        )
        recovery = self.signed(
            BackupRecoveryReceipt(
                "target-a",
                "a" * 40,
                "b" * 40,
                "e" * 64,
                snapshot,
                snapshot,
                True,
                "backup_recovery_observer",
                "recovery-key",
                self.now,
                self.now + 1000,
            )
        )
        rollback = self.signed(
            RollbackRehearsalReceipt(
                "target-a",
                "a" * 40,
                "f" * 40,
                "1" * 40,
                snapshot,
                True,
                "rollback_rehearsal_observer",
                "rollback-key",
                self.now,
                self.now + 1000,
            )
        )
        operator = self.signed(
            OperatorAcceptanceReceipt(
                "target-a",
                "operator-a",
                semantic_digest(asdict(deployment)),
                semantic_digest(asdict(recovery)),
                semantic_digest(asdict(rollback)),
                True,
                "operator_acceptance_authority",
                "operator-key",
                self.now,
                self.now + 1000,
            )
        )
        return deployment, recovery, rollback, operator

    def test_complete_separated_evidence_verifies_without_release_authority(self):
        decision = verify_production_acceptance_evidence(
            *self.evidence(), self.trust, now_ns=self.now
        )
        self.assertTrue(decision.deployment_verified)
        self.assertTrue(decision.operator_acceptance_verified)
        self.assertFalse(decision.production_implementation)
        self.assertFalse(decision.release_authority)

    def test_identity_collision_rejects(self):
        deployment, recovery, rollback, operator = self.evidence()
        collision_trust = HmacTrustStore(
            {
                ("target_deployment_observer", "shared-key"): b"shared",
                ("backup_recovery_observer", "shared-key"): b"shared",
                ("rollback_rehearsal_observer", "rollback-key"): b"rollback",
                ("operator_acceptance_authority", "operator-key"): b"operator",
            }
        )
        deployment = replace(
            deployment, signing_identity="shared-key", signature=""
        )
        deployment = replace(
            deployment,
            signature=collision_trust.sign(
                deployment, deployment.issuer, deployment.signing_identity
            ),
        )
        recovery = replace(recovery, signing_identity="shared-key", signature="")
        recovery = replace(
            recovery,
            signature=collision_trust.sign(
                recovery, recovery.issuer, recovery.signing_identity
            ),
        )
        operator = replace(
            operator,
            deployment_receipt_digest=semantic_digest(asdict(deployment)),
            recovery_receipt_digest=semantic_digest(asdict(recovery)),
            signature="",
        )
        operator = replace(
            operator,
            signature=collision_trust.sign(
                operator, operator.issuer, operator.signing_identity
            ),
        )
        with self.assertRaisesRegex(ValueError, "role_collision"):
            verify_production_acceptance_evidence(
                deployment,
                recovery,
                rollback,
                operator,
                collision_trust,
                now_ns=self.now,
            )


if __name__ == "__main__":
    unittest.main()
