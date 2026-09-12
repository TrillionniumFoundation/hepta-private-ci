use std::collections::BTreeSet;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;

use super::*;
use crate::FailureDomainV1;
use crate::OrganNodeV1;
use crate::OrganRole;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture identity")
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("fixture generation")
}

fn graph(value: u64) -> OrganGraphsV1 {
    OrganGraphsV1 {
        generation: generation(value),
        organs: vec![OrganNodeV1 {
            id: id("organ"),
            owner: id("owner"),
            role: OrganRole::Other,
            inputs: vec![],
            outputs: vec![id("message.v1")],
            effect_scope: BTreeSet::new(),
            terminal: FallbackTerminal::SafeState(Digest32::of_bytes(b"safe")),
        }],
        initialization: vec![],
        runtime: vec![],
        feedback: vec![],
        fallback: vec![],
        failure_domains: vec![FailureDomainV1 {
            organ: 0,
            process: id("process"),
            host: id("host"),
        }],
    }
}

#[derive(Clone, Copy, Debug)]
enum FailurePoint {
    CandidateStart,
    CandidateMigration,
    PredecessorStop,
}

#[derive(Debug)]
struct Organ {
    id: StableId,
    start_failure: bool,
    stop_failure: bool,
    stops: Arc<Mutex<usize>>,
}

impl TrustedReadOnlyOrganV1 for Organ {
    fn id(&self) -> &StableId {
        &self.id
    }

    fn start(&mut self) -> Result<(), OrganHandlerFaultV1> {
        if self.start_failure {
            Err(OrganHandlerFaultV1::new(id("start.failed")))
        } else {
            Ok(())
        }
    }

    fn handle(
        &mut self,
        _input_port: usize,
        _payload: &[u8],
    ) -> Result<Vec<u8>, OrganHandlerFaultV1> {
        panic!("quarantined generation must never dispatch")
    }

    fn stop(&mut self) -> Result<(), OrganHandlerFaultV1> {
        *self.stops.lock().expect("counter lock") += 1;
        if self.stop_failure {
            Err(OrganHandlerFaultV1::new(id("stop.failed")))
        } else {
            Ok(())
        }
    }
}

struct Migration {
    fail_migrate: bool,
    calls: Vec<&'static str>,
}

impl OrganStateMigrationV1 for Migration {
    fn snapshot(&mut self, predecessor: Generation) -> Result<Vec<u8>, OrganMigrationError> {
        assert_eq!(predecessor, generation(7));
        self.calls.push("snapshot");
        Ok(b"retained-state".to_vec())
    }

    fn migrate(
        &mut self,
        snapshot: &[u8],
        predecessor: Generation,
        candidate: Generation,
    ) -> Result<(), OrganMigrationError> {
        assert_eq!(
            (snapshot, predecessor, candidate),
            (&b"retained-state"[..], generation(7), generation(8))
        );
        self.calls.push("migrate");
        if self.fail_migrate {
            Err(OrganMigrationError::Callback(id("migration.failed")))
        } else {
            Ok(())
        }
    }

    fn rollback(
        &mut self,
        snapshot: &[u8],
        predecessor: Generation,
        candidate: Generation,
    ) -> Result<(), OrganMigrationError> {
        assert_eq!(
            (snapshot, predecessor, candidate),
            (&b"retained-state"[..], generation(7), generation(8))
        );
        self.calls.push("rollback");
        Err(OrganMigrationError::Callback(id("rollback.failed")))
    }
}

#[test]
fn rollback_failure_is_visible_and_quarantines_every_failure_path() {
    for point in [
        FailurePoint::CandidateStart,
        FailurePoint::CandidateMigration,
        FailurePoint::PredecessorStop,
    ] {
        let old_stops = Arc::new(Mutex::new(0));
        let new_stops = Arc::new(Mutex::new(0));
        let old = Organ {
            id: id("organ"),
            start_failure: false,
            stop_failure: matches!(point, FailurePoint::PredecessorStop),
            stops: Arc::clone(&old_stops),
        };
        let candidate = Organ {
            id: id("organ"),
            start_failure: matches!(point, FailurePoint::CandidateStart),
            stop_failure: true,
            stops: Arc::clone(&new_stops),
        };
        let mut host = OrganHostV1::new(graph(7), vec![Box::new(old)]).expect("valid host");
        host.start_all().expect("predecessor starts");
        let mut migration = Migration {
            fail_migrate: matches!(point, FailurePoint::CandidateMigration),
            calls: vec![],
        };
        let error = host
            .replace_read_only_generation_with_migration(
                generation(7),
                graph(8),
                vec![Box::new(candidate)],
                &mut migration,
            )
            .expect_err("rollback failed");
        let fault = OrganFaultRecordV1 {
            organ: id("organ"),
            code: id("stop.failed"),
        };
        let rollback = OrganMigrationError::Callback(id("rollback.failed"));
        let expected = match point {
            FailurePoint::CandidateStart => OrganRuntimeError::CandidateStartFailed {
                error: Box::new(OrganRuntimeError::StartFailed {
                    fault: OrganFaultRecordV1 {
                        organ: id("organ"),
                        code: id("start.failed"),
                    },
                    cleanup_faults: vec![fault],
                }),
                rollback_error: Some(rollback),
            },
            FailurePoint::CandidateMigration => OrganRuntimeError::CandidateMigrationFailed {
                error: OrganMigrationError::Callback(id("migration.failed")),
                rollback_error: Some(rollback),
                candidate_cleanup_faults: vec![fault],
            },
            FailurePoint::PredecessorStop => OrganRuntimeError::ReplacementRollbackFailed {
                replacement_error: Box::new(OrganRuntimeError::ReplacementStopFailed {
                    predecessor_faults: vec![fault.clone()],
                    candidate_cleanup_faults: vec![fault],
                }),
                rollback_error: rollback,
            },
        };
        assert_eq!(error, expected);
        assert_eq!(host.generation(), generation(7));
        assert_eq!(
            host.statuses(),
            vec![HostedOrganStatusV1 {
                id: id("organ"),
                state: HostedOrganStateV1::Quarantined,
            }]
        );
        assert_eq!(
            host.dispatch_once(generation(7), &id("organ"), /*output_port*/ 0, b"blocked"),
            Err(OrganRuntimeError::OrganNotReady {
                organ: id("organ"),
                state: HostedOrganStateV1::Quarantined,
            })
        );
        assert!(matches!(
            host.start_all(),
            Err(OrganRuntimeError::InvalidStartState { .. })
        ));
        assert_eq!(
            migration
                .calls
                .iter()
                .filter(|call| **call == "rollback")
                .count(),
            1
        );
        assert_eq!(*new_stops.lock().expect("counter lock"), 1);
        drop(host);
        assert_eq!(*old_stops.lock().expect("counter lock"), 1);
        assert_eq!(*new_stops.lock().expect("counter lock"), 1);
    }
}
