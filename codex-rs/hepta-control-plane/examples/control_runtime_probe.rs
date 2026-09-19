use std::time::Instant;

use codex_hepta_control_plane::AuthenticatedOwnerPortV1;
use codex_hepta_control_plane::EvaluatedPlanV1;
use codex_hepta_control_plane::GlobalPlanningRequestV1;
use codex_hepta_control_plane::GlobalStateSnapshotV1;
use codex_hepta_control_plane::NduPlanningError;
use codex_hepta_control_plane::NduPlanningInputV1;
use codex_hepta_control_plane::NduPlanningPortV1;
use codex_hepta_control_plane::OwnerPortErrorV1;
use codex_hepta_control_plane::OwnerReadinessV1;
use codex_hepta_control_plane::OwnerSummaryV1;
use codex_hepta_control_plane::PlanCandidateV1;
use codex_hepta_control_plane::PlannerAxisValueV1;
use codex_hepta_control_plane::PlanningRequestV1;
use codex_hepta_control_plane::PreparedPlanInputV1;
use codex_hepta_control_plane::ResourceReservationV1;
use codex_hepta_control_plane::SnapshotRequestV1;
use codex_hepta_control_plane::canonical_ndu_planning_policy_digest;
use codex_hepta_control_plane::canonical_resource_profile_digest;
use codex_hepta_control_plane::evaluate_prepared_plan_with_ndu;
use codex_hepta_control_plane::plan_global_v1;
use codex_hepta_ndu::AxisDirection;
use codex_hepta_ndu::AxisValue;
use codex_hepta_ndu::ContributionSet;
use codex_hepta_ndu::FeasibilityPosture;
use codex_hepta_ndu::RequiredOrganSet;
use codex_hepta_ndu::UtilityContribution;
use codex_hepta_ndu::UtilityProfile;
use codex_hepta_ndu::legacy_evaluation_policy;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

const OWNER_COUNT: usize = 32;
const CANDIDATE_COUNT: usize = 128;
const RESOURCE_AXIS_COUNT: usize = 32;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("probe identifiers are valid")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn q32(value: i64) -> FixedQ32 {
    FixedQ32::from_raw(value << 32)
}

#[derive(Clone)]
struct FixedOwnerPort {
    summary: OwnerSummaryV1,
}

impl AuthenticatedOwnerPortV1 for FixedOwnerPort {
    fn owner_id(&self) -> &StableId {
        &self.summary.owner_id
    }

    fn snapshot_summary(
        &self,
        _request: &SnapshotRequestV1,
    ) -> Result<OwnerSummaryV1, OwnerPortErrorV1> {
        Ok(self.summary.clone())
    }
}

struct RealNduPort {
    input: NduPlanningInputV1,
}

impl NduPlanningPortV1 for RealNduPort {
    fn evaluate(
        &self,
        snapshot: &GlobalStateSnapshotV1,
        prepared: &PreparedPlanInputV1,
        now_micros: u64,
    ) -> Result<EvaluatedPlanV1, NduPlanningError> {
        evaluate_prepared_plan_with_ndu(snapshot, prepared, self.input.clone(), now_micros)
    }
}

fn build_fixture() -> (
    Vec<FixedOwnerPort>,
    RealNduPort,
    GlobalPlanningRequestV1,
) {
    let generation = Generation::new(17).expect("generation");
    let owner_ids: Vec<_> = (0..OWNER_COUNT)
        .map(|index| id(&format!("owner-{index:02}")))
        .collect();
    let resource_axes: Vec<_> = (0..RESOURCE_AXIS_COUNT)
        .map(|index| id(&format!("resource-{index:02}")))
        .collect();
    let utility_axis = id("bounded-utility");

    let owners = owner_ids
        .iter()
        .enumerate()
        .map(|(index, owner_id)| FixedOwnerPort {
            summary: OwnerSummaryV1 {
                owner_id: owner_id.clone(),
                revision: Revision::new(u64::try_from(index + 1).expect("revision"))
                    .expect("nonzero revision"),
                objective_digest: digest("probe-objective"),
                body_generation: generation,
                configuration_digest: digest("probe-configuration"),
                observed_at_micros: 9_990,
                expires_at_micros: 1_000_000,
                readiness: OwnerReadinessV1::Ready,
                source_frontier_digest: digest(&format!("frontier:{index}")),
                support_digest: digest(&format!("support:{index}")),
            },
        })
        .collect::<Vec<_>>();

    let profile = UtilityProfile {
        profile_id: id("control-runtime-probe"),
        dimensions: vec![(utility_axis.clone(), AxisDirection::Maximize)],
        risk_ceilings: vec![],
        resource_ceilings: vec![],
        required_organs: RequiredOrganSet {
            organ_ids: owner_ids.clone(),
        },
    };
    let mut ndu_input = NduPlanningInputV1 {
        policy: legacy_evaluation_policy(&profile).expect("policy"),
        profile,
        scalarization: None,
        contributions: ContributionSet {
            objective_digest: digest("probe-objective"),
            generation,
            contributions: Vec::with_capacity(OWNER_COUNT * CANDIDATE_COUNT),
        },
    };

    let candidates = (0..CANDIDATE_COUNT)
        .map(|index| {
            let candidate_id = if index == 0 {
                id("abstain")
            } else {
                id(&format!("candidate-{index:03}"))
            };
            for owner_id in &owner_ids {
                ndu_input.contributions.contributions.push(UtilityContribution {
                    candidate_id: candidate_id.clone(),
                    organ_id: owner_id.clone(),
                    objective_digest: digest("probe-objective"),
                    generation,
                    feasibility: FeasibilityPosture::Feasible,
                    utility: vec![AxisValue {
                        axis: utility_axis.clone(),
                        value: q32(i64::try_from(index).expect("candidate index")),
                    }],
                    risk: vec![],
                    resource: vec![],
                    uncertainty: vec![AxisValue {
                        axis: utility_axis.clone(),
                        value: FixedQ32::ZERO,
                    }],
                    support_digest: digest(&format!(
                        "candidate:{index}:owner:{}",
                        owner_id.as_str()
                    )),
                });
            }
            PlanCandidateV1 {
                candidate_id: candidate_id.clone(),
                operation_id: id(&format!("operation-{index:03}")),
                plan_digest: digest(&format!("plan:{index}")),
                required_owner_ids: owner_ids.clone(),
                final_payload_digests: if index == 0 {
                    vec![]
                } else {
                    vec![digest(&format!("payload:{index}"))]
                },
                resource_costs: resource_axes
                    .iter()
                    .map(|axis| PlannerAxisValueV1 {
                        axis: axis.clone(),
                        value: if index == 0 {
                            FixedQ32::ZERO
                        } else {
                            FixedQ32::ONE
                        },
                    })
                    .collect(),
            }
        })
        .collect::<Vec<_>>();

    let reservations = resource_axes
        .iter()
        .map(|axis| ResourceReservationV1 {
            axis: axis.clone(),
            endowment: q32(100),
            essential_floor: q32(10),
        })
        .collect::<Vec<_>>();
    let evaluation_policy_digest =
        canonical_ndu_planning_policy_digest(&ndu_input).expect("NDU profile digest");
    let resource_profile_digest =
        canonical_resource_profile_digest(&reservations).expect("resource profile digest");

    (
        owners,
        RealNduPort { input: ndu_input },
        GlobalPlanningRequestV1 {
            snapshot_request: SnapshotRequestV1 {
                objective_digest: digest("probe-objective"),
                body_generation: generation,
                configuration_digest: digest("probe-configuration"),
                revocation_frontier_digest: digest("probe-revocation-frontier"),
                snapshot_policy_digest: digest("probe-snapshot-policy"),
                collected_at_micros: 10_000,
                maximum_owner_age_micros: 100,
                expires_at_micros: 1_000_000,
                required_owner_ids: owner_ids,
            },
            planning_request: PlanningRequestV1 {
                plan_id: id("probe-global-plan"),
                now_micros: 10_000,
                deadline_micros: 900_000,
                evaluation_policy_digest,
                resource_profile_digest,
                candidates,
                resource_reservations: reservations,
            },
            now_micros: 10_000,
        },
    )
}

fn percentile(sorted: &[u128], percentile: usize) -> u128 {
    let index = sorted
        .len()
        .saturating_mul(percentile)
        .saturating_sub(1)
        / 100;
    sorted[index.min(sorted.len() - 1)]
}

fn linux_high_water_kib() -> Option<u64> {
    let status = std::fs::read_to_string("/proc/self/status").ok()?;
    status.lines().find_map(|line| {
        line.strip_prefix("VmHWM:")
            .and_then(|rest| rest.split_whitespace().next())
            .and_then(|value| value.parse().ok())
    })
}

fn main() {
    let iterations = std::env::args()
        .nth(1)
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|value| *value > 0)
        .unwrap_or(25);
    let (owners, ndu, request) = build_fixture();
    let owner_refs: Vec<&dyn AuthenticatedOwnerPortV1> = owners
        .iter()
        .map(|owner| owner as &dyn AuthenticatedOwnerPortV1)
        .collect();

    let warmup = plan_global_v1(&owner_refs, &ndu, request.clone()).expect("warmup global plan");
    assert_eq!(warmup.snapshot.owner_summaries().len(), OWNER_COUNT);
    assert_eq!(warmup.prepared.feasible_candidates().len(), CANDIDATE_COUNT);
    assert_eq!(warmup.grant_requests.requests().len(), 1);

    let mut samples = Vec::with_capacity(iterations);
    for _ in 0..iterations {
        let started = Instant::now();
        let result = plan_global_v1(&owner_refs, &ndu, request.clone()).expect("global plan");
        assert_eq!(result.grant_requests.requests().len(), 1);
        samples.push(started.elapsed().as_micros());
    }
    samples.sort_unstable();

    let p50 = percentile(&samples, 50);
    let p95 = percentile(&samples, 95);
    let p99 = percentile(&samples, 99);
    let maximum = *samples.last().expect("at least one sample");
    let runner_os = std::env::var("RUNNER_OS").unwrap_or_else(|_| std::env::consts::OS.to_string());
    let runner_arch =
        std::env::var("RUNNER_ARCH").unwrap_or_else(|_| std::env::consts::ARCH.to_string());
    let source_sha = std::env::var("TESTED_SHA")
        .or_else(|_| std::env::var("GITHUB_SHA"))
        .unwrap_or_else(|_| "unknown".to_string());
    let hwm = linux_high_water_kib()
        .map(|value| value.to_string())
        .unwrap_or_else(|| "null".to_string());

    println!(
        "{{\"schema\":\"hepta.control-runtime.named-host-probe.v1\",\"source_sha\":\"{source_sha}\",\"runner_os\":\"{runner_os}\",\"runner_arch\":\"{runner_arch}\",\"iterations\":{iterations},\"owners\":{OWNER_COUNT},\"candidates\":{CANDIDATE_COUNT},\"required_owners_per_candidate\":{OWNER_COUNT},\"resource_axes\":{RESOURCE_AXIS_COUNT},\"ndu_contributions\":{},\"p50_us\":{p50},\"p95_us\":{p95},\"p99_us\":{p99},\"max_us\":{maximum},\"process_vm_hwm_kib\":{hwm}}}",
        OWNER_COUNT * CANDIDATE_COUNT
    );
}
