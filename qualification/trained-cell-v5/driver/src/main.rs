//! Development-only actual-parameter conversion, serving and owner mechanics.
//! Positive lifecycle metrics are synthetic. No actual scientific candidate is
//! accepted by this executable, and no installed product credential is used.

mod fixture;
mod parity;

use codex_hepta_learning_artifacts::*;
use codex_hepta_neuron::TrainedCellBundleV5;
use codex_hepta_neuron::TrainedCellErrorV5;
use codex_hepta_neuron::TrainedCellInputBindingV5;
use codex_hepta_neuron::trained_cell_compatibility_digest_v5;
use codex_hepta_neuron::trained_cell_normalization_digest_v5;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde_json::Value;
use serde_json::json;
use std::collections::BTreeMap;
use std::fs::File;
use std::fs::{self};
use std::path::Path;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
fn ensure(condition: bool, message: &str) -> Result<()> {
    if condition {
        Ok(())
    } else {
        Err(message.to_string().into())
    }
}
fn id(value: &str) -> Result<StableId> {
    Ok(StableId::new(value)?)
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn inventory(root: &Path) -> Result<BTreeMap<PathBuf, Vec<u8>>> {
    let mut files = BTreeMap::new();
    for entry in fs::read_dir(root)? {
        let path = entry?.path();
        if path.is_dir() {
            files.extend(inventory(&path)?);
        } else {
            files.insert(path.clone(), fs::read(path)?);
        }
    }
    Ok(files)
}

fn decode(
    bytes: &[u8],
    manifest: &ArtifactManifest,
) -> std::result::Result<TrainedCellBundleV5, TrainedCellErrorV5> {
    let bundle = TrainedCellBundleV5::decode(bytes, manifest.content_digest)?;
    if bundle.artifact_id() != &manifest.artifact_id
        || bundle.generation() != manifest.generation
        || bundle.content_digest() != manifest.content_digest
        || bytes.len() as u64 != manifest.encoded_size_bytes
        || manifest.compatibility_digest != trained_cell_compatibility_digest_v5()
    {
        return Err(TrainedCellErrorV5::Binding);
    }
    Ok(bundle)
}

fn files(
    root: &Path,
    owner: &LearningArtifactOwnerService,
    manifest: &LearningArtifactManifestV2,
    now: u64,
) -> Result<(File, File)> {
    let receipt = owner.current_registry_view(now)?.receipt();
    Ok((
        File::open(root.join("registries").join(format!(
            "{}-{}.snapshot",
            receipt.head_digest, receipt.file_digest
        )))?,
        File::open(root.join("payloads").join(format!(
            "{}-{}.bin",
            manifest.artifact_id, manifest.bytes_digest
        )))?,
    ))
}

fn load(
    f: &fixture::Fixture,
    owner: &LearningArtifactOwnerService,
    manifest: &LearningArtifactManifestV2,
) -> Result<OwnerTypedSelectedCandidateV5<TrainedCellBundleV5>> {
    let (snapshot, payload) = files(&f.config.root, owner, manifest, f.config.now)?;
    Ok(OwnerTypedSelectedCandidateV5::load(
        snapshot,
        payload,
        f.selection(owner, &manifest.artifact_id)?,
        OwnerCandidateContextV5 {
            owner,
            manifest,
            now: f.config.now,
        },
        trained_cell_compatibility_digest_v5(),
        decode,
    )?)
}

fn main() -> Result<()> {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    ensure(
        args.len() == 2,
        "usage: qualification DEVELOPMENT_PARITY_DIRECTORY NEW_OUTPUT_DIRECTORY",
    )?;
    let input_root = Path::new(&args[0]);
    let output = Path::new(&args[1]);
    let inputs = parity::Inputs::load(input_root)?;
    ensure(
        inputs.manifest["scope"] == "development-v4",
        "positive mechanics fixture only accepts explicitly development-tagged V4 parameters",
    )?;
    inputs.verify_family(
        "30880ddaae978f622cf6a99cf3888771daa954777e6f9ce2a75c25f01f166280",
        ["uci", "newsgroups"],
    )?;
    for (index, (payload, source)) in [
        (
            "12390a274a502da20027769d3aded963dbab66ed31d0891ffd687023ffce1375",
            "9737384bb5fef3a684709e8da06216b56fe22e8a122febd063eca935a830725a",
        ),
        (
            "573a9abe84ad70928a842104cd3af82d1e41b29c85ac5588a40c84e42b7e0533",
            "3b88671eb6d88abaa3717c2252e4d80092e09931c5e0c0a85d338aa0fcfdaf52",
        ),
    ]
    .iter()
    .enumerate()
    {
        ensure(
            inputs.manifest["versions"][index]["payload_sha256"] == *payload
                && inputs.manifest["versions"][index]["source_bundle_sha256"] == *source,
            "development fixture differs from known V4 all12 parameters",
        )?;
    }
    let preflight = [
        parity::compare_unpublished(&inputs, 0)?,
        parity::compare_unpublished(&inputs, 1)?,
    ];
    fs::create_dir(output)?;
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let f = fixture::Fixture::new(&output.join("owner"), now)?;
    let baseline = TrainedCellBundleV5::decode(
        &inputs.payloads[0],
        parity::hash(&inputs.manifest["versions"][0]["payload_sha256"])?,
    )?;
    let candidate = TrainedCellBundleV5::decode(
        &inputs.payloads[1],
        parity::hash(&inputs.manifest["versions"][1]["payload_sha256"])?,
    )?;
    let baseline_manifest = f.manifest(
        &baseline,
        &inputs.payloads[0],
        None,
        parity::hash(&inputs.manifest["versions"][0]["source_bundle_sha256"])?,
    );
    let candidate_manifest = f.manifest(
        &candidate,
        &inputs.payloads[1],
        Some(baseline.artifact_id().clone()),
        parity::hash(&inputs.manifest["versions"][1]["source_bundle_sha256"])?,
    );
    let mut owner = LearningArtifactOwnerService::open(f.config.clone())?;
    let baseline_request = f.request(
        owner.registry(),
        owner.withdrawal_registry(),
        baseline_manifest.clone(),
        inputs.payloads[0].clone(),
    )?;
    let baseline_head = baseline_request.signed_current_head.clone();
    ensure(
        !owner.publish(baseline_request)?.authority.grants_any(),
        "baseline gained authority",
    )?;
    let baseline_archive = inventory(&f.config.root)?;
    let candidate_request = f.request(
        owner.registry(),
        owner.withdrawal_registry(),
        candidate_manifest.clone(),
        inputs.payloads[1].clone(),
    )?;
    let required_head = candidate_request.signed_current_head.clone();
    let before = inventory(&f.config.root)?;
    let mut publisher =
        ScientificCandidatePublisherV1::new(owner, f.policy.clone(), f.reviewer()?)?;
    ensure(
        matches!(
            publisher.publish(
                candidate_request.clone(),
                ScientificReviewEvidenceV1::Missing
            ),
            Err(ScientificCandidateReviewError::MissingReview)
        ),
        "missing review accepted",
    )?;
    ensure(
        matches!(
            publisher.publish(
                candidate_request.clone(),
                f.review(&candidate_request, 0.0)?
            ),
            Err(ScientificCandidateReviewError::GateFailed("task"))
        ),
        "failed measured task accepted",
    )?;
    let mut wrong = candidate_request.clone();
    wrong.payload[100] ^= 1;
    ensure(
        matches!(
            publisher.publish(wrong, f.review(&candidate_request, -0.01)?),
            Err(ScientificCandidateReviewError::CandidateBinding)
        ),
        "tampered typed payload accepted",
    )?;
    ensure(
        inventory(&f.config.root)? == before,
        "rejection changed owner bytes",
    )?;
    let publication = publisher.publish(
        candidate_request.clone(),
        f.review(&candidate_request, -0.01)?,
    )?;
    ensure(
        !publication.publication.authority.grants_any(),
        "publication gained authority",
    )?;
    let published = inventory(&f.config.root)?;
    let retried = publisher.publish(
        candidate_request.clone(),
        f.review(&candidate_request, -0.01)?,
    )?;
    ensure(
        retried == publication && inventory(&f.config.root)? == published,
        "exact retry changed publication",
    )?;
    drop(publisher);

    let mut config = f.config.clone();
    config.required_current_head = Some(required_head.clone());
    let mut owner = LearningArtifactOwnerService::open(config.clone())?;
    ensure(
        owner.registry().manifest(candidate.artifact_id()).is_some()
            && owner.recovery_required().is_none(),
        "reopen lost candidate",
    )?;
    let head = owner.current_registry_view(now)?.receipt().head_digest;
    let mut typed = load(&f, &owner, &candidate_manifest)?;
    let candidate_parity = parity::compare(&inputs, 1, &mut typed, &owner, now)?;
    ensure(
        candidate_parity == preflight[1],
        "published candidate differs from pre-publication parity",
    )?;
    let before_rollback = inventory(&f.config.root)?;
    let (snapshot, payload) = files(&f.config.root, &owner, &baseline_manifest, now)?;
    typed.rollback_to_predecessor(
        snapshot,
        payload,
        f.selection(&owner, baseline.artifact_id())?,
        OwnerCandidateContextV5 {
            owner: &owner,
            manifest: &baseline_manifest,
            now,
        },
        decode,
    )?;
    let baseline_parity = parity::compare(&inputs, 0, &mut typed, &owner, now)?;
    ensure(
        baseline_parity == preflight[0],
        "rollback predecessor differs from pre-publication parity",
    )?;
    ensure(
        inventory(&f.config.root)? == before_rollback
            && owner.current_registry_view(now)?.receipt().head_digest == head,
        "serving rollback rewound owner history",
    )?;

    // Test actual per-use source withdrawal without manufacturing a registry
    // Revoke event. The owner's compact registry intentionally stays unchanged.
    let mut withdrawn_candidate = load(&f, &owner, &candidate_manifest)?;
    let mut rollback_candidate = load(&f, &owner, &candidate_manifest)?;
    let mut mixed_frontier_candidate = load(&f, &owner, &candidate_manifest)?;
    let mut withdrawals = owner.withdrawal_registry().clone();
    f.withdraw(&mut withdrawals, &candidate_manifest)?;
    owner.install_withdrawal_frontier(withdrawals.clone())?;
    ensure(
        matches!(
            withdrawn_candidate.with_owner(&owner, now, |_| ()),
            Err(OwnerTypedCandidateErrorV5::Admission(_))
        ),
        "withdrawn source remained readable",
    )?;
    ensure(
        matches!(
            rollback_candidate.with_owner(&owner, now, |_| ()),
            Err(OwnerTypedCandidateErrorV5::Admission(_))
        ),
        "second withdrawn source remained readable",
    )?;
    let (snapshot, payload) = files(&f.config.root, &owner, &baseline_manifest, now)?;
    rollback_candidate.rollback_to_predecessor(
        snapshot,
        payload,
        f.selection(&owner, baseline.artifact_id())?,
        OwnerCandidateContextV5 {
            owner: &owner,
            manifest: &baseline_manifest,
            now,
        },
        decode,
    )?;
    ensure(
        rollback_candidate.with_owner(&owner, now, |bundle| bundle.content_digest())?
            == baseline.content_digest(),
        "eligible predecessor did not recover",
    )?;
    f.withdraw(&mut withdrawals, &baseline_manifest)?;
    owner.install_withdrawal_frontier(withdrawals.clone())?;
    ensure(
        matches!(
            rollback_candidate.with_owner(&owner, now, |_| ()),
            Err(OwnerTypedCandidateErrorV5::Admission(_))
        ),
        "withdrawn predecessor remained readable",
    )?;
    ensure(
        matches!(
            withdrawn_candidate.with_owner(&owner, now, |_| ()),
            Err(OwnerTypedCandidateErrorV5::Typed(
                TypedCandidateErrorV5::Current(PinnedCandidateLoadError::Unavailable)
            ))
        ),
        "closed reader revived",
    )?;
    ensure(
        owner.current_registry_view(now)?.receipt().head_digest == head,
        "withdrawal test changed registry history",
    )?;
    // Observe a new withdrawal feed alongside a valid but stale signed registry.
    // The registry failure must not discard the independently newer source view.
    let stale_root = output.join("stale-registry-owner");
    fs::create_dir(&stale_root)?;
    for (path, bytes) in baseline_archive {
        let target = stale_root.join(path.strip_prefix(&f.config.root)?);
        fs::create_dir_all(target.parent().ok_or("backup parent missing")?)?;
        fs::write(target, bytes)?;
    }
    let mut stale_config = f.config.clone();
    stale_config.root = stale_root;
    stale_config.required_current_head = Some(baseline_head);
    stale_config.withdrawal_registry = withdrawals;
    let stale_registry_owner = LearningArtifactOwnerService::open(stale_config)?;
    ensure(
        matches!(
            mixed_frontier_candidate.with_owner(&stale_registry_owner, now, |_| ()),
            Err(OwnerTypedCandidateErrorV5::Typed(
                TypedCandidateErrorV5::Current(PinnedCandidateLoadError::FrontierMismatch)
            ))
        ),
        "mixed stale registry view accepted",
    )?;
    drop(stale_registry_owner);
    drop(owner);
    // A host restoring an old withdrawal feed still cannot revive this reader.
    let old_feed_owner = LearningArtifactOwnerService::open(config)?;
    let (snapshot, payload) = files(&f.config.root, &old_feed_owner, &baseline_manifest, now)?;
    ensure(
        matches!(
            withdrawn_candidate.rollback_to_predecessor(
                snapshot,
                payload,
                f.selection(&old_feed_owner, baseline.artifact_id())?,
                OwnerCandidateContextV5 {
                    owner: &old_feed_owner,
                    manifest: &baseline_manifest,
                    now
                },
                decode
            ),
            Err(OwnerTypedCandidateErrorV5::WithdrawalFrontier)
        ),
        "stale withdrawal feed revived predecessor",
    )?;
    let (snapshot, payload) = files(&f.config.root, &old_feed_owner, &baseline_manifest, now)?;
    ensure(
        matches!(
            mixed_frontier_candidate.rollback_to_predecessor(
                snapshot,
                payload,
                f.selection(&old_feed_owner, baseline.artifact_id())?,
                OwnerCandidateContextV5 {
                    owner: &old_feed_owner,
                    manifest: &baseline_manifest,
                    now
                },
                decode
            ),
            Err(OwnerTypedCandidateErrorV5::WithdrawalFrontier)
        ),
        "mixed frontier failure forgot newer withdrawals",
    )?;

    let report = json!({"schema":"hepta.typed-native-development-qualification.v5","status":"completed",
        "input_manifest_sha256":Digest32::of_bytes(&fs::read(input_root.join("manifest.json"))?).to_string(),
        "scope":"development V4 actual weights and features; synthetic review metrics, synthetic dataset notices, public ephemeral host keys",
        "parity":[baseline_parity,candidate_parity],"payloads":inputs.manifest["versions"].as_array().ok_or("versions missing")?.iter().map(|v|json!({"artifact_id":v["artifact_id"],"payload_sha256":v["payload_sha256"],"source_bundle_sha256":v["source_bundle_sha256"]})).collect::<Vec<_>>(),
        "checks":{"missing_review_rejected":true,"failed_measured_task_rejected":true,"tampered_payload_rejected":true,"reject_owner_bytes_unchanged":true,
            "positive_synthetic_lifecycle_only":true,"exact_retry_idempotent":true,"required_current_reopen":true,"all12_native_candidate_serving":true,
            "all12_explicit_predecessor_rollback":true,"rollback_owner_bytes_unchanged":true,"source_withdrawal_closes_cached_serving":true,
            "eligible_predecessor_reload_after_candidate_withdrawal":true,"withdrawn_predecessor_rejected":true,"stale_withdrawal_feed_cannot_revive":true,
            "mixed_stale_registry_does_not_forget_new_withdrawals":true},
        "registry_head_sha256":head.to_string(),"synthetic_policy_sha256":f.policy.digest().to_string(),"synthetic_review_sha256":publication.review_digest.to_string(),
        "scientific_acceptance":false,"production_authority":false,"authority":"DENY_ALL",
        "limits":["No actual scientific review passes here.","No product activation or Encoder execution.","Serving rollback restores theta only; complete Adam/RNG/clock restoration is a separate research checkpoint path.","Host must authenticate and install the latest withdrawal feed and serialize view/use.","Float64 parity is bounded fixture coverage at fixed 1e-12 tolerance, not cross-platform bitwise identity."]});
    fs::write(
        output.join("qualification.json"),
        serde_json::to_vec_pretty(&report)?,
    )?;
    println!("{}", serde_json::to_string_pretty(&report)?);
    Ok(())
}
