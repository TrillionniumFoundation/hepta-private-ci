//! Explicit completed-history DATA opens no original learning writer. The new
//! actual Root must authenticate every old cut without renewing old evidence.

use std::fs::File;
use std::os::unix::fs::FileExt;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use serde_json::Value;
use serde_json::json;

use super::cold_administration::OriginalColdAdministration;
use super::post_a_retained::RetainedOrdinaryQ24Fixture;
use crate::ordinary_q24_cold_snapshot_tests::OriginalBusinessSnapshot;

pub(super) struct OriginalColdPlan<'a> {
    pub(super) original: &'a RetainedOrdinaryQ24Fixture,
    pub(super) administration: OriginalColdAdministration,
    pub(super) profile: crate::HostAuthorityLearningProfileV1,
    pub(super) historical: PathBuf,
    pub(super) completed_deployment: PathBuf,
    pub(super) sealed: File,
}

impl<'a> OriginalColdPlan<'a> {
    pub(super) fn prepare(
        original: &'a RetainedOrdinaryQ24Fixture,
        administration: OriginalColdAdministration,
    ) -> anyhow::Result<Self> {
        anyhow::ensure!(
            std::time::Instant::now() < administration.end,
            "original cold preparation deadline"
        );
        original.daemon.require_dead()?;
        original.root.require_dead()?;
        original.source.require_dead()?;
        let initial = original.plan.profile.original_initial_data()?;
        let proof: Digest32 = administration
            .successor
            .writer_proof
            .sha256()?
            .as_str()
            .parse()?;
        let profile = crate::HostAuthorityLearningProfileV1::new(
            &administration.successor.identity,
            proof.into_array(),
            initial.request.clone(),
            initial.owners.clone(),
        )?;
        anyhow::ensure!(
            profile.original_initial_data()? == initial,
            "cold must retain the entire old request, owners, business expiry and initial head"
        );
        let read = |path: &Path| -> anyhow::Result<Value> {
            let pin = OriginalBusinessSnapshot::capture(&[path.to_path_buf()])?;
            let value = serde_json::from_slice(&super::observer::read_private(
                path, /*bound*/ 65_536,
            )?);
            pin.require_unchanged(&[path.to_path_buf()])?;
            Ok(value?)
        };
        let mut historical = read(&original.plan.root.historical)?;
        anyhow::ensure!(
            historical["initial"] == serde_json::to_value(&original.plan.profile)?,
            "original historical recipient metadata differs"
        );
        historical["initial"] = serde_json::to_value(&profile)?;
        let completed_path = PathBuf::from(
            historical["completed_learning_deployment"]
                .as_str()
                .ok_or_else(|| anyhow::anyhow!("original first-acceptance deployment absent"))?,
        );
        let mut completed = read(&completed_path)?;
        anyhow::ensure!(
            completed["schema"] == 1
                && completed["purpose"] == "runtime.learning.completed-deployment.v1"
                && completed["mode"] == "accept"
                && completed["initial"] == initial.head_digest.to_string()
                && completed["target"]
                    == Digest32::from_array(
                        original
                            .plan
                            .resources
                            .original
                            .plan
                            .deployment
                            .target
                            .digest()?
                    )
                    .to_string()
                && completed["independent_b"]
                    == serde_json::to_value(&original.plan.root.independent_b)?
                && completed["publication"]
                    == serde_json::to_value(&original.plan.root.publication)?,
            "original first-acceptance deployment differs"
        );
        // Only this explicit phase is excluded from the Root's durable
        // deployment binding. All seven original paths and cuts stay fixed.
        completed["mode"] = json!("capture_retired");
        let directory = &administration.directory;
        let historical_path = directory.join("historical.json");
        let completed_deployment = directory.join("completed-learning.json");
        historical["completed_learning_deployment"] = serde_json::to_value(&completed_deployment)?;
        for (path, value) in [
            (&historical_path, &historical),
            (&completed_deployment, &completed),
        ] {
            super::root::write_json(path, value)?;
        }
        let held = &original.plan.sealed;
        let length = held.metadata()?.len();
        anyhow::ensure!(
            (1..=1_048_576).contains(&length),
            "original sealed deployment bound"
        );
        crate::authority_host_bootstrap_seal::validate_sealed(held, length)?;
        let mut bytes = vec![0; usize::try_from(length)?];
        held.read_exact_at(&mut bytes, /*offset*/ 0)?;
        crate::authority_host_bootstrap_seal::validate_sealed(held, length)?;
        let before: Value = serde_json::from_slice(&bytes)?;
        let mut daemon = before.clone();
        anyhow::ensure!(
            daemon["identity_digest"]
                == crate::neuron_generation_process_identity_digest_v1(
                    &original.plan.resources.successor.identity,
                )?
                .to_string()
                && daemon["freeze_mode"] == "create"
                && daemon["stages"]["mode"] == "create"
                && daemon["delivery_mode"] == "create"
                && daemon["continuation"]["task"]["mode"] == "create"
                && daemon["continuation"]["generation"]["selection_mode"] == "create"
                && daemon["continuation"]["generation"]["next_use_mode"] == "create"
                && daemon["completed_history"].is_null(),
            "original daemon deployment was not the real fresh ordinary phase"
        );
        daemon["identity_digest"] = json!(
            crate::neuron_generation_process_identity_digest_v1(
                &administration.successor.identity,
            )?
            .to_string()
        );
        // The product must branch before these original Create-mode owners.
        // Changing them to Recover would hide an accidental writer reopen.
        daemon["completed_history"] = json!("capture_retired");
        super::root::write_json(&directory.join("original-daemon-deployment.json"), &before)?;
        super::root::write_json(&directory.join("cold-daemon-deployment.json"), &daemon)?;
        let sealed =
            super::fixture::seal_original_readonly_deployment(&serde_json::to_vec(&daemon)?)?;
        original.daemon.require_dead()?;
        original.root.require_dead()?;
        anyhow::ensure!(
            std::time::Instant::now() < administration.end,
            "original cold deployment deadline"
        );
        Ok(Self {
            original,
            administration,
            profile,
            historical: historical_path,
            completed_deployment,
            sealed,
        })
    }
}
