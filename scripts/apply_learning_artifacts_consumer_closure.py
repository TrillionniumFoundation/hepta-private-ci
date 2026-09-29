#!/usr/bin/env python3
"""Apply the bounded learning.artifacts consumer/observability closure once.

This is a deterministic source materializer for the isolated operational-closure
branch. It refuses unknown source shapes and is idempotent after the patch lands.
Qualification never invokes this script as a repair step.
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


def append_once(path: str, marker: str, value: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if marker in text:
        return
    target.write_text(text.rstrip() + "\n\n" + value.strip() + "\n", encoding="utf-8")


def patch_pinned() -> None:
    path = "codex-rs/hepta-learning-artifacts/src/pinned.rs"
    replace_once(
        path,
        """    /// An earlier failed refresh requires a newly admitted consumer.\n    Unavailable,\n    /// Snapshot, lineage, eligibility, file, or payload validation failed.\n""",
        """    /// An earlier failed refresh requires a newly admitted consumer.\n    Unavailable,\n    /// The authenticated withdrawal frontier changed; reload under the new frontier.\n    WithdrawalFrontierChanged,\n    /// Snapshot, lineage, eligibility, file, or payload validation failed.\n""",
    )
    replace_once(
        path,
        """            Self::Unavailable => formatter.write_str(\"candidate refresh failed; reload required\"),\n            Self::Storage(error) => write!(formatter, \"pinned candidate storage error: {error}\"),\n""",
        """            Self::Unavailable => formatter.write_str(\"candidate refresh failed; reload required\"),\n            Self::WithdrawalFrontierChanged => {\n                formatter.write_str(\"withdrawal frontier changed; reload required\")\n            }\n            Self::Storage(error) => write!(formatter, \"pinned candidate storage error: {error}\"),\n""",
    )
    replace_once(
        path,
        """            Self::PinMismatch | Self::FrontierMismatch | Self::Ineligible | Self::Unavailable => {\n                None\n            }\n""",
        """            Self::PinMismatch\n            | Self::FrontierMismatch\n            | Self::Ineligible\n            | Self::Unavailable\n            | Self::WithdrawalFrontierChanged => None,\n""",
    )
    replace_once(
        path,
        """pub struct VerifiedCurrentRegistryViewV1 {\n    receipt: RegistrySnapshotReceipt,\n    registry: ArtifactRegistry,\n    witness_digest: Digest32,\n    trust_digest: Digest32,\n}\n""",
        """pub struct VerifiedCurrentRegistryViewV1 {\n    receipt: RegistrySnapshotReceipt,\n    registry: ArtifactRegistry,\n    witness_digest: Digest32,\n    trust_digest: Digest32,\n    withdrawal_head_digest: Digest32,\n}\n""",
    )
    replace_once(
        path,
        """        Self {\n            receipt,\n            registry,\n            witness_digest,\n            trust_digest,\n        }\n""",
        """        Self {\n            receipt,\n            registry,\n            witness_digest,\n            trust_digest,\n            withdrawal_head_digest: Digest32::ZERO,\n        }\n""",
    )
    replace_once(
        path,
        """    pub const fn trust_digest(&self) -> Digest32 {\n        self.trust_digest\n    }\n\n    pub(crate) fn registry(&self) -> &ArtifactRegistry {\n""",
        """    pub const fn trust_digest(&self) -> Digest32 {\n        self.trust_digest\n    }\n\n    #[must_use]\n    pub const fn withdrawal_head_digest(&self) -> Digest32 {\n        self.withdrawal_head_digest\n    }\n\n    pub(crate) fn with_withdrawal_head(mut self, withdrawal_head_digest: Digest32) -> Self {\n        self.withdrawal_head_digest = withdrawal_head_digest;\n        self\n    }\n\n    pub(crate) fn registry(&self) -> &ArtifactRegistry {\n""",
    )
    replace_once(
        path,
        """            .field(\"trust_digest\", &self.trust_digest)\n            .finish_non_exhaustive()\n""",
        """            .field(\"trust_digest\", &self.trust_digest)\n            .field(\"withdrawal_head_digest\", &self.withdrawal_head_digest)\n            .finish_non_exhaustive()\n""",
    )
    replace_once(
        path,
        """pub struct RevalidatingCandidate {\n    candidate: LoadedPinnedCandidate,\n    unavailable: bool,\n}\n""",
        """pub struct RevalidatingCandidate {\n    candidate: LoadedPinnedCandidate,\n    unavailable: bool,\n    withdrawal_head_digest: Option<Digest32>,\n}\n""",
    )
    replace_once(
        path,
        """        Self {\n            candidate,\n            unavailable: false,\n        }\n""",
        """        Self {\n            candidate,\n            unavailable: false,\n            withdrawal_head_digest: None,\n        }\n""",
    )
    replace_once(
        path,
        """        self.with_verified_registry(current.receipt, current.registry, consume)\n""",
        """        let withdrawal_head_digest = current.withdrawal_head_digest;\n        self.with_verified_registry(\n            current.receipt,\n            current.registry,\n            withdrawal_head_digest,\n            consume,\n        )\n""",
    )
    replace_once(
        path,
        """    fn with_verified_registry<T>(\n        &mut self,\n        current: RegistrySnapshotReceipt,\n        registry: ArtifactRegistry,\n        consume: impl FnOnce(&[u8]) -> T,\n    ) -> Result<T, PinnedCandidateLoadError> {\n        if self.unavailable {\n            return Err(PinnedCandidateLoadError::Unavailable);\n        }\n        self.unavailable = true;\n        let previous = self.candidate.spec.registry_receipt;\n""",
        """    fn with_verified_registry<T>(\n        &mut self,\n        current: RegistrySnapshotReceipt,\n        registry: ArtifactRegistry,\n        withdrawal_head_digest: Digest32,\n        consume: impl FnOnce(&[u8]) -> T,\n    ) -> Result<T, PinnedCandidateLoadError> {\n        if self.unavailable {\n            return Err(PinnedCandidateLoadError::Unavailable);\n        }\n        self.unavailable = true;\n        if withdrawal_head_digest.is_zero()\n            || self\n                .withdrawal_head_digest\n                .is_some_and(|previous| previous != withdrawal_head_digest)\n        {\n            return Err(PinnedCandidateLoadError::WithdrawalFrontierChanged);\n        }\n        let previous = self.candidate.spec.registry_receipt;\n""",
    )
    replace_once(
        path,
        """        self.candidate.spec.registry_receipt = current;\n        let result = consume(&self.candidate.bytes);\n""",
        """        self.candidate.spec.registry_receipt = current;\n        self.withdrawal_head_digest = Some(withdrawal_head_digest);\n        let result = consume(&self.candidate.bytes);\n""",
    )
    replace_once(
        path,
        """        let registry = read_registry_snapshot(snapshot, current)?;\n        self.with_verified_registry(current, registry, consume)\n""",
        """        let registry = read_registry_snapshot(snapshot, current)?;\n        let withdrawal_head_digest = self\n            .withdrawal_head_digest\n            .unwrap_or_else(|| Digest32::of_bytes(b\"hepta.test.withdrawal-frontier.v1\"));\n        self.with_verified_registry(current, registry, withdrawal_head_digest, consume)\n""",
    )
    append_once(
        path,
        "withdrawal_change_closes_existing_consumer_until_explicit_reload",
        r'''
#[cfg(test)]
mod withdrawal_frontier_tests {
    use super::*;
    use codex_hepta_types::Generation;
    use codex_hepta_types::StableId;

    use crate::ArtifactEvent;
    use crate::ArtifactKind;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid fixture id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn manifest() -> ArtifactManifest {
        ArtifactManifest {
            artifact_id: id("candidate"),
            kind: ArtifactKind::Policy,
            generation: Generation::new(1).expect("valid generation"),
            predecessor_id: None,
            content_digest: digest("payload"),
            objective_digest: digest("objective"),
            support_digest: digest("support"),
            producer_id: id("producer"),
            compatibility_digest: digest("compatibility"),
            encoded_size_bytes: 7,
        }
    }

    fn view(
        registry: ArtifactRegistry,
        receipt: RegistrySnapshotReceipt,
        withdrawal: Digest32,
    ) -> VerifiedCurrentRegistryViewV1 {
        VerifiedCurrentRegistryViewV1::new(
            receipt,
            registry,
            digest("witness"),
            digest("trust"),
        )
        .with_withdrawal_head(withdrawal)
    }

    #[test]
    fn withdrawal_change_closes_existing_consumer_until_explicit_reload() {
        let manifest = manifest();
        let mut registry = ArtifactRegistry::new();
        registry
            .append(ArtifactEvent::Register {
                event_id: id("register"),
                manifest: manifest.clone(),
            })
            .expect("register fixture");
        let receipt = RegistrySnapshotReceipt {
            binding: digest("binding"),
            head_digest: registry.snapshot().head_digest,
            file_digest: digest("file"),
            records: 1,
            encoded_bytes: 1,
        };
        let candidate = LoadedPinnedCandidate {
            spec: PinnedCandidateSpec {
                registry_receipt: receipt,
                manifest,
            },
            bytes: b"payload".to_vec(),
        };
        let mut consumer = RevalidatingCandidate::new(candidate);
        assert_eq!(
            consumer
                .with_current(view(registry.clone(), receipt, digest("withdrawal-a")), |bytes| {
                    bytes.len()
                })
                .expect("first current use"),
            7
        );
        assert_eq!(
            consumer.with_current(
                view(registry.clone(), receipt, digest("withdrawal-b")),
                |_| panic!("changed withdrawal frontier reached consumer"),
            ),
            Err(PinnedCandidateLoadError::WithdrawalFrontierChanged)
        );
        assert_eq!(
            consumer.with_current(
                view(registry, receipt, digest("withdrawal-a")),
                |_| panic!("closed consumer revived without reload"),
            ),
            Err(PinnedCandidateLoadError::Unavailable)
        );
    }
}
''',
    )


def patch_owner_service() -> None:
    replace_once(
        "codex-rs/hepta-learning-artifacts/src/owner_service.rs",
        """            Ok(self.host.current_registry_view(now)?)\n""",
        """            Ok(self\n                .host\n                .current_registry_view(now)?\n                .with_withdrawal_head(self.withdrawal_registry.head_digest()))\n""",
    )


def patch_operational_metrics() -> None:
    path = "codex-rs/hepta-learning-artifacts/src/owner/operational_metrics.rs"
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    marker = "hepta.learning-artifactd.operational-metrics.v1"
    if marker in text:
        return
    insertion = r'''
impl ArtifactOwnerOperationalSnapshotV1 {
    #[must_use]
    pub fn erasure_ready(&self) -> bool {
        self.pinned_bytes == 0 && self.pending_physical_erase_bytes == 0
    }

    #[must_use]
    pub fn response_json(&self) -> String {
        let blockers = self
            .block_counts
            .iter()
            .map(|(reason, count)| format!("\"{}\":{}", reason.as_str(), count))
            .collect::<Vec<_>>()
            .join(",");
        let stages = self
            .stages
            .iter()
            .map(|(stage, summary)| {
                format!(
                    concat!(
                        "\"{}\":{{\"count\":{},\"totalMicros\":{},",
                        "\"lastMicros\":{},\"maxMicros\":{},",
                        "\"p50Micros\":{},\"p95Micros\":{},\"p99Micros\":{}}}"
                    ),
                    stage.as_str(),
                    summary.count,
                    summary.total_micros,
                    summary.last_micros,
                    summary.max_micros,
                    summary.p50_micros,
                    summary.p95_micros,
                    summary.p99_micros,
                )
            })
            .collect::<Vec<_>>()
            .join(",");
        format!(
            concat!(
                "{{\"schema\":\"hepta.learning-artifactd.operational-metrics.v1\",",
                "\"recoveryOperationId\":{},\"oldestPendingAttemptAgeMs\":{},",
                "\"withdrawalBlockedCount\":{},\"withdrawalBlockedDurationMs\":{},",
                "\"drainDurationMs\":{},\"recoveryReconciliationFailures\":{},",
                "\"pinnedBytes\":{},\"pendingPhysicalEraseBytes\":{},",
                "\"erasureReady\":{},\"ownerEpochConflicts\":{},",
                "\"withdrawalEpochConflicts\":{},\"blockCounts\":{{{}}},",
                "\"stages\":{{{}}}}}"
            ),
            optional_id_json(self.recovery_operation_id.as_ref()),
            optional_u64_json(self.oldest_pending_attempt_age_ms),
            self.withdrawal_blocked_count,
            optional_u64_json(self.withdrawal_blocked_duration_ms),
            optional_u64_json(self.drain_duration_ms),
            self.recovery_reconciliation_failures,
            self.pinned_bytes,
            self.pending_physical_erase_bytes,
            self.erasure_ready(),
            self.owner_epoch_conflicts,
            self.withdrawal_epoch_conflicts,
            blockers,
            stages,
        )
    }
}

fn optional_u64_json(value: Option<u64>) -> String {
    value.map_or_else(|| "null".to_owned(), |value| value.to_string())
}

fn optional_id_json(value: Option<&StableId>) -> String {
    value.map_or_else(|| "null".to_owned(), |value| format!("\"{value}\""))
}

'''
    needle = "#[cfg(test)]\nmod tests"
    if text.count(needle) != 1:
        raise RuntimeError(f"{path}: test module insertion point changed")
    target.write_text(text.replace(needle, insertion + needle, 1), encoding="utf-8")


def patch_reference_host() -> None:
    replace_once(
        "codex-rs/hepta-learning-artifacts/src/owner/publication_coordination.rs",
        """            ArtifactOwnerActionV1::Metrics => {\n                require_empty_payload(&request.payload)?;\n                Ok(ExecutionResultV1::json(\n                    self.metrics().response_json(),\n                    false,\n                ))\n            }\n""",
        """            ArtifactOwnerActionV1::Metrics => {\n                require_empty_payload(&request.payload)?;\n                let operational = self\n                    .service\n                    .lock()\n                    .map_err(|_| ArtifactOwnerCommandError::Poisoned)?\n                    .operational_metrics()\n                    .response_json();\n                Ok(ExecutionResultV1::json(\n                    format!(\n                        \"{{\\\"schema\\\":\\\"hepta.learning-artifactd.metrics.v2\\\",\\\"counters\\\":{},\\\"operational\\\":{}}}\",\n                        self.metrics().response_json(),\n                        operational,\n                    ),\n                    false,\n                ))\n            }\n""",
    )
    replace_once(
        "codex-rs/hepta-learning-artifacts/REFERENCE_HOST_PROTOCOL.md",
        "| `metrics` | Bounded counters | Always authenticated |",
        "| `metrics` | Bounded counters, blocker ages, resource gauges and per-stage latency summaries | Always authenticated |",
    )
    replace_once(
        "codex-rs/hepta-learning-artifacts/REFERENCE_HOST_PROTOCOL.md",
        """## Versioning\n""",
        """## Operational metrics\n\nThe `metrics` response uses `hepta.learning-artifactd.metrics.v2`. It retains the\nrequest counters as a nested V1 object and adds a bounded operational object with\nthe oldest recovery age, withdrawal-block count and duration, drain duration,\nreconciliation failures, pinned and pending-erasure bytes, owner/withdrawal epoch\nconflicts and bounded p50/p95/p99 summaries for each durability stage. These are\nobservations only: `erasureReady` is false while bytes remain pinned or await\nphysical reconciliation and never performs erasure or grants publication.\n\n## Versioning\n""",
    )


def patch_qualification() -> None:
    path = ".github/workflows/hepta-learning-artifacts-qualification.yml"
    replace_once(
        path,
        "branches: [main, 'codex/learning-artifacts-qualification-recovery-*', 'codex/learning-artifacts-qualified-host-*']",
        "branches: [main, 'codex/learning-artifacts-qualification-recovery-*', 'codex/learning-artifacts-qualified-host-*', 'codex/learning-artifacts-operational-closure-*']",
    )
    replace_once(
        path,
        """      - name: Evidence verifier regression tests\n        run: python3 -m unittest discover -s scripts -p 'test_hepta_artifact_*.py' -v\n      - name: Execute every native gate and retain each outcome\n""",
        """      - name: Evidence verifier regression tests\n        run: python3 -m unittest discover -s scripts -p 'test_hepta_artifact_*.py' -v\n      - name: Execute declared crash-test feature on exact Linux source\n        if: matrix.os == 'ubuntu-24.04' && matrix.lane == 'exact-head'\n        shell: bash\n        run: |\n          set -euo pipefail\n          cargo test --manifest-path codex-rs/Cargo.toml --locked \\\n            -p codex-hepta-learning-artifacts --features artifact_test_hooks \\\n            owner_service::tests::process::sigkill_every_durable_phase_reconciles_exactly_and_preserves_writer_exclusion \\\n            -- --nocapture --test-threads=1\n      - name: Execute every native gate and retain each outcome\n""",
    )


def main() -> int:
    patch_pinned()
    patch_owner_service()
    patch_operational_metrics()
    patch_reference_host()
    patch_qualification()
    print("learning.artifacts consumer and operational closure materialized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
