//! Distinct paired full-information plan; no OPE conversion.
//! The first profile is explicitly previously observed engineering evidence.

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

const MAGIC: &[u8; 8] = b"HEPTPF01";
const MAX_BYTES: usize = 2048;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairedPlanSpecV1 {
    pub plan_id: StableId,
    pub candidate_id: StableId,
    pub baseline_id: StableId,
    pub holdout_window_id: StableId,
    pub objective_digest: Digest32,
    pub dataset_digest: Digest32,
    /// Source cohort identity, independent of arm, measured outcomes and analysis.
    pub holdout_digest: Digest32,
    pub context_manifest_digest: Digest32,
    pub version_manifest_digest: Digest32,
    pub source_bundle_digest: Digest32,
    /// Exact escrowed observations, frozen only in this post-hoc engineering profile.
    pub outcome_bundle_digest: Digest32,
    pub metric_digest: Digest32,
    pub audit_observer_digest: Digest32,
    pub reward_observer_digest: Digest32,
    pub estimand_digest: Digest32,
    pub source_cases: u32,
    pub seeds: u32,
    pub family_alpha_ppm: u32,
    /// Includes both mean loss and factual-error comparisons, plus any family.
    pub simultaneous_comparisons: u32,
    pub required_modalities: u8,
    pub minimum_loss_improvement: FixedQ32,
    pub maximum_fact_error_increase: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FrozenPairedPlanV1 {
    spec: PairedPlanSpecV1,
    plan_digest: Digest32,
    receipt_seal: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairedProfileError(pub &'static str);
impl std::fmt::Display for PairedProfileError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "invalid paired profile: {}", self.0)
    }
}
impl std::error::Error for PairedProfileError {}

pub fn freeze_paired_plan_v1(
    spec: PairedPlanSpecV1,
) -> Result<FrozenPairedPlanV1, PairedProfileError> {
    validate_spec(&spec)?;
    let plan_digest = Digest32::of_bytes(&body(&spec));
    Ok(FrozenPairedPlanV1 {
        spec,
        plan_digest,
        receipt_seal: seal(
            b"hepta.paired-full-information.plan-seal.v1",
            &[plan_digest],
        ),
    })
}

impl FrozenPairedPlanV1 {
    pub fn spec(&self) -> &PairedPlanSpecV1 {
        &self.spec
    }
    pub fn plan_digest(&self) -> Digest32 {
        self.plan_digest
    }
    pub fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
    /// No caller can reclassify old observations as preregistered qualification.
    pub fn previously_observed_engineering_only(&self) -> bool {
        true
    }
    pub fn validate(&self) -> Result<(), PairedProfileError> {
        validate_spec(&self.spec)?;
        if self.plan_digest != Digest32::of_bytes(&body(&self.spec))
            || self.receipt_seal
                != seal(
                    b"hepta.paired-full-information.plan-seal.v1",
                    &[self.plan_digest],
                )
        {
            return Err(PairedProfileError("plan seal"));
        }
        Ok(())
    }
}

fn validate_spec(s: &PairedPlanSpecV1) -> Result<(), PairedProfileError> {
    if s.candidate_id == s.baseline_id
        || !(1..=4096).contains(&s.source_cases)
        || !(1..=32).contains(&s.seeds)
        || !(1..=100_000).contains(&s.family_alpha_ppm)
        || !(2..=1024).contains(&s.simultaneous_comparisons)
        || s.required_modalities != 3
        || !(0..=(1_i64 << 32)).contains(&s.minimum_loss_improvement.raw())
        || !(0..=(1_i64 << 32)).contains(&s.maximum_fact_error_increase.raw())
        || s.audit_observer_digest == s.reward_observer_digest
        || digests(s).iter().copied().any(Digest32::is_zero)
    {
        return Err(PairedProfileError("frozen bounds or identities"));
    }
    if body(s).len() + 64 > MAX_BYTES {
        return Err(PairedProfileError("plan byte bound"));
    }
    Ok(())
}

fn digests(s: &PairedPlanSpecV1) -> [Digest32; 11] {
    [
        s.objective_digest,
        s.dataset_digest,
        s.holdout_digest,
        s.context_manifest_digest,
        s.version_manifest_digest,
        s.source_bundle_digest,
        s.outcome_bundle_digest,
        s.metric_digest,
        s.audit_observer_digest,
        s.reward_observer_digest,
        s.estimand_digest,
    ]
}

fn body(s: &PairedPlanSpecV1) -> Vec<u8> {
    let mut bytes = MAGIC.to_vec();
    // Explicit evidence-use tag 0 = observed engineering replay. No fresh mode.
    bytes.push(0);
    for id in [
        &s.plan_id,
        &s.candidate_id,
        &s.baseline_id,
        &s.holdout_window_id,
    ] {
        bytes.extend_from_slice(&(id.as_str().len() as u16).to_be_bytes());
        bytes.extend_from_slice(id.as_str().as_bytes());
    }
    for value in digests(s) {
        bytes.extend_from_slice(value.as_array());
    }
    for value in [
        s.source_cases,
        s.seeds,
        s.family_alpha_ppm,
        s.simultaneous_comparisons,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    bytes.push(s.required_modalities);
    bytes.extend_from_slice(&s.minimum_loss_improvement.raw().to_be_bytes());
    bytes.extend_from_slice(&s.maximum_fact_error_increase.raw().to_be_bytes());
    bytes
}

pub(crate) fn seal(domain: &[u8], digests: &[Digest32]) -> Digest32 {
    let mut bytes = domain.to_vec();
    for value in digests {
        bytes.extend_from_slice(value.as_array());
    }
    Digest32::of_bytes(&bytes)
}

pub(crate) fn encode_paired_plan(plan: &FrozenPairedPlanV1) -> Result<Vec<u8>, PairedProfileError> {
    plan.validate()?;
    let mut bytes = body(&plan.spec);
    bytes.extend_from_slice(plan.plan_digest.as_array());
    bytes.extend_from_slice(plan.receipt_seal.as_array());
    Ok(bytes)
}

pub(crate) fn decode_paired_plan(
    mut bytes: &[u8],
) -> Result<FrozenPairedPlanV1, PairedProfileError> {
    fn take<'a>(b: &mut &'a [u8], n: usize) -> Result<&'a [u8], PairedProfileError> {
        let (a, rest) = b
            .split_at_checked(n)
            .ok_or(PairedProfileError("plan encoding"))?;
        *b = rest;
        Ok(a)
    }
    fn id(b: &mut &[u8]) -> Result<StableId, PairedProfileError> {
        let n = u16::from_be_bytes(
            take(b, 2)?
                .try_into()
                .map_err(|_| PairedProfileError("id"))?,
        ) as usize;
        if !(1..=128).contains(&n) {
            return Err(PairedProfileError("id bound"));
        }
        StableId::new(std::str::from_utf8(take(b, n)?).map_err(|_| PairedProfileError("id utf8"))?)
            .map_err(|_| PairedProfileError("id"))
    }
    if bytes.len() > MAX_BYTES || take(&mut bytes, 8)? != MAGIC || take(&mut bytes, 1)? != [0] {
        return Err(PairedProfileError("plan version or evidence-use mode"));
    }
    let ids = [
        id(&mut bytes)?,
        id(&mut bytes)?,
        id(&mut bytes)?,
        id(&mut bytes)?,
    ];
    let mut ds = [Digest32::ZERO; 13];
    for d in &mut ds[..11] {
        *d = Digest32::from_array(
            take(&mut bytes, 32)?
                .try_into()
                .map_err(|_| PairedProfileError("digest"))?,
        );
    }
    let mut ns = [0; 4];
    for n in &mut ns {
        *n = u32::from_be_bytes(
            take(&mut bytes, 4)?
                .try_into()
                .map_err(|_| PairedProfileError("count"))?,
        );
    }
    let required = take(&mut bytes, 1)?[0];
    let loss = i64::from_be_bytes(
        take(&mut bytes, 8)?
            .try_into()
            .map_err(|_| PairedProfileError("margin"))?,
    );
    let fact = i64::from_be_bytes(
        take(&mut bytes, 8)?
            .try_into()
            .map_err(|_| PairedProfileError("margin"))?,
    );
    for d in &mut ds[11..] {
        *d = Digest32::from_array(
            take(&mut bytes, 32)?
                .try_into()
                .map_err(|_| PairedProfileError("seal"))?,
        );
    }
    if !bytes.is_empty() {
        return Err(PairedProfileError("trailing plan bytes"));
    }
    let [plan_id, candidate_id, baseline_id, holdout_window_id] = ids;
    let result = FrozenPairedPlanV1 {
        spec: PairedPlanSpecV1 {
            plan_id,
            candidate_id,
            baseline_id,
            holdout_window_id,
            objective_digest: ds[0],
            dataset_digest: ds[1],
            holdout_digest: ds[2],
            context_manifest_digest: ds[3],
            version_manifest_digest: ds[4],
            source_bundle_digest: ds[5],
            outcome_bundle_digest: ds[6],
            metric_digest: ds[7],
            audit_observer_digest: ds[8],
            reward_observer_digest: ds[9],
            estimand_digest: ds[10],
            source_cases: ns[0],
            seeds: ns[1],
            family_alpha_ppm: ns[2],
            simultaneous_comparisons: ns[3],
            required_modalities: required,
            minimum_loss_improvement: FixedQ32::from_raw(loss),
            maximum_fact_error_increase: FixedQ32::from_raw(fact),
        },
        plan_digest: ds[11],
        receipt_seal: ds[12],
    };
    result.validate()?;
    Ok(result)
}
