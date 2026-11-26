//! Coverage accounting for deterministic parameter-plasticity generation.
//!
//! A generator digest proves exact regeneration for one supplied profile. It does
//! not prove that the profile covered every parameter that the frozen mutation
//! grammar expected to be learnable. This module records that second fact. The
//! draft binds the expected and observed parameter sets, every explicit omission,
//! the scale policy, grammar, artifact/window and current owner frontiers. A
//! product host seals the draft only after authenticating an independent Observer.
//! Neither a draft nor a sealed receipt grants selection, installation, activation
//! or mutation authority.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::GeneratedParameterCandidateSetV3;
use crate::ParameterCandidateKindV2;
use crate::ParameterGeneratorErrorV3;
use crate::ParameterGeneratorProfileV3;
use crate::ProposalWindowV2;
use crate::verify_generated_parameter_candidates_v3;

const MAX_COVERAGE_PARAMETERS_V1: usize = 4_096;
const MAX_COVERAGE_SCALES_V1: usize = 31;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum GeneratorCoverageTerminalV1 {
    CandidatesGenerated,
    ZeroEligibleSignals,
    PolicyDisabledUpdates,
    NoAdmissibleUpdate,
}

impl GeneratorCoverageTerminalV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::CandidatesGenerated => 0,
            Self::ZeroEligibleSignals => 1,
            Self::PolicyDisabledUpdates => 2,
            Self::NoAdmissibleUpdate => 3,
        }
    }
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct GeneratorCoverageGapV1 {
    pub parameter_id: StableId,
    /// Content-addressed reason owned by the frozen grammar/owner-evidence path.
    pub reason_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct GeneratorCoverageFrontierV1 {
    pub artifact_registry_head_digest: Digest32,
    pub qualification_evidence_head_digest: Digest32,
    pub owner_evidence_set_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GeneratorCoverageDraftV1 {
    pub selected_artifact_digest: Digest32,
    pub window: ProposalWindowV2,
    pub mutation_grammar_digest: Digest32,
    pub expected_parameter_ids: Vec<StableId>,
    pub expected_parameter_set_digest: Digest32,
    pub actual_signal_parameter_ids: Vec<StableId>,
    pub actual_signal_set_digest: Digest32,
    pub missing_parameters: Vec<GeneratorCoverageGapV1>,
    pub declared_update_scales: Vec<FixedQ32>,
    pub scale_policy_digest: Digest32,
    pub update_candidate_count: u32,
    pub frontier: GeneratorCoverageFrontierV1,
    pub terminal: GeneratorCoverageTerminalV1,
    pub draft_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GeneratorCoverageReceiptV1 {
    pub draft: GeneratorCoverageDraftV1,
    /// Digest returned by signature verification for the Observer that attested
    /// `generator_coverage_observer_payload_v1(draft)`.
    pub observer_authentication_digest: Digest32,
    pub coverage_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum GeneratorCoverageErrorV1 {
    Generator(ParameterGeneratorErrorV3),
    ExpectedParameterCountOutOfRange,
    ScaleCountOutOfRange,
    DuplicateExpectedParameter(String),
    DuplicateSignalParameter(String),
    DuplicateGap(String),
    UnexpectedSignal(String),
    MissingGap(String),
    UnexpectedGap(String),
    EmptyDigest(&'static str),
    NonCanonicalOrder,
    TerminalMismatch,
    DigestMismatch,
    Arithmetic,
}

impl fmt::Display for GeneratorCoverageErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for GeneratorCoverageErrorV1 {}
impl From<ParameterGeneratorErrorV3> for GeneratorCoverageErrorV1 {
    fn from(value: ParameterGeneratorErrorV3) -> Self {
        Self::Generator(value)
    }
}

pub fn build_generator_coverage_draft_v1(
    profile: &ParameterGeneratorProfileV3,
    generated: &GeneratedParameterCandidateSetV3,
    expected_parameter_ids: Vec<StableId>,
    missing_parameters: Vec<GeneratorCoverageGapV1>,
    frontier: GeneratorCoverageFrontierV1,
) -> Result<GeneratorCoverageDraftV1, GeneratorCoverageErrorV1> {
    verify_generated_parameter_candidates_v3(profile.clone(), generated)?;
    validate_frontier(frontier)?;
    if profile.mutation_policy.mutation_grammar_digest.is_zero() {
        return Err(GeneratorCoverageErrorV1::EmptyDigest(
            "mutation grammar",
        ));
    }

    let expected_parameter_ids = canonical_expected(expected_parameter_ids)?;
    let actual_signal_parameter_ids = canonical_signals(
        profile
            .signals
            .iter()
            .map(|signal| signal.parameter_id.clone())
            .collect(),
    )?;
    let missing_parameters = canonical_gaps(missing_parameters)?;
    validate_set_relationship(
        &expected_parameter_ids,
        &actual_signal_parameter_ids,
        &missing_parameters,
    )?;

    let mut declared_update_scales = profile.update_scales.clone();
    declared_update_scales.sort();
    if declared_update_scales.len() > MAX_COVERAGE_SCALES_V1 {
        return Err(GeneratorCoverageErrorV1::ScaleCountOutOfRange);
    }
    let update_candidate_count = u32::try_from(
        generated
            .candidates
            .iter()
            .filter(|candidate| candidate.kind == ParameterCandidateKindV2::Update)
            .count(),
    )
    .map_err(|_| GeneratorCoverageErrorV1::Arithmetic)?;
    let terminal = terminal_for(
        actual_signal_parameter_ids.len(),
        declared_update_scales.len(),
        update_candidate_count,
    )?;

    let mut draft = GeneratorCoverageDraftV1 {
        selected_artifact_digest: profile.selected_artifact_digest,
        window: profile.window.clone(),
        mutation_grammar_digest: profile.mutation_policy.mutation_grammar_digest,
        expected_parameter_set_digest: digest_ids(
            b"hepta.plasticity.generator-coverage.expected.v1\0",
            &expected_parameter_ids,
        )?,
        expected_parameter_ids,
        actual_signal_set_digest: digest_ids(
            b"hepta.plasticity.generator-coverage.actual.v1\0",
            &actual_signal_parameter_ids,
        )?,
        actual_signal_parameter_ids,
        missing_parameters,
        scale_policy_digest: digest_scales(&declared_update_scales)?,
        declared_update_scales,
        update_candidate_count,
        frontier,
        terminal,
        draft_digest: Digest32::ZERO,
    };
    draft.draft_digest = digest_draft(&draft)?;
    verify_generator_coverage_draft_v1(&draft)?;
    Ok(draft)
}

pub fn generator_coverage_observer_payload_v1(draft: &GeneratorCoverageDraftV1) -> Vec<u8> {
    let mut bytes = b"hepta.plasticity.generator-coverage-observer.v1\0".to_vec();
    bytes.extend_from_slice(draft.draft_digest.as_array());
    bytes
}

pub fn seal_generator_coverage_receipt_v1(
    draft: GeneratorCoverageDraftV1,
    observer_authentication_digest: Digest32,
) -> Result<GeneratorCoverageReceiptV1, GeneratorCoverageErrorV1> {
    verify_generator_coverage_draft_v1(&draft)?;
    if observer_authentication_digest.is_zero() {
        return Err(GeneratorCoverageErrorV1::EmptyDigest(
            "observer authentication",
        ));
    }
    let mut bytes = b"hepta.plasticity.generator-coverage-receipt.v1\0".to_vec();
    bytes.extend_from_slice(draft.draft_digest.as_array());
    bytes.extend_from_slice(observer_authentication_digest.as_array());
    let receipt = GeneratorCoverageReceiptV1 {
        draft,
        observer_authentication_digest,
        coverage_digest: Digest32::of_bytes(&bytes),
    };
    verify_generator_coverage_receipt_v1(&receipt)?;
    Ok(receipt)
}

pub fn verify_generator_coverage_draft_v1(
    draft: &GeneratorCoverageDraftV1,
) -> Result<(), GeneratorCoverageErrorV1> {
    for (name, digest) in [
        ("selected artifact", draft.selected_artifact_digest),
        ("window", draft.window.window_digest),
        ("mutation grammar", draft.mutation_grammar_digest),
        ("expected parameter set", draft.expected_parameter_set_digest),
        ("actual signal set", draft.actual_signal_set_digest),
        ("scale policy", draft.scale_policy_digest),
        (
            "artifact registry frontier",
            draft.frontier.artifact_registry_head_digest,
        ),
        (
            "qualification evidence frontier",
            draft.frontier.qualification_evidence_head_digest,
        ),
        ("owner evidence set", draft.frontier.owner_evidence_set_digest),
        ("coverage draft", draft.draft_digest),
    ] {
        if digest.is_zero() {
            return Err(GeneratorCoverageErrorV1::EmptyDigest(name));
        }
    }

    let expected = canonical_expected(draft.expected_parameter_ids.clone())?;
    let actual = canonical_signals(draft.actual_signal_parameter_ids.clone())?;
    let gaps = canonical_gaps(draft.missing_parameters.clone())?;
    let mut scales = draft.declared_update_scales.clone();
    scales.sort();
    if expected != draft.expected_parameter_ids
        || actual != draft.actual_signal_parameter_ids
        || gaps != draft.missing_parameters
        || scales != draft.declared_update_scales
    {
        return Err(GeneratorCoverageErrorV1::NonCanonicalOrder);
    }
    if scales.len() > MAX_COVERAGE_SCALES_V1 {
        return Err(GeneratorCoverageErrorV1::ScaleCountOutOfRange);
    }
    validate_set_relationship(&expected, &actual, &gaps)?;
    if digest_ids(
        b"hepta.plasticity.generator-coverage.expected.v1\0",
        &expected,
    )? != draft.expected_parameter_set_digest
        || digest_ids(
            b"hepta.plasticity.generator-coverage.actual.v1\0",
            &actual,
        )? != draft.actual_signal_set_digest
        || digest_scales(&scales)? != draft.scale_policy_digest
    {
        return Err(GeneratorCoverageErrorV1::DigestMismatch);
    }
    if terminal_for(actual.len(), scales.len(), draft.update_candidate_count)? != draft.terminal {
        return Err(GeneratorCoverageErrorV1::TerminalMismatch);
    }
    if digest_draft(draft)? != draft.draft_digest {
        return Err(GeneratorCoverageErrorV1::DigestMismatch);
    }
    Ok(())
}

pub fn verify_generator_coverage_receipt_v1(
    receipt: &GeneratorCoverageReceiptV1,
) -> Result<(), GeneratorCoverageErrorV1> {
    verify_generator_coverage_draft_v1(&receipt.draft)?;
    if receipt.observer_authentication_digest.is_zero() || receipt.coverage_digest.is_zero() {
        return Err(GeneratorCoverageErrorV1::EmptyDigest("coverage receipt"));
    }
    let mut bytes = b"hepta.plasticity.generator-coverage-receipt.v1\0".to_vec();
    bytes.extend_from_slice(receipt.draft.draft_digest.as_array());
    bytes.extend_from_slice(receipt.observer_authentication_digest.as_array());
    if Digest32::of_bytes(&bytes) != receipt.coverage_digest {
        return Err(GeneratorCoverageErrorV1::DigestMismatch);
    }
    Ok(())
}

fn validate_frontier(
    frontier: GeneratorCoverageFrontierV1,
) -> Result<(), GeneratorCoverageErrorV1> {
    for (name, digest) in [
        (
            "artifact registry frontier",
            frontier.artifact_registry_head_digest,
        ),
        (
            "qualification evidence frontier",
            frontier.qualification_evidence_head_digest,
        ),
        ("owner evidence set", frontier.owner_evidence_set_digest),
    ] {
        if digest.is_zero() {
            return Err(GeneratorCoverageErrorV1::EmptyDigest(name));
        }
    }
    Ok(())
}

fn canonical_expected(
    mut ids: Vec<StableId>,
) -> Result<Vec<StableId>, GeneratorCoverageErrorV1> {
    if !(1..=MAX_COVERAGE_PARAMETERS_V1).contains(&ids.len()) {
        return Err(GeneratorCoverageErrorV1::ExpectedParameterCountOutOfRange);
    }
    ids.sort();
    if let Some(pair) = ids.windows(2).find(|pair| pair[0] == pair[1]) {
        return Err(GeneratorCoverageErrorV1::DuplicateExpectedParameter(
            pair[0].to_string(),
        ));
    }
    Ok(ids)
}

fn canonical_signals(
    mut ids: Vec<StableId>,
) -> Result<Vec<StableId>, GeneratorCoverageErrorV1> {
    if ids.len() > MAX_COVERAGE_PARAMETERS_V1 {
        return Err(GeneratorCoverageErrorV1::ExpectedParameterCountOutOfRange);
    }
    ids.sort();
    if let Some(pair) = ids.windows(2).find(|pair| pair[0] == pair[1]) {
        return Err(GeneratorCoverageErrorV1::DuplicateSignalParameter(
            pair[0].to_string(),
        ));
    }
    Ok(ids)
}

fn canonical_gaps(
    mut gaps: Vec<GeneratorCoverageGapV1>,
) -> Result<Vec<GeneratorCoverageGapV1>, GeneratorCoverageErrorV1> {
    if gaps.len() > MAX_COVERAGE_PARAMETERS_V1 {
        return Err(GeneratorCoverageErrorV1::ExpectedParameterCountOutOfRange);
    }
    gaps.sort();
    for gap in &gaps {
        if gap.reason_digest.is_zero() {
            return Err(GeneratorCoverageErrorV1::EmptyDigest("coverage gap reason"));
        }
    }
    if let Some(pair) = gaps
        .windows(2)
        .find(|pair| pair[0].parameter_id == pair[1].parameter_id)
    {
        return Err(GeneratorCoverageErrorV1::DuplicateGap(
            pair[0].parameter_id.to_string(),
        ));
    }
    Ok(gaps)
}

fn validate_set_relationship(
    expected: &[StableId],
    actual: &[StableId],
    gaps: &[GeneratorCoverageGapV1],
) -> Result<(), GeneratorCoverageErrorV1> {
    let expected_set = expected.iter().cloned().collect::<BTreeSet<_>>();
    let actual_set = actual.iter().cloned().collect::<BTreeSet<_>>();
    if let Some(unexpected) = actual_set.difference(&expected_set).next() {
        return Err(GeneratorCoverageErrorV1::UnexpectedSignal(
            unexpected.to_string(),
        ));
    }
    let required_gaps = expected_set
        .difference(&actual_set)
        .cloned()
        .collect::<Vec<_>>();
    let actual_gaps = gaps
        .iter()
        .map(|gap| gap.parameter_id.clone())
        .collect::<Vec<_>>();
    if let Some(missing) = required_gaps
        .iter()
        .find(|parameter_id| !actual_gaps.contains(parameter_id))
    {
        return Err(GeneratorCoverageErrorV1::MissingGap(
            missing.to_string(),
        ));
    }
    if let Some(unexpected) = actual_gaps
        .iter()
        .find(|parameter_id| !required_gaps.contains(parameter_id))
    {
        return Err(GeneratorCoverageErrorV1::UnexpectedGap(
            unexpected.to_string(),
        ));
    }
    Ok(())
}

fn terminal_for(
    actual_signal_count: usize,
    scale_count: usize,
    update_candidate_count: u32,
) -> Result<GeneratorCoverageTerminalV1, GeneratorCoverageErrorV1> {
    if update_candidate_count > 31 {
        return Err(GeneratorCoverageErrorV1::TerminalMismatch);
    }
    if actual_signal_count == 0 {
        if update_candidate_count != 0 {
            return Err(GeneratorCoverageErrorV1::TerminalMismatch);
        }
        return Ok(GeneratorCoverageTerminalV1::ZeroEligibleSignals);
    }
    if scale_count == 0 {
        if update_candidate_count != 0 {
            return Err(GeneratorCoverageErrorV1::TerminalMismatch);
        }
        return Ok(GeneratorCoverageTerminalV1::PolicyDisabledUpdates);
    }
    if update_candidate_count == 0 {
        return Ok(GeneratorCoverageTerminalV1::NoAdmissibleUpdate);
    }
    Ok(GeneratorCoverageTerminalV1::CandidatesGenerated)
}

fn digest_ids(
    domain: &[u8],
    ids: &[StableId],
) -> Result<Digest32, GeneratorCoverageErrorV1> {
    let mut bytes = domain.to_vec();
    push_len(&mut bytes, ids.len())?;
    for id in ids {
        push_id(&mut bytes, id)?;
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_scales(scales: &[FixedQ32]) -> Result<Digest32, GeneratorCoverageErrorV1> {
    let mut bytes = b"hepta.plasticity.generator-coverage.scales.v1\0".to_vec();
    push_len(&mut bytes, scales.len())?;
    for scale in scales {
        bytes.extend_from_slice(&scale.raw().to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_draft(
    draft: &GeneratorCoverageDraftV1,
) -> Result<Digest32, GeneratorCoverageErrorV1> {
    let mut bytes = b"hepta.plasticity.generator-coverage-draft.v1\0".to_vec();
    bytes.extend_from_slice(draft.selected_artifact_digest.as_array());
    push_id(&mut bytes, &draft.window.window_id)?;
    bytes.extend_from_slice(draft.window.window_digest.as_array());
    bytes.extend_from_slice(draft.mutation_grammar_digest.as_array());
    bytes.extend_from_slice(draft.expected_parameter_set_digest.as_array());
    bytes.extend_from_slice(draft.actual_signal_set_digest.as_array());
    bytes.extend_from_slice(draft.scale_policy_digest.as_array());
    push_len(&mut bytes, draft.expected_parameter_ids.len())?;
    for id in &draft.expected_parameter_ids {
        push_id(&mut bytes, id)?;
    }
    push_len(&mut bytes, draft.actual_signal_parameter_ids.len())?;
    for id in &draft.actual_signal_parameter_ids {
        push_id(&mut bytes, id)?;
    }
    push_len(&mut bytes, draft.missing_parameters.len())?;
    for gap in &draft.missing_parameters {
        push_id(&mut bytes, &gap.parameter_id)?;
        bytes.extend_from_slice(gap.reason_digest.as_array());
    }
    push_len(&mut bytes, draft.declared_update_scales.len())?;
    for scale in &draft.declared_update_scales {
        bytes.extend_from_slice(&scale.raw().to_be_bytes());
    }
    bytes.extend_from_slice(&draft.update_candidate_count.to_be_bytes());
    for digest in [
        draft.frontier.artifact_registry_head_digest,
        draft.frontier.qualification_evidence_head_digest,
        draft.frontier.owner_evidence_set_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.push(draft.terminal.tag());
    Ok(Digest32::of_bytes(&bytes))
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), GeneratorCoverageErrorV1> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| GeneratorCoverageErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn push_len(bytes: &mut Vec<u8>, value: usize) -> Result<(), GeneratorCoverageErrorV1> {
    let value = u32::try_from(value).map_err(|_| GeneratorCoverageErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&value.to_be_bytes());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::LayerNormDenominatorV2;
    use crate::ParameterMutationRuleV1;
    use crate::ParameterMutationSurfaceV1;
    use crate::ParameterPlasticitySignalV3;
    use crate::build_parameter_mutation_policy_v1;
    use crate::generate_parameter_candidates_v3;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid id")
    }

    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }

    fn profile() -> ParameterGeneratorProfileV3 {
        let selected_artifact_digest = digest(b"coverage-artifact");
        let window = ProposalWindowV2 {
            window_id: id("coverage-window:1"),
            window_digest: digest(b"coverage-window"),
        };
        ParameterGeneratorProfileV3 {
            selected_artifact_digest,
            window: window.clone(),
            norm_layers: vec![LayerNormDenominatorV2 {
                layer_id: id("layer:1"),
                baseline_squared_l2_raw_q64: 1_u128 << 64,
            }],
            mutation_policy: build_parameter_mutation_policy_v1(
                id("coverage-policy:1"),
                digest(b"coverage-grammar"),
                selected_artifact_digest,
                window,
                vec![ParameterMutationRuleV1 {
                    parameter_id: id("parameter:1"),
                    layer_id: id("layer:1"),
                    surface: ParameterMutationSurfaceV1::LearnableParameter,
                    minimum_delta: FixedQ32::from_raw(-(1_i64 << 24)),
                    maximum_delta: FixedQ32::from_raw(1_i64 << 24),
                }],
            )
            .expect("mutation policy"),
            update_scales: vec![FixedQ32::ONE],
            signals: vec![ParameterPlasticitySignalV3 {
                layer_id: id("layer:1"),
                parameter_id: id("parameter:1"),
                eligibility: FixedQ32::ONE,
                modulator: FixedQ32::ONE,
                learning_rate: FixedQ32::from_raw(1_i64 << 20),
                lower_bound: FixedQ32::from_raw(-(1_i64 << 24)),
                upper_bound: FixedQ32::from_raw(1_i64 << 24),
                evidence_digest: digest(b"signal-evidence"),
            }],
        }
    }

    fn frontier() -> GeneratorCoverageFrontierV1 {
        GeneratorCoverageFrontierV1 {
            artifact_registry_head_digest: digest(b"artifact-head"),
            qualification_evidence_head_digest: digest(b"evidence-head"),
            owner_evidence_set_digest: digest(b"owner-evidence-set"),
        }
    }

    #[test]
    fn coverage_binds_expected_signals_gaps_scales_and_observer() {
        let profile = profile();
        let generated = generate_parameter_candidates_v3(profile.clone()).expect("generate");
        let draft = build_generator_coverage_draft_v1(
            &profile,
            &generated,
            vec![id("parameter:2"), id("parameter:1")],
            vec![GeneratorCoverageGapV1 {
                parameter_id: id("parameter:2"),
                reason_digest: digest(b"disabled-by-owner-policy"),
            }],
            frontier(),
        )
        .expect("coverage draft");
        assert_eq!(
            draft.terminal,
            GeneratorCoverageTerminalV1::CandidatesGenerated
        );
        assert_eq!(draft.expected_parameter_ids[0], id("parameter:1"));
        let receipt = seal_generator_coverage_receipt_v1(
            draft.clone(),
            digest(b"verified-observer-authentication"),
        )
        .expect("seal coverage");
        verify_generator_coverage_receipt_v1(&receipt).expect("verify receipt");

        let mut tampered = receipt;
        tampered.draft.missing_parameters[0].reason_digest = digest(b"other-reason");
        assert_eq!(
            verify_generator_coverage_receipt_v1(&tampered),
            Err(GeneratorCoverageErrorV1::DigestMismatch)
        );
    }

    #[test]
    fn empty_signal_and_empty_scale_profiles_have_distinct_terminals() {
        let mut no_signals = profile();
        no_signals.signals.clear();
        let generated =
            generate_parameter_candidates_v3(no_signals.clone()).expect("no-signal generate");
        let draft = build_generator_coverage_draft_v1(
            &no_signals,
            &generated,
            vec![id("parameter:1")],
            vec![GeneratorCoverageGapV1 {
                parameter_id: id("parameter:1"),
                reason_digest: digest(b"zero-eligible-signal"),
            }],
            frontier(),
        )
        .expect("zero-signal draft");
        assert_eq!(
            draft.terminal,
            GeneratorCoverageTerminalV1::ZeroEligibleSignals
        );

        let mut no_scales = profile();
        no_scales.update_scales.clear();
        let generated =
            generate_parameter_candidates_v3(no_scales.clone()).expect("no-scale generate");
        let draft = build_generator_coverage_draft_v1(
            &no_scales,
            &generated,
            vec![id("parameter:1")],
            Vec::new(),
            frontier(),
        )
        .expect("disabled-policy draft");
        assert_eq!(
            draft.terminal,
            GeneratorCoverageTerminalV1::PolicyDisabledUpdates
        );
    }

    #[test]
    fn every_omitted_expected_parameter_requires_one_reason() {
        let mut no_signals = profile();
        no_signals.signals.clear();
        let generated =
            generate_parameter_candidates_v3(no_signals.clone()).expect("generate");
        assert_eq!(
            build_generator_coverage_draft_v1(
                &no_signals,
                &generated,
                vec![id("parameter:1")],
                Vec::new(),
                frontier(),
            ),
            Err(GeneratorCoverageErrorV1::MissingGap(
                "parameter:1".to_string()
            ))
        );
    }
}
