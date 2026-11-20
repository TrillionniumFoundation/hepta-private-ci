use super::*;
use codex_hepta_agentd::AgentdHos2Usage;
use pretty_assertions::assert_eq;

#[test]
fn observed_bootstrap_updates_are_preserved_instead_of_reset_to_one() {
    let mut boot = vec![0; 192];
    boot[96..112].copy_from_slice(&[3; 16]);
    boot[168..176].copy_from_slice(&50_000_000_u64.to_le_bytes());
    boot[176..184].copy_from_slice(&100_000_000_u64.to_le_bytes());
    let mut usage = AgentdHos2Usage {
        boot_id: [3; 16],
        observer_space_id: [4; 16],
        revision: 2,
        sample_boottime_ns: 5,
        cumulative_cpu_ns: 6,
        window_start_ns: 7,
        window_consumed_ns: 8,
        active_cap_ns: 50_000_000,
        active_period_ns: 100_000_000,
        event_sequence: 9,
        dropped_events: 0,
    };
    for revision in [2, 17, u64::MAX - 1] {
        usage.revision = revision;
        assert_eq!(initial_revision(&usage, &boot).unwrap(), revision);
        assert_eq!(next_revision(revision).unwrap(), revision + 1);
    }
    for revision in [0, u64::MAX] {
        usage.revision = revision;
        assert!(initial_revision(&usage, &boot).is_err());
    }
    usage.revision = 2;
    usage.boot_id[0] = 9;
    assert!(initial_revision(&usage, &boot).is_err());
    usage.boot_id = [3; 16];
    usage.active_cap_ns = 25_000_000;
    assert!(initial_revision(&usage, &boot).is_err());
    usage.active_cap_ns = 50_000_000;
    usage.active_period_ns += 1;
    assert!(initial_revision(&usage, &boot).is_err());
}
