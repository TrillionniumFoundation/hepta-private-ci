//! Explicit cold DATA selects existing owners. The new actual Root must still
//! authenticate every old cut; these descriptions cannot renew old evidence.

use std::fs::File;
use std::os::unix::fs::FileExt;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use serde_json::Value;
use serde_json::json;

use super::cold_administration::OriginalColdAdministration;
use super::post_a_retained::RetainedOrdinaryQ24Fixture;

pub(super) struct OriginalColdPlan<'a> {
    pub(super) original: &'a RetainedOrdinaryQ24Fixture,
    pub(super) administration: OriginalColdAdministration,
    pub(super) profile: crate::HostAuthorityLearningProfileV1,
    pub(super) historical: PathBuf,
    pub(super) learning: PathBuf,
    pub(super) publication: PathBuf,
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
        let read = |path| -> anyhow::Result<Value> {
            Ok(serde_json::from_slice(&super::observer::read_private(
                path, /*bound*/ 65_536,
            )?)?)
        };
        let mut historical = read(&original.plan.root.historical)?;
        anyhow::ensure!(
            historical["initial"] == serde_json::to_value(&original.plan.profile)?,
            "original historical recipient metadata differs"
        );
        historical["initial"] = serde_json::to_value(&profile)?;
        let mut learning = read(&original.plan.root.learning)?;
        anyhow::ensure!(
            learning["mode"] == "register"
                && learning["initial"] == initial.head_digest.to_string(),
            "original learning registration metadata differs"
        );
        learning["mode"] = json!("reopen");
        let mut publication = read(&original.plan.root.publication)?;
        anyhow::ensure!(
            publication["schema"] == 2
                && publication["inputs"]["mode"] == "reserve"
                && publication["initial"] == initial.head_digest.to_string(),
            "original explicit V2 publication metadata differs"
        );
        publication["inputs"]["mode"] = json!("recover");
        let directory = &administration.directory;
        let historical_path = directory.join("historical.json");
        let learning_path = directory.join("learning.json");
        let publication_path = directory.join("publication.json");
        for (path, value) in [
            (&historical_path, &historical),
            (&learning_path, &learning),
            (&publication_path, &publication),
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
                && daemon["continuation"]["generation"]["next_use_mode"] == "create",
            "original daemon deployment was not the real fresh ordinary phase"
        );
        daemon["identity_digest"] = json!(
            crate::neuron_generation_process_identity_digest_v1(
                &administration.successor.identity,
            )?
            .to_string()
        );
        daemon["freeze_mode"] = json!("recover");
        daemon["stages"]["mode"] = json!("recover");
        daemon["delivery_mode"] = json!("recover");
        daemon["continuation"]["task"]["mode"] = json!("recover");
        daemon["continuation"]["task"]["recovery"] = json!("capture_retired");
        daemon["continuation"]["generation"]["selection_mode"] = json!("recover");
        daemon["continuation"]["generation"]["next_use_mode"] = json!("recover");
        super::root::write_json(&directory.join("original-daemon-deployment.json"), &before)?;
        super::root::write_json(&directory.join("cold-daemon-deployment.json"), &daemon)?;
        let sealed =
            crate::authority_host_bootstrap_seal::seal_bytes(&serde_json::to_vec(&daemon)?)?;
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
            learning: learning_path,
            publication: publication_path,
            sealed,
        })
    }
}
