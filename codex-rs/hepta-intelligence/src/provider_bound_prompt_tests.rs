use super::*;

use crate::PromptRegistryCompilationRequestV2;
use crate::compile_prompt_registry_v2;
use crate::prompt_delivery::tests::admitted_registry;
use crate::prompt_delivery::tests::canonical_selection;
use codex_hepta_context_compiler::ContextAdmissionRecordV2;
use codex_hepta_context_compiler::ContextModelProfileV2;
use codex_hepta_context_compiler::ProviderRequestSegmentKindV2;
use codex_hepta_context_compiler::ProviderTokenizerIdentityV2;
use codex_hepta_context_compiler::canonical_context_serializer_digest;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_prompt_registry::DurablePromptRegistry;
use codex_hepta_prompt_registry::PromptModelTupleV2;
use codex_hepta_prompt_registry::PromptRealizationBindingV2;
use codex_hepta_prompt_registry::final_use_realization_binding;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn tokenizer_identity(tuple: &PromptModelTupleV2) -> ProviderTokenizerIdentityV2 {
    ProviderTokenizerIdentityV2 {
        provider_id_digest: digest("provider"),
        provider_model_digest: tuple.model_digest,
        tokenizer_binary_digest: digest("tokenizer-binary:v1"),
        tokenizer_version_digest: digest("tokenizer-version:2026-09"),
        vocabulary_digest: digest("tokenizer-vocabulary:fixture"),
        normalization_policy_digest: digest("tokenizer-normalization:none"),
    }
}

fn register_strict_realization(
    registry: &mut DurablePromptRegistry,
    base_tuple: &PromptModelTupleV2,
    authority: &FinalUseAuthority,
    signing_key: &SigningKey,
    grant_now: u64,
    payload: &[u8],
) -> PromptModelTupleV2 {
    let mut tuple = base_tuple.clone();
    tuple.tokenizer_digest = tokenizer_identity(base_tuple).digest();
    let factor = registry
        .registry()
        .expect("registry")
        .factor(&id("factor:verify"))
        .cloned()
        .expect("admitted factor");
    let realization = PromptRealizationBindingV2 {
        realization_id: id("realization:verify:provider-bound"),
        factor_id: factor.factor_id.clone(),
        model_id: tuple.model_id.clone(),
        model_version: tuple.model_version.clone(),
        model_digest: tuple.model_digest,
        tokenizer_digest: tuple.tokenizer_digest,
        template_digest: tuple.template_digest,
        tool_schema_digest: tuple.tool_schema_digest,
        context_profile_digest: tuple.context_profile_digest,
        locale_id: tuple.locale_id.clone(),
        role: PromptRoleV2::DeveloperInstruction,
        payload_digest: Digest32::of_bytes(payload),
        token_cost: 4,
        expires_unix_ms: None,
    };
    let actor = id("publisher:prompt:provider-bound");
    let scope = digest("scope:realization:provider-bound");
    let binding = final_use_realization_binding(
        &factor,
        &actor,
        scope,
        &realization,
        None,
    )
    .expect("provider-bound realization authority binding");
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "review-authority:prompt".to_owned(),
        authority_epoch: 1,
        grant_id: "realization:prompt:provider-bound:1".to_owned(),
        nonce: [41; 32],
        binding,
        not_before_unix_ms: grant_now.saturating_sub(1_000),
        expires_at_unix_ms: grant_now + 30_000,
    };
    let signed = SignedFinalUseGrant {
        signature: signing_key
            .sign(&grant.signing_bytes().expect("provider-bound signing bytes"))
            .to_bytes()
            .to_vec(),
        grant,
    };
    registry
        .register_realization_payload_final_use_v2(
            authority,
            &signed,
            &actor,
            scope,
            realization,
            payload.to_vec(),
            None,
        )
        .expect("register provider-bound realization");
    tuple
}

#[derive(Clone)]
struct FixtureTokenizer {
    identity: ProviderTokenizerIdentityV2,
}

impl ExactProviderRequestTokenizerV2 for FixtureTokenizer {
    fn identity(&self) -> ProviderTokenizerIdentityV2 {
        self.identity.clone()
    }

    fn count_tokens(
        &self,
        exact_provider_request: &[u8],
    ) -> Result<u64, ProviderBoundContextErrorV2> {
        let bytes = u64::try_from(exact_provider_request.len())
            .map_err(|_| ProviderBoundContextErrorV2::Arithmetic)?;
        Ok(bytes.saturating_add(3) / 4)
    }
}

struct FixtureSnapshotVerifier {
    digest: Digest32,
    scope: Digest32,
    authority_domain: Digest32,
}

impl ContextAdmissionVerifierV2 for FixtureSnapshotVerifier {
    fn verifier_digest(&self) -> Digest32 {
        self.digest
    }

    fn verify_record(&self, record: &ContextAdmissionRecordV2) -> bool {
        record.scope_digest == self.scope
            && record.authority_domain_digest == self.authority_domain
            && record.validate_shape().is_ok()
    }

    fn verify_snapshot(&self, snapshot: &ContextAdmissionSnapshotV2) -> bool {
        snapshot.scope_digest == self.scope
            && snapshot.authority_domain_digest == self.authority_domain
            && snapshot.revocation_set_complete
            && snapshot.validate_shape().is_ok()
    }
}

struct FixtureFramingPolicy;

impl ProviderRequestFramingPolicyV2 for FixtureFramingPolicy {
    fn policy_digest(&self) -> Digest32 {
        digest("provider-request-framing-policy:v1")
    }

    fn permits(&self, framing_kind: &StableId, bytes: &[u8]) -> bool {
        match framing_kind.as_str() {
            "provider:request-prefix" => {
                bytes.starts_with(b"hepta.provider-request.v2\0")
                    && bytes.len() == b"hepta.provider-request.v2\0".len() + 32
            }
            "provider:request-suffix" => bytes == b"\0provider-request-end",
            _ => false,
        }
    }
}

struct FixtureRequestBuilder {
    omit_suffix_coverage: bool,
}

impl ProviderRequestBuilderV2 for FixtureRequestBuilder {
    fn build_provider_request(
        &self,
        canonical_context: &CanonicalContextPayloadV2,
        preparation: &ContextDeliveryPreparationV2,
    ) -> Result<ProviderRequestMaterializationV2, String> {
        let mut prefix = b"hepta.provider-request.v2\0".to_vec();
        prefix.extend_from_slice(preparation.preparation_digest().as_array());
        let suffix = b"\0provider-request-end";
        let mut bytes = prefix.clone();
        let context_start = bytes.len();
        bytes.extend_from_slice(canonical_context.payload());
        let context_end = bytes.len();
        bytes.extend_from_slice(suffix);
        let request_end = bytes.len();

        let prefix_end = u64::try_from(prefix.len()).map_err(|error| error.to_string())?;
        let context_start = u64::try_from(context_start).map_err(|error| error.to_string())?;
        let context_end = u64::try_from(context_end).map_err(|error| error.to_string())?;
        let request_end = u64::try_from(request_end).map_err(|error| error.to_string())?;
        let mut segments = vec![
            ProviderRequestSegmentV2::from_bytes(
                ProviderRequestSegmentKindV2::TypedFraming {
                    framing_kind: id("provider:request-prefix"),
                },
                0,
                prefix_end,
                &bytes,
            )
            .map_err(|error| format!("prefix: {error:?}"))?,
            ProviderRequestSegmentV2::from_bytes(
                ProviderRequestSegmentKindV2::CanonicalContext,
                context_start,
                context_end,
                &bytes,
            )
            .map_err(|error| format!("context: {error:?}"))?,
        ];
        if !self.omit_suffix_coverage {
            segments.push(
                ProviderRequestSegmentV2::from_bytes(
                    ProviderRequestSegmentKindV2::TypedFraming {
                        framing_kind: id("provider:request-suffix"),
                    },
                    context_end,
                    request_end,
                    &bytes,
                )
                .map_err(|error| format!("suffix: {error:?}"))?,
            );
        }
        Ok(ProviderRequestMaterializationV2 {
            exact_request_bytes: bytes,
            segments,
            wire_semantic_digest: digest("provider-wire-semantics:v1"),
        })
    }
}

fn compiled_source() -> (
    tempfile::TempDir,
    PromptModelTupleV2,
    PromptRegistryCompiledContextV2,
) {
    let temporary = tempfile::tempdir().expect("tempdir");
    let root = temporary.path().join("prompt-registry-provider-bound");
    let payload = b"Inspect evidence before mutation.";
    let (mut registry, base_tuple, authority, signing_key, grant_now) =
        admitted_registry(&root, payload);
    let tuple = register_strict_realization(
        &mut registry,
        &base_tuple,
        &authority,
        &signing_key,
        grant_now,
        payload,
    );
    let selected = canonical_selection(&registry, &tuple, 100);
    let serializer_digest =
        canonical_context_serializer_digest(tuple.template_digest, tuple.tool_schema_digest);
    let output = compile_prompt_registry_v2(
        &registry,
        &selected.portfolio,
        &selected.exercise_request,
        PromptRegistryCompilationRequestV2 {
            compilation_id: id("compilation:provider-bound:1"),
            serialization_id: id("serialization:legacy-transition:1"),
            attachment_id: id("attachment:legacy-transition:1"),
            registry_model_tuple: tuple.clone(),
            context_model_profile: ContextModelProfileV2 {
                model_digest: tuple.model_digest,
                provider_id_digest: digest("provider"),
                provider_model_digest: tuple.model_digest,
                tokenizer_digest: tuple.tokenizer_digest,
                serializer_digest,
                template_digest: tuple.template_digest,
                tool_schema_digest: tuple.tool_schema_digest,
                maximum_context_tokens: 4_096,
            },
            now_unix_ms: 100,
            token_budget: 4_096,
            truncation_policy_digest: digest("truncation:provider-bound"),
        },
    )
    .expect("compile provider-bound source");
    (temporary, tuple, output)
}

fn snapshots(
    source: &PromptRegistryCompiledContextV2,
) -> (ContextAdmissionSnapshotV2, ContextAdmissionSnapshotV2) {
    let receipt = source.compiled.receipt();
    let attachment = ContextAdmissionSnapshotV2::new(
        id("snapshot:provider-bound:attachment"),
        receipt.scope_digest(),
        receipt.authority_domain_digest(),
        101,
        1,
        Vec::new(),
        true,
        None,
    )
    .expect("attachment snapshot");
    let successor = ContextAdmissionSnapshotV2::new(
        id("snapshot:provider-bound:pre-dispatch"),
        receipt.scope_digest(),
        receipt.authority_domain_digest(),
        102,
        2,
        Vec::new(),
        true,
        Some(attachment.snapshot_digest),
    )
    .expect("pre-dispatch snapshot");
    (attachment, successor)
}

#[test]
fn registry_source_composes_into_one_attested_provider_request() {
    let (_temporary, tuple, source) = compiled_source();
    let receipt = source.compiled.receipt();
    let verifier = FixtureSnapshotVerifier {
        digest: receipt.admission_verifier_digest(),
        scope: receipt.scope_digest(),
        authority_domain: receipt.authority_domain_digest(),
    };
    let identity = tokenizer_identity(&tuple);
    assert_eq!(identity.digest(), tuple.tokenizer_digest);
    let tokenizer = FixtureTokenizer { identity };
    let (attachment_snapshot, pre_dispatch_snapshot) = snapshots(&source);

    let prepared = prepare_provider_bound_prompt_v2(
        &source,
        ProviderBoundPromptPrepareRequestV2 {
            serialization_id: id("serialization:provider-bound:1"),
            attachment_id: id("attachment:provider-bound:1"),
            preparation_id: id("preparation:provider-bound:1"),
            attachment_snapshot,
            pre_dispatch_snapshot,
        },
        &verifier,
        &FixtureRequestBuilder {
            omit_suffix_coverage: false,
        },
        &FixtureFramingPolicy,
        &tokenizer,
    )
    .expect("strict provider-bound preparation");

    prepared
        .validate_for(&source, &FixtureFramingPolicy)
        .expect("strict package validates");
    assert_eq!(prepared.authority(), AuthorityPosture::DENY_ALL);
    assert_eq!(
        prepared.preparation().payload_digest(),
        prepared
            .canonical_serialization()
            .canonical_payload()
            .coverage()
            .payload_digest()
    );
    assert_eq!(
        prepared.final_tokenization().request_digest(),
        prepared.provider_request().request_digest()
    );
    assert!(
        prepared
            .provider_request()
            .bytes()
            .windows(
                prepared
                    .canonical_serialization()
                    .canonical_payload()
                    .payload()
                    .len()
            )
            .any(|window| {
                window
                    == prepared
                        .canonical_serialization()
                        .canonical_payload()
                        .payload()
            })
    );
}

#[test]
fn unclassified_trailing_provider_bytes_fail_closed() {
    let (_temporary, tuple, source) = compiled_source();
    let receipt = source.compiled.receipt();
    let verifier = FixtureSnapshotVerifier {
        digest: receipt.admission_verifier_digest(),
        scope: receipt.scope_digest(),
        authority_domain: receipt.authority_domain_digest(),
    };
    let tokenizer = FixtureTokenizer {
        identity: tokenizer_identity(&tuple),
    };
    let (attachment_snapshot, pre_dispatch_snapshot) = snapshots(&source);
    let error = prepare_provider_bound_prompt_v2(
        &source,
        ProviderBoundPromptPrepareRequestV2 {
            serialization_id: id("serialization:provider-bound:gap"),
            attachment_id: id("attachment:provider-bound:gap"),
            preparation_id: id("preparation:provider-bound:gap"),
            attachment_snapshot,
            pre_dispatch_snapshot,
        },
        &verifier,
        &FixtureRequestBuilder {
            omit_suffix_coverage: true,
        },
        &FixtureFramingPolicy,
        &tokenizer,
    )
    .expect_err("uncovered suffix must fail");
    assert!(matches!(
        error,
        ProviderBoundPromptErrorV2::ProviderBound(
            ProviderBoundContextErrorV2::SegmentGapOrOverlap
        )
    ));
}

#[test]
fn pre_dispatch_snapshot_reset_fails_closed() {
    let (_temporary, tuple, source) = compiled_source();
    let receipt = source.compiled.receipt();
    let verifier = FixtureSnapshotVerifier {
        digest: receipt.admission_verifier_digest(),
        scope: receipt.scope_digest(),
        authority_domain: receipt.authority_domain_digest(),
    };
    let tokenizer = FixtureTokenizer {
        identity: tokenizer_identity(&tuple),
    };
    let (attachment_snapshot, mut pre_dispatch_snapshot) = snapshots(&source);
    pre_dispatch_snapshot.predecessor_snapshot_digest = None;
    pre_dispatch_snapshot.snapshot_digest = pre_dispatch_snapshot.compute_digest();
    let error = prepare_provider_bound_prompt_v2(
        &source,
        ProviderBoundPromptPrepareRequestV2 {
            serialization_id: id("serialization:provider-bound:reset"),
            attachment_id: id("attachment:provider-bound:reset"),
            preparation_id: id("preparation:provider-bound:reset"),
            attachment_snapshot,
            pre_dispatch_snapshot,
        },
        &verifier,
        &FixtureRequestBuilder {
            omit_suffix_coverage: false,
        },
        &FixtureFramingPolicy,
        &tokenizer,
    )
    .expect_err("snapshot reset must fail");
    assert!(matches!(
        error,
        ProviderBoundPromptErrorV2::ProviderBound(_)
            | ProviderBoundPromptErrorV2::Context(_)
    ));
}
