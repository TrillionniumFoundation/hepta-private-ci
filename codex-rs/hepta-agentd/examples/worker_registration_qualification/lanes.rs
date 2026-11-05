//! Actual dedicated Child exercises the three Root lanes without an effect owner.

use codex_hepta_agentd::WorkerRootLaneBootstrapV1;
use codex_hepta_agentd::receive_root_production_handoff;
use codex_hepta_agentd::receive_worker_root_registration;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::HostConsumerFrontierRequestV1;
use std::io::Read;
use std::io::Seek;
use std::io::Write;
use std::os::unix::net::UnixDatagram;
use std::os::unix::net::UnixStream;
use std::time::Duration;

pub(super) fn run(mode: &str, socket: UnixDatagram, agent: &AgentId, generation: u64) -> Result<(), Box<dyn std::error::Error>> {
    let unacknowledged = socket.try_clone()?;
    let registration = receive_worker_root_registration(socket, agent, generation, Duration::from_secs(5))?;
    let message = match mode {
        "lanes-roundtrip" => {
            let executor = tokio::runtime::Builder::new_current_thread().enable_all().build()?;
            let mut lanes = executor.block_on(registration.receive_worker_lanes(Duration::from_secs(5)))?;
            let bootstrap = lanes.bootstrap_observation().clone();
            let observation = lanes.read_observation()?;
            let proof = lanes.read_original_writer_proof()?;
            let initial = lanes.load_frontier()?;
            let mut next = initial;
            // Explicit raw frontier protocol fixture; no claim that this hash
            // represents a FinalUse journal, authorization or physical effect.
            next.state_sha256 = [0x57; 32];
            lanes.compare_and_set_frontier(&initial, &next)?;
            assert_eq!(lanes.load_frontier()?, next);
            assert_eq!(lanes.compare_and_set_frontier(&initial, &next), Err(AuthorityTrustError::Conflict));
            let after_conflict = lanes.load_frontier()?;
            assert_eq!(after_conflict, next);
            assert_eq!(lanes.read_original_writer_proof()?, proof);
            assert!(!bootstrap.effect_authorization_available && !observation.effect_authorization_available);
            drop(lanes);
            executor.shutdown_timeout(Duration::from_secs(1));
            serde_json::json!({"kind":"three_original_lanes", "bootstrap":bootstrap, "observation":observation,
                "original_proof":proof, "initial_frontier":initial, "next_frontier":next,
                "after_exact_conflict":after_conflict, "effect_owner_created":false})
        }
        "lanes-root-head-revoked" => {
            let executor = tokio::runtime::Builder::new_current_thread().enable_all().build()?;
            let mut lanes = executor.block_on(registration.receive_worker_lanes(Duration::from_secs(5)))?;
            let bootstrap = lanes.bootstrap_observation().clone();
            let before = lanes.read_observation()?;
            let original_proof = lanes.read_original_writer_proof()?;
            let initial = lanes.load_frontier()?;
            assert!(!bootstrap.effect_authorization_available && !before.effect_authorization_available);
            let ready = serde_json::json!({"kind":"worker_floor_ready_before_original_revoke",
                "bootstrap":&bootstrap, "observation":&before, "writer_proof":&original_proof,
                "frontier":initial, "effect_authorization_available":false});
            let bytes = serde_json::to_vec(&ready)?;
            assert!(bytes.len() <= 64 * 1024);
            {
                let mut output = std::io::stdout().lock();
                output.write_all(&(bytes.len() as u32).to_be_bytes())?;
                output.write_all(&bytes)?;
                output.flush()?;
            }
            let mut advance = [0];
            std::io::stdin().read_exact(&mut advance)?;
            assert_eq!(advance, [2]);
            // The original Root must still serve its new observation and the
            // exact same live writer proof. No alternative issuer is selected.
            let current = lanes.read_observation()?;
            let current_proof = lanes.read_original_writer_proof()?;
            assert_eq!(current_proof, original_proof);
            assert!(!current.effect_authorization_available);
            let first_load = lanes.load_frontier();
            let retry_load = lanes.load_frontier();
            let later_observation = lanes.read_observation();
            let first_error = first_load.as_ref().err().map(|error| format!("{error:?}"));
            let retry_error = retry_load.as_ref().err().map(|error| format!("{error:?}"));
            let later_error = later_observation.as_ref().err().map(|error| error.to_string());
            // Report the real original behavior, including accepted stale
            // values on the unfixed source. The parent owns the regression
            // assertion; this Child does not synthesize a refused outcome.
            let report = serde_json::json!({"kind":"worker_floor_current_head_result",
                "current_observation":current, "current_writer_proof":current_proof,
                "initial_load_refused":first_load.is_err(), "initial_load_frontier":first_load.ok(),
                "initial_load_error":first_error,
                "retry_load_refused":retry_load.is_err(), "retry_load_frontier":retry_load.ok(),
                "retry_load_error":retry_error,
                "later_observation_refused":later_observation.is_err(),
                "later_observation_error":later_error, "effect_authorization_available":false});
            drop(lanes);
            executor.shutdown_timeout(Duration::from_secs(1));
            report
        }
        "lanes-second-offer-no-ack" => {
            let (mut sealed, _root) = receive_root_production_handoff(unacknowledged, Duration::from_secs(5))?;
            sealed.rewind()?;
            let mut bytes = Vec::new();
            Read::by_ref(&mut sealed).take(64 * 1024 + 1).read_to_end(&mut bytes)?;
            assert!(bytes.len() <= 64 * 1024);
            let offer: WorkerRootLaneBootstrapV1 = serde_json::from_slice(&bytes)?;
            // Even a hostile original Child can reach the kernel backlog.
            // No Root lane may consume its request before the second ACK.
            let mut streams = Vec::new();
            for path in [&offer.sockets.observation, &offer.sockets.issuer, &offer.sockets.consumer_frontier] {
                let stream = UnixStream::connect(path)?;
                stream.set_read_timeout(Some(Duration::from_millis(80)))?;
                streams.push(stream);
            }
            let request = serde_json::to_vec(&HostConsumerFrontierRequestV1::Load { schema_version: 1, request_id: 1 })?;
            let stream = &mut streams[2];
            stream.write_all(&(request.len() as u32).to_be_bytes())?;
            stream.write_all(&request)?;
            let mut response = [0];
            let error = stream.read(&mut response).expect_err("unacknowledged Worker must receive no frontier response");
            assert!(matches!(error.kind(), std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock));
            drop(streams);
            drop(registration);
            serde_json::json!({"kind":"second_offer_without_ack", "raw_offer_bytes":bytes.len(),
                "actual_connections":3, "frontier_response_bytes":0, "effect_owner_created":false})
        }
        _ => return Err("unknown explicit Worker lane qualification mode".into()),
    };
    let bytes = serde_json::to_vec(&message)?;
    assert!(bytes.len() <= 64 * 1024);
    let mut stdout = std::io::stdout().lock();
    stdout.write_all(&(bytes.len() as u32).to_be_bytes())?;
    stdout.write_all(&bytes)?;
    stdout.flush()?;
    // Keep the real Child alive while Root observes closed lane streams, so
    // successful EOF cleanup is not confused with a racing pidfd exit.
    let mut stop = [0];
    std::io::stdin().read_exact(&mut stop)?;
    assert_eq!(stop, [1]);
    Ok(())
}
