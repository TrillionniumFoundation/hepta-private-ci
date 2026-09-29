#!/usr/bin/env python3
"""Apply bounded compile, lint and qualification-contract fixes once.

The materializer refuses changed source shapes and is idempotent after success.
It does not run during read-only qualification.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one source shape, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_bootstrap() -> None:
    replace_once(
        "codex-rs/hepta-learning-artifacts/src/owner/bootstrap.rs",
        "return Err(ArtifactOwnerConfigError::InvalidValue(prefix));",
        "return Err(ArtifactOwnerConfigError::InvalidEntry(prefix.to_owned()));",
    )


def patch_imports() -> None:
    replace_once(
        "codex-rs/hepta-learning-artifacts/src/owner/capability_validation.rs",
        "use std::str::FromStr;\n",
        "",
    )
    replace_once(
        "codex-rs/hepta-learning-artifacts/src/owner/publication_coordination.rs",
        "use codex_hepta_types::StableId;\n",
        "",
    )


def patch_crash_tests() -> None:
    target = ROOT / "codex-rs/hepta-learning-artifacts/src/owner/service_crash_tests.rs"
    text = target.read_text(encoding="utf-8")
    if "std::assert_eq!(" in text:
        return
    count = text.count("assert_eq!(")
    if count != 4:
        raise RuntimeError(f"service_crash_tests.rs: expected four assert_eq macros, found {count}")
    target.write_text(text.replace("assert_eq!(", "std::assert_eq!("), encoding="utf-8")


def patch_owner_service() -> None:
    path = "codex-rs/hepta-learning-artifacts/src/owner_service.rs"
    replace_once(
        path,
        "use codex_hepta_types::Digest32;\nuse codex_hepta_types::StableId;",
        "use codex_hepta_types::AuthorityPosture;\nuse codex_hepta_types::Digest32;\nuse codex_hepta_types::StableId;",
    )
    replace_once(
        path,
        """    pub fn operational_metrics_handle(&self) -> ArtifactOwnerOperationalMetricsV1 {\n        self.operational_metrics.clone()\n    }\n\n    pub fn begin_drain(&mut self) {\n""",
        """    pub fn operational_metrics_handle(&self) -> ArtifactOwnerOperationalMetricsV1 {\n        self.operational_metrics.clone()\n    }\n\n    #[must_use]\n    pub const fn authority_posture(&self) -> AuthorityPosture {\n        AuthorityPosture::DENY_ALL\n    }\n\n    pub fn begin_drain(&mut self) {\n""",
    )
    replace_once(
        path,
        "verify_durable_inputs(&self.root, &staged, request, &recovery.checkpoint)?;",
        "verify_durable_inputs(&self.root, staged, request, &recovery.checkpoint)?;",
    )
    replace_once(
        path,
        """            Self::RequestMismatch | Self::IdentityConflict => {\n                LearningArtifactOwnerServiceErrorCodeV1::IdentityConflict\n            }\n""",
        """            Self::RequestMismatch\n            | Self::IdentityConflict\n            | Self::Host(ArtifactOwnerHostError::IdentityConflict) => {\n                LearningArtifactOwnerServiceErrorCodeV1::IdentityConflict\n            }\n""",
    )
    replace_once(
        path,
        """                | ArtifactOwnerHostError::WriterLeaseContext\n                | ArtifactOwnerHostError::CurrentHeadExpired\n                | ArtifactOwnerHostError::CurrentHeadRollback,\n""",
        """                | ArtifactOwnerHostError::WriterLeaseContext\n                | ArtifactOwnerHostError::InvalidSignature\n                | ArtifactOwnerHostError::RegistryPredecessorMismatch\n                | ArtifactOwnerHostError::CurrentHeadConflict\n                | ArtifactOwnerHostError::CurrentHeadExpired\n                | ArtifactOwnerHostError::CurrentHeadRollback,\n""",
    )
    replace_once(
        path,
        """            Self::Host(_)\n            | Self::Publication(_) => LearningArtifactOwnerServiceErrorCodeV1::Internal,\n""",
        """            Self::Host(\n                ArtifactOwnerHostError::Storage(_)\n                | ArtifactOwnerHostError::Publication(_)\n                | ArtifactOwnerHostError::Registry(_)\n                | ArtifactOwnerHostError::Io(_)\n                | ArtifactOwnerHostError::InvalidTrust\n                | ArtifactOwnerHostError::InvalidKey\n                | ArtifactOwnerHostError::CurrentHeadContext\n                | ArtifactOwnerHostError::PathBoundary\n                | ArtifactOwnerHostError::InternalInvariant,\n            )\n            | Self::Publication(_) => LearningArtifactOwnerServiceErrorCodeV1::Internal,\n""",
    )


def patch_pinned_compatibility() -> None:
    path = "codex-rs/hepta-learning-artifacts/src/pinned.rs"
    replace_once(
        path,
        """        if withdrawal_head_digest.is_zero()\n            || self\n                .withdrawal_head_digest\n                .is_some_and(|previous| previous != withdrawal_head_digest)\n        {\n""",
        """        if self.withdrawal_head_digest.is_some_and(|previous| {\n            withdrawal_head_digest.is_zero() || previous != withdrawal_head_digest\n        }) {\n""",
    )
    replace_once(
        path,
        """        self.candidate.spec.registry_receipt = current;\n        self.withdrawal_head_digest = Some(withdrawal_head_digest);\n        let result = consume(&self.candidate.bytes);\n""",
        """        self.candidate.spec.registry_receipt = current;\n        if !withdrawal_head_digest.is_zero() {\n            self.withdrawal_head_digest = Some(withdrawal_head_digest);\n        }\n        let result = consume(&self.candidate.bytes);\n""",
    )


def patch_qualification_runner() -> None:
    replace_once(
        "scripts/hepta_artifact_qualification.py",
        """        \"tests\": [\"just\", \"test\", \"--locked\", \"-p\", PACKAGE, \"--ignore-default-filter\", \"--run-ignored\", \"all\", \"--retries\", \"0\", \"--no-fail-fast\"],\n""",
        """        \"tests\": [\"just\", \"test\", \"--locked\", \"-p\", PACKAGE, \"--ignore-default-filter\", \"--run-ignored\", \"all\", \"--retries\", \"0\"],\n""",
    )


def patch_traceability() -> None:
    replace_once(
        "qualification/lane-e/TEST_TRACEABILITY.json",
        """          \"source\": \"codex-rs/hepta-learning-artifacts/src/owner_service.rs\",\n          \"function\": \"named_owner_service_publishes_retries_and_reopens_from_current_head\"\n""",
        """          \"source\": \"codex-rs/hepta-learning-artifacts/src/owner_service_tests.rs\",\n          \"function\": \"named_owner_service_publishes_retries_and_reopens_from_current_head\"\n""",
    )


def converge_coverage_pin() -> None:
    changed = 0
    for path in sorted((ROOT / ".github/workflows").glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        updated = text.replace("cargo-llvm-cov@0.9.1", "cargo-llvm-cov@0.9.0")
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            changed += 1
    if changed == 0:
        all_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((ROOT / ".github/workflows").glob("*.yml"))
        )
        if "cargo-llvm-cov@0.9.1" in all_text:
            raise RuntimeError("coverage pin remains unconverged")


def main() -> int:
    patch_bootstrap()
    patch_imports()
    patch_crash_tests()
    patch_owner_service()
    patch_pinned_compatibility()
    patch_qualification_runner()
    patch_traceability()
    converge_coverage_pin()
    print("learning.artifacts compile and qualification fixes materialized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
