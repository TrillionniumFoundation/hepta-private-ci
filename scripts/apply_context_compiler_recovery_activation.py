#!/usr/bin/env python3
"""Activate raw-free recovery, durable evidence and redacted diagnostics."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one activation anchor, found {count}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


v2 = "codex-rs/hepta-context-compiler/src/v2.rs"
replace_once(
    v2,
    "use codex_hepta_types::StableId;\n\npub const MAX_CONTEXT_CANDIDATES_V2",
    "use codex_hepta_types::StableId;\n\n"
    "#[path = \"v2/delivery_evidence.rs\"]\n"
    "mod delivery_evidence;\n"
    "#[path = \"v2/preparation_archive.rs\"]\n"
    "mod preparation_archive;\n"
    "#[path = \"v2/recovery.rs\"]\n"
    "mod recovery;\n"
    "#[path = \"v2/redaction.rs\"]\n"
    "mod redaction;\n\n"
    "pub use recovery::ContextDeliveryRecoveryBindingV2;\n"
    "pub use recovery::build_delivery_recovery_binding_v2;\n"
    "pub use recovery::observe_recovered_final_provider_delivery_v2;\n\n"
    "pub const MAX_CONTEXT_CANDIDATES_V2",
)
replace_once(
    v2,
    "#[derive(Clone, Debug, Eq, PartialEq)]\npub struct ContextRealizedItemV2",
    "#[derive(Clone, Eq, PartialEq)]\npub struct ContextRealizedItemV2",
)
replace_once(
    v2,
    "#[derive(Clone, Debug, Eq, PartialEq)]\npub struct SerializedContextV2",
    "#[derive(Clone, Eq, PartialEq)]\npub struct SerializedContextV2",
)
replace_once(
    v2,
    "#[derive(Clone, Debug, Eq, PartialEq)]\npub enum ContextCompilerV2Error",
    "#[derive(Clone, Eq, PartialEq)]\npub enum ContextCompilerV2Error",
)
replace_once(
    v2,
    "    InvalidObservationTime,\n    AuthorityGranted,",
    "    InvalidObservationTime,\n"
    "    DeliveryEvidenceEncodingFailed,\n"
    "    RecoveryEvidenceInvalid,\n"
    "    AuthorityGranted,",
)
replace_once(
    v2,
    "impl fmt::Display for ContextCompilerV2Error {\n"
    "    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {\n"
    "        write!(formatter, \"{self:?}\")\n"
    "    }\n"
    "}",
    "impl fmt::Display for ContextCompilerV2Error {\n"
    "    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {\n"
    "        formatter.write_str(self.code())\n"
    "    }\n"
    "}",
)

lib = "codex-rs/hepta-context-compiler/src/lib.rs"
replace_once(
    lib,
    "pub use v2::ContextDeliveryReceiptV2;\n",
    "pub use v2::ContextDeliveryReceiptV2;\n"
    "pub use v2::ContextDeliveryRecoveryBindingV2;\n",
)
replace_once(
    lib,
    "pub use v2::build_attachment;\n",
    "pub use v2::build_attachment;\n"
    "pub use v2::build_delivery_recovery_binding_v2;\n",
)
replace_once(
    lib,
    "pub use v2::observe_final_provider_delivery_v2;\n",
    "pub use v2::observe_final_provider_delivery_v2;\n"
    "pub use v2::observe_recovered_final_provider_delivery_v2;\n",
)

provider = "codex-rs/hepta-context-compiler/src/provider_closure.rs"
replace_once(
    provider,
    "#[derive(Clone, Debug, Eq, PartialEq)]\npub enum ProviderClosureErrorV2",
    "#[derive(Clone, Eq, PartialEq)]\npub enum ProviderClosureErrorV2",
)
replace_once(
    provider,
    "impl fmt::Display for ProviderClosureErrorV2 {",
    "impl ProviderClosureErrorV2 {\n"
    "    #[must_use]\n"
    "    pub const fn code(&self) -> &'static str {\n"
    "        match self {\n"
    "            Self::Core(_) => \"provider_closure_v2_core\",\n"
    "            Self::EmptyDigest(_) => \"provider_closure_v2_empty_digest\",\n"
    "            Self::SnapshotPredecessorMismatch => \"provider_closure_v2_snapshot_predecessor_mismatch\",\n"
    "            Self::InvalidTokenizerIdentity => \"provider_closure_v2_invalid_tokenizer_identity\",\n"
    "            Self::TokenizerFailed(_) => \"provider_closure_v2_tokenizer_failed\",\n"
    "            Self::InvalidTokenCount => \"provider_closure_v2_invalid_token_count\",\n"
    "            Self::FinalRequestEmpty => \"provider_closure_v2_final_request_empty\",\n"
    "            Self::FinalRequestTooLarge => \"provider_closure_v2_final_request_too_large\",\n"
    "            Self::ContextPayloadNotUtf8 => \"provider_closure_v2_context_payload_not_utf8\",\n"
    "            Self::ContextPayloadMissing => \"provider_closure_v2_context_payload_missing\",\n"
    "            Self::ContextPayloadAmbiguous => \"provider_closure_v2_context_payload_ambiguous\",\n"
    "            Self::FramingVerifierRejected(_) => \"provider_closure_v2_framing_verifier_rejected\",\n"
    "            Self::SegmentCoverageInvalid => \"provider_closure_v2_segment_coverage_invalid\",\n"
    "            Self::Arithmetic => \"provider_closure_v2_arithmetic\",\n"
    "        }\n"
    "    }\n"
    "}\n\n"
    "impl fmt::Debug for ProviderClosureErrorV2 {\n"
    "    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {\n"
    "        formatter.write_str(self.code())\n"
    "    }\n"
    "}\n\n"
    "impl fmt::Display for ProviderClosureErrorV2 {",
)
replace_once(
    provider,
    "        write!(formatter, \"{self:?}\")",
    "        formatter.write_str(self.code())",
)
