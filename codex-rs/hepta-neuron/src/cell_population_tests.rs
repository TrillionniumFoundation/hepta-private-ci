use pretty_assertions::assert_eq;

use super::*;
use crate::CellFunctionalRoleV1;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn limits() -> CellPopulationLimitsV1 {
    CellPopulationLimitsV1 {
        max_types: 16,
        max_expert_versions: 16,
        max_instances: 16,
        max_active_instances: 16,
        max_reserved_state_bytes: 1_024,
    }
}

#[derive(Clone)]
struct Inventory {
    capabilities: Vec<CellCapabilityContractV1>,
    experts: Vec<CellExpertVersionV1>,
    instances: Vec<CellInstanceV1>,
}

impl Inventory {
    fn population(
        self,
        limits: CellPopulationLimitsV1,
    ) -> Result<CellPopulationV1, CellPopulationErrorV1> {
        CellPopulationV1::new(
            digest("scope"),
            limits,
            self.capabilities,
            self.experts,
            self.instances,
        )
    }
}

fn inventory() -> Inventory {
    let capabilities: Vec<_> = ["code", "science"]
        .into_iter()
        .map(|name| CellCapabilityContractV1 {
            type_id: id(&format!("memory.{name}")),
            generation: Generation::new(1).expect("generation"),
            role: CellFunctionalRoleV1::MemoryAssociation,
            input_schema_digest: digest("input"),
            output_schema_digest: digest("output"),
            state_schema_digest: digest("state"),
            behavior_contract_digest: digest(name),
        })
        .collect();
    let experts: Vec<_> = [0, 0, 1]
        .into_iter()
        .enumerate()
        .map(|(index, capability)| CellExpertVersionV1 {
            version_id: id(&format!("expert.{index}")),
            type_id: capabilities[capability].type_id.clone(),
            capability_digest: capabilities[capability].digest().expect("capability"),
            shared_base_digest: digest("one shared base"),
            parameter_bundle_digest: digest(&format!("bundle.{index}")),
        })
        .collect();
    let instances = [0, 0, 1, 2]
        .into_iter()
        .enumerate()
        .map(|(index, expert)| CellInstanceV1 {
            instance_id: id(&format!("cell.{index}")),
            scope_digest: digest("scope"),
            generation: Generation::new(1).expect("generation"),
            type_id: experts[expert].type_id.clone(),
            expert_version_id: experts[expert].version_id.clone(),
            state_owner_id: id("neuron.runtime"),
            state_slot_id: id(&format!("slot.{index}")),
            state_schema_digest: digest("state"),
            reserved_state_bytes: 64,
            disposition: CellInstanceDispositionV1::Available,
        })
        .collect();
    Inventory {
        capabilities,
        experts,
        instances,
    }
}

fn active(instance: &CellInstanceV1) -> CellActiveInstanceV1 {
    CellActiveInstanceV1 {
        instance_id: instance.instance_id.clone(),
        scope_digest: instance.scope_digest,
        generation: instance.generation,
        expert_version_id: instance.expert_version_id.clone(),
    }
}

#[test]
fn census_separates_types_versions_state_slots_and_observed_active_subset() {
    let inventory = inventory();
    let observations = [
        active(&inventory.instances[0]),
        active(&inventory.instances[3]),
    ];
    let population = inventory.clone().population(limits()).expect("population");
    let expected = CellPopulationCensusV1 {
        scope_digest: digest("scope"),
        type_count: 2,
        expert_version_count: 3,
        instance_count: 4,
        active_instance_count: 2,
        reserved_state_bytes: 256,
        authority: AuthorityPosture::DENY_ALL,
    };
    assert_eq!(population.census(&observations), Ok(expected.clone()));
    let mut reordered = inventory;
    reordered.capabilities.reverse();
    reordered.experts.reverse();
    reordered.instances.reverse();
    assert_eq!(reordered.population(limits()), Ok(population.clone()));
    assert_eq!(
        population.census(&[observations[1].clone(), observations[0].clone()]),
        Ok(expected)
    );
    assert_eq!(
        population.census(&[]),
        Ok(CellPopulationCensusV1 {
            active_instance_count: 0,
            ..population.census(&observations).expect("observed")
        })
    );
}

#[test]
fn duplicate_type_names_and_semantic_aliases_do_not_inflate_type_count() {
    let mut value = inventory();
    value.capabilities[1].type_id = value.capabilities[0].type_id.clone();
    assert_eq!(
        value.population(limits()),
        Err(CellPopulationErrorV1::DuplicateType(id("memory.code")))
    );
    let mut value = inventory();
    let mut alias = value.capabilities[0].clone();
    alias.type_id = id("another.name");
    alias.generation = alias.generation.next().expect("next");
    alias.role = CellFunctionalRoleV1::LearningDevelopment;
    value.capabilities.push(alias);
    assert_eq!(
        value.population(limits()),
        Err(CellPopulationErrorV1::TypeAlias(id("another.name")))
    );
}

#[test]
fn expert_versions_bind_registered_capabilities_and_cannot_alias_a_bundle() {
    let original = inventory();
    let mut value = original.clone();
    value.experts[0].type_id = id("unknown.type");
    assert_eq!(
        value.population(limits()),
        Err(CellPopulationErrorV1::UnregisteredType(id("unknown.type")))
    );
    let mut value = original.clone();
    value.experts[0].capability_digest =
        original.capabilities[1].digest().expect("other capability");
    assert_eq!(
        value.population(limits()),
        Err(CellPopulationErrorV1::CapabilityMismatch(id("expert.0")))
    );
    let mut value = original.clone();
    value.experts[1].version_id = id("expert.0");
    assert_eq!(
        value.population(limits()),
        Err(CellPopulationErrorV1::DuplicateExpertVersion(id(
            "expert.0"
        )))
    );
    let mut value = original.clone();
    value.experts[1].parameter_bundle_digest = value.experts[0].parameter_bundle_digest;
    assert_eq!(
        value.population(limits()),
        Err(CellPopulationErrorV1::ExpertVersionAlias(id("expert.1")))
    );
    for field in ["shared base", "parameter bundle"] {
        let mut value = original.clone();
        if field == "shared base" {
            value.experts[0].shared_base_digest = Digest32::ZERO;
        } else {
            value.experts[0].parameter_bundle_digest = Digest32::ZERO;
        }
        assert_eq!(
            value.population(limits()),
            Err(CellPopulationErrorV1::EmptyDigest(field))
        );
    }
}

#[test]
fn instances_require_registered_matching_type_expert_scope_and_state_schema() {
    let original = inventory();
    let mut value = original.clone();
    value.instances[0].expert_version_id = id("missing.expert");
    assert_eq!(
        value.population(limits()),
        Err(CellPopulationErrorV1::UnregisteredExpertVersion(id(
            "missing.expert"
        )))
    );
    let mut value = original.clone();
    value.instances[0].type_id = id("missing.type");
    assert_eq!(
        value.population(limits()),
        Err(CellPopulationErrorV1::UnregisteredType(id("missing.type")))
    );
    let mut value = original.clone();
    value.instances[0].type_id = value.capabilities[1].type_id.clone();
    assert_eq!(
        value.population(limits()),
        Err(CellPopulationErrorV1::InstanceTypeMismatch(id("cell.0")))
    );
    let mut value = original.clone();
    value.instances[0].scope_digest = digest("other scope");
    assert_eq!(
        value.population(limits()),
        Err(CellPopulationErrorV1::ScopeMismatch(id("cell.0")))
    );
    let mut value = original;
    value.instances[0].state_schema_digest = digest("incompatible state schema");
    assert_eq!(
        value.population(limits()),
        Err(CellPopulationErrorV1::StateSchemaMismatch(id("cell.0")))
    );
}

#[test]
fn duplicate_instances_and_state_slots_are_rejected_across_owner_names() {
    let mut value = inventory();
    value.instances[1].instance_id = id("cell.0");
    assert_eq!(
        value.population(limits()),
        Err(CellPopulationErrorV1::DuplicateInstance(id("cell.0")))
    );
    for owner in ["neuron.runtime", "different.owner"] {
        let mut value = inventory();
        value.instances[1].state_slot_id = id("slot.0");
        value.instances[1].state_owner_id = id(owner);
        assert_eq!(
            value.population(limits()),
            Err(CellPopulationErrorV1::StateSlotAlias(id("slot.0")))
        );
    }
}

#[test]
fn all_inventory_and_active_budgets_are_checked_independently() {
    let original = limits();
    for (restricted, name) in [
        (
            CellPopulationLimitsV1 {
                max_types: 1,
                ..original
            },
            "types",
        ),
        (
            CellPopulationLimitsV1 {
                max_expert_versions: 2,
                ..original
            },
            "expert versions",
        ),
        (
            CellPopulationLimitsV1 {
                max_instances: 3,
                max_active_instances: 3,
                ..original
            },
            "instances",
        ),
        (
            CellPopulationLimitsV1 {
                max_reserved_state_bytes: 255,
                ..original
            },
            "reserved state bytes",
        ),
    ] {
        assert_eq!(
            inventory().population(restricted),
            Err(CellPopulationErrorV1::CapacityExceeded(name))
        );
    }
    let value = inventory();
    let observations = [active(&value.instances[0]), active(&value.instances[1])];
    let population = value
        .population(CellPopulationLimitsV1 {
            max_active_instances: 1,
            ..original
        })
        .expect("inventory remains within bounds");
    assert_eq!(
        population.census(&observations),
        Err(CellPopulationErrorV1::CapacityExceeded("active instances"))
    );
}

#[test]
fn invalid_limits_and_state_reservation_overflow_fail_closed() {
    let original = limits();
    for restricted in [
        CellPopulationLimitsV1 {
            max_types: 0,
            ..original
        },
        CellPopulationLimitsV1 {
            max_instances: MAX_POPULATION_ENTRIES_V1 + 1,
            ..original
        },
        CellPopulationLimitsV1 {
            max_active_instances: 17,
            ..original
        },
        CellPopulationLimitsV1 {
            max_reserved_state_bytes: 0,
            ..original
        },
    ] {
        assert_eq!(
            inventory().population(restricted),
            Err(CellPopulationErrorV1::InvalidLimits)
        );
    }
    let mut value = inventory();
    value.instances[0].reserved_state_bytes = 0;
    assert_eq!(
        value.population(original),
        Err(CellPopulationErrorV1::InvalidStateReservation(id("cell.0")))
    );
    let mut value = inventory();
    value.instances[0].reserved_state_bytes = u64::MAX;
    assert_eq!(
        value.population(CellPopulationLimitsV1 {
            max_reserved_state_bytes: u64::MAX,
            ..original
        }),
        Err(CellPopulationErrorV1::CapacityExceeded(
            "reserved state bytes"
        ))
    );
}

#[test]
fn active_observations_cannot_repeat_cross_scope_or_rebind_versions() {
    let value = inventory();
    let original = active(&value.instances[0]);
    let population = value.population(limits()).expect("population");
    assert_eq!(
        population.census(&[original.clone(), original.clone()]),
        Err(CellPopulationErrorV1::DuplicateActiveInstance(id("cell.0")))
    );
    let mut changed = original.clone();
    changed.instance_id = id("missing.instance");
    assert_eq!(
        population.census(&[changed]),
        Err(CellPopulationErrorV1::UnregisteredActiveInstance(id(
            "missing.instance"
        )))
    );
    let mut changed = original.clone();
    changed.scope_digest = digest("other scope");
    assert_eq!(
        population.census(&[changed]),
        Err(CellPopulationErrorV1::ScopeMismatch(id("cell.0")))
    );
    let mut changed = original.clone();
    changed.generation = changed.generation.next().expect("next");
    assert_eq!(
        population.census(&[changed]),
        Err(CellPopulationErrorV1::ActiveVersionMismatch(id("cell.0")))
    );
    let mut changed = original;
    changed.expert_version_id = id("expert.1");
    assert_eq!(
        population.census(&[changed]),
        Err(CellPopulationErrorV1::ActiveVersionMismatch(id("cell.0")))
    );
}

#[test]
fn quarantined_and_retired_instances_remain_accounted_but_cannot_be_active() {
    for disposition in [
        CellInstanceDispositionV1::Quarantined,
        CellInstanceDispositionV1::Retired,
    ] {
        let mut value = inventory();
        value.instances[0].disposition = disposition;
        let observation = active(&value.instances[0]);
        let population = value.population(limits()).expect("retained inventory");
        assert_eq!(
            population.census(&[observation]),
            Err(CellPopulationErrorV1::InstanceUnavailable(id("cell.0")))
        );
        assert_eq!(
            population.census(&[]),
            Ok(CellPopulationCensusV1 {
                scope_digest: digest("scope"),
                type_count: 2,
                expert_version_count: 3,
                instance_count: 4,
                active_instance_count: 0,
                reserved_state_bytes: 256,
                authority: AuthorityPosture::DENY_ALL,
            })
        );
    }
}
