//! Synthetic role credentials and virtual time test admission mechanics only.
use super::*;
use crate::CitationAuditJudgementV1;
use crate::CitationAuditRequestV1;
use crate::CitationClaimKindV1;
use crate::CitationClaimV1;
use crate::CitationJudgementV1;
use crate::CitationSourceV1;
use crate::CitationVerdictV1;
use crate::ObservedFutureWindowV1;
use crate::citation_judgement_payload_v1;
use crate::citation_request_payload_v1;
use crate::verify_signed_citation_audit_v1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn d(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture id")
}

struct Fixture {
    keys: [SigningKey; 3],
    verifier: LearningEvidenceVerifierV1,
    selection: SelfEvolutionSelectionReceiptV1,
    census: MemoryCitationCensusV1,
    audits: Vec<VerifiedCitationAuditV1>,
    timing: LongitudinalTimeEvidenceV1,
}
#[derive(Clone, Copy)]
enum Data {
    Valid,
    SmallPerfect,
    ReusedRoot,
    WrongExperiment,
    LowPrecision,
    Abstain,
}
impl Fixture {
    fn new(data: Data) -> Self {
        let keys = [
            SigningKey::from_bytes(&[51; 32]),
            SigningKey::from_bytes(&[52; 32]),
            SigningKey::from_bytes(&[53; 32]),
        ];
        let roles = [
            LearningEvidenceRoleV1::Generator,
            LearningEvidenceRoleV1::Evaluator,
            LearningEvidenceRoleV1::Observer,
        ];
        let signers = keys
            .iter()
            .enumerate()
            .map(|(index, key)| TrustedLearningSignerV1 {
                principal: AuthenticatedPrincipalV1 {
                    principal_id: id(&format!("actor-{index}")),
                    credential_chain_digest: d(&format!("credential-{index}")),
                    signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                    scope_digest: d("scope"),
                    authority_epoch: 1,
                    authenticated_at: 1,
                    expires_at: 200,
                },
                controller_id: id(&format!("controller-{index}")),
                verifying_key: key.verifying_key().to_bytes(),
                roles: vec![roles[index]],
                revoked_at: None,
            })
            .collect();
        let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: d("scope"),
            objective_digest: d("objective"),
            authority_epoch: 1,
            signers,
        })
        .expect("test trust");
        let selection = SelfEvolutionSelectionReceiptV1 {
            selection_id: id("s"),
            objective_digest: d("objective"),
            predecessor_id: id("old"),
            predecessor_generation: Generation::new(1).expect("generation"),
            predecessor_artifact_digest: d("old"),
            candidate_id: id("new"),
            candidate_generation: Generation::new(2).expect("generation"),
            candidate_artifact_digest: d("new"),
            no_change_baseline_id: id("baseline"),
            no_change_baseline_digest: d("baseline"),
            dataset_digest: d("dataset"),
            ledger_head_digest: d("ledger"),
            evaluation_evidence_digest: d("eval"),
            evaluation_authentication_digest: d("auth"),
            evaluation_trust_digest: verifier.trust_digest(),
            frozen_plan_digest: d("plan"),
            minimum_dataset_records: 200,
            minimum_future_window_micros: 10,
            authority: AuthorityPosture::DENY_ALL,
        };
        let dummy = SignedLearningEvidenceV1 {
            evidence_id: id("dummy"),
            principal_id: id("actor-2"),
            role: LearningEvidenceRoleV1::Observer,
            trust_digest: verifier.trust_digest(),
            scope_digest: d("scope"),
            objective_digest: d("objective"),
            authority_epoch: 1,
            issued_at: 80,
            expires_at: 190,
            payload_digest: d("dummy"),
            signature: [0; 64],
        };
        let mut f = Self {
            keys,
            verifier,
            selection,
            census: MemoryCitationCensusV1 {
                selection_digest: d("selection-token"),
                snapshots: Vec::new(),
            },
            audits: Vec::new(),
            timing: LongitudinalTimeEvidenceV1 {
                frozen_unix_micros: 20,
                windows: Vec::new(),
                observer: dummy,
            },
        };
        let per_snapshot = if matches!(data, Data::SmallPerfect) {
            70
        } else {
            120
        };
        for snapshot in 0..3 {
            let starts = 1 + snapshot as u64 * 25;
            let mut requests = Vec::new();
            for row in 0..per_snapshot {
                let i = snapshot * per_snapshot + row;
                let extra = matches!(data, Data::LowPrecision) && i < 3;
                let abstain = matches!(data, Data::Abstain);
                let answer = if abstain {
                    "I cannot answer."
                } else if extra {
                    "Blue [E1] [E2]."
                } else {
                    "Blue [E1]."
                };
                let request = CitationAuditRequestV1 {
                    query_id: format!("q-{i}"),
                    scope: "scope".into(),
                    experiment_digest: if matches!(data, Data::WrongExperiment) {
                        d("other-plan")
                    } else {
                        d("plan")
                    },
                    family_digest: d(&format!("family-{i}")),
                    prompt_digest: d(&format!("prompt-{i}")),
                    question: "Which color?".into(),
                    question_time: "virtual-test-time".into(),
                    answer: answer.into(),
                    sources: if abstain {
                        Vec::new()
                    } else {
                        vec![CitationSourceV1 {
                            label: "E1".into(),
                            identity: format!("source-{i}"),
                            source_root: if matches!(data, Data::ReusedRoot) {
                                d("one-root")
                            } else {
                                d(&format!("root-{i}"))
                            },
                            excerpt: "Blue.".into(),
                        }]
                    },
                };
                let mut citations = if abstain {
                    Vec::new()
                } else {
                    vec![CitationJudgementV1 {
                        start: 5,
                        verdict: CitationVerdictV1::Entailed,
                    }]
                };
                if extra {
                    citations.push(CitationJudgementV1 {
                        start: 10,
                        verdict: CitationVerdictV1::Unsupported,
                    });
                }
                let judgement = CitationAuditJudgementV1 {
                    claims: vec![CitationClaimV1 {
                        start: 0,
                        end: answer.len() as u32,
                        kind: if abstain {
                            CitationClaimKindV1::Abstention
                        } else {
                            CitationClaimKindV1::Factual
                        },
                    }],
                    citations,
                };
                let request_bytes = citation_request_payload_v1(&request).expect("request");
                let judged_bytes =
                    citation_judgement_payload_v1(&request, &judgement).expect("judgement");
                f.audits.push(
                    verify_signed_citation_audit_v1(
                        &request,
                        &judgement,
                        &f.sign(0, &request_bytes),
                        &f.sign(1, &judged_bytes),
                        &f.verifier,
                        &BTreeSet::new(),
                        85,
                    )
                    .expect("signed fixture audit"),
                );
                requests.push(Digest32::of_bytes(&request_bytes));
            }
            let snapshot_id = id(&format!("snapshot-{snapshot}"));
            let cut = d(&format!("cut-{snapshot}"));
            f.census.snapshots.push(MemorySnapshotCensusV1 {
                snapshot_id: snapshot_id.clone(),
                source_cut: cut,
                delivery_log_head: d(&format!("log-{snapshot}")),
                starts_unix_micros: starts,
                ends_unix_micros: starts + 20,
                attempted_deliveries: per_snapshot as u64,
                request_digests: requests,
            });
            if snapshot > 0 {
                f.timing.windows.push(ObservedFutureWindowV1 {
                    window_id: id(&format!("w-{snapshot}")),
                    snapshot_id,
                    starts_unix_micros: starts,
                    ends_unix_micros: starts + 20,
                    observation_count: per_snapshot as u64,
                    observed_source_cut: cut,
                });
            }
        }
        f
    }
    fn sign(&self, index: usize, payload: &[u8]) -> SignedLearningEvidenceV1 {
        let role = [
            LearningEvidenceRoleV1::Generator,
            LearningEvidenceRoleV1::Evaluator,
            LearningEvidenceRoleV1::Observer,
        ][index];
        let mut signed = SignedLearningEvidenceV1 {
            evidence_id: id(&format!("evidence-{index}")),
            principal_id: id(&format!("actor-{index}")),
            role,
            trust_digest: self.verifier.trust_digest(),
            scope_digest: d("scope"),
            objective_digest: d("objective"),
            authority_epoch: 1,
            issued_at: 80,
            expires_at: 190,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        signed.signature = self.keys[index].sign(&signed.signing_bytes()).to_bytes();
        signed
    }
    fn check(&self) -> Result<VerifiedMemoryCitationGateV1, CitationAuditError> {
        let signed = self.sign(2, &memory_citation_census_payload_v1(&self.census)?);
        verify_census(
            CensusContext {
                selection: &self.selection,
                snapshot_ids: &self
                    .census
                    .snapshots
                    .iter()
                    .map(|s| s.snapshot_id.clone())
                    .collect::<Vec<_>>(),
                timing: &self.timing,
                verifier: &self.verifier,
                revoked_roots: &BTreeSet::new(),
                now: 85,
            },
            &self.census,
            &signed,
            self.audits.clone(),
        )
    }
}

#[test]
fn complete_signed_census_counts_unique_sources_and_is_not_authority() {
    let f = Fixture::new(Data::Valid);
    let gate = f.check().expect("complete fixture census");
    assert_eq!(
        gate.counts(),
        MemoryCitationGateCountsV1 {
            audited_deliveries: 360,
            independent_source_groups: 360,
            snapshots: 3,
            citations: 360,
            entailed: 360,
            factual_claims: 360
        }
    );
    assert_eq!(gate.authority(), AuthorityPosture::DENY_ALL);
    assert_eq!(gate.decision_digest(), f.census.selection_digest);
}

#[test]
fn an_old_census_cannot_outlive_trust_source_withdrawal_or_clock() {
    let f = Fixture::new(Data::Valid);
    let gate = f.check().expect("complete census");
    assert!(
        gate.revalidate_current(&f.verifier, &BTreeSet::new(), 86)
            .is_ok()
    );
    for now in [84, 191] {
        assert!(
            gate.revalidate_current(&f.verifier, &BTreeSet::new(), now)
                .is_err()
        );
    }
    assert!(
        gate.revalidate_current(&f.verifier, &BTreeSet::from([d("root-0")]), 86)
            .is_err()
    );
}

#[test]
fn duplicate_roots_wrong_experiments_abstentions_and_low_precision_fail() {
    for data in [
        Data::ReusedRoot,
        Data::WrongExperiment,
        Data::LowPrecision,
        Data::Abstain,
    ] {
        assert!(Fixture::new(data).check().is_err());
    }
}

#[test]
fn missing_audits_and_renamed_snapshots_cannot_shrink_the_denominator() {
    let mut f = Fixture::new(Data::Valid);
    f.audits.pop();
    assert!(f.check().is_err());
    let mut f = Fixture::new(Data::Valid);
    f.census.snapshots[0].attempted_deliveries += 1;
    assert!(f.check().is_err());
    let mut f = Fixture::new(Data::Valid);
    f.census.snapshots[1].source_cut = f.census.snapshots[0].source_cut;
    assert!(f.check().is_err());
    let mut f = Fixture::new(Data::Valid);
    f.census.snapshots[1].request_digests[0] = f.census.snapshots[0].request_digests[0];
    assert!(f.check().is_err());
}

#[test]
fn changed_time_count_and_unobserved_intervals_reject() {
    let mut f = Fixture::new(Data::Valid);
    f.timing.windows[0].observation_count += 1;
    assert!(f.check().is_err());
    let mut f = Fixture::new(Data::Valid);
    f.census.snapshots[2].ends_unix_micros = 95;
    assert!(f.check().is_err());
    let mut f = Fixture::new(Data::Valid);
    f.census.snapshots[2].starts_unix_micros += 1;
    assert!(f.check().is_err());
}

#[test]
fn forged_signature_and_generator_as_census_observer_are_rejected() {
    let f = Fixture::new(Data::Valid);
    let payload = memory_citation_census_payload_v1(&f.census).expect("payload");
    let mut forged = f.sign(2, &payload);
    forged.signature[0] ^= 1;
    for signed in [forged, f.sign(0, &payload)] {
        assert!(
            verify_census(
                CensusContext {
                    selection: &f.selection,
                    snapshot_ids: &f
                        .census
                        .snapshots
                        .iter()
                        .map(|s| s.snapshot_id.clone())
                        .collect::<Vec<_>>(),
                    timing: &f.timing,
                    verifier: &f.verifier,
                    revoked_roots: &BTreeSet::new(),
                    now: 85
                },
                &f.census,
                &signed,
                f.audits.clone()
            )
            .is_err()
        );
    }
}

#[test]
fn signed_perfect_but_small_census_is_not_99_percent_confidence() {
    let f = Fixture::new(Data::SmallPerfect);
    assert!(matches!(
        f.check(),
        Err(CitationAuditError::Invalid("insufficient family-level citation confidence"))
    ));
}

#[test]
fn signed_micro_precision_above_99_percent_can_still_fail_confidence() {
    // 360 entailed of 363 citations: observed precision > 99%, with three
    // distinct family errors. Complete authentic signatures are insufficient.
    let f = Fixture::new(Data::LowPrecision);
    assert!(matches!(
        f.check(),
        Err(CitationAuditError::Invalid("insufficient family-level citation confidence"))
    ));
}
