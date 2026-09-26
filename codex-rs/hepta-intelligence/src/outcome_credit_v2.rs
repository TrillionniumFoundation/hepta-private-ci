//! Authenticated post-execution Outcome/Credit closure for intelligence runs.
//!
//! The learning ledger remains the sole fact owner. This adapter binds an
//! already-observed outcome to the exact active durable Decision for a run and
//! delegates every mutation to `LedgerWriter`. Outcome and CreditBatch are
//! separate durable facts: if credit admission fails after the outcome commit,
//! the error preserves the committed outcome receipt so reconciliation retries
//! the same identities and never redispatches the run.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_learning_ledger::AppendReceipt;
use codex_hepta_learning_ledger::AuthenticatedOutcomeV1;
use codex_hepta_learning_ledger::CreditAllocationBatchV1;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::OutcomeTerminalityV1;
use codex_hepta_learning_ledger::ProductionLedgerError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::credit_batch_signing_payload_v2;
use codex_hepta_learning_ledger::finalize_credit_batch;
use codex_hepta_learning_ledger::outcome_signing_payload_v2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObservedOutcomeRequestV2 {
    pub run_id: StableId,
    pub expected_ledger_head: Digest32,
    pub outcome: AuthenticatedOutcomeV1,
    pub evidence: SignedLearningEvidenceV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OutcomeCreditClosureRequestV2 {
    pub outcome: ObservedOutcomeRequestV2,
    pub credit: CreditAllocationBatchV1,
    pub credit_evidence: SignedLearningEvidenceV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OutcomeCreditClosureReceiptV2 {
    pub run_id: StableId,
    pub episode_id: StableId,
    pub outcome: AppendReceipt,
    pub credit: AppendReceipt,
    pub closure_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Debug)]
pub enum OutcomeCreditClosureErrorV2 {
    Binding(&'static str),
    Outcome(ProductionLedgerError),
    Credit {
        outcome: AppendReceipt,
        error: ProductionLedgerError,
    },
}

impl fmt::Display for OutcomeCreditClosureErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for OutcomeCreditClosureErrorV2 {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Binding(_) => None,
            Self::Outcome(error) => Some(error),
            Self::Credit { error, .. } => Some(error),
        }
    }
}

/// Append one independently authenticated observed outcome after proving that
/// the run identity still names an active authenticated Decision for the same
/// episode. Corrections use the same operation with a correction predecessor.
pub fn append_observed_outcome_v2(
    ledger: &mut LedgerWriter,
    request: ObservedOutcomeRequestV2,
    now: u64,
) -> Result<AppendReceipt, OutcomeCreditClosureErrorV2> {
    if request.expected_ledger_head.is_zero() {
        return Err(OutcomeCreditClosureErrorV2::Binding(
            "missing decision/outcome predecessor",
        ));
    }
    ledger
        .verify_active_decision_binding(&request.run_id, &request.outcome.episode_id)
        .map_err(OutcomeCreditClosureErrorV2::Outcome)?;
    // Historical acknowledgement is not renewed write authority. Bind the
    // complete supplied payload before lookup, even when the evidence expired.
    if Digest32::of_bytes(&outcome_signing_payload_v2(&request.outcome))
        != request.evidence.payload_digest
    {
        return Err(OutcomeCreditClosureErrorV2::Binding(
            "outcome recovery payload",
        ));
    }
    let identity = ledger.authenticated_append_identity(
        &request.outcome.record_id,
        request.expected_ledger_head,
        &request.evidence,
    );
    if let Some(receipt) = ledger
        .recover_authenticated_append(&identity)
        .map_err(OutcomeCreditClosureErrorV2::Outcome)?
    {
        return Ok(receipt);
    }
    // Absence is not permission to write: normal live admission still applies.
    ledger
        .append_outcome(
            request.expected_ledger_head,
            request.outcome,
            &request.evidence,
            now,
        )
        .map_err(OutcomeCreditClosureErrorV2::Outcome)
}

/// Close a terminal learning episode with one authenticated terminal/corrected
/// Outcome followed by one authenticated conserved CreditBatch. Deterministic
/// request binding is checked before the first append. Signature/trust failure
/// on credit may occur after the outcome is durable; that partial commit is
/// returned explicitly and is safe to reconcile by retrying the same request.
pub fn append_outcome_credit_v2(
    ledger: &mut LedgerWriter,
    request: OutcomeCreditClosureRequestV2,
    now: u64,
) -> Result<OutcomeCreditClosureReceiptV2, OutcomeCreditClosureErrorV2> {
    validate_terminal_request(&request)?;
    let run_id = request.outcome.run_id.clone();
    let episode_id = request.outcome.outcome.episode_id.clone();

    let outcome_receipt = append_observed_outcome_v2(ledger, request.outcome, now)?;
    let credit_receipt = (|| {
        // Derive historical identity at the principal's declared authentication
        // time, not current authorization. Only an exact already-committed
        // record can use this path; an absent batch still validates `now` below.
        let finalized = finalize_credit_batch(
            request.credit.clone(),
            request.credit.allocator.authenticated_at,
        )
        .map_err(ProductionLedgerError::Causal)?;
        let payload = credit_batch_signing_payload_v2(&request.credit, finalized.batch_digest);
        if Digest32::of_bytes(&payload) != request.credit_evidence.payload_digest {
            return Err(ProductionLedgerError::Binding("credit recovery payload"));
        }
        let identity = ledger.authenticated_append_identity(
            &request.credit.batch_id,
            outcome_receipt.chain_digest,
            &request.credit_evidence,
        );
        if let Some(receipt) = ledger.recover_authenticated_append(&identity)? {
            return Ok(receipt);
        }
        ledger.append_credit_batch(
            outcome_receipt.chain_digest,
            request.credit,
            &request.credit_evidence,
            now,
        )
    })()
    .map_err(|error| OutcomeCreditClosureErrorV2::Credit {
        outcome: outcome_receipt.clone(),
        error,
    })?;

    let mut bytes = b"hepta.intelligence.outcome-credit-closure.v2\0".to_vec();
    push_id(&mut bytes, &run_id)?;
    push_id(&mut bytes, &episode_id)?;
    bytes.extend_from_slice(outcome_receipt.event_digest.as_array());
    bytes.extend_from_slice(outcome_receipt.chain_digest.as_array());
    bytes.extend_from_slice(credit_receipt.event_digest.as_array());
    bytes.extend_from_slice(credit_receipt.chain_digest.as_array());

    Ok(OutcomeCreditClosureReceiptV2 {
        run_id,
        episode_id,
        outcome: outcome_receipt,
        credit: credit_receipt,
        closure_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn validate_terminal_request(
    request: &OutcomeCreditClosureRequestV2,
) -> Result<(), OutcomeCreditClosureErrorV2> {
    if request.outcome.expected_ledger_head.is_zero() {
        return Err(OutcomeCreditClosureErrorV2::Binding(
            "missing decision/outcome predecessor",
        ));
    }
    if request.outcome.outcome.watermark.terminality != OutcomeTerminalityV1::Terminal {
        return Err(OutcomeCreditClosureErrorV2::Binding("non-terminal outcome"));
    }
    let Some(terminal_value) = request.outcome.outcome.value else {
        return Err(OutcomeCreditClosureErrorV2::Binding("non-terminal outcome"));
    };
    if request.credit.episode_id != request.outcome.outcome.episode_id {
        return Err(OutcomeCreditClosureErrorV2::Binding("episode"));
    }
    if request.credit.outcome_id != request.outcome.outcome.outcome_id {
        return Err(OutcomeCreditClosureErrorV2::Binding("outcome"));
    }
    if request.credit.terminal_outcome != terminal_value {
        return Err(OutcomeCreditClosureErrorV2::Binding("terminal value"));
    }
    if !request.credit.finalized {
        return Err(OutcomeCreditClosureErrorV2::Binding("credit not finalized"));
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), OutcomeCreditClosureErrorV2> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len())
        .map_err(|_| OutcomeCreditClosureErrorV2::Binding("identifier length"))?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
    use codex_hepta_learning_ledger::AppendDisposition;
    use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
    use codex_hepta_learning_ledger::CandidateSetCompletenessReceiptV1;
    use codex_hepta_learning_ledger::CreditAllocationV1;
    use codex_hepta_learning_ledger::DurableLedger;
    use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
    use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
    use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
    use codex_hepta_learning_ledger::LearningTrustDistributionV1;
    use codex_hepta_learning_ledger::LearningTrustRootV1;
    use codex_hepta_learning_ledger::LedgerWitnessStore;
    use codex_hepta_learning_ledger::OutcomeWatermarkV1;
    use codex_hepta_learning_ledger::ProductionDecisionV2;
    use codex_hepta_learning_ledger::SignedLearningTrustDistributionV1;
    use codex_hepta_learning_ledger::TrustedLearningSignerV1;
    use codex_hepta_learning_ledger::activate_learning_trust;
    use codex_hepta_learning_ledger::candidate_ids_digest_v2;
    use codex_hepta_learning_ledger::candidate_order_digest_v2;
    use codex_hepta_learning_ledger::credit_batch_signing_payload_v2;
    use codex_hepta_learning_ledger::decision_signing_payload_v2;
    use codex_hepta_learning_ledger::finalize_credit_batch;
    use codex_hepta_learning_ledger::outcome_signing_payload_v2;
    use codex_hepta_types::FixedQ32;
    use codex_hepta_types::ProbabilityQ32;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;
    use std::fs::File;
    use std::fs::OpenOptions;
    use std::path::PathBuf;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("fixture id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn trusted(
        name: &str,
        controller: &str,
        seed: u8,
        role: LearningEvidenceRoleV1,
    ) -> TrustedLearningSignerV1 {
        let key = SigningKey::from_bytes(&[seed; 32]);
        TrustedLearningSignerV1 {
            principal: AuthenticatedPrincipalV1 {
                principal_id: id(name),
                credential_chain_digest: digest(&format!("{name}-credential")),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                scope_digest: digest("scope"),
                authority_epoch: 7,
                authenticated_at: 10,
                expires_at: 100,
            },
            controller_id: id(controller),
            verifying_key: key.verifying_key().to_bytes(),
            roles: vec![role],
            revoked_at: None,
        }
    }

    fn trust() -> LearningEvidenceTrustV1 {
        LearningEvidenceTrustV1 {
            scope_digest: digest("scope"),
            objective_digest: digest("objective"),
            authority_epoch: 7,
            signers: vec![
                trusted(
                    "generator",
                    "generator-controller",
                    1,
                    LearningEvidenceRoleV1::Generator,
                ),
                trusted(
                    "observer",
                    "observer-controller",
                    2,
                    LearningEvidenceRoleV1::Observer,
                ),
                trusted(
                    "allocator",
                    "allocator-controller",
                    3,
                    LearningEvidenceRoleV1::CreditAllocator,
                ),
            ],
        }
    }

    fn principal(name: &str) -> AuthenticatedPrincipalV1 {
        trust()
            .signers
            .into_iter()
            .find(|signer| signer.principal.principal_id == id(name))
            .expect("principal")
            .principal
    }

    fn activated_trust() -> ActivatedLearningTrustV1 {
        let root_key = SigningKey::from_bytes(&[99; 32]);
        let root = LearningTrustRootV1 {
            root_id: id("learning-root"),
            scope_digest: digest("scope"),
            verifying_key: root_key.verifying_key().to_bytes(),
            valid_from: 1,
            expires_at: 200,
            revoked_at: None,
        };
        let mut signed = SignedLearningTrustDistributionV1 {
            distribution: LearningTrustDistributionV1 {
                distribution_id: id("trust-distribution"),
                generation: 1,
                effective_at: 20,
                trust: trust(),
            },
            root_id: root.root_id.clone(),
            issued_at: 15,
            expires_at: 90,
            signature: [0; 64],
        };
        signed.signature = root_key
            .sign(&signed.signing_bytes().expect("trust payload"))
            .to_bytes();
        activate_learning_trust(&root, signed, None, 50).expect("activated trust")
    }

    fn seed(name: &str) -> u8 {
        match name {
            "generator" => 1,
            "observer" => 2,
            "allocator" => 3,
            _ => panic!("unknown signer"),
        }
    }

    fn sign(
        verifier: &LearningEvidenceVerifierV1,
        name: &str,
        role: LearningEvidenceRoleV1,
        payload: &[u8],
    ) -> SignedLearningEvidenceV1 {
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: id(&format!("evidence-{name}-{}", Digest32::of_bytes(payload))),
            principal_id: id(name),
            role,
            trust_digest: verifier.trust_digest(),
            scope_digest: digest("scope"),
            objective_digest: digest("objective"),
            authority_epoch: 7,
            issued_at: 20,
            expires_at: 90,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        evidence.signature = SigningKey::from_bytes(&[seed(name); 32])
            .sign(&evidence.signing_bytes())
            .to_bytes();
        evidence
    }

    struct Fixture {
        _temp: tempfile::TempDir,
        ledger_path: PathBuf,
        witness_path: PathBuf,
    }

    impl Fixture {
        fn new() -> Self {
            let temp = tempfile::tempdir().expect("tempdir");
            let ledger_path = temp.path().join("ledger");
            let witness_path = temp.path().join("witness");
            File::create(&ledger_path).expect("ledger file");
            File::create(&witness_path).expect("witness file");
            Self {
                _temp: temp,
                ledger_path,
                witness_path,
            }
        }

        fn open(path: &PathBuf) -> File {
            OpenOptions::new()
                .read(true)
                .write(true)
                .open(path)
                .expect("open fixture")
        }

        fn directory(&self) -> File {
            File::open(self._temp.path()).expect("directory")
        }

        fn recover_writer(&self) -> LedgerWriter {
            let binding = digest("production-ledger-binding");
            let witness = LedgerWitnessStore::recover(Self::open(&self.witness_path), binding)
                .expect("recover witness");
            let frontier = witness.frontier().expect("witness frontier");
            let ledger = DurableLedger::recover(
                Self::open(&self.ledger_path),
                binding,
                32,
                LedgerRecovery::Acknowledged(frontier.anchor),
            )
            .expect("recover ledger");
            let directory = self.directory();
            LedgerWriter::from_durable(ledger, witness, activated_trust(), &directory, &directory)
                .expect("recover writer")
        }

        fn writer(&self) -> LedgerWriter {
            let binding = digest("production-ledger-binding");
            let ledger =
                DurableLedger::create(Self::open(&self.ledger_path), binding, 32).expect("ledger");
            let witness = LedgerWitnessStore::create(Self::open(&self.witness_path), binding)
                .expect("witness");
            let ledger_directory = self.directory();
            let witness_directory = self.directory();
            LedgerWriter::from_durable(
                ledger,
                witness,
                activated_trust(),
                &ledger_directory,
                &witness_directory,
            )
            .expect("writer")
        }
    }

    fn decision() -> ProductionDecisionV2 {
        let candidates = vec![id("action"), id("abstain")];
        ProductionDecisionV2 {
            record_id: id("run-v2"),
            episode_id: id("episode-v2"),
            run_snapshot_digest: digest("run-snapshot"),
            objective_digest: digest("objective"),
            policy_digest: digest("policy"),
            candidate_ids: candidates.clone(),
            selected_candidate_id: id("action"),
            selected_propensity: ProbabilityQ32::ONE,
            completeness: CandidateSetCompletenessReceiptV1 {
                set_id: id("candidate-set"),
                state_digest: digest("state"),
                generator_id: id("generator"),
                generator_code_digest: digest("generator-code"),
                grammar_digest: digest("grammar"),
                hard_filter_digest: digest("hard-filter"),
                truncation_digest: digest("truncation"),
                candidates_digest: candidate_ids_digest_v2(&candidates),
                candidate_count: 2,
                omitted_count_bound: 0,
                canonical_order_digest: candidate_order_digest_v2(&candidates),
                complete_for_generator: true,
            },
            support_digest: digest("decision-support"),
        }
    }

    fn append_decision(writer: &mut LedgerWriter) -> AppendReceipt {
        let request = decision();
        let payload = decision_signing_payload_v2(&request).expect("decision payload");
        let evidence = sign(
            writer.verifier(),
            "generator",
            LearningEvidenceRoleV1::Generator,
            &payload,
        );
        writer
            .append_decision(Digest32::ZERO, request, &evidence, 50)
            .expect("decision")
    }

    fn outcome(
        record_id: &str,
        outcome_id: &str,
        predecessor: Option<&str>,
        value: i64,
    ) -> AuthenticatedOutcomeV1 {
        AuthenticatedOutcomeV1 {
            record_id: id(record_id),
            outcome_id: id(outcome_id),
            episode_id: id("episode-v2"),
            observer: principal("observer"),
            observed_at: Some(40),
            value: Some(FixedQ32::from_raw(value)),
            unit_profile_digest: digest("reward-unit"),
            support_digest: digest("outcome-support"),
            watermark: OutcomeWatermarkV1 {
                latest_observable_at: 45,
                expected_delay_profile_digest: digest("delay-profile"),
                terminality: OutcomeTerminalityV1::Terminal,
                censoring_reason: None,
                correction_predecessor: predecessor.map(id),
                finalized_at: Some(46),
            },
        }
    }

    fn observed_request(
        writer: &LedgerWriter,
        expected: Digest32,
        value: AuthenticatedOutcomeV1,
    ) -> ObservedOutcomeRequestV2 {
        let payload = outcome_signing_payload_v2(&value);
        let evidence = sign(
            writer.verifier(),
            "observer",
            LearningEvidenceRoleV1::Observer,
            &payload,
        );
        ObservedOutcomeRequestV2 {
            run_id: id("run-v2"),
            expected_ledger_head: expected,
            outcome: value,
            evidence,
        }
    }

    fn credit(outcome_id: &str, value: i64) -> CreditAllocationBatchV1 {
        CreditAllocationBatchV1 {
            batch_id: id(&format!("credit-{outcome_id}")),
            episode_id: id("episode-v2"),
            outcome_id: id(outcome_id),
            allocator: principal("allocator"),
            terminal_outcome: FixedQ32::from_raw(value),
            allocations: vec![CreditAllocationV1 {
                target_id: id("artifact-a"),
                credit: FixedQ32::from_raw(value),
            }],
            conservation_residual: FixedQ32::ZERO,
            support_digest: digest("credit-support"),
            finalized: true,
        }
    }

    fn closure_request(
        writer: &LedgerWriter,
        expected: Digest32,
        outcome: AuthenticatedOutcomeV1,
        credit: CreditAllocationBatchV1,
    ) -> OutcomeCreditClosureRequestV2 {
        let observed = observed_request(writer, expected, outcome);
        let batch_digest = finalize_credit_batch(credit.clone(), 50)
            .expect("credit finalize")
            .batch_digest;
        let payload = credit_batch_signing_payload_v2(&credit, batch_digest);
        let evidence = sign(
            writer.verifier(),
            "allocator",
            LearningEvidenceRoleV1::CreditAllocator,
            &payload,
        );
        OutcomeCreditClosureRequestV2 {
            outcome: observed,
            credit,
            credit_evidence: evidence,
        }
    }

    #[test]
    fn product_path_records_outcome_correction_then_conserved_credit() {
        let fixture = Fixture::new();
        let mut writer = fixture.writer();
        let decision = append_decision(&mut writer);

        let initial = outcome("outcome-record-1", "outcome-1", None, 100);
        let initial_request = observed_request(&writer, decision.chain_digest, initial);
        let first =
            append_observed_outcome_v2(&mut writer, initial_request, 50).expect("initial outcome");

        let corrected = outcome("outcome-record-2", "outcome-2", Some("outcome-1"), 120);
        let request = closure_request(
            &writer,
            first.chain_digest,
            corrected,
            credit("outcome-2", 120),
        );
        let receipt = append_outcome_credit_v2(&mut writer, request.clone(), 50)
            .expect("corrected terminal closure");
        assert_eq!(receipt.outcome.disposition, AppendDisposition::Appended);
        assert_eq!(receipt.credit.disposition, AppendDisposition::Appended);
        assert!(!receipt.authority.grants_any());
        assert_eq!(
            writer.witness_frontier().expect("frontier").anchor.sequence,
            4
        );

        let replay = append_outcome_credit_v2(&mut writer, request, 50).expect("replay");
        assert_eq!(
            replay.outcome.disposition,
            AppendDisposition::IdempotentReplay
        );
        assert_eq!(
            replay.credit.disposition,
            AppendDisposition::IdempotentReplay
        );
        assert_eq!(replay.closure_digest, receipt.closure_digest);
    }

    #[test]
    fn credit_failure_preserves_outcome_for_exact_reconciliation() {
        let fixture = Fixture::new();
        let mut writer = fixture.writer();
        let decision = append_decision(&mut writer);
        let terminal = outcome("outcome-record-1", "outcome-1", None, 100);
        let mut request = closure_request(
            &writer,
            decision.chain_digest,
            terminal,
            credit("outcome-1", 100),
        );
        request.credit_evidence.signature[0] ^= 0x80;
        let error = append_outcome_credit_v2(&mut writer, request.clone(), 50)
            .expect_err("credit signature must fail");
        let committed = match error {
            OutcomeCreditClosureErrorV2::Credit { outcome, .. } => outcome,
            other => panic!("expected partial credit failure, got {other:?}"),
        };
        assert_eq!(committed.disposition, AppendDisposition::Appended);
        assert_eq!(
            writer.witness_frontier().expect("frontier").anchor.sequence,
            2
        );

        let batch_digest = finalize_credit_batch(request.credit.clone(), 50)
            .expect("credit finalize")
            .batch_digest;
        let payload = credit_batch_signing_payload_v2(&request.credit, batch_digest);
        request.credit_evidence = sign(
            writer.verifier(),
            "allocator",
            LearningEvidenceRoleV1::CreditAllocator,
            &payload,
        );
        let reconciled = append_outcome_credit_v2(&mut writer, request, 50)
            .expect("reconcile exact outcome then credit");
        assert_eq!(
            reconciled.outcome.disposition,
            AppendDisposition::IdempotentReplay
        );
        assert_eq!(reconciled.credit.disposition, AppendDisposition::Appended);
        assert_eq!(
            writer.witness_frontier().expect("frontier").anchor.sequence,
            3
        );
    }

    #[test]
    fn run_episode_mismatch_rejects_before_any_outcome_append() {
        let fixture = Fixture::new();
        let mut writer = fixture.writer();
        let decision = append_decision(&mut writer);
        let terminal = outcome("outcome-record-1", "outcome-1", None, 100);
        let mut observed = observed_request(&writer, decision.chain_digest, terminal);
        observed.run_id = id("different-run");

        assert!(matches!(
            append_observed_outcome_v2(&mut writer, observed, 50),
            Err(OutcomeCreditClosureErrorV2::Outcome(
                ProductionLedgerError::Binding("active decision run/episode binding")
            ))
        ));
        assert_eq!(
            writer.witness_frontier().expect("frontier").anchor.sequence,
            1
        );
    }

    use codex_hepta_learning_ledger::LedgerRecovery;

    #[test]
    fn terminal_retry_after_reopen_and_signature_expiry_returns_original_receipt() {
        let fixture = Fixture::new();
        let mut writer = fixture.writer();
        let decision = append_decision(&mut writer);
        let observed = outcome("outcome-recovery-record", "outcome-recovery", None, 100);
        let request = observed_request(&writer, decision.chain_digest, observed);
        let committed =
            append_observed_outcome_v2(&mut writer, request.clone(), 50).expect("append");
        let before = writer.snapshot().expect("snapshot");
        let frontier = writer.witness_frontier().expect("frontier");
        drop(writer);
        let binding = digest("production-ledger-binding");
        let ledger = DurableLedger::recover(
            Fixture::open(&fixture.ledger_path),
            binding,
            32,
            LedgerRecovery::Acknowledged(frontier.anchor),
        )
        .expect("recover ledger");
        let witness = LedgerWitnessStore::recover(Fixture::open(&fixture.witness_path), binding)
            .expect("recover witness");
        let directory = fixture.directory();
        let mut writer =
            LedgerWriter::from_durable(ledger, witness, activated_trust(), &directory, &directory)
                .expect("recover writer");
        let recovered = append_observed_outcome_v2(&mut writer, request.clone(), 500)
            .expect("historical receipt needs no renewed signature");
        assert_eq!(recovered.disposition, AppendDisposition::IdempotentReplay);
        assert_eq!(recovered.chain_digest, committed.chain_digest);
        assert_eq!(recovered.event_digest, committed.event_digest);
        assert_eq!(writer.snapshot().expect("snapshot"), before);
        assert_eq!(writer.witness_frontier().expect("frontier"), frontier);

        let mut changed = request.clone();
        changed.outcome.value = Some(FixedQ32::from_raw(999));
        assert!(matches!(
            append_observed_outcome_v2(&mut writer, changed, 500),
            Err(OutcomeCreditClosureErrorV2::Binding(
                "outcome recovery payload"
            ))
        ));
        let mut changed = request.clone();
        changed.run_id = id("wrong-run");
        assert!(append_observed_outcome_v2(&mut writer, changed, 500).is_err());
        let mut changed = request.clone();
        changed.expected_ledger_head = digest("wrong-predecessor");
        assert!(append_observed_outcome_v2(&mut writer, changed, 500).is_err());
        let mut changed = request;
        changed.evidence.signature[0] ^= 1;
        assert!(append_observed_outcome_v2(&mut writer, changed, 500).is_err());
        assert_eq!(writer.snapshot().expect("unchanged snapshot"), before);
    }

    #[test]
    fn absent_outcome_cannot_use_expired_evidence_as_recovery_authority() {
        let fixture = Fixture::new();
        let mut writer = fixture.writer();
        let decision = append_decision(&mut writer);
        let observed = outcome("absent-outcome-record", "absent-outcome", None, 100);
        let request = observed_request(&writer, decision.chain_digest, observed);
        let before = writer.snapshot().expect("snapshot");
        assert!(append_observed_outcome_v2(&mut writer, request, 500).is_err());
        assert_eq!(writer.snapshot().expect("unchanged snapshot"), before);
    }

    #[test]
    fn full_closure_recovery_preserves_receipts_and_rejects_changed_credit() {
        let fixture = Fixture::new();
        let mut writer = fixture.writer();
        let decision = append_decision(&mut writer);
        let request = closure_request(
            &writer,
            decision.chain_digest,
            outcome("closed-record", "closed", None, 100),
            credit("closed", 100),
        );
        let mut expected = append_outcome_credit_v2(&mut writer, request.clone(), 50)
            .expect("commit complete closure");
        let before = writer.snapshot().expect("snapshot");
        drop(writer);
        let mut writer = fixture.recover_writer();
        expected.outcome.disposition = AppendDisposition::IdempotentReplay;
        expected.credit.disposition = AppendDisposition::IdempotentReplay;
        assert_eq!(
            append_outcome_credit_v2(&mut writer, request.clone(), 500)
                .expect("recover expired closure"),
            expected
        );
        assert_eq!(
            append_outcome_credit_v2(&mut writer, request.clone(), 1000)
                .expect("repeated recovery"),
            expected
        );
        for mutation in 0..4 {
            let mut changed = request.clone();
            match mutation {
                0 => changed.credit.allocations[0].target_id = id("different-artifact"),
                1 => changed.credit.support_digest = digest("different-credit-support"),
                2 => changed.credit.allocator.authority_epoch += 1,
                3 => changed.credit_evidence.signature[0] ^= 1,
                _ => unreachable!(),
            }
            assert!(matches!(
                append_outcome_credit_v2(&mut writer, changed, 500),
                Err(OutcomeCreditClosureErrorV2::Credit { .. })
            ));
        }
        assert_eq!(writer.snapshot().expect("unchanged snapshot"), before);
    }

    #[test]
    fn partial_closure_recovery_never_uses_expired_authority_for_missing_credit() {
        let fixture = Fixture::new();
        let mut writer = fixture.writer();
        let decision = append_decision(&mut writer);
        let request = closure_request(
            &writer,
            decision.chain_digest,
            outcome("partial-record", "partial", None, 100),
            credit("partial", 100),
        );
        let mut expected = append_observed_outcome_v2(&mut writer, request.outcome.clone(), 50)
            .expect("commit outcome only");
        let before = writer.snapshot().expect("snapshot");
        drop(writer);
        let mut writer = fixture.recover_writer();
        expected.disposition = AppendDisposition::IdempotentReplay;
        match append_outcome_credit_v2(&mut writer, request, 500) {
            Err(OutcomeCreditClosureErrorV2::Credit { outcome, .. }) => {
                assert_eq!(outcome, expected);
            }
            other => panic!("missing credit requires current authority: {other:?}"),
        }
        assert_eq!(writer.snapshot().expect("unchanged snapshot"), before);
    }

    #[test]
    fn full_closure_survives_process_exit_after_commit() {
        const CHILD_DIRECTORY: &str = "HEPTA_TEST_OUTCOME_CREDIT_CRASH_DIRECTORY";
        if let Some(directory) = std::env::var_os(CHILD_DIRECTORY) {
            let directory = PathBuf::from(directory);
            let binding = digest("production-ledger-binding");
            let ledger =
                DurableLedger::create(Fixture::open(&directory.join("ledger")), binding, 32)
                    .expect("child ledger");
            let witness =
                LedgerWitnessStore::create(Fixture::open(&directory.join("witness")), binding)
                    .expect("child witness");
            let handle = File::open(&directory).expect("child directory");
            let mut writer =
                LedgerWriter::from_durable(ledger, witness, activated_trust(), &handle, &handle)
                    .expect("child writer");
            let decision = append_decision(&mut writer);
            let request = closure_request(
                &writer,
                decision.chain_digest,
                outcome("crash-record", "crash", None, 100),
                credit("crash", 100),
            );
            append_outcome_credit_v2(&mut writer, request, 50).expect("child durable commit");
            // Exit without destructors or an application-level acknowledgement.
            // This tests real process recovery, not a live provider/model claim.
            std::process::exit(73);
        }
        let fixture = Fixture::new();
        let output = std::process::Command::new(std::env::current_exe().expect("test executable"))
            .args([
                "--exact",
                "outcome_credit_v2::tests::full_closure_survives_process_exit_after_commit",
                "--nocapture",
            ])
            .env(CHILD_DIRECTORY, fixture._temp.path())
            .output()
            .expect("spawn independent writer process");
        assert_eq!(
            output.status.code(),
            Some(73),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        let mut writer = fixture.recover_writer();
        let before = writer.snapshot().expect("recovered snapshot");
        let records = writer.records().expect("recovered records");
        assert_eq!(records.len(), 3);
        let request = closure_request(
            &writer,
            records[0].chain_digest,
            outcome("crash-record", "crash", None, 100),
            credit("crash", 100),
        );
        let recovered = append_outcome_credit_v2(&mut writer, request, 500)
            .expect("recover exact historical outcome and credit");
        assert_eq!(
            (
                recovered.outcome.event_digest,
                recovered.credit.event_digest
            ),
            (records[1].event_digest, records[2].event_digest)
        );
        assert_eq!(
            (recovered.outcome.disposition, recovered.credit.disposition),
            (
                AppendDisposition::IdempotentReplay,
                AppendDisposition::IdempotentReplay
            )
        );
        assert_eq!(writer.snapshot().expect("unchanged snapshot"), before);
    }
}
