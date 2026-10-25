//! Actual source revalidation can block after an earlier valid NDU read.
//! These tests change real NDU state at that barrier; no decoder is executed.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::MemoryCellSourceError;
use codex_hepta_memory::ProductionAuthorityLease;
use codex_hepta_memory::ProductionAuthorityToken;
use codex_hepta_memory::ProductionDurableWriter;
use codex_hepta_neuron::NeuronRuntimeError;
use codex_hepta_neuron::canonical_feature_vector_digest_v1;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use std::assert_eq;

use super::*;
use crate::native_memory_current_test_support;
use crate::native_memory_shadow_namespace::NativeMemoryJournalContext;
use crate::native_memory_shadow_namespace::NativeMemoryShadowStartV1;
use crate::native_memory_shadow_namespace::open_runtime;
use crate::native_memory_shadow_namespace::tests::files;
use crate::native_memory_shadow_namespace::tests::profile;
use crate::native_memory_test_support;
use crate::native_memory_types::query_features;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn ndu_change_during_source_revalidation_stops_decoder_and_successful_tick() {
    enum Change {
        Selection,
        ReadGrantRevoked,
        GrantExpired,
    }
    for change in [
        Change::Selection,
        Change::ReadGrantRevoked,
        Change::GrantExpired,
    ] {
        let current = native_memory_current_test_support::fixture().await;
        let temp = tempfile::tempdir().unwrap();
        let owner = current.objective.state.identity().agent_id.clone();
        let fleet = HeptaFleetRoot::parse(temp.path().join("fleet")).unwrap();
        let store = CognitiveStore::open(&fleet.layout().agent(&owner))
            .await
            .unwrap();
        let now = crate::authbus_ingress::now_ms().unwrap();
        let lease = ProductionAuthorityLease::from_verified_parts(
            owner,
            Sha256Digest::for_bytes(b"current-guard-source"),
            /*authority_epoch*/ 1,
            /*owner_epoch*/ 1,
            now / 1000 + 3600,
            ProductionAuthorityToken::from_verified_bytes(b"current-guard-token".to_vec()).unwrap(),
        )
        .unwrap();
        let armed = Arc::new(AtomicBool::new(false));
        let arm = Arc::clone(&armed);
        let barrier_released = Arc::new(AtomicBool::new(false));
        let release_observed = Arc::clone(&barrier_released);
        let (entered_tx, entered_rx) = mpsc::sync_channel(1);
        let (release_tx, release_rx) = mpsc::sync_channel(1);
        let release_rx = Mutex::new(release_rx);
        let verifier = Arc::new(
            move |authority: &ProductionAuthorityLease, expected: &AgentId| {
                if &authority.agent_id != expected {
                    return Err("source owner mismatch".to_string());
                }
                if arm.swap(false, Ordering::SeqCst) {
                    entered_tx.send(()).map_err(|error| error.to_string())?;
                    release_rx
                        .lock()
                        .map_err(|error| error.to_string())?
                        .recv_timeout(Duration::from_secs(10))
                        .map_err(|error| error.to_string())?;
                    release_observed.store(true, Ordering::SeqCst);
                }
                Ok(())
            },
        );
        let writer = Arc::new(
            ProductionDurableWriter::open_with_live_verifier(
                store,
                lease,
                verifier,
                "current-guard-source",
                /*generation*/ 1,
            )
            .await
            .unwrap(),
        );
        // The helper's separate verifier handle is unused; the actual writer
        // retains the blocking verifier above throughout this test.
        let mut source = native_memory_test_support::fixture_with_writer(
            temp,
            writer,
            Arc::new(native_memory_test_support::Verifier(AtomicBool::new(false))),
        )
        .await;
        source.config.output_width = 5;
        let mut query = current.query("guarded-current-read");
        query.key = source.admission.query().key.clone();
        let admission = Arc::new(
            source
                .writer
                .admit_memory_cell(&source.access, &query, &source.claim)
                .await
                .unwrap(),
        );
        let prepared = current
            .host
            .prepare_read("run.current", query.clone())
            .unwrap();
        let signed = current.sign(prepared.binding().clone(), "guarded-current-read");
        let mut context = prepared.authorize(&signed).unwrap();
        let observed = context.current().unwrap();
        let binding = context.binding().cloned();
        let (mut runtime, _) = open_runtime(
            files(source.temp.path(), NativeMemoryShadowStartV1::Bootstrap),
            profile(&source.config),
            &source.config,
            admission.binding(),
            source.writer.owner_agent_id().as_str(),
            NativeMemoryJournalContext {
                subject: &observed.subject_id,
                objective: observed.objective_digest,
                binding: binding.as_ref(),
            },
        )
        .unwrap();
        let features = query_features(&query.key.question().unwrap()).unwrap();
        let input = NeuronTickInputV1 {
            tick_id: query.request_id.clone(),
            subject_id: observed.subject_id,
            logical_sequence: 1,
            monotonic_time_micros: observed.monotonic_time_micros,
            checkpoint_digest: Digest32::ZERO,
            input_feature_digest: canonical_feature_vector_digest_v1(&features),
            feature_vector_q24: features,
            objective_digest: observed.objective_digest,
            ndu_snapshot_digest: observed.ndu_snapshot_digest,
            body_generation: observed.body_generation,
            modulator_digest: observed.modulator_digest,
        };
        let dispatches = Arc::new(AtomicU64::new(0));
        let mut inner = NativeMemoryModelPort::new(
            Arc::clone(&source.writer),
            admission,
            source.config.clone(),
            tokio::runtime::Handle::current(),
            Arc::clone(&dispatches),
            tokio_util::sync::CancellationToken::new(),
        )
        .unwrap();
        inner
            .bind_tick(&input, &runtime.model_request(&input).unwrap())
            .unwrap();
        let request = inner.request();
        assert_eq!(inner.execute(&request), Err(NeuronModelError::Rejected));
        assert_eq!(dispatches.load(Ordering::SeqCst), 0);
        let anchor = runtime.current_anchor().unwrap();
        let journal = std::fs::read(source.temp.path().join("shadow-journal")).unwrap();
        let witness = std::fs::read(source.temp.path().join("shadow-witness")).unwrap();
        armed.store(true, Ordering::SeqCst);
        let work = tokio::task::spawn_blocking(move || {
            let mut guarded = NativeCurrentModel {
                inner: &mut inner,
                context: &mut context,
                input: &input,
                binding: binding.as_ref(),
            };
            let result = runtime.tick_shadow(&mut guarded, input.clone());
            (
                result,
                runtime.current_anchor().unwrap(),
                inner.failure().map(str::to_owned),
            )
        });
        tokio::task::spawn_blocking(move || entered_rx.recv_timeout(Duration::from_secs(10)))
            .await
            .unwrap()
            .expect("real source verifier must reach the barrier");
        match change {
            Change::Selection => current.select("second", "switch-during-source-validation"),
            Change::ReadGrantRevoked => {
                current.feed(/*revision*/ 3, &["guarded-current-read"])
            }
            Change::GrantExpired => {
                current.wall.0.fetch_add(61_000, Ordering::SeqCst);
            }
        }
        let authority_after_change = current.authority.frontier().unwrap();
        release_tx.send(()).unwrap();
        let (result, after, failure) = work.await.unwrap();
        assert!(matches!(
            result,
            Err(NeuronRuntimeError::Model(NeuronModelError::Rejected))
        ));
        assert!(
            barrier_released.load(Ordering::SeqCst),
            "source verifier must receive the release"
        );
        let expected_failure = match change {
            Change::Selection => {
                r#"native memory rejected: InvalidContext("current projection version")"#
            }
            Change::ReadGrantRevoked => "native memory rejected: Authority(Revoked)",
            Change::GrantExpired => "native memory rejected: Authority(Expired)",
        };
        assert_eq!(failure.as_deref(), Some(expected_failure));
        assert_eq!(dispatches.load(Ordering::SeqCst), 0);
        assert_eq!(after, anchor);
        assert_eq!(
            std::fs::read(source.temp.path().join("shadow-journal")).unwrap(),
            journal
        );
        assert_eq!(
            std::fs::read(source.temp.path().join("shadow-witness")).unwrap(),
            witness
        );
        assert_eq!(
            current.authority.frontier().unwrap(),
            authority_after_change
        );
        assert!(matches!(
            source
                .writer
                .admit_memory_cell(&source.access, &query, &source.claim)
                .await,
            Err(MemoryCellSourceError::Replay)
        ));
    }
}
