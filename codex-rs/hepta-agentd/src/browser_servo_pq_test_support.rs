//! Real ML-DSA issuers and independent local Unix trust-service fixtures.
//! The scripted private Browser channel qualifies Agentd's authorization
//! boundary; it is not a Servo browser or production key-custody qualification.

use super::*;
use std::collections::BTreeSet;
use std::collections::VecDeque;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::FinalUseAuthenticationProfile;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocationUpdate;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::PqAuthorityTrustKey;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use codex_hepta_contracts::authority_trust_unix::PqTrustOperationV2;
use codex_hepta_contracts::authority_trust_unix::PqTrustOutcomeV2;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;

#[path = "automation_effect_host_pq_test_support.rs"]
mod trust;
use trust::write_private;

pub(super) const NOW: u64 = 1_000_000;

pub(super) struct Fixture {
    clock: trust::Service,
    frontier: trust::Service,
    issuer: PqNativeSigningKey,
    feed_signer: PqNativeSigningKey,
    pub(super) now: Arc<AtomicU64>,
    pub(super) advance_after_clock: Arc<Mutex<Option<u64>>>,
    pub(super) head: FinalUseRevocations,
    pub(super) config: Value,
    pub(super) config_path: PathBuf,
    pub(super) feed_path: PathBuf,
    pub(super) local: PathBuf,
    pub(super) trust_root: PathBuf,
    pub(super) root: tempfile::TempDir,
}

impl Fixture {
    pub(super) fn new() -> anyhow::Result<Self> {
        let root = tempfile::tempdir()?;
        let canonical = root.path().canonicalize()?;
        let local = canonical.join("local");
        let trust_root = canonical.join("external-trust");
        for path in [&local, &trust_root] {
            fs::create_dir(path)?;
            fs::set_permissions(path, fs::Permissions::from_mode(0o700))?;
        }
        let now = Arc::new(AtomicU64::new(NOW));
        let time = Arc::clone(&now);
        let advance_after_clock = Arc::new(Mutex::new(None));
        let advance = Arc::clone(&advance_after_clock);
        let clock = trust::Service::start(
            &trust_root,
            "clock.sock",
            /*seed*/ 74,
            move |operation| {
                Ok(match operation {
                    PqTrustOperationV2::ClockNow => {
                        let unix_ms = time.load(Ordering::SeqCst);
                        if let Some(next) = advance.lock().expect("clock script").take() {
                            time.store(next, Ordering::SeqCst);
                        }
                        PqTrustOutcomeV2::Clock { unix_ms }
                    }
                    PqTrustOperationV2::FrontierLoad { .. }
                    | PqTrustOperationV2::FrontierCompareAndSet { .. }
                    | PqTrustOperationV2::LearningFrontierLoad { .. }
                    | PqTrustOperationV2::LearningFrontierCompareAndSet { .. }
                    | PqTrustOperationV2::ReleaseFrontierLoad { .. }
                    | PqTrustOperationV2::ReleaseFrontierCompareAndSet { .. } => {
                        PqTrustOutcomeV2::Unavailable
                    }
                })
            },
        )?;
        let head = FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        };
        let frontier = trust::frontier_service(
            &trust_root,
            FinalUseFrontier::for_initial_head_with_profile(
                &head,
                FinalUseAuthenticationProfile::MlDsa65V2,
            )?,
        )?;
        let (issuer, issuer_key) = trust::key(/*seed*/ 71)?;
        let (feed_signer, feed_key) = trust::key(/*seed*/ 72)?;
        let artifact = local.join("private-channel-fixture");
        let artifact_bytes = b"scripted transport qualification, not a Servo worker";
        write_private(&artifact, artifact_bytes)?;
        let config_path = local.join("browser.json");
        let feed_path = local.join("feed.json");
        let config = json!({
            "schema_version": 2, "authentication_profile": "ml_dsa65_v2",
            "authority_state_dir": local.join("authority"),
            "final_use": {"signer_id": "pq-issuer", "issuer_keys": [pin(&issuer_key)], "head": head,
                "revocation_distributor_id": "pq-feed", "revocation_keys": [pin(&feed_key)],
                "signed_revocations_file": feed_path, "external_clock": clock.config_json(),
                "external_frontier": frontier.config_json()},
            "node_path": local.join("node-never-spawned"), "service_path": artifact,
            "service_sha256": hex_lower(&sha256_bytes(artifact_bytes)), "worker_path": artifact,
            "worker_sha256": hex_lower(&sha256_bytes(artifact_bytes)),
            "profile_root": local.join("profile"), "journal_path": local.join("journal"),
            "bwrap_path": local.join("bwrap-never-spawned"), "driver_timeout_ms": 2000,
        });
        let fixture = Self {
            clock,
            frontier,
            issuer,
            feed_signer,
            now,
            advance_after_clock,
            head,
            config,
            config_path,
            feed_path,
            local,
            trust_root,
            root,
        };
        fixture.write_config()?;
        fixture.publish(fixture.head.clone(), NOW + 60_000)?;
        Ok(fixture)
    }

    pub(super) fn write_config(&self) -> anyhow::Result<()> {
        write_private(&self.config_path, &serde_json::to_vec(&self.config)?)
    }

    pub(super) fn publish(&self, head: FinalUseRevocations, expires: u64) -> anyhow::Result<()> {
        let update = FinalUseRevocationUpdate::new_pq("pq-feed".into(), head, NOW - 1000, expires);
        let signature = self
            .feed_signer
            .sign_exact_message(&update.signing_bytes()?)?
            .to_vec();
        write_private(
            &self.feed_path,
            &serde_json::to_vec(&SignedFinalUseRevocationUpdate { update, signature })?,
        )
    }

    pub(super) fn invocation(
        &self,
        nonce: u8,
        expires: u64,
    ) -> anyhow::Result<BrowserFinalUseInvocation> {
        let binding = FinalUseBinding {
            subject_id: "principal.1".into(),
            destination_id: "browser.profile.1".into(),
            request_sha256: [0x11; 32],
            scope_sha256: [0x22; 32],
            payload_sha256: [0x33; 32],
        };
        let grant = FinalUseGrant {
            schema_version: 2,
            signer_id: "pq-issuer".into(),
            authority_epoch: 9,
            grant_id: format!("browser-grant.{nonce}"),
            nonce: [nonce; 32],
            binding: binding.clone(),
            not_before_unix_ms: NOW - 1000,
            expires_at_unix_ms: expires,
        };
        let signature = self
            .issuer
            .sign_exact_message(&grant.signing_bytes()?)?
            .to_vec();
        Ok(BrowserFinalUseInvocation {
            signed_grant: SignedFinalUseGrant { grant, signature },
            binding,
        })
    }

    pub(super) fn trust_requests(&self) -> usize {
        self.clock.requests.load(Ordering::SeqCst) + self.frontier.requests.load(Ordering::SeqCst)
    }
}

fn pin(key: &PqAuthorityTrustKey) -> Value {
    json!({"key_id": key.key_id, "public_key_id": key.public_key_id, "public_key_spki": key.public_key_spki,
        "not_before_authority_epoch": key.not_before_authority_epoch, "not_after_authority_epoch": key.not_after_authority_epoch})
}

pub(super) struct ScriptedBrowser {
    output: Arc<Mutex<Vec<Value>>>,
    incoming: VecDeque<Vec<u8>>,
    next_sequence: u64,
    request_digest: [u8; 32],
}

impl ScriptedBrowser {
    pub(super) fn new(output: Arc<Mutex<Vec<Value>>>, request_digest: [u8; 32]) -> Self {
        Self {
            output,
            incoming: VecDeque::new(),
            next_sequence: 1,
            request_digest,
        }
    }

    fn queue(&mut self, kind: &str, id: &str, payload: Value) -> Result<(), BrowserServoError> {
        let digest = sha256_bytes(canonical_json(&payload)?.as_bytes());
        let frame = json!({"schema": PROTOCOL_SCHEMA, "protocolVersion": PROTOCOL_VERSION,
            "sequence": self.next_sequence, "kind": kind, "requestId": id,
            "payloadDigest": hex_lower(&digest), "payload": payload});
        self.next_sequence += 1;
        let body = canonical_json(&frame)?.into_bytes();
        let mut bytes = (body.len() as u32).to_be_bytes().to_vec();
        bytes.extend(body);
        self.incoming.push_back(bytes);
        Ok(())
    }
}

impl BrowserServoTransport for ScriptedBrowser {
    fn write_frame(&mut self, bytes: &[u8]) -> Result<(), BrowserServoError> {
        let value: Value =
            serde_json::from_slice(&bytes[4..]).map_err(crate::browser_servo_pq::invalid)?;
        let id = value["requestId"].as_str().expect("request id");
        self.output
            .lock()
            .expect("outbound frames")
            .push(value.clone());
        if value["kind"] == "authority_enter" {
            let payload = &value["payload"];
            self.queue(
                "dispatch_boundary",
                id,
                json!({"requestDigest": payload["requestDigest"],
                "witnessDigest": payload["witnessDigest"], "localDispatchCrossed": true}),
            )?;
            self.queue(
                "response",
                id,
                json!({"ok":true,"result":{"status":"indeterminate","terminalObserved":false}}),
            )?;
        } else if value["payload"]["method"] == "navigate_or_act" {
            self.queue(
                "authority_challenge",
                id,
                json!({"requestDigest":hex_lower(&self.request_digest),"authorityEpoch":9}),
            )?;
        } else {
            self.queue(
                "response",
                id,
                json!({"ok":true,"result":{"status":"indeterminate","terminalObserved":false}}),
            )?;
        }
        Ok(())
    }

    fn read_frame(&mut self) -> Result<Vec<u8>, BrowserServoError> {
        self.incoming.pop_front().ok_or_else(|| {
            BrowserServoError::Unavailable("scripted private channel exhausted".into())
        })
    }
}
