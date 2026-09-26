#!/usr/bin/env python3
"""Repair exact Decision/Outcome observation against persisted V2 ledger rows."""

from pathlib import Path


PATH = Path("codex-rs/hepta-agentd/src/intelligence_learning.rs")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count == 0 and new in text:
        return text
    if count != 1:
        raise SystemExit(f"{PATH}: expected one {label} anchor, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    text = PATH.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "use codex_hepta_learning_ledger::AuthenticatedOutcomeV1;",
        "use codex_hepta_learning_ledger::AuthenticatedOutcomeTerminality;\nuse codex_hepta_learning_ledger::AuthenticatedOutcomeV1;",
        "outcome terminality import",
    )
    text = replace_once(
        text,
        "use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;",
        "use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;\nuse codex_hepta_learning_ledger::validate_candidate_set_completeness;",
        "completeness import",
    )
    text = replace_once(
        text,
        '''            let Ok(completeness) = payload.completeness.to_typed() else {
                return false;
            };
            let Ok(candidate_ids) = payload''',
        '''            let Ok(completeness) = payload.completeness.to_typed() else {
                return false;
            };
            let Ok(completeness_digest) = validate_candidate_set_completeness(&completeness)
            else {
                return false;
            };
            let Ok(candidate_ids) = payload''',
        "completeness digest",
    )
    text = replace_once(
        text,
        '''            else {
                return false;
            };
            matches!(
                &record.event,
                LedgerEvent::AuthenticatedDecisionV2(value)''',
        '''            else {
                return false;
            };
            let Ok(evidence) = payload
                .evidence
                .to_typed(LearningEvidenceRoleV1::Generator)
            else {
                return false;
            };
            let authentication_digest = learning_evidence_digest_v1(&evidence);
            matches!(
                &record.event,
                LedgerEvent::AuthenticatedDecisionV2(value)''',
        "decision evidence observation",
    )
    text = replace_once(
        text,
        '''                        && value.selected_propensity.raw() == payload.selected_propensity_raw
                        && value.completeness == completeness
                        && value.support_digest == support_digest''',
        '''                        && value.selected_propensity.raw() == payload.selected_propensity_raw
                        && value.candidate_completeness_digest == completeness_digest
                        && value.support_digest == support_digest
                        && value.generator_id == evidence.principal_id
                        && value.generator_scope_digest == evidence.scope_digest
                        && value.generator_authority_epoch == evidence.authority_epoch
                        && value.authentication_digest == authentication_digest''',
        "persisted decision comparison",
    )
    text = replace_once(
        text,
        '''        LearningPayloadV1::Outcome(payload) => {
            let Ok(expected) = payload.outcome.to_typed() else {
                return false;
            };
            matches!(
                &record.event,
                LedgerEvent::AuthenticatedOutcomeV2(value) if value == &expected
            )
        }''',
        '''        LearningPayloadV1::Outcome(payload) => {
            let Ok(expected) = payload.outcome.to_typed() else {
                return false;
            };
            let Ok(evidence) = payload
                .evidence
                .to_typed(LearningEvidenceRoleV1::Observer)
            else {
                return false;
            };
            let terminality = match expected.watermark.terminality {
                OutcomeTerminalityV1::Pending => AuthenticatedOutcomeTerminality::Pending,
                OutcomeTerminalityV1::Censored => AuthenticatedOutcomeTerminality::Censored,
                OutcomeTerminalityV1::Terminal => AuthenticatedOutcomeTerminality::Terminal,
            };
            let authentication_digest = learning_evidence_digest_v1(&evidence);
            matches!(
                &record.event,
                LedgerEvent::AuthenticatedOutcomeV2(value)
                    if value.record_id == expected.record_id
                        && value.outcome_id == expected.outcome_id
                        && value.episode_id == expected.episode_id
                        && value.observer_id == expected.observer.principal_id
                        && value.observer_credential_chain_digest
                            == expected.observer.credential_chain_digest
                        && value.observer_signing_key_digest
                            == expected.observer.signing_key_digest
                        && value.observer_scope_digest == expected.observer.scope_digest
                        && value.observer_authority_epoch == expected.observer.authority_epoch
                        && value.observed_at == expected.observed_at
                        && value.value == expected.value
                        && value.unit_profile_digest == expected.unit_profile_digest
                        && value.support_digest == expected.support_digest
                        && value.latest_observable_at
                            == expected.watermark.latest_observable_at
                        && value.expected_delay_profile_digest
                            == expected.watermark.expected_delay_profile_digest
                        && value.terminality == terminality
                        && value.censoring_reason == expected.watermark.censoring_reason
                        && value.correction_predecessor
                            == expected.watermark.correction_predecessor
                        && value.finalized_at == expected.watermark.finalized_at
                        && value.authentication_digest == authentication_digest
            )
        }''',
        "persisted outcome comparison",
    )
    text = replace_once(
        text,
        '''fn apply_payload(
    writer: &mut LedgerWriter,''',
        '''fn learning_evidence_digest_v1(evidence: &SignedLearningEvidenceV1) -> Digest32 {
    let mut bytes = evidence.signing_bytes();
    bytes.extend_from_slice(&evidence.signature);
    Digest32::of_bytes(&bytes)
}

fn apply_payload(
    writer: &mut LedgerWriter,''',
        "learning evidence digest helper",
    )
    PATH.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
