use codex_hepta_memory_federation_wire::FederationReplayKeyV1;
use std::error::Error;
use std::fs;
use std::path::PathBuf;
use std::time::{Duration, Instant};

use codex_hepta_memory_federation_wire::{
    DurableFederationStateV1, FEDERATION_NONCE_BYTES, FEDERATION_RECOVERY_CLEANUP_BATCH,
    FEDERATION_REPLAY_CLEANUP_BATCH, FederationCancelMessageV1,
    FederationCancellationReasonV1, FederationRecoveryError, FederationRecoveryLimitsV1,
    ReplayCacheV1, ReplayError,
};
use codex_hepta_types::{Digest32, StableId};
use serde::Serialize;

const NOW: u64 = 4_000_000;
const EXPIRES: u64 = NOW + 10_000;
const PEERS: usize = 16;
const REPLAY_PER_PEER: usize = 1_024;
const ATTEMPTS_PER_PEER: usize = 1_024;

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Metrics {
    schema: &'static str,
    profile: &'static str,
    peer_count: usize,
    live_replay_entries: usize,
    live_fill_nanos: u64,
    live_partition_rejections: usize,
    live_cleanup_removed: usize,
    live_cleanup_batches: usize,
    live_cleanup_maximum_batch: usize,
    live_cleanup_nanos: u64,
    durable_replay_entries: usize,
    durable_replay_partition_rejections: usize,
    durable_attempt_entries: usize,
    durable_attempt_partition_rejections: usize,
    durable_cleanup_removed: usize,
    durable_cleanup_batches: usize,
    durable_cleanup_maximum_batch: usize,
    durable_cleanup_nanos: u64,
    cancellation_count: usize,
    cancellation_total_nanos: u64,
    cancellation_average_nanos: u64,
    snapshot_bytes: usize,
    snapshot_encode_nanos: u64,
    restore_nanos: u64,
    notes: [&'static str; 3],
}

fn main() -> Result<(), Box<dyn Error>> {
    let output = std::env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .ok_or("usage: memory_federation_capacity_probe <output.json>")?;
    let local = sid("probe-local")?;

    let mut live = ReplayCacheV1::with_limits(PEERS * REPLAY_PER_PEER, REPLAY_PER_PEER)?;
    let started = Instant::now();
    for peer in 0..PEERS {
        let peer_id = sid(&format!("live-peer-{peer}"))?;
        let key_id = sid(&format!("live-key-{peer}"))?;
        for slot in 0..REPLAY_PER_PEER {
            live.admit(
                FederationReplayKeyV1 {
                    sender_peer_id: &peer_id,
                    receiver_peer_id: &local,
                    key_id: &key_id,
                    generation: 1,
                    nonce: &nonce(peer, slot),
                },
                EXPIRES,
                NOW,
            )?;
        }
    }
    let live_fill_nanos = nanos(started.elapsed());
    let live_replay_entries = live.len();
    let mut live_partition_rejections = 0;
    for peer in 0..PEERS {
        match live.admit(
            FederationReplayKeyV1 {
                sender_peer_id: &sid(&format!("live-peer-{peer}"))?,
                receiver_peer_id: &local,
                key_id: &sid(&format!("live-key-{peer}"))?,
                generation: 1,
                nonce: &nonce(peer, REPLAY_PER_PEER),
            },
            EXPIRES,
            NOW,
        ) {
            Err(ReplayError::CapacityExhausted | ReplayError::CredentialCapacityExhausted) => {
                live_partition_rejections += 1;
            }
            Err(error) => return Err(error.into()),
            Ok(()) => return Err("live replay admitted beyond capacity".into()),
        }
    }
    let cleanup_started = Instant::now();
    let mut live_cleanup_removed = 0;
    let mut live_cleanup_batches = 0;
    let mut live_cleanup_maximum_batch = 0;
    loop {
        let removed =
            live.purge_expired_bounded(EXPIRES, FEDERATION_REPLAY_CLEANUP_BATCH)?;
        if removed == 0 {
            break;
        }
        live_cleanup_removed += removed;
        live_cleanup_batches += 1;
        live_cleanup_maximum_batch = live_cleanup_maximum_batch.max(removed);
    }
    let live_cleanup_nanos = nanos(cleanup_started.elapsed());
    if live_cleanup_removed != live_replay_entries
        || !live.is_empty()
        || live_cleanup_maximum_batch > FEDERATION_REPLAY_CLEANUP_BATCH
    {
        return Err("live replay bounded cleanup mismatch".into());
    }

    let limits = FederationRecoveryLimitsV1 {
        replay_capacity: PEERS * REPLAY_PER_PEER,
        replay_per_peer_capacity: REPLAY_PER_PEER,
        attempt_capacity: PEERS * ATTEMPTS_PER_PEER,
        attempt_per_peer_capacity: ATTEMPTS_PER_PEER,
    };
    let mut durable = DurableFederationStateV1::empty(local.clone(), limits, NOW)?;
    for peer in 0..PEERS {
        let peer_id = sid(&format!("durable-peer-{peer}"))?;
        let key_id = sid(&format!("durable-key-{peer}"))?;
        for slot in 0..REPLAY_PER_PEER {
            let key = durable.preflight_frame(
                FederationReplayKeyV1 {
                    sender_peer_id: &peer_id,
                    receiver_peer_id: &local,
                    key_id: &key_id,
                    generation: 1,
                    nonce: &nonce(peer, slot),
                },
                EXPIRES,
                NOW,
            )?;
            durable.record_verified_frame(key, &peer_id, EXPIRES)?;
        }
    }
    let durable_replay_entries = durable.replay_len();
    let mut durable_replay_partition_rejections = 0;
    for peer in 0..PEERS {
        match durable.preflight_frame(
            FederationReplayKeyV1 {
                sender_peer_id: &sid(&format!("durable-peer-{peer}"))?,
                receiver_peer_id: &local,
                key_id: &sid(&format!("durable-key-{peer}"))?,
                generation: 1,
                nonce: &nonce(peer, REPLAY_PER_PEER),
            },
            EXPIRES,
            NOW,
        ) {
            Err(
                FederationRecoveryError::ReplayCapacityExhausted
                | FederationRecoveryError::ReplayPeerCapacityExhausted,
            ) => durable_replay_partition_rejections += 1,
            Err(error) => return Err(error.into()),
            Ok(_) => return Err("durable replay admitted beyond capacity".into()),
        }
    }

    let mut attempts = Vec::with_capacity(limits.attempt_capacity);
    for peer in 0..PEERS {
        let peer_id = sid(&format!("durable-peer-{peer}"))?;
        for slot in 0..ATTEMPTS_PER_PEER {
            let query_id = sid(&format!("query-{peer}-{slot}"))?;
            let binding = digest(&format!("binding-{peer}-{slot}"));
            durable.begin_attempt(&peer_id, &query_id, binding, EXPIRES, NOW)?;
            attempts.push((peer_id.clone(), query_id, binding, peer, slot));
        }
    }
    let durable_attempt_entries = durable.attempt_len();
    let mut durable_attempt_partition_rejections = 0;
    for peer in 0..PEERS {
        match durable.begin_attempt(
            &sid(&format!("durable-peer-{peer}"))?,
            &sid(&format!("query-overflow-{peer}"))?,
            digest(&format!("binding-overflow-{peer}")),
            EXPIRES,
            NOW,
        ) {
            Err(
                FederationRecoveryError::AttemptCapacityExhausted
                | FederationRecoveryError::AttemptPeerCapacityExhausted,
            ) => durable_attempt_partition_rejections += 1,
            Err(error) => return Err(error.into()),
            Ok(()) => return Err("durable attempt admitted beyond capacity".into()),
        }
    }

    let durable_cleanup_started = Instant::now();
    let mut durable_cleanup = durable.clone();
    let mut durable_cleanup_removed = 0;
    let mut durable_cleanup_batches = 0;
    let mut durable_cleanup_maximum_batch = 0;
    loop {
        let removed = durable_cleanup
            .purge_expired_bounded(EXPIRES, FEDERATION_RECOVERY_CLEANUP_BATCH)?;
        if removed == 0 {
            break;
        }
        durable_cleanup_removed += removed;
        durable_cleanup_batches += 1;
        durable_cleanup_maximum_batch = durable_cleanup_maximum_batch.max(removed);
    }
    let durable_cleanup_nanos = nanos(durable_cleanup_started.elapsed());
    if durable_cleanup_removed != durable_replay_entries + durable_attempt_entries
        || durable_cleanup.replay_len() != 0
        || durable_cleanup.attempt_len() != 0
        || durable_cleanup_maximum_batch > FEDERATION_RECOVERY_CLEANUP_BATCH
    {
        return Err("durable bounded cleanup mismatch".into());
    }

    let cancellation_started = Instant::now();
    for (peer_id, query_id, binding, peer, slot) in &attempts {
        durable.observe_cancel(
            peer_id,
            &FederationCancelMessageV1 {
                query_id: query_id.clone(),
                query_binding_digest: *binding,
                cancellation_id: sid(&format!("cancel-{peer}-{slot}"))?,
                reason: FederationCancellationReasonV1::CallerCancelled,
            },
            NOW + 1,
        )?;
    }
    let cancellation_total_nanos = nanos(cancellation_started.elapsed());
    let cancellation_count = attempts.len();
    let cancellation_average_nanos =
        cancellation_total_nanos / u64::try_from(cancellation_count).unwrap_or(u64::MAX).max(1);

    let encode_started = Instant::now();
    let snapshot = durable.snapshot_bytes()?;
    let snapshot_encode_nanos = nanos(encode_started.elapsed());
    let restore_started = Instant::now();
    let restored = DurableFederationStateV1::restore(local, limits, NOW + 2, &snapshot)?;
    let restore_nanos = nanos(restore_started.elapsed());
    if restored.replay_len() != durable_replay_entries
        || restored.attempt_len() != durable_attempt_entries
    {
        return Err("durable recovery entry-count mismatch".into());
    }

    let metrics = Metrics {
        schema: "hepta.memory-federation.capacity-probe.v1",
        profile: "logical-host-candidate-not-production-slo",
        peer_count: PEERS,
        live_replay_entries,
        live_fill_nanos,
        live_partition_rejections,
        live_cleanup_removed,
        live_cleanup_batches,
        live_cleanup_maximum_batch,
        live_cleanup_nanos,
        durable_replay_entries,
        durable_replay_partition_rejections,
        durable_attempt_entries,
        durable_attempt_partition_rejections,
        durable_cleanup_removed,
        durable_cleanup_batches,
        durable_cleanup_maximum_batch,
        durable_cleanup_nanos,
        cancellation_count,
        cancellation_total_nanos,
        cancellation_average_nanos,
        snapshot_bytes: snapshot.len(),
        snapshot_encode_nanos,
        restore_nanos,
        notes: [
            "single-process logical-host measurement",
            "durations are diagnostics, not release thresholds",
            "real transport and two-host qualification remain external gates",
        ],
    };
    let mut bytes = serde_json::to_vec_pretty(&metrics)?;
    bytes.push(b'\n');
    if let Some(parent) = output.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(&output, &bytes)?;
    print!("{}", String::from_utf8(bytes)?);
    Ok(())
}

fn sid(value: &str) -> Result<StableId, Box<dyn Error>> {
    StableId::new(value.to_string()).map_err(|error| error.into())
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn nonce(peer: usize, slot: usize) -> [u8; FEDERATION_NONCE_BYTES] {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.memory-federation.capacity-probe-nonce.v1");
    bytes.extend_from_slice(&u64::try_from(peer).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(&u64::try_from(slot).unwrap_or(u64::MAX).to_be_bytes());
    *Digest32::of_bytes(&bytes).as_array()
}

fn nanos(duration: Duration) -> u64 {
    u64::try_from(duration.as_nanos()).unwrap_or(u64::MAX)
}
