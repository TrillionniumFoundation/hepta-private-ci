//! Repository measurement of the real recovery path, not host acceptance.
//!
//! Seeds only a temporary owner. No live store, signing key or deployment is
//! accepted as input. Filesystem/RSS peaks are sampled lower bounds; verifier
//! timing is explicitly a fixture measurement, not production signing cost.

use std::error::Error;
use std::io;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::thread;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveRecoveryRequirement;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::KgFactSetDraft;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::ProductionAuthorityLease;
use codex_hepta_memory::ProductionAuthorityToken;
use codex_hepta_memory::ProductionAuthorityVerifier;
use codex_hepta_memory::SourceDraft;
use codex_hepta_paths::HeptaFleetRoot;
use serde_json::json;
use tempfile::TempDir;

struct FixtureVerifier {
    calls_us: Mutex<Vec<u64>>,
}

impl ProductionAuthorityVerifier for FixtureVerifier {
    fn verify(&self, authority: &ProductionAuthorityLease, agent: &AgentId) -> Result<(), String> {
        let start = Instant::now();
        let result = if &authority.agent_id != agent
            || authority.authority_epoch == 0
            || authority.owner_epoch == 0
        {
            Err("fixture authority owner or epoch mismatch".to_string())
        } else {
            authority
                .fencing_token_digest()
                .map(|_| ())
                .map_err(|error| error.to_string())
        };
        self.calls_us
            .lock()
            .map_err(|_| "fixture verifier measurement lock poisoned".to_string())?
            .push(micros(start.elapsed()));
        result
    }
}

#[derive(Default)]
struct SampledResources {
    samples: u64,
    rss_peak_bytes: Option<u64>,
    root_peak_bytes: u64,
}

struct Sampler {
    stop: Arc<AtomicBool>,
    handle: Option<thread::JoinHandle<io::Result<SampledResources>>>,
}

impl Sampler {
    fn start(root: PathBuf) -> Self {
        let stop = Arc::new(AtomicBool::new(false));
        let stopped = Arc::clone(&stop);
        let handle = thread::spawn(move || {
            let mut samples = SampledResources::default();
            loop {
                samples.samples += 1;
                samples.root_peak_bytes = samples.root_peak_bytes.max(directory_bytes(&root)?);
                if let Some(rss) = rss_bytes()? {
                    samples.rss_peak_bytes = Some(rss.max(samples.rss_peak_bytes.unwrap_or(0)));
                }
                if stopped.load(Ordering::Acquire) {
                    return Ok(samples);
                }
                thread::sleep(Duration::from_millis(/*millis*/ 5));
            }
        });
        Self {
            stop,
            handle: Some(handle),
        }
    }

    fn finish(mut self) -> io::Result<SampledResources> {
        self.stop.store(true, Ordering::Release);
        self.handle
            .take()
            .ok_or_else(|| io::Error::other("resource sampler already joined"))?
            .join()
            .map_err(|_| io::Error::other("resource sampler panicked"))?
    }
}

impl Drop for Sampler {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Release);
        if let Some(handle) = self.handle.take() {
            let _ = handle.join();
        }
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    let count = setting(
        "HEPTA_COGNITIVE_RECOVERY_RECORDS",
        /*default*/ 256,
        /*maximum*/ 16_384,
    )?;
    let repetitions = setting(
        "HEPTA_COGNITIVE_RECOVERY_REPETITIONS",
        /*default*/ 3,
        /*maximum*/ 32,
    )?;
    let temp = TempDir::new()?;
    let fleet = temp.path().join("fleet");
    std::fs::create_dir(&fleet)?;
    let owner = AgentId::parse("00000000-0000-4000-8000-00000000c059")?;
    let layout = HeptaFleetRoot::parse(fleet)?.layout().agent(&owner);
    let scopes = (0..count.div_ceil(8192))
        .map(|index| {
            let workspace_sha256 =
                Sha256Digest::for_bytes(format!("recovery-perf-{index}").as_bytes());
            (
                CognitiveAccess::workspace_private(owner.clone(), workspace_sha256.clone()),
                CognitiveScope::WorkspacePrivate { workspace_sha256 },
            )
        })
        .collect::<Vec<_>>();
    let store = CognitiveStore::open(&layout).await?;
    for index in 0..count {
        let (access, scope) = &scopes[index / 8192];
        let content = format!("recovery-profile-{index}:{}", "x".repeat(256));
        store
            .remember_with_kg(
                access,
                &SourceDraft {
                    scope: scope.clone(),
                    kind: LedgerSourceKind::ExplicitMemoryDirective,
                    event_key: format!("recovery-profile-source-{index}"),
                    content: content.as_bytes().to_vec(),
                    observed_at_unix_seconds: 1,
                },
                &MemoryDraft {
                    stable_key: format!("recovery-profile-memory-{index}"),
                    revision: MemoryRevisionDraft {
                        scope: scope.clone(),
                        content,
                        verification: MemoryVerification::Verified,
                        lifecycle: MemoryLifecycleState::Active,
                        valid_from_unix_seconds: 1,
                        valid_to_unix_seconds: None,
                        citations: Vec::new(),
                    },
                },
                &KgFactSetDraft::default(),
            )
            .await?;
    }
    let (anchor, initial_acquire, initial_held) = store.recovery_anchor_measured().await?;
    store.close_for_recovery_handoff().await?;
    let root = layout.cognitive_root();
    let baseline_bytes = directory_bytes(root)?;
    let sampler = Sampler::start(root.to_path_buf());
    let verifier = FixtureVerifier {
        calls_us: Mutex::new(Vec::new()),
    };
    let mut runs = Vec::with_capacity(repetitions);
    for iteration in 0..repetitions {
        let authority = ProductionAuthorityLease::from_verified_parts(
            owner.clone(),
            Sha256Digest::for_bytes(format!("fixture-recovery-grant-{iteration}").as_bytes()),
            /*authority_epoch*/ 1,
            /*owner_epoch*/ 1,
            /*lease_expires_at_unix_seconds*/ u64::MAX,
            ProductionAuthorityToken::from_verified_bytes(
                format!("fixture-recovery-token-{iteration}").into_bytes(),
            )?,
        )?;
        let started = Instant::now();
        let recovered = CognitiveStore::open_with_recovery(
            &layout,
            CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
            &authority,
            &verifier,
        )
        .await?;
        let recovery_us = micros(started.elapsed());
        let (observed, acquire, held) = recovered.recovery_anchor_measured().await?;
        if observed != anchor {
            return Err("recovery changed the exact owner cut".into());
        }
        let mut page_us = Vec::new();
        let mut records = 0;
        for (access, scope) in &scopes {
            let mut after = None;
            loop {
                let started = Instant::now();
                let page = recovered
                    .lane_c_snapshot_page(
                        access, scope, /*now_unix_seconds*/ 10, /*maximum_heads*/ 512,
                        after,
                    )
                    .await?;
                page_us.push(micros(started.elapsed()));
                records += page.records().len();
                if page.is_complete() {
                    break;
                }
                after = Some(page.next().ok_or("incomplete page has no cursor")?.clone());
            }
        }
        if records != count {
            return Err("recovered pages lost or duplicated retained records".into());
        }
        runs.push(json!({
            "iteration": iteration,
            "descriptorRecoveryUs": recovery_us,
            "anchorAcquisitionUs": micros(acquire),
            "anchorHeldTransactionUs": micros(held),
            "pageUs": page_us,
            "retainedRecords": records,
            "rootBytesIncludingRetainedGenerations": directory_bytes(root)?,
            "activeDatabaseBytes": std::fs::metadata(recovered.path())?.len(),
            "exactCutPreserved": true,
        }));
        recovered.close_for_recovery_handoff().await?;
    }
    let samples = sampler.finish()?;
    let report = json!({
        "schema": "hepta.cognitive-store-recovery-perf.v1",
        "sourceCommit": std::env::var("SOURCE_SHA").ok(),
        "testedCommit": std::env::var("TESTED_SHA").ok(),
        "testedTree": std::env::var("TESTED_TREE").ok(),
        "debugAssertions": cfg!(debug_assertions),
        "records": count,
        "repetitions": repetitions,
        "initialAnchorAcquisitionUs": micros(initial_acquire),
        "initialAnchorHeldTransactionUs": micros(initial_held),
        "runs": runs,
        "samplingIntervalMs": 5,
        "sampleCount": samples.samples,
        "rssPeakSampledBytes": samples.rss_peak_bytes,
        "rootBaselineBytes": baseline_bytes,
        "rootPeakSampledBytes": samples.root_peak_bytes,
        "additionalDiskPeakSampledBytes": samples.root_peak_bytes.saturating_sub(baseline_bytes),
        "fixtureAuthorityVerificationUs": verifier.calls_us.lock().map_err(|_| "poisoned verifier")?.clone(),
        "claimBoundary": {
            "sampledPeaksAreLowerBounds": true,
            "authorityIsFixture": true,
            "targetHostQualified": false,
            "destructivePruningPerformed": false,
            "physicalErasureProved": false,
        },
    });
    let rendered = serde_json::to_string_pretty(&report)?;
    println!("{rendered}");
    if let Some(output) = std::env::var_os("HEPTA_COGNITIVE_RECOVERY_OUTPUT") {
        let output = PathBuf::from(output);
        if let Some(parent) = output.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(output, format!("{rendered}\n"))?;
    }
    Ok(())
}

fn setting(name: &str, default: usize, maximum: usize) -> Result<usize, Box<dyn Error>> {
    let value = std::env::var(name)
        .ok()
        .map(|text| text.parse::<usize>())
        .transpose()?
        .unwrap_or(default);
    if !(1..=maximum).contains(&value) {
        return Err(format!("{name} must be 1..={maximum}").into());
    }
    Ok(value)
}

fn micros(duration: Duration) -> u64 {
    u64::try_from(duration.as_micros()).unwrap_or(u64::MAX)
}

fn directory_bytes(root: &Path) -> io::Result<u64> {
    let mut bytes = 0_u64;
    let mut entries = 0;
    for entry in std::fs::read_dir(root)? {
        entries += 1;
        if entries > 1024 {
            return Err(io::Error::other(
                "measurement directory exceeds bounded inventory",
            ));
        }
        let path = entry?.path();
        let metadata = match std::fs::symlink_metadata(path) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == io::ErrorKind::NotFound => continue,
            Err(error) => return Err(error),
        };
        if !metadata.is_file() {
            return Err(io::Error::other(
                "unexpected non-file in measurement directory",
            ));
        }
        bytes = bytes
            .checked_add(metadata.len())
            .ok_or_else(|| io::Error::other("disk-size overflow"))?;
    }
    Ok(bytes)
}

#[cfg(target_os = "linux")]
fn rss_bytes() -> io::Result<Option<u64>> {
    let status = std::fs::read_to_string("/proc/self/status")?;
    let value = status
        .lines()
        .find_map(|line| line.strip_prefix("VmRSS:"))
        .and_then(|value| value.split_whitespace().next())
        .ok_or_else(|| io::Error::other("VmRSS is unavailable"))?;
    let kib = value.parse::<u64>().map_err(io::Error::other)?;
    Ok(Some(
        kib.checked_mul(1024)
            .ok_or_else(|| io::Error::other("RSS overflow"))?,
    ))
}

#[cfg(not(target_os = "linux"))]
fn rss_bytes() -> io::Result<Option<u64>> {
    Ok(None)
}
