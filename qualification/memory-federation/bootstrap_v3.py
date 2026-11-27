#!/usr/bin/env python3
"""Apply the memory.federation V3 integration patch to a checked-out branch.

This one-shot helper exists only because the repository is being edited through
GitHub's contents API. The bootstrap workflow removes it after the integrated
candidate is qualified.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def path(relative: str) -> Path:
    value = (ROOT / relative).resolve()
    value.relative_to(ROOT)
    return value


def read(relative: str) -> str:
    return path(relative).read_text(encoding="utf-8")


def write(relative: str, content: str) -> None:
    target = path(relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_text(encoding="utf-8") == content:
        return
    target.write_text(content, encoding="utf-8")


def replace_once(relative: str, old: str, new: str) -> None:
    text = read(relative)
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{relative}: expected one replacement anchor, found {count}")
    write(relative, text.replace(old, new, 1))


def replace_count(relative: str, old: str, new: str, expected: int) -> None:
    text = read(relative)
    if text.count(new) == expected:
        return
    count = text.count(old)
    if count != expected:
        raise SystemExit(
            f"{relative}: expected {expected} replacement anchors, found {count}"
        )
    write(relative, text.replace(old, new))


def replace_between(relative: str, start: str, end: str, replacement: str) -> None:
    text = read(relative)
    if replacement in text:
        return
    first = text.find(start)
    if first < 0:
        raise SystemExit(f"{relative}: missing section start {start!r}")
    last = text.find(end, first + len(start))
    if last < 0:
        raise SystemExit(f"{relative}: missing section end {end!r}")
    write(relative, text[:first] + replacement + text[last:])


def append_once(relative: str, marker: str, content: str) -> None:
    text = read(relative)
    if marker in text:
        return
    write(relative, text.rstrip() + "\n\n" + content.rstrip() + "\n")


def patch_workspace() -> None:
    replace_once(
        "codex-rs/Cargo.toml",
        '    "hepta-memory-federation",\n    "hepta-memory-retrieval",',
        '    "hepta-memory-federation",\n    "hepta-memory-federation-wire",\n    "hepta-memory-retrieval",',
    )


def patch_canonical_crate() -> None:
    cargo = "codex-rs/hepta-memory-federation/Cargo.toml"
    replace_once(
        cargo,
        "[lints]\nworkspace = true\n\n[dependencies]",
        "[lints]\nworkspace = true\n\n[features]\ndefault = []\nlegacy-v1 = []\n\n[dependencies]",
    )
    write(
        "codex-rs/hepta-memory-federation/src/lib.rs",
        '''//! Scoped, fail-closed remote cognitive read verification.\n\n#![forbid(unsafe_code)]\n\n#[cfg(feature = "legacy-v1")]\nmod legacy_v1;\nmod v2;\n\n#[cfg(feature = "legacy-v1")]\n#[deprecated(note = "legacy V1 is compatibility-only; use the V2 checked engine")]\npub use legacy_v1::Error;\n#[cfg(feature = "legacy-v1")]\n#[deprecated(note = "legacy V1 is compatibility-only; use FederatedLeaseV2")]\npub use legacy_v1::FederatedReadLease;\n#[cfg(feature = "legacy-v1")]\n#[deprecated(note = "legacy V1 is compatibility-only; use FederatedQueryV2")]\npub use legacy_v1::FederatedReadRequest;\n#[cfg(feature = "legacy-v1")]\n#[deprecated(note = "legacy V1 is compatibility-only; use FederatedResultV2")]\npub use legacy_v1::FederatedReadReceipt;\n#[cfg(feature = "legacy-v1")]\n#[deprecated(note = "legacy V1 is compatibility-only; use FederatedValidityV2")]\npub use legacy_v1::FederatedStatus;\n#[cfg(feature = "legacy-v1")]\n#[deprecated(note = "legacy V1 is compatibility-only; use RemoteFederatedResponseV2")]\npub use legacy_v1::RemoteObservation;\n#[cfg(feature = "legacy-v1")]\n#[deprecated(note = "legacy V1 is compatibility-only; use execute_once")]\npub use legacy_v1::observe;\n\npub use v2::FederatedCompletenessV2;\npub use v2::FederatedCoverageV2;\npub use v2::FederatedEvidenceItemV2;\npub use v2::FederatedFailureCoverageV2;\npub use v2::FederatedLeaseV2;\npub use v2::FederatedQueryV2;\npub use v2::FederatedResultV2;\npub use v2::FederatedValidityV2;\npub use v2::FederationAttemptControlV2;\npub use v2::FederationAuthorityFuture;\npub use v2::FederationAuthorityObservationV2;\npub use v2::FederationAuthorityStateV2;\npub use v2::FederationAuthorityV2;\npub use v2::FederationCancellationReceiptV2;\npub use v2::FederationCancellationRequestV2;\npub use v2::FederationStopFuture;\npub use v2::FederationStopReasonV2;\npub use v2::FederationTransportFuture;\npub use v2::FederationTransportOutcomeV2;\npub use v2::FederationTransportResultV2;\npub use v2::FederationTransportV2;\npub use v2::FederationV2Error;\npub use v2::MAX_FEDERATED_RESULTS_V2;\npub use v2::RemoteFederatedResponseV2;\npub use v2::execute_once;\npub use v2::observe_cancellation;\n''',
    )


def patch_memory_exports() -> None:
    replace_once(
        "codex-rs/hepta-memory/src/lib.rs",
        "mod cognitive_federation;\n",
        "mod cognitive_federation;\nmod cognitive_federation_profile;\n",
    )
    replace_once(
        "codex-rs/hepta-memory/src/lib.rs",
        "pub use cognitive_federation::MAX_FEDERATION_SOURCES_PER_AGENT;\n",
        "pub use cognitive_federation::MAX_FEDERATION_SOURCES_PER_AGENT;\n"
        "pub use cognitive_federation_profile::FederationRuntimeProfile;\n"
        "pub use cognitive_federation_profile::FederationRuntimeProfileError;\n"
        "pub use cognitive_federation_profile::MAX_PRODUCT_FEDERATION_ADMITTED_PEERS_HARD;\n"
        "pub use cognitive_federation_profile::MAX_PRODUCT_FEDERATION_DISCOVERY_CONCURRENCY_HARD;\n"
        "pub use cognitive_federation_profile::MAX_PRODUCT_FEDERATION_OWNER_LAYOUTS_HARD;\n"
        "pub use cognitive_federation_profile::MAX_PRODUCT_FEDERATION_PER_OWNER_BUDGET_MS_HARD;\n"
        "pub use cognitive_federation_profile::MAX_PRODUCT_FEDERATION_REVALIDATION_CONCURRENCY_HARD;\n"
        "pub use cognitive_federation_profile::MAX_PRODUCT_FEDERATION_TOTAL_BUDGET_MS_HARD;\n",
    )
    replace_once(
        "codex-rs/hepta-memory/src/cognitive_federation.rs",
        "pub enum FederationRevalidationDrift {\n    CapabilityMissing,\n",
        "pub enum FederationRevalidationDrift {\n    CapabilityMissing,\n"
        "    OwnerUnavailable,\n    RevalidationTimedOut,\n",
    )


def patch_runtime() -> None:
    relative = "codex-rs/hepta-memory/src/cognitive_runtime.rs"
    replace_once(
        relative,
        "use std::collections::BTreeSet;\n",
        "use std::collections::BTreeMap;\nuse std::collections::BTreeSet;\n",
    )
    replace_once(
        relative,
        "use futures::future::join_all;\n",
        "use futures::StreamExt;\nuse futures::future::join_all;\nuse futures::stream;\n",
    )
    replace_once(
        relative,
        "use crate::FederationRevalidationDrift;\nuse crate::MAX_FEDERATION_SOURCES_PER_AGENT;\n",
        "use crate::FederationRevalidationDrift;\nuse crate::FederationRuntimeProfile;\n",
    )
    text = read(relative)
    text = text.replace(
        "const PRODUCT_FEDERATION_TOTAL_BUDGET: Duration = Duration::from_secs(2);\n"
        "const MAX_PRODUCT_FEDERATION_OWNER_LAYOUTS: usize = 128;\n",
        "",
    )
    write(relative, text)
    replace_once(
        relative,
        "        omitted_owner_candidates: u32,\n    },",
        "        omitted_owner_candidates: u32,\n"
        "        profile: FederationRuntimeProfile,\n    },",
    )
    replace_between(
        relative,
        "    pub fn with_federation_sources(\n",
        "    /// Legacy accessor retained for compatibility-only tests and callers.\n",
        '''    pub fn with_federation_sources(\n        self,\n        consumer_agent_id: AgentId,\n        owner_layouts: Vec<HeptaAgentLayout>,\n    ) -> Self {\n        self.with_federation_sources_profile(\n            consumer_agent_id,\n            owner_layouts,\n            FederationRuntimeProfile::default(),\n        )\n    }\n\n    /// Product composition with an immutable host-selected bound profile.\n    /// Request bytes cannot widen this profile.\n    pub fn with_federation_sources_profile(\n        self,\n        consumer_agent_id: AgentId,\n        mut owner_layouts: Vec<HeptaAgentLayout>,\n        profile: FederationRuntimeProfile,\n    ) -> Self {\n        owner_layouts.sort_by(|left, right| left.agent_id().cmp(right.agent_id()));\n        owner_layouts.dedup_by(|left, right| left.agent_id() == right.agent_id());\n        let omitted_owner_candidates = u32::try_from(\n            owner_layouts\n                .len()\n                .saturating_sub(profile.max_owner_layouts()),\n        )\n        .unwrap_or(u32::MAX);\n        owner_layouts.truncate(profile.max_owner_layouts());\n        if owner_layouts.is_empty() {\n            return self;\n        }\n        match self {\n            Self::Available(store)\n            | Self::AvailableFederated { store, .. }\n            | Self::AvailableFederatedV2 { store, .. } => Self::AvailableFederatedV2 {\n                store,\n                consumer_agent_id,\n                owner_layouts: Arc::new(owner_layouts),\n                omitted_owner_candidates,\n                profile,\n            },\n            Self::Absent | Self::Unavailable(_) => self,\n        }\n    }\n\n''',
    )
    old_retrieve = '''            Self::AvailableFederatedV2 {\n                consumer_agent_id,\n                owner_layouts,\n                omitted_owner_candidates,\n                ..\n            } => {\n                retrieve_federated_product(\n                    consumer_agent_id,\n                    owner_layouts.as_slice(),\n                    *omitted_owner_candidates,\n                    access,\n                    request,\n                )'''
    new_retrieve = '''            Self::AvailableFederatedV2 {\n                consumer_agent_id,\n                owner_layouts,\n                omitted_owner_candidates,\n                profile,\n                ..\n            } => {\n                retrieve_federated_product(\n                    consumer_agent_id,\n                    owner_layouts.as_slice(),\n                    *omitted_owner_candidates,\n                    *profile,\n                    access,\n                    request,\n                )'''
    replace_count(relative, old_retrieve, new_retrieve, 2)
    replace_once(
        relative,
        '''            Self::AvailableFederatedV2 {\n                consumer_agent_id,\n                owner_layouts,\n                ..\n            } => {\n                revalidate_federated_product_batch(\n                    consumer_agent_id,\n                    owner_layouts.as_slice(),\n                    access,''',
        '''            Self::AvailableFederatedV2 {\n                consumer_agent_id,\n                owner_layouts,\n                profile,\n                ..\n            } => {\n                revalidate_federated_product_batch(\n                    consumer_agent_id,\n                    owner_layouts.as_slice(),\n                    *profile,\n                    access,''',
    )
    replace_once(
        relative,
        '''            Self::AvailableFederatedV2 {\n                consumer_agent_id,\n                owner_layouts,\n                ..\n            } => {\n                revalidate_federated_product(\n                    consumer_agent_id,\n                    owner_layouts.as_slice(),\n                    access,''',
        '''            Self::AvailableFederatedV2 {\n                consumer_agent_id,\n                owner_layouts,\n                profile,\n                ..\n            } => {\n                revalidate_federated_product(\n                    consumer_agent_id,\n                    owner_layouts.as_slice(),\n                    *profile,\n                    access,''',
    )
    replace_once(
        relative,
        '''async fn retrieve_federated_product(\n    consumer_agent_id: &AgentId,\n    owner_layouts: &[HeptaAgentLayout],\n    omitted_owner_candidates: u32,\n    access: &FederationConsumerAccess,''',
        '''async fn retrieve_federated_product(\n    consumer_agent_id: &AgentId,\n    owner_layouts: &[HeptaAgentLayout],\n    omitted_owner_candidates: u32,\n    profile: FederationRuntimeProfile,\n    access: &FederationConsumerAccess,''',
    )
    replace_once(
        relative,
        "u64::try_from(PRODUCT_FEDERATION_TOTAL_BUDGET.as_millis()).unwrap_or(u64::MAX)",
        "u64::try_from(profile.total_budget().as_millis()).unwrap_or(u64::MAX)",
    )
    replace_between(
        relative,
        "    let discovery = async {\n",
        "    readers.sort_by(|(_, left), (_, right)| {\n",
        '''    let total_owner_candidates = owner_layouts.len();\n    let discovery_deadline = tokio::time::Instant::now() + profile.total_budget();\n    let mut discovery_stream = stream::iter(owner_layouts.iter().cloned())\n        .map(|owner_layout| async move {\n            let outcome = tokio::time::timeout(\n                profile.per_owner_budget(),\n                FederatedMemoryReader::discover(\n                    &owner_layout,\n                    consumer_agent_id,\n                    request.now_unix_seconds(),\n                ),\n            )\n            .await\n            .map_err(|_| {\n                CognitiveStoreError::Unavailable(\n                    "memory federation owner discovery timed out".to_string(),\n                )\n            })\n            .and_then(|result| result);\n            (owner_layout, outcome)\n        })\n        .buffer_unordered(profile.discovery_concurrency());\n    let mut readers = Vec::new();\n    let mut discovery_failures = 0usize;\n    let mut processed_owner_candidates = 0usize;\n    loop {\n        match tokio::time::timeout_at(discovery_deadline, discovery_stream.next()).await {\n            Ok(Some((owner_layout, outcome))) => {\n                processed_owner_candidates = processed_owner_candidates.saturating_add(1);\n                match outcome {\n                    Ok(discovered) => {\n                        for reader in discovered {\n                            if reader.capability().scope().consumer_workspace_sha256()\n                                != access.workspace_sha256()\n                            {\n                                continue;\n                            }\n                            readers.push((owner_layout.clone(), reader));\n                        }\n                    }\n                    Err(_) => {\n                        discovery_failures = discovery_failures.saturating_add(1);\n                    }\n                }\n            }\n            Ok(None) => break,\n            Err(_) => {\n                discovery_failures = discovery_failures.saturating_add(\n                    total_owner_candidates.saturating_sub(processed_owner_candidates),\n                );\n                break;\n            }\n        }\n    }\n''',
    )
    text = read(relative)
    text = text.replace(
        "observable_peer_slots.saturating_sub(MAX_FEDERATION_SOURCES_PER_AGENT)",
        "observable_peer_slots.saturating_sub(profile.max_admitted_peers())",
    )
    text = text.replace(
        "readers.truncate(MAX_FEDERATION_SOURCES_PER_AGENT);",
        "readers.truncate(profile.max_admitted_peers());",
    )
    text = text.replace(
        "discovery_failures.min(MAX_FEDERATION_SOURCES_PER_AGENT.saturating_sub(readers.len()))",
        "discovery_failures.min(profile.max_admitted_peers().saturating_sub(readers.len()))",
    )
    write(relative, text)
    replace_between(
        relative,
        "async fn revalidate_federated_product(\n",
        "struct ProductReaderTransport<'a> {\n",
        '''async fn revalidate_federated_product(\n    consumer_agent_id: &AgentId,\n    owner_layouts: &[HeptaAgentLayout],\n    profile: FederationRuntimeProfile,\n    access: &FederationConsumerAccess,\n    binding: &FederatedMemoryRevalidationBinding,\n    now_unix_seconds: i64,\n) -> Result<FederatedRevalidationStatus, CognitiveStoreError> {\n    revalidate_federated_product_batch(\n        consumer_agent_id,\n        owner_layouts,\n        profile,\n        access,\n        std::slice::from_ref(binding),\n        now_unix_seconds,\n    )\n    .await?\n    .pop()\n    .ok_or_else(|| {\n        CognitiveStoreError::Corrupt(\n            "single federated product revalidation returned no status".to_string(),\n        )\n    })\n}\n\nasync fn revalidate_federated_product_batch(\n    consumer_agent_id: &AgentId,\n    owner_layouts: &[HeptaAgentLayout],\n    profile: FederationRuntimeProfile,\n    access: &FederationConsumerAccess,\n    bindings: &[FederatedMemoryRevalidationBinding],\n    now_unix_seconds: i64,\n) -> Result<Vec<FederatedRevalidationStatus>, CognitiveStoreError> {\n    if bindings.is_empty() {\n        return Ok(Vec::new());\n    }\n    if access.agent_id() != consumer_agent_id {\n        return Ok(vec![\n            FederatedRevalidationStatus::Stale(FederationRevalidationDrift::Consumer);\n            bindings.len()\n        ]);\n    }\n\n    let mut statuses = vec![None; bindings.len()];\n    let mut groups = BTreeMap::<\n        (String, String),\n        (\n            HeptaAgentLayout,\n            Vec<usize>,\n            Vec<FederatedMemoryRevalidationBinding>,\n        ),\n    >::new();\n    for (index, binding) in bindings.iter().enumerate() {\n        let Some(owner_layout) = owner_layouts\n            .iter()\n            .find(|layout| layout.agent_id() == &binding.source_agent_id)\n            .cloned()\n        else {\n            statuses[index] = Some(FederatedRevalidationStatus::Stale(\n                FederationRevalidationDrift::CapabilityMissing,\n            ));\n            continue;\n        };\n        let key = (\n            binding.source_agent_id.as_str().to_string(),\n            binding.capability.id().as_str().to_string(),\n        );\n        let entry = groups\n            .entry(key)\n            .or_insert_with(|| (owner_layout, Vec::new(), Vec::new()));\n        entry.1.push(index);\n        entry.2.push(binding.clone());\n    }\n\n    let deadline = tokio::time::Instant::now() + profile.total_budget();\n    let mut revalidations = stream::iter(groups.into_iter())\n        .map(\n            |((_owner_id, capability_id), (owner_layout, indices, group_bindings))| async move {\n                let expected_count = indices.len();\n                let operation = async {\n                    let readers = FederatedMemoryReader::discover(\n                        &owner_layout,\n                        consumer_agent_id,\n                        now_unix_seconds,\n                    )\n                    .await?;\n                    let Some(reader) = readers\n                        .into_iter()\n                        .find(|reader| reader.capability().id().as_str() == capability_id)\n                    else {\n                        return Ok(vec![\n                            FederatedRevalidationStatus::Stale(\n                                FederationRevalidationDrift::CapabilityMissing,\n                            );\n                            expected_count\n                        ]);\n                    };\n                    reader\n                        .revalidate_many(access, &group_bindings, now_unix_seconds)\n                        .await\n                };\n                let group_statuses = match tokio::time::timeout(\n                    profile.per_owner_budget(),\n                    operation,\n                )\n                .await\n                {\n                    Err(_) => vec![\n                        FederatedRevalidationStatus::Stale(\n                            FederationRevalidationDrift::RevalidationTimedOut,\n                        );\n                        expected_count\n                    ],\n                    Ok(Err(_)) => vec![\n                        FederatedRevalidationStatus::Stale(\n                            FederationRevalidationDrift::OwnerUnavailable,\n                        );\n                        expected_count\n                    ],\n                    Ok(Ok(group_statuses)) => group_statuses,\n                };\n                if group_statuses.len() != expected_count {\n                    return Err(CognitiveStoreError::Corrupt(\n                        "product federation batch revalidation changed result cardinality"\n                            .to_string(),\n                    ));\n                }\n                Ok::<_, CognitiveStoreError>((indices, group_statuses))\n            },\n        )\n        .buffer_unordered(profile.revalidation_concurrency());\n\n    let mut global_timeout = false;\n    loop {\n        match tokio::time::timeout_at(deadline, revalidations.next()).await {\n            Ok(Some(Ok((indices, group_statuses)))) => {\n                for (index, status) in indices.into_iter().zip(group_statuses) {\n                    statuses[index] = Some(status);\n                }\n            }\n            Ok(Some(Err(error))) => return Err(error),\n            Ok(None) => break,\n            Err(_) => {\n                global_timeout = true;\n                break;\n            }\n        }\n    }\n\n    Ok(statuses\n        .into_iter()\n        .map(|status| {\n            status.unwrap_or(FederatedRevalidationStatus::Stale(if global_timeout {\n                FederationRevalidationDrift::RevalidationTimedOut\n            } else {\n                FederationRevalidationDrift::CapabilityMissing\n            }))\n        })\n        .collect())\n}\n\n''',
    )
    replace_once(
        relative,
        '''            let completeness = if items.is_empty() {\n                FederatedCompletenessV2::Empty\n            } else {\n                FederatedCompletenessV2::Complete\n            };''',
        '''            let completeness = if items.is_empty() {\n                FederatedCompletenessV2::Empty\n            } else if items.len() >= MAX_RETRIEVAL_RESULTS {\n                // The owner reader currently has no authenticated has_more=false\n                // witness. A full top-K result is therefore conservatively partial.\n                FederatedCompletenessV2::Partial\n            } else {\n                FederatedCompletenessV2::Complete\n            };''',
    )


def patch_runtime_identity_and_tests() -> None:
    relative = "codex-rs/hepta-memory/src/cognitive_runtime_identity.rs"
    replace_once(
        relative,
        '''                    omitted_owner_candidates: left_omitted_owner_candidates,\n                },''',
        '''                    omitted_owner_candidates: left_omitted_owner_candidates,\n                    profile: left_profile,\n                },''',
    )
    replace_once(
        relative,
        '''                    omitted_owner_candidates: right_omitted_owner_candidates,\n                },''',
        '''                    omitted_owner_candidates: right_omitted_owner_candidates,\n                    profile: right_profile,\n                },''',
    )
    replace_once(
        relative,
        '''                    && left_owner_layouts.as_slice() == right_owner_layouts.as_slice()\n                    && left_omitted_owner_candidates == right_omitted_owner_candidates''',
        '''                    && left_owner_layouts.as_slice() == right_owner_layouts.as_slice()\n                    && left_omitted_owner_candidates == right_omitted_owner_candidates\n                    && left_profile == right_profile''',
    )
    replace_once(
        "codex-rs/hepta-memory/src/cognitive_runtime_identity_tests.rs",
        "use crate::CognitiveUnavailableReason;\n",
        "use crate::CognitiveUnavailableReason;\nuse crate::FederationRuntimeProfile;\n",
    )
    replace_once(
        "codex-rs/hepta-memory/src/cognitive_runtime_identity_tests.rs",
        "        omitted_owner_candidates: 1,\n    };",
        "        omitted_owner_candidates: 1,\n"
        "        profile: FederationRuntimeProfile::default(),\n    };",
    )


def patch_agentd() -> None:
    config = "codex-rs/hepta-agentd/src/config.rs"
    replace_once(
        config,
        "use codex_hepta_fleet::ResourceBudget;\n",
        "use codex_hepta_fleet::ResourceBudget;\nuse codex_hepta_memory::FederationRuntimeProfile;\n",
    )
    replace_once(
        config,
        "    cognitive_ranker: Option<std::sync::Arc<crate::PinnedCognitiveRanker>>,\n",
        "    cognitive_ranker: Option<std::sync::Arc<crate::PinnedCognitiveRanker>>,\n"
        "    memory_federation_profile: FederationRuntimeProfile,\n",
    )
    replace_once(
        config,
        "            cognitive_ranker: None,\n",
        "            cognitive_ranker: None,\n"
        "            memory_federation_profile: FederationRuntimeProfile::default(),\n",
    )
    replace_once(
        config,
        '''    /// Select the retrieval product profile explicitly. Compatibility preserves\n    /// the legacy owner-ranked path.''',
        '''    /// Fix the memory-federation resource profile for this Agentd generation.\n    /// The validated type can only narrow repository hard ceilings.\n    pub fn with_memory_federation_profile(\n        mut self,\n        profile: FederationRuntimeProfile,\n    ) -> Self {\n        self.memory_federation_profile = profile;\n        self\n    }\n\n    pub(crate) fn memory_federation_profile(&self) -> FederationRuntimeProfile {\n        self.memory_federation_profile\n    }\n\n    /// Select the retrieval product profile explicitly. Compatibility preserves\n    /// the legacy owner-ranked path.''',
    )

    runtime = "codex-rs/hepta-agentd/src/runtime.rs"
    replace_once(
        runtime,
        "use codex_hepta_memory::CognitiveRuntime;\n",
        "use codex_hepta_memory::CognitiveRuntime;\n"
        "use codex_hepta_memory::FederationRuntimeProfile;\n",
    )
    replace_once(
        runtime,
        "    let retrieval_mode = config.cognitive_retrieval_mode();\n",
        "    let memory_federation_profile = config.memory_federation_profile();\n"
        "    let retrieval_mode = config.cognitive_retrieval_mode();\n",
    )
    replace_once(
        runtime,
        '''        cognitive_runtime,\n        federation_owner_layouts,\n    )''',
        '''        cognitive_runtime,\n        federation_owner_layouts,\n        memory_federation_profile,\n    )''',
    )
    replace_once(
        runtime,
        '''    owner_layouts: Vec<codex_hepta_paths::HeptaAgentLayout>,\n) -> Result<CognitiveRuntime, AgentdError> {''',
        '''    owner_layouts: Vec<codex_hepta_paths::HeptaAgentLayout>,\n    profile: FederationRuntimeProfile,\n) -> Result<CognitiveRuntime, AgentdError> {''',
    )
    replace_once(
        runtime,
        '''    let runtime = runtime.with_federation_sources(state.identity().agent_id.clone(), owner_layouts);''',
        '''    let runtime = runtime.with_federation_sources_profile(\n        state.identity().agent_id.clone(),\n        owner_layouts,\n        profile,\n    );''',
    )


def patch_blocking_ci() -> None:
    relative = ".github/workflows/blocking-ci.yml"
    replace_once(
        relative,
        "  lightweight:\n    name: Lightweight prose and derived checks\n",
        '''  memory-federation:\n    name: Memory federation qualification\n    needs: scope\n    if: needs.scope.outputs.native == 'true' || needs.scope.outputs.full_repo == 'true'\n    uses: ./.github/workflows/memory-federation-v3-qualification.yml\n    secrets: inherit\n\n  lightweight:\n    name: Lightweight prose and derived checks\n''',
    )
    replace_once(
        relative,
        "      - hepta-scoped\n      - lightweight\n",
        "      - hepta-scoped\n      - memory-federation\n      - lightweight\n",
    )
    replace_once(
        relative,
        '''          if not (native or full):\n              allowed.append("hepta-contract-gate")''',
        '''          if not (native or full):\n              allowed += ["hepta-contract-gate", "memory-federation"]''',
    )
    replace_once(
        ".github/workflows/hepta-consolidated-source.yml",
        "        codex-hepta-memory codex-hepta-memory-federation\n",
        "        codex-hepta-memory codex-hepta-memory-federation\n"
        "        codex-hepta-memory-federation-wire\n",
    )
    old = path(".github/workflows/memory-federation-v2-final-verify.yml")
    if old.exists():
        old.unlink()


def patch_module_registry() -> None:
    relative = "docs/modules/MODULES.json"
    value = json.loads(read(relative))
    module = next(row for row in value["modules"] if row["id"] == "memory.federation")
    root = "codex-rs/hepta-memory-federation-wire"
    if all(binding["path"] != root for binding in module["rootBindings"]):
        module["rootBindings"].append({"path": root, "mode": "exclusive"})
    if root not in module["sourceEvidenceRoots"]:
        module["sourceEvidenceRoots"].append(root)
    module["sourceEvidenceRoots"].sort()
    write(relative, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def patch_docs() -> None:
    append_once(
        "docs/modules/memory.federation/TECHNICAL.md",
        "## 16. V3 qualification, host profile and authenticated wire candidate",
        '''## 16. V3 qualification, host profile and authenticated wire candidate\n\nThe product runtime now stores a validated `FederationRuntimeProfile` selected by\nAgentd at composition. It bounds owner candidates, admitted peers, discovery and\nrevalidation concurrency, the request horizon, and the per-owner horizon. Values\nmay only narrow hard repository ceilings; request bytes cannot widen them.\n\nOwner discovery uses bounded streaming concurrency and retains observations that\nfinish before the shared deadline. Final revalidation groups exact\nowner/capability bindings, executes groups with bounded concurrency, and returns\ntyped `OwnerUnavailable` or `RevalidationTimedOut` stale states. Retrieval may\ndegrade partially with explicit coverage, but the prepared model-input payload is\nstill guarded all-or-nothing: any stale binding discards the exact prepared\nfederated proposal before provider dispatch.\n\nOwner results at the local top-K ceiling are conservatively `Partial` until the\nowner store supplies an authenticated `has_more=false` witness. A shorter nonempty\nresult is `Complete`; an empty result is `Empty`; product aggregation truncation\nremains separately counted.\n\nThe legacy V1 observation API is absent from the default crate surface and is\ncompiled only with the `legacy-v1` compatibility feature. Product callers use the\ndefault feature set.\n\nCross-host contracts live in\n[`WIRE_V1.md`](WIRE_V1.md) and\n`codex-rs/hepta-memory-federation-wire`. The registered schema, credentials, MAC,\nnonce/replay protection, frontier chain, and cancellation ACK are a transport\ncandidate, not product activation. The current Agentd product path remains the\nin-process, read-only owner-store adapter until two-real-host and target-transport\nqualification pass.\n\nThe executable evidence contract is\n[qualification/memory-federation/V3_PRODUCTION_CLOSURE.md](../../../qualification/memory-federation/V3_PRODUCTION_CLOSURE.md).''',
    )
    append_once(
        "docs/modules/memory.federation/V2_HARDENING.md",
        "## V3 continuation",
        '''## V3 continuation\n\nV2 remains the canonical one-peer checked engine. V3 does not weaken or replace\nits digest, authority, deadline, or final-use rules. It adds host-selected bounded\nproduct scheduling, typed partial revalidation failures, conservative top-K\ncompleteness, default-surface retirement of V1, required exact-head/current-base\nqualification, and a separate authenticated cross-host wire candidate. See\n`WIRE_V1.md` and `qualification/memory-federation/V3_PRODUCTION_CLOSURE.md`.''',
    )
    append_once(
        "qualification/module-execution-dossiers/detail/memory.federation.md",
        "## 9. V3 production-closure implementation",
        '''## 9. V3 production-closure implementation\n\nThe current product candidate adds a fixed `FederationRuntimeProfile`, bounded\nstreaming owner discovery, bounded concurrent owner/capability revalidation, and\ntyped unavailable/timeout stale states. Retrieval preserves partial peer\ncoverage; prepared model-input delivery remains all-or-nothing against the exact\nbinding set. Top-K-at-ceiling results are partial without an authenticated\nnegative `has_more` witness.\n\nThe default canonical crate exports only V2. V1 is feature-gated as\n`legacy-v1` and is exercised only by a dedicated compatibility regression.\n\nThe second owned root, `codex-rs/hepta-memory-federation-wire`, registers the\nauthenticated frame schema and implements directional credential lifecycle, MAC,\nCSPRNG nonce, bounded fail-closed replay admission, chained frontier witnesses,\nand cancellation acknowledgements. It is deliberately not composed into the\ncurrent in-process product path. Real-host transport, independent acceptance,\nactivation, promotion, and release remain external gates.\n\nV3 qualification runs exact source-head and deterministic current-base merge\nlanes, records every command, and emits self-digesting attestations plus a second\nenvelope binding GitHub's evidence artifact digest. `productExecutionProved` may\nchange only in a metadata-only receipt after both lanes pass for the frozen source\ncandidate.''',
    )
    append_once(
        "qualification/memory-federation/FINAL_V2_VERIFICATION.md",
        "## Superseded execution workflow",
        '''## Superseded execution workflow\n\nThe frozen V2 source history remains valid provenance, but its pending workflow is\nsuperseded by `.github/workflows/memory-federation-v3-qualification.yml` and\n`V3_PRODUCTION_CLOSURE.md`. No V2 receipt is promoted into V3 product execution\nevidence.''',
    )


def main() -> None:
    patch_workspace()
    patch_canonical_crate()
    patch_memory_exports()
    patch_runtime()
    patch_runtime_identity_and_tests()
    patch_agentd()
    patch_blocking_ci()
    patch_module_registry()
    patch_docs()


if __name__ == "__main__":
    main()
