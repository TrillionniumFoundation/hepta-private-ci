//! Deterministic reference implementation for the bounded Bellman/operator path.
//!
//! This module admits an explicit applicability certificate, constructs a fixed
//! farthest-point sensor core, evaluates a complete tabular Bellman grid, and
//! checks the declared regularity/error budget. It is a qualification reference,
//! not a neural trainer, online policy, selector or runtime authority.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

const MAX_ACTIONS: usize = 128;
const MAX_CELLS: usize = 262_144;
const MAX_DESIGN_POINTS: usize = 16_384;
const MAX_DIMENSIONS: usize = 32;
const MAX_ERROR_COMPONENTS: usize = 32;
const MAX_SENSORS: usize = 4_096;
const SCALE: i128 = 1_i128 << 32;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ApplicabilityDecisionV1 {
    Pass,
    Fail,
}

impl ApplicabilityDecisionV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Pass => 0,
            Self::Fail => 1,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperatorApplicabilityCertificateV1 {
    pub certificate_id: StableId,
    pub axis_partition_digest: Digest32,
    pub domain_digest: Digest32,
    pub action_space_digest: Digest32,
    pub holder_exponents_digest: Digest32,
    pub holder_constants_digest: Digest32,
    pub state_lipschitz_digest: Digest32,
    pub action_lipschitz_digest: Digest32,
    pub ellipticity_nu_lcb: FixedQ32,
    pub control_interval_millis: u64,
    pub evaluator_id: StableId,
    pub evaluator_credential_digest: Digest32,
    pub fallback_digest: Digest32,
    pub expires_at: u64,
    pub decision: ApplicabilityDecisionV1,
}

pub fn validate_applicability_certificate(
    certificate: &OperatorApplicabilityCertificateV1,
    now: u64,
) -> Result<Digest32, OperatorClosureError> {
    for (label, digest) in [
        ("axis partition", certificate.axis_partition_digest),
        ("operator domain", certificate.domain_digest),
        ("action space", certificate.action_space_digest),
        ("Holder exponents", certificate.holder_exponents_digest),
        ("Holder constants", certificate.holder_constants_digest),
        ("state Lipschitz profile", certificate.state_lipschitz_digest),
        ("action Lipschitz profile", certificate.action_lipschitz_digest),
        ("evaluator credential", certificate.evaluator_credential_digest),
        ("operator fallback", certificate.fallback_digest),
    ] {
        require_digest(digest, label)?;
    }
    if certificate.decision != ApplicabilityDecisionV1::Pass {
        return Err(OperatorClosureError::ApplicabilityRejected);
    }
    if certificate.ellipticity_nu_lcb <= FixedQ32::ZERO {
        return Err(OperatorClosureError::EllipticityUnsupported);
    }
    if !(10..=3_600_000).contains(&certificate.control_interval_millis) {
        return Err(OperatorClosureError::ControlInterval);
    }
    if now > certificate.expires_at {
        return Err(OperatorClosureError::ApplicabilityExpired);
    }

    let mut bytes = b"hepta.bellman-operator.applicability.v1".to_vec();
    push_id(&mut bytes, &certificate.certificate_id);
    for digest in [
        certificate.axis_partition_digest,
        certificate.domain_digest,
        certificate.action_space_digest,
        certificate.holder_exponents_digest,
        certificate.holder_constants_digest,
        certificate.state_lipschitz_digest,
        certificate.action_lipschitz_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&certificate.ellipticity_nu_lcb.raw().to_be_bytes());
    bytes.extend_from_slice(&certificate.control_interval_millis.to_be_bytes());
    push_id(&mut bytes, &certificate.evaluator_id);
    bytes.extend_from_slice(certificate.evaluator_credential_digest.as_array());
    bytes.extend_from_slice(certificate.fallback_digest.as_array());
    bytes.extend_from_slice(&certificate.expires_at.to_be_bytes());
    bytes.push(certificate.decision.tag());
    Ok(Digest32::of_bytes(&bytes))
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SensorPointV1 {
    pub point_id: StableId,
    pub coordinates: Vec<FixedQ32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SensorCoreDesignV1 {
    pub sensor_core_id: StableId,
    pub state_axis_digest: Digest32,
    pub candidate_design_digest: Digest32,
    pub seed_digest: Digest32,
    pub requested_count: usize,
    pub candidates: Vec<SensorPointV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperatorSensorCoreManifestV1 {
    pub sensor_core_id: StableId,
    pub state_axis_digest: Digest32,
    pub candidate_design_digest: Digest32,
    pub seed_digest: Digest32,
    pub selected_points: Vec<SensorPointV1>,
    pub fill_distance_q32: FixedQ32,
    pub separation_radius_q32: FixedQ32,
    pub mesh_ratio_q32: FixedQ32,
    pub hull_digest: Digest32,
    pub manifest_digest: Digest32,
    pub authority: AuthorityPosture,
}

pub fn build_sensor_core(
    mut design: SensorCoreDesignV1,
) -> Result<OperatorSensorCoreManifestV1, OperatorClosureError> {
    for (label, digest) in [
        ("state axis", design.state_axis_digest),
        ("candidate design", design.candidate_design_digest),
        ("sensor seed", design.seed_digest),
    ] {
        require_digest(digest, label)?;
    }
    if design.candidates.len() < 2
        || design.candidates.len() > MAX_DESIGN_POINTS
        || design.requested_count < 2
        || design.requested_count > MAX_SENSORS
        || design.requested_count > design.candidates.len()
    {
        return Err(OperatorClosureError::SensorCount);
    }
    design
        .candidates
        .sort_by_key(|candidate| candidate.point_id.clone());
    if let Some(adjacent) = design
        .candidates
        .windows(2)
        .find(|adjacent| adjacent[0].point_id == adjacent[1].point_id)
    {
        return Err(OperatorClosureError::DuplicateSensorId(
            adjacent[0].point_id.to_string(),
        ));
    }
    let dimensions = design.candidates[0].coordinates.len();
    if !(1..=MAX_DIMENSIONS).contains(&dimensions) {
        return Err(OperatorClosureError::SensorDimension);
    }
    for candidate in &design.candidates {
        if candidate.coordinates.len() != dimensions
            || candidate
                .coordinates
                .iter()
                .any(|coordinate| !(FixedQ32::ZERO..=FixedQ32::ONE).contains(coordinate))
        {
            return Err(OperatorClosureError::SensorCoordinate);
        }
    }
    for left in 0..design.candidates.len() {
        for right in left + 1..design.candidates.len() {
            if design.candidates[left].coordinates == design.candidates[right].coordinates {
                return Err(OperatorClosureError::DuplicateSensorCoordinates);
            }
        }
    }

    let mut selected_flags = vec![false; design.candidates.len()];
    let mut selected_indices = vec![0_usize];
    selected_flags[0] = true;
    let mut nearest_squared = design
        .candidates
        .iter()
        .map(|candidate| distance_squared(candidate, &design.candidates[0]))
        .collect::<Result<Vec<_>, _>>()?;
    while selected_indices.len() < design.requested_count {
        let mut best: Option<(usize, u128)> = None;
        for (index, distance) in nearest_squared.iter().copied().enumerate() {
            if selected_flags[index] {
                continue;
            }
            if best.is_none_or(|(_, best_distance)| distance > best_distance) {
                best = Some((index, distance));
            }
        }
        let Some((selected_index, _)) = best else {
            return Err(OperatorClosureError::InternalInvariant);
        };
        selected_flags[selected_index] = true;
        selected_indices.push(selected_index);
        for (index, candidate) in design.candidates.iter().enumerate() {
            let distance = distance_squared(candidate, &design.candidates[selected_index])?;
            nearest_squared[index] = nearest_squared[index].min(distance);
        }
    }

    let selected_points = selected_indices
        .iter()
        .map(|index| design.candidates[*index].clone())
        .collect::<Vec<_>>();
    let fill_distance_raw = integer_sqrt(
        nearest_squared
            .iter()
            .copied()
            .max()
            .ok_or(OperatorClosureError::InternalInvariant)?,
    )?;
    let mut minimum_separation_squared = u128::MAX;
    for left in 0..selected_points.len() {
        for right in left + 1..selected_points.len() {
            minimum_separation_squared = minimum_separation_squared
                .min(distance_squared(&selected_points[left], &selected_points[right])?);
        }
    }
    let separation_radius_raw = integer_sqrt(minimum_separation_squared)? / 2;
    if separation_radius_raw == 0 {
        return Err(OperatorClosureError::SensorSeparation);
    }
    let mesh_ratio_raw = fill_distance_raw
        .checked_shl(32)
        .ok_or(OperatorClosureError::Arithmetic)?
        / separation_radius_raw;
    let fill_distance_q32 = fixed_from_u128(fill_distance_raw)?;
    let separation_radius_q32 = fixed_from_u128(separation_radius_raw)?;
    let mesh_ratio_q32 = fixed_from_u128(mesh_ratio_raw)?;
    if mesh_ratio_q32.raw() > 4 * FixedQ32::ONE.raw() {
        return Err(OperatorClosureError::MeshRatio);
    }

    let hull_digest = digest_sensor_points(
        b"hepta.bellman-operator.sensor-hull.v1",
        &selected_points,
    )?;
    let mut bytes = b"hepta.bellman-operator.sensor-core.v1".to_vec();
    push_id(&mut bytes, &design.sensor_core_id);
    bytes.extend_from_slice(design.state_axis_digest.as_array());
    bytes.extend_from_slice(design.candidate_design_digest.as_array());
    bytes.extend_from_slice(design.seed_digest.as_array());
    bytes.extend_from_slice(
        &u32::try_from(selected_points.len())
            .map_err(|_| OperatorClosureError::Arithmetic)?
            .to_be_bytes(),
    );
    for point in &selected_points {
        push_sensor_point(&mut bytes, point)?;
    }
    for value in [
        fill_distance_q32,
        separation_radius_q32,
        mesh_ratio_q32,
    ] {
        bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    bytes.extend_from_slice(hull_digest.as_array());
    let manifest_digest = Digest32::of_bytes(&bytes);
    Ok(OperatorSensorCoreManifestV1 {
        sensor_core_id: design.sensor_core_id,
        state_axis_digest: design.state_axis_digest,
        candidate_design_digest: design.candidate_design_digest,
        seed_digest: design.seed_digest,
        selected_points,
        fill_distance_q32,
        separation_radius_q32,
        mesh_ratio_q32,
        hull_digest,
        manifest_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BellmanReferenceCellV1 {
    pub sensor_id: StableId,
    pub action_id: StableId,
    pub reward: FixedQ32,
    pub continuation_value: FixedQ32,
    pub terminal: bool,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BellmanReferencePlanV1 {
    pub plan_id: StableId,
    pub objective_digest: Digest32,
    pub sensor_core_digest: Digest32,
    pub gamma: FixedQ32,
    pub sensor_ids: Vec<StableId>,
    pub action_ids: Vec<StableId>,
    pub cells: Vec<BellmanReferenceCellV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BellmanReferenceTargetV1 {
    pub sensor_id: StableId,
    pub action_id: StableId,
    pub target: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GreedyReferenceActionV1 {
    pub sensor_id: StableId,
    pub action_id: StableId,
    pub value: FixedQ32,
    pub action_gap: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BellmanReferenceReceiptV1 {
    pub plan_id: StableId,
    pub targets: Vec<BellmanReferenceTargetV1>,
    pub greedy_actions: Vec<GreedyReferenceActionV1>,
    pub evidence_digest: Digest32,
    pub authority: AuthorityPosture,
}

pub fn evaluate_bellman_reference(
    mut plan: BellmanReferencePlanV1,
) -> Result<BellmanReferenceReceiptV1, OperatorClosureError> {
    for (label, digest) in [
        ("objective", plan.objective_digest),
        ("sensor core", plan.sensor_core_digest),
    ] {
        require_digest(digest, label)?;
    }
    if !(FixedQ32::ZERO..=FixedQ32::ONE).contains(&plan.gamma) {
        return Err(OperatorClosureError::InvalidGamma);
    }
    if plan.sensor_ids.is_empty()
        || plan.sensor_ids.len() > MAX_SENSORS
        || !(2..=MAX_ACTIONS).contains(&plan.action_ids.len())
    {
        return Err(OperatorClosureError::ReferenceGridLimit);
    }
    normalize_ids(&mut plan.sensor_ids)?;
    normalize_ids(&mut plan.action_ids)?;
    let expected_cells = plan
        .sensor_ids
        .len()
        .checked_mul(plan.action_ids.len())
        .filter(|count| *count <= MAX_CELLS)
        .ok_or(OperatorClosureError::ReferenceGridLimit)?;
    if plan.cells.len() != expected_cells {
        return Err(OperatorClosureError::IncompleteReferenceGrid);
    }
    plan.cells.sort_by_key(|cell| (cell.sensor_id.clone(), cell.action_id.clone()));
    if plan.cells.windows(2).any(|adjacent| {
        adjacent[0].sensor_id == adjacent[1].sensor_id
            && adjacent[0].action_id == adjacent[1].action_id
    }) {
        return Err(OperatorClosureError::DuplicateReferenceCell);
    }

    let mut targets = Vec::with_capacity(plan.cells.len());
    let mut cell_index = 0_usize;
    for sensor_id in &plan.sensor_ids {
        for action_id in &plan.action_ids {
            let cell = &plan.cells[cell_index];
            if &cell.sensor_id != sensor_id || &cell.action_id != action_id {
                return Err(OperatorClosureError::IncompleteReferenceGrid);
            }
            require_digest(cell.evidence_digest, "Bellman cell evidence")?;
            let continuation = if cell.terminal {
                FixedQ32::ZERO
            } else {
                multiply_q32(plan.gamma, cell.continuation_value)?
            };
            let target = add_q32(cell.reward, continuation)?;
            targets.push(BellmanReferenceTargetV1 {
                sensor_id: sensor_id.clone(),
                action_id: action_id.clone(),
                target,
            });
            cell_index += 1;
        }
    }

    let mut greedy_actions = Vec::with_capacity(plan.sensor_ids.len());
    for (sensor_index, sensor_id) in plan.sensor_ids.iter().enumerate() {
        let start = sensor_index * plan.action_ids.len();
        let end = start + plan.action_ids.len();
        let mut rows = targets[start..end].to_vec();
        rows.sort_by(|left, right| {
            right
                .target
                .cmp(&left.target)
                .then_with(|| left.action_id.cmp(&right.action_id))
        });
        let best = &rows[0];
        let second = &rows[1];
        greedy_actions.push(GreedyReferenceActionV1 {
            sensor_id: sensor_id.clone(),
            action_id: best.action_id.clone(),
            value: best.target,
            action_gap: subtract_q32(best.target, second.target)?,
        });
    }

    let mut bytes = b"hepta.bellman-operator.reference-receipt.v1".to_vec();
    push_id(&mut bytes, &plan.plan_id);
    bytes.extend_from_slice(plan.objective_digest.as_array());
    bytes.extend_from_slice(plan.sensor_core_digest.as_array());
    bytes.extend_from_slice(&plan.gamma.raw().to_be_bytes());
    for target in &targets {
        push_id(&mut bytes, &target.sensor_id);
        push_id(&mut bytes, &target.action_id);
        bytes.extend_from_slice(&target.target.raw().to_be_bytes());
    }
    for greedy in &greedy_actions {
        push_id(&mut bytes, &greedy.sensor_id);
        push_id(&mut bytes, &greedy.action_id);
        bytes.extend_from_slice(&greedy.value.raw().to_be_bytes());
        bytes.extend_from_slice(&greedy.action_gap.raw().to_be_bytes());
    }
    Ok(BellmanReferenceReceiptV1 {
        plan_id: plan.plan_id,
        targets,
        greedy_actions,
        evidence_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperatorErrorComponentV1 {
    pub component_id: StableId,
    pub normalized_error: FixedQ32,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperatorRegularityAssessmentV1 {
    pub artifact_id: StableId,
    pub measured_rank: u16,
    pub reconstruction_gain_q32: FixedQ32,
    pub monotonicity_violations: u32,
    pub positivity_violations: u32,
    pub holder_residual_q32: FixedQ32,
    pub action_lipschitz_residual_q32: FixedQ32,
    pub ood_false_acceptance_q32: FixedQ32,
    pub error_components: Vec<OperatorErrorComponentV1>,
    pub dominant_component_approved: bool,
    pub evaluator_id: StableId,
    pub evaluator_credential_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperatorRegularityAdmissionV1 {
    pub artifact_id: StableId,
    pub total_normalized_error: FixedQ32,
    pub assessment_digest: Digest32,
    pub authority: AuthorityPosture,
}

pub fn admit_operator_regularity(
    mut assessment: OperatorRegularityAssessmentV1,
) -> Result<OperatorRegularityAdmissionV1, OperatorClosureError> {
    require_digest(
        assessment.evaluator_credential_digest,
        "regularity evaluator credential",
    )?;
    if !(1..=64).contains(&assessment.measured_rank) {
        return Err(OperatorClosureError::MeasuredRank);
    }
    let maximum_gain = FixedQ32::ONE.raw() + FixedQ32::ONE.raw() / 50;
    if assessment.reconstruction_gain_q32.raw() < 0
        || assessment.reconstruction_gain_q32.raw() > maximum_gain
    {
        return Err(OperatorClosureError::ReconstructionGain);
    }
    if assessment.monotonicity_violations != 0 || assessment.positivity_violations != 0 {
        return Err(OperatorClosureError::ShapeViolation);
    }
    let maximum_error = FixedQ32::ONE.raw() / 20;
    let maximum_ood_false_acceptance = FixedQ32::ONE.raw() / 200;
    for value in [
        assessment.holder_residual_q32,
        assessment.action_lipschitz_residual_q32,
    ] {
        if value.raw() < 0 || value.raw() > maximum_error {
            return Err(OperatorClosureError::RegularityResidual);
        }
    }
    if assessment.ood_false_acceptance_q32.raw() < 0
        || assessment.ood_false_acceptance_q32.raw() >= maximum_ood_false_acceptance
    {
        return Err(OperatorClosureError::OodFalseAcceptance);
    }
    if assessment.error_components.is_empty()
        || assessment.error_components.len() > MAX_ERROR_COMPONENTS
    {
        return Err(OperatorClosureError::ErrorComponentLimit);
    }
    assessment
        .error_components
        .sort_by_key(|component| component.component_id.clone());
    if let Some(adjacent) = assessment
        .error_components
        .windows(2)
        .find(|adjacent| adjacent[0].component_id == adjacent[1].component_id)
    {
        return Err(OperatorClosureError::DuplicateErrorComponent(
            adjacent[0].component_id.to_string(),
        ));
    }
    let mut total = 0_i128;
    let mut maximum_component = 0_i128;
    for component in &assessment.error_components {
        require_digest(component.evidence_digest, "error component evidence")?;
        let value = i128::from(component.normalized_error.raw());
        if value < 0 {
            return Err(OperatorClosureError::RegularityResidual);
        }
        total = total
            .checked_add(value)
            .ok_or(OperatorClosureError::Arithmetic)?;
        maximum_component = maximum_component.max(value);
    }
    if total > i128::from(maximum_error) {
        return Err(OperatorClosureError::TotalErrorBudget);
    }
    if maximum_component * 2 > total && !assessment.dominant_component_approved {
        return Err(OperatorClosureError::DominantErrorComponent);
    }
    let total_normalized_error = FixedQ32::from_raw(
        i64::try_from(total).map_err(|_| OperatorClosureError::Arithmetic)?,
    );

    let mut bytes = b"hepta.bellman-operator.regularity-admission.v1".to_vec();
    push_id(&mut bytes, &assessment.artifact_id);
    bytes.extend_from_slice(&assessment.measured_rank.to_be_bytes());
    for value in [
        assessment.reconstruction_gain_q32,
        assessment.holder_residual_q32,
        assessment.action_lipschitz_residual_q32,
        assessment.ood_false_acceptance_q32,
    ] {
        bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    bytes.extend_from_slice(&assessment.monotonicity_violations.to_be_bytes());
    bytes.extend_from_slice(&assessment.positivity_violations.to_be_bytes());
    for component in &assessment.error_components {
        push_id(&mut bytes, &component.component_id);
        bytes.extend_from_slice(&component.normalized_error.raw().to_be_bytes());
        bytes.extend_from_slice(component.evidence_digest.as_array());
    }
    bytes.push(u8::from(assessment.dominant_component_approved));
    push_id(&mut bytes, &assessment.evaluator_id);
    bytes.extend_from_slice(assessment.evaluator_credential_digest.as_array());
    bytes.extend_from_slice(&total_normalized_error.raw().to_be_bytes());
    Ok(OperatorRegularityAdmissionV1 {
        artifact_id: assessment.artifact_id,
        total_normalized_error,
        assessment_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OperatorClosureError {
    EmptyDigest(&'static str),
    ApplicabilityRejected,
    EllipticityUnsupported,
    ControlInterval,
    ApplicabilityExpired,
    SensorCount,
    SensorDimension,
    SensorCoordinate,
    DuplicateSensorId(String),
    DuplicateSensorCoordinates,
    SensorSeparation,
    MeshRatio,
    InvalidGamma,
    ReferenceGridLimit,
    DuplicateIdentity(String),
    IncompleteReferenceGrid,
    DuplicateReferenceCell,
    MeasuredRank,
    ReconstructionGain,
    ShapeViolation,
    RegularityResidual,
    OodFalseAcceptance,
    ErrorComponentLimit,
    DuplicateErrorComponent(String),
    TotalErrorBudget,
    DominantErrorComponent,
    InternalInvariant,
    Arithmetic,
}

impl fmt::Display for OperatorClosureError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for OperatorClosureError {}

fn distance_squared(
    left: &SensorPointV1,
    right: &SensorPointV1,
) -> Result<u128, OperatorClosureError> {
    if left.coordinates.len() != right.coordinates.len() {
        return Err(OperatorClosureError::SensorDimension);
    }
    left.coordinates
        .iter()
        .zip(&right.coordinates)
        .try_fold(0_u128, |sum, (left, right)| {
            let delta = i128::from(left.raw()) - i128::from(right.raw());
            let magnitude = delta.unsigned_abs();
            sum.checked_add(
                magnitude
                    .checked_mul(magnitude)
                    .ok_or(OperatorClosureError::Arithmetic)?,
            )
            .ok_or(OperatorClosureError::Arithmetic)
        })
}

fn integer_sqrt(value: u128) -> Result<u128, OperatorClosureError> {
    if value == u128::MAX {
        return Err(OperatorClosureError::InternalInvariant);
    }
    Ok(value.isqrt())
}

fn fixed_from_u128(value: u128) -> Result<FixedQ32, OperatorClosureError> {
    Ok(FixedQ32::from_raw(
        i64::try_from(value).map_err(|_| OperatorClosureError::Arithmetic)?,
    ))
}

fn multiply_q32(left: FixedQ32, right: FixedQ32) -> Result<FixedQ32, OperatorClosureError> {
    let product = i128::from(left.raw())
        .checked_mul(i128::from(right.raw()))
        .ok_or(OperatorClosureError::Arithmetic)?;
    let quotient = product / SCALE;
    let remainder = product % SCALE;
    let twice = remainder
        .checked_abs()
        .and_then(|value| value.checked_mul(2))
        .ok_or(OperatorClosureError::Arithmetic)?;
    let rounded = if twice > SCALE || (twice == SCALE && quotient % 2 != 0) {
        quotient
            .checked_add(product.signum())
            .ok_or(OperatorClosureError::Arithmetic)?
    } else {
        quotient
    };
    Ok(FixedQ32::from_raw(
        i64::try_from(rounded).map_err(|_| OperatorClosureError::Arithmetic)?,
    ))
}

fn add_q32(left: FixedQ32, right: FixedQ32) -> Result<FixedQ32, OperatorClosureError> {
    let value = i128::from(left.raw())
        .checked_add(i128::from(right.raw()))
        .ok_or(OperatorClosureError::Arithmetic)?;
    Ok(FixedQ32::from_raw(
        i64::try_from(value).map_err(|_| OperatorClosureError::Arithmetic)?,
    ))
}

fn subtract_q32(left: FixedQ32, right: FixedQ32) -> Result<FixedQ32, OperatorClosureError> {
    let value = i128::from(left.raw())
        .checked_sub(i128::from(right.raw()))
        .ok_or(OperatorClosureError::Arithmetic)?;
    Ok(FixedQ32::from_raw(
        i64::try_from(value).map_err(|_| OperatorClosureError::Arithmetic)?,
    ))
}

fn normalize_ids(values: &mut Vec<StableId>) -> Result<(), OperatorClosureError> {
    values.sort();
    if let Some(adjacent) = values
        .windows(2)
        .find(|adjacent| adjacent[0] == adjacent[1])
    {
        return Err(OperatorClosureError::DuplicateIdentity(
            adjacent[0].to_string(),
        ));
    }
    Ok(())
}

fn digest_sensor_points(
    domain: &[u8],
    points: &[SensorPointV1],
) -> Result<Digest32, OperatorClosureError> {
    let mut bytes = domain.to_vec();
    bytes.extend_from_slice(
        &u32::try_from(points.len())
            .map_err(|_| OperatorClosureError::Arithmetic)?
            .to_be_bytes(),
    );
    for point in points {
        push_sensor_point(&mut bytes, point)?;
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn push_sensor_point(
    bytes: &mut Vec<u8>,
    point: &SensorPointV1,
) -> Result<(), OperatorClosureError> {
    push_id(bytes, &point.point_id);
    bytes.extend_from_slice(
        &u32::try_from(point.coordinates.len())
            .map_err(|_| OperatorClosureError::Arithmetic)?
            .to_be_bytes(),
    );
    for coordinate in &point.coordinates {
        bytes.extend_from_slice(&coordinate.raw().to_be_bytes());
    }
    Ok(())
}

fn require_digest(digest: Digest32, label: &'static str) -> Result<(), OperatorClosureError> {
    if digest.is_zero() {
        return Err(OperatorClosureError::EmptyDigest(label));
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "reference_tests.rs"]
mod tests;
