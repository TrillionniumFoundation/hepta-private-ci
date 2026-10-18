//! One fixed initial-purpose Root writer. Existing service publication owns all
//! payload, admission, registry, signed CURRENT, recovery and durable ACK steps.
use super::state::OriginalHead;
use super::state::OriginalTimeSignature;
use super::*;
use ed25519_dalek::Signer;

pub(super) fn publish(inputs: Inputs) -> HostResult<Value> {
    let key = role::actual_role(&inputs, &inputs.profile.owner)?;
    let mut service = open_original(&inputs, &key, inputs.profile.withdrawals()?)?;
    let binding = inputs.storage_binding();
    let mut receipts = Vec::new();
    for index in 0..3 {
        inputs.revalidate()?;
        let manifest = inputs.artifacts[index].clone();
        let validated = validate_artifact_manifest_v2(manifest.clone(), now_ms()?)?;
        let sidecar = inputs
            .profile
            .owner_root
            .join("admissions")
            .join(format!("{}.manifest", validated.manifest_digest));
        let admission = if sidecar.try_exists()? {
            let original = read_artifact_admission_by_manifest_digest(
                std::fs::File::open(&sidecar)?,
                validated.manifest_digest,
            )?;
            if original.validated_manifest != validated
                || original.withdrawal_scope_digest
                    != service
                        .withdrawal_registry()
                        .scope_digest()
                        .ok_or("scope")?
                || original.withdrawal_head_digest != service.withdrawal_registry().head_digest()
            {
                return Err("original full admission differs".into());
            }
            original
        } else {
            admit_manifest_at_withdrawal_head_v3(
                service.withdrawal_registry(),
                service.withdrawal_registry().head_digest(),
                manifest,
                now_ms()?,
            )?
        };
        let operation = id(&format!(
            "initial-cpu:{index}:{}",
            inputs.evidence.authentication_digest()
        ))?;
        let preview =
            service.preview_registered_head(operation.clone(), admission.clone(), now_ms()?)?;
        let head_name = format!("head-{index}.json");
        let signed = match state::read::<OriginalHead>(&inputs, &head_name)? {
            Some(original) => original.native(&inputs, binding)?,
            None => {
                if preview.original_signed_head.is_some() {
                    return Err("Root original issuance disappeared".into());
                }
                let mut signed = SignedCurrentArtifactHeadV1 {
                    withdrawal_scope_digest: service
                        .withdrawal_registry()
                        .scope_digest()
                        .ok_or("scope")?,
                    binding,
                    witness: RegistryHeadWitnessV1 {
                        registry_id: id(&inputs.profile.registry_id)?,
                        generation: preview.generation,
                        head_digest: preview.head_digest,
                        predecessor_head_digest: preview.predecessor,
                        authority_epoch: 1,
                        signer_id: id(&inputs.profile.owner.id)?,
                        signing_key_digest: Digest32::of_bytes(key.verifying_key().as_bytes()),
                        issued_at: now_ms()?,
                        expires_at: inputs
                            .evidence
                            .expires_at()
                            .min(inputs.profile.expires_at_ms),
                    },
                    signature: [0; 64],
                };
                signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
                let original = OriginalHead {
                    time: OriginalTimeSignature::new(
                        &inputs,
                        signed.witness.issued_at,
                        signed.witness.expires_at,
                        signed.signature,
                    ),
                    generation: signed.witness.generation.get(),
                    predecessor: preview.predecessor.to_string(),
                    head: preview.head_digest.to_string(),
                };
                state::retain(&inputs, &head_name, &original)?;
                signed
            }
        };
        if signed.witness.head_digest != preview.head_digest
            || signed.witness.predecessor_head_digest != preview.predecessor
            || signed.witness.generation != preview.generation
            || preview
                .original_signed_head
                .as_ref()
                .is_some_and(|original| original != &signed)
        {
            return Err("original fixed head changed".into());
        }
        inputs.revalidate()?;
        let receipt = service.publish(LearningArtifactPublishRequestV1 {
            operation_id: operation,
            admission,
            payload: inputs.payloads[index].clone(),
            signed_current_head: signed.clone(),
            expected_registry_predecessor_head: preview.predecessor,
            now: now_ms()?,
        })?;
        state::retain(
            &inputs,
            &format!("done-{index}"),
            &Digest32::of_bytes(&signed.signing_bytes()).to_string(),
        )?;
        service.publish_root_read_frontier(now_ms()?)?;
        receipts.push(serde_json::json!({"artifact_id":inputs.artifacts[index].artifact_id.as_str(),"original_operation_id":receipt.operation_id.as_str(),
            "registry_head":signed.witness.head_digest.to_string(),"original_head_issued_at":signed.witness.issued_at,"acknowledged":true}));
    }
    // These seven protocol directories contain public immutable state only.
    // Signing keys and the independent restart floor stay in private role homes.
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::PermissionsExt;
    for name in [
        "writer",
        "transactions",
        "payloads",
        "registries",
        "witnesses",
        "heads",
        "admissions",
    ] {
        let directory = inputs.profile.owner_root.join(name);
        let metadata = std::fs::symlink_metadata(&directory)?;
        if !metadata.is_dir() || metadata.uid() != 0 || directory.canonicalize()? != directory {
            return Err("Root public artifact directory boundary".into());
        }
        let mut permissions_changed = metadata.mode() & 0o777 != 0o755;
        if permissions_changed {
            std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o755))?;
        }
        if name != "writer" {
            let budget = MAX_DURABLE_ARTIFACT_RECORDS * if name == "transactions" { 6 } else { 2 };
            for (index, entry) in std::fs::read_dir(&directory)?.enumerate() {
                if index >= budget {
                    return Err("durable public artifact capacity".into());
                }
                let path = entry?.path();
                let metadata = std::fs::symlink_metadata(&path)?;
                if !metadata.is_file()
                    || metadata.uid() != 0
                    || path.canonicalize()? != path
                    || !(1..=2).contains(&metadata.nlink())
                {
                    return Err("Root public artifact file boundary".into());
                }
                if metadata.mode() & 0o777 != 0o644 {
                    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644))?;
                    std::fs::File::open(path)?.sync_all()?;
                    permissions_changed = true;
                }
            }
        }
        if permissions_changed {
            std::fs::File::open(directory)?.sync_all()?;
        }
    }
    inputs.revalidate()?;
    let current = inputs.current()?.current_registry_view(now_ms()?)?;
    if inputs
        .artifacts
        .iter()
        .any(|manifest| !current.is_eligible(&manifest.artifact_id))
    {
        return Err("initial CURRENT lacks eligible exact artifacts".into());
    }
    Ok(
        serde_json::json!({"schema":if inputs.evidence.operational_lease().is_some() {"hepta.cpu-neuron.continued-installed-model-publication.v2"} else if inputs.first_installation_successor {"hepta.cpu-neuron.first-installed-profile-publication.v1"} else if inputs.renewal.is_some() {"hepta.cpu-neuron.fresh-operational-publication.v1"} else {"hepta.cpu-neuron.initial-root-publication.v1"},"profile_digest":inputs.profile_source.digest,
        "independent_evidence_digest":inputs.evidence.authentication_digest().to_string(),"generation":1,"qualified_predecessor":null,
        "current_head":current.receipt().head_digest.to_string(),"publications":receipts,"primary_superiority":false,"holdout_consumed":false,"production_activation":false}),
    )
}
fn lease(inputs: &Inputs, time: &OriginalTimeSignature) -> HostResult<SignedArtifactWriterLeaseV1> {
    Ok(SignedArtifactWriterLeaseV1 {
        lease_id: id(&format!("initial-cpu:{}", inputs.profile_source.digest))?,
        producer_id: id(&inputs.profile.owner.id)?,
        registry_id: id(&inputs.profile.registry_id)?,
        withdrawal_scope_digest: inputs
            .profile
            .withdrawals()?
            .scope_digest()
            .ok_or("scope")?,
        signer_id: id(&inputs.profile.owner.id)?,
        signing_key_digest: Digest32::of_bytes(&public(&inputs.profile.owner.public_key_hex)?),
        authority_epoch: 1,
        lease_generation: inputs
            .renewal
            .as_ref()
            .map(|renewal| renewal.lease_generation)
            .unwrap_or(1),
        issued_at: time.issued_at,
        expires_at: time.expires_at,
        signature: time.signature()?,
    })
}

/// Reopen the same exclusive owner/lease/restart floor. The caller supplies the
/// full monotonic withdrawal frontier; this never initializes another owner.
pub(super) fn open_original(
    inputs: &Inputs,
    key: &SigningKey,
    withdrawals: DatasetWithdrawalRegistry,
) -> HostResult<LearningArtifactOwnerService> {
    state::directory(inputs)?;
    let binding = inputs.storage_binding();
    if let Some(renewal) = &inputs.renewal {
        renewal.validate_original_root_floor()?;
    }
    let lease_time = match state::read::<OriginalTimeSignature>(inputs, "lease.json")? {
        Some(time) => time,
        None => {
            if std::fs::read_dir(&inputs.profile.original_owner_state)?
                .next()
                .is_some()
            {
                return Err("missing original writer lease".into());
            }
            let mut time = OriginalTimeSignature::new(
                inputs,
                now_ms()?,
                inputs
                    .evidence
                    .expires_at()
                    .min(inputs.profile.expires_at_ms),
                [0; 64],
            );
            let lease = lease(inputs, &time)?;
            time.signature_hex = state::hex(&key.sign(&lease.signing_bytes()).to_bytes());
            state::retain(inputs, "lease.json", &time)?;
            time
        }
    };
    lease_time.validate(inputs)?;
    let mut required = inputs
        .renewal
        .as_ref()
        .map(|renewal| renewal.retained.clone());
    for index in 0..3 {
        let original = state::read::<OriginalHead>(inputs, &format!("head-{index}.json"))?;
        let done = state::read::<String>(inputs, &format!("done-{index}"))?;
        if let Some(original) = original {
            let signed = original.native(inputs, binding)?;
            let preimage = Digest32::of_bytes(&signed.signing_bytes());
            if done
                .as_ref()
                .is_some_and(|digest| digest != &preimage.to_string())
            {
                return Err("Root original ACK conflict".into());
            }
            let actual = inputs.profile.owner_root.join("heads").join(format!(
                "{}-{preimage}.head",
                signed.witness.generation.get()
            ));
            if done.is_some() || actual.try_exists()? {
                required = Some(signed);
            }
        } else if done.is_some() {
            return Err("original acknowledged head missing".into());
        }
    }
    let config = LearningArtifactOwnerServiceConfigV1 {
        root: inputs.profile.owner_root.clone(),
        trust: inputs.trust()?,
        writer_lease: lease(inputs, &lease_time)?,
        required_current_head: required,
        withdrawal_registry: withdrawals,
        storage_binding: binding,
        now: now_ms()?,
    };
    let service = if inputs.renewal.is_some() {
        LearningArtifactOwnerService::open_for_fresh_evidence_publication(config)?
    } else {
        LearningArtifactOwnerService::open(config)?
    };
    Ok(service)
}
