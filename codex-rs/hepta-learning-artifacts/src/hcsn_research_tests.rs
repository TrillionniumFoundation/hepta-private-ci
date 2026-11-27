use super::*;
use crate::test_support::FixtureValue;
use pretty_assertions::assert_eq;

fn fixture() -> (
    HcsnResearchRequestV2,
    HcsnResearchOutcomeV2,
    Vec<HcsnParameterV2>,
) {
    let parameters = vec![
        HcsnParameterV2 {
            id: StableId::new("dynamics").fixture("id"),
            role: HcsnParameterRoleV2::Dynamics,
            bytes: 0.5_f64.to_le_bytes().to_vec(),
        },
        HcsnParameterV2 {
            id: StableId::new("readout").fixture("id"),
            role: HcsnParameterRoleV2::Readout,
            bytes: 0.0_f64.to_le_bytes().to_vec(),
        },
    ];
    let mask = vec![parameters[1].id.clone()];
    let digest = Digest32::of_bytes(b"admitted context fixture");
    let binding = HcsnResearchBindingV2 {
        request_digest: digest,
        base_checkpoint_digest: digest,
        code_digest: digest,
        dataset_digest: digest,
        runtime_digest: digest,
        backend_state_schema_digest: digest,
        base_parameters_digest: hcsn_parameters_digest_v2(&parameters).fixture("parameters"),
        parameter_mask_digest: hcsn_parameter_mask_digest_v2(&mask).fixture("mask"),
    };
    let request = HcsnResearchRequestV2 {
        binding,
        rule: HcsnLearningRuleV2::ClosedFormReadout,
        trainable_parameters: mask,
        maximum_elapsed_micros: 100,
        maximum_peak_working_bytes: 1_024,
    };
    let outcome = HcsnResearchOutcomeV2 {
        binding,
        evidence: HcsnRuleEvidenceV2::ClosedFormReadout {
            solve_receipt_digest: digest,
        },
        discovery: HcsnResearchCostV2::default(),
        application: HcsnResearchCostV2 {
            elapsed_micros: 20,
            forward_calls: 2,
            peak_working_bytes: 128,
            ..HcsnResearchCostV2::default()
        },
        evaluation: HcsnResearchCostV2 {
            elapsed_micros: 10,
            forward_calls: 1,
            ..HcsnResearchCostV2::default()
        },
        receipt_digest: Digest32::ZERO,
    };
    (request, outcome, parameters)
}

fn validate(
    request: &HcsnResearchRequestV2,
    outcome: &HcsnResearchOutcomeV2,
    before: &[HcsnParameterV2],
    after: &[HcsnParameterV2],
) -> Result<HcsnResearchDispositionV2, HcsnResearchErrorV2> {
    let mut signed = outcome.clone();
    let receipt =
        signed.encode_receipt(hcsn_parameters_digest_v2(after).fixture("parameter digest"));
    signed.receipt_digest = Digest32::of_bytes(&receipt);
    validate_hcsn_research_outcome_v2(request, &signed, before, after, &receipt)
}

#[test]
fn readout_solve_changes_only_admitted_bytes_and_unchanged_bytes_are_no_update() {
    let (request, outcome, before) = fixture();
    let mut after = before.clone();
    let samples = [(1.0_f64, 2.0_f64), (2.0, 4.0)];
    let solution = samples.iter().map(|(x, y)| x * y).sum::<f64>()
        / samples.iter().map(|(x, _)| x * x).sum::<f64>();
    after[1].bytes = solution.to_le_bytes().to_vec();
    assert_eq!(
        validate(&request, &outcome, &before, &after),
        Ok(HcsnResearchDispositionV2::Candidate {
            parameters_digest: hcsn_parameters_digest_v2(&after).fixture("candidate"),
            changed_parameters: vec![after[1].id.clone()]
        })
    );
    assert_eq!(
        validate(&request, &outcome, &before, &before),
        Ok(HcsnResearchDispositionV2::NoUpdate)
    );
    after[0].bytes[0] ^= 1;
    assert_eq!(
        validate(&request, &outcome, &before, &after),
        Err(HcsnResearchErrorV2::Mask)
    );
}

#[test]
fn explicit_bp_requires_backward_work_and_cannot_relabel_closed_form() {
    let (mut request, mut outcome, before) = fixture();
    let mut after = before.clone();
    after[1].bytes = 2.0_f64.to_le_bytes().to_vec();
    request.rule = HcsnLearningRuleV2::TaskBp;
    assert_eq!(
        validate(&request, &outcome, &before, &after),
        Err(HcsnResearchErrorV2::Rule)
    );
    outcome.evidence = HcsnRuleEvidenceV2::TaskBp {
        gradient_digest: Digest32::ZERO,
    };
    assert_eq!(
        validate(&request, &outcome, &before, &before),
        Ok(HcsnResearchDispositionV2::NoUpdate)
    );
    outcome.application.optimizer_steps = 1;
    assert_eq!(
        validate(&request, &outcome, &before, &before),
        Err(HcsnResearchErrorV2::Rule)
    );
    assert_eq!(
        validate(&request, &outcome, &before, &after),
        Err(HcsnResearchErrorV2::Rule)
    );
    outcome.evidence = HcsnRuleEvidenceV2::TaskBp {
        gradient_digest: Digest32::of_bytes(b"actual-gradient-fixture"),
    };
    outcome.application.backward_calls = 1;
    assert!(matches!(
        validate(&request, &outcome, &before, &after),
        Ok(HcsnResearchDispositionV2::Candidate { .. })
    ));
}

#[test]
fn programmatic_edit_accounts_for_discovery_even_without_optimizer_application() {
    let (mut request, mut outcome, before) = fixture();
    let mut after = before.clone();
    after[1].bytes[0] = 1;
    request.rule = HcsnLearningRuleV2::ProgrammaticWeightEdit;
    outcome.evidence = HcsnRuleEvidenceV2::ProgrammaticWeightEdit {
        program_digest: Digest32::of_bytes(b"edit program"),
        discovery_receipt_digest: Digest32::of_bytes(b"discovery including training"),
    };
    assert_eq!(
        validate(&request, &outcome, &before, &after),
        Err(HcsnResearchErrorV2::Rule)
    );
    outcome.discovery = HcsnResearchCostV2 {
        elapsed_micros: 60,
        backward_calls: 40,
        optimizer_steps: 40,
        ..HcsnResearchCostV2::default()
    };
    assert!(matches!(
        validate(&request, &outcome, &before, &after),
        Ok(HcsnResearchDispositionV2::Candidate { .. })
    ));
    outcome.discovery.elapsed_micros = 71;
    assert_eq!(
        validate(&request, &outcome, &before, &after),
        Err(HcsnResearchErrorV2::Cost)
    );
    outcome.discovery.elapsed_micros = u64::MAX;
    assert_eq!(
        validate(&request, &outcome, &before, &after),
        Err(HcsnResearchErrorV2::Cost)
    );
}

#[test]
fn rejects_context_substitution_receipt_corruption_and_parameter_schema_changes() {
    let (request, outcome, before) = fixture();
    let other = Digest32::of_bytes(b"substituted context");
    for field in 0..8 {
        let mut altered = outcome.clone();
        let b = &mut altered.binding;
        let digests = [
            &mut b.request_digest,
            &mut b.base_checkpoint_digest,
            &mut b.code_digest,
            &mut b.dataset_digest,
            &mut b.runtime_digest,
            &mut b.backend_state_schema_digest,
            &mut b.base_parameters_digest,
            &mut b.parameter_mask_digest,
        ];
        *digests[field] = other;
        assert_eq!(
            validate(&request, &altered, &before, &before),
            Err(HcsnResearchErrorV2::Binding)
        );
    }
    assert_eq!(
        validate_hcsn_research_outcome_v2(&request, &outcome, &before, &before, b"altered receipt"),
        Err(HcsnResearchErrorV2::Receipt)
    );
    let mut altered = before.clone();
    altered[1].role = HcsnParameterRoleV2::Dynamics;
    assert_eq!(
        validate(&request, &outcome, &before, &altered),
        Err(HcsnResearchErrorV2::Parameters)
    );
    altered = before.clone();
    altered[1].bytes.push(0);
    assert_eq!(
        validate(&request, &outcome, &before, &altered),
        Err(HcsnResearchErrorV2::Parameters)
    );
}

#[test]
fn authenticated_receipt_cannot_be_reused_with_altered_cost_or_result() {
    let (request, mut outcome, before) = fixture();
    let receipt = outcome.encode_receipt(hcsn_parameters_digest_v2(&before).fixture("parameters"));
    outcome.receipt_digest = Digest32::of_bytes(&receipt);
    outcome.application.forward_calls += 1;
    assert_eq!(
        validate_hcsn_research_outcome_v2(&request, &outcome, &before, &before, &receipt),
        Err(HcsnResearchErrorV2::Receipt)
    );
    outcome.application.forward_calls -= 1;
    let mut changed = before.clone();
    changed[1].bytes[0] ^= 1;
    assert_eq!(
        validate_hcsn_research_outcome_v2(&request, &outcome, &before, &changed, &receipt),
        Err(HcsnResearchErrorV2::Receipt)
    );
}
