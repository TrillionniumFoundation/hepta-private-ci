//! Explicit post-A Root publication input capture. The material producer may
//! supply data in its original file, never locations, trust or a Root owner.

use std::io;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use serde::Deserialize;

use super::super::ACTIVE;
use super::super::CLOSED;
use super::super::CONSUMED;
use super::super::PREPARED;
use super::super::RootGenerationPublicationEnrollmentCapabilityV1;
use super::super::RootGenerationPublicationRegistrationV1;
use super::data::LateMaterial;
use super::files::DirectoryPin;
use super::files::MetadataFile;
use super::files::OriginalFile;
use super::input_data::PublicationInputData;
use super::inputs::OriginalInputs;
use crate::authority_host_service::generation_publication::original_root;

#[path = "authority_host_post_a_publication_material.rs"]
mod material;
use material::MaterialData;
use material::RetainedMaterial;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct PostAPublicationData {
    schema: u8,
    purpose: String,
    initial: String,
    inputs: PublicationInputData,
    material: MaterialData,
}

pub(in crate::authority_host_runtime::session) struct OriginalPostAPublicationFiles {
    descriptor: MetadataFile,
    data: PublicationInputData,
    initial: String,
    uid: u32,
    inputs: OriginalInputs,
    directories: Vec<DirectoryPin>,
    material: RetainedMaterial,
}

pub(in crate::authority_host_runtime::session) struct OriginalPostAPublicationDeployment {
    files: Arc<OriginalPostAPublicationFiles>,
    capability: RootGenerationPublicationEnrollmentCapabilityV1,
}

impl OriginalPostAPublicationFiles {
    pub(in crate::authority_host_runtime::session) fn retain_original_publication(
        path: &Path,
        initial: &LearningIterationSnapshotV1,
        uid: u32,
        gid: u32,
    ) -> io::Result<Arc<Self>> {
        original_root()?;
        let (descriptor, bytes) = MetadataFile::open_metadata(path)?;
        let data: PostAPublicationData =
            serde_json::from_slice(&bytes).map_err(io::Error::other)?;
        if data.schema != 1
            || data.purpose != "runtime.learning.post-a-publication-deployment.v1"
            || data.initial != initial.head_digest.to_string()
            || !initial.receipts.is_empty()
            || data.inputs.issuer_keys.is_empty()
        {
            return Err(io::Error::other(
                "fixed original post-A publication deployment required",
            ));
        }
        let directories = vec![
            DirectoryPin::capture_root(&data.inputs.current_directory)?,
            DirectoryPin::capture_private(&data.inputs.artifact_root)?,
            DirectoryPin::capture_private(&data.inputs.consumer_state_root)?,
        ];
        let inputs = OriginalInputs {
            current: RootAuthorityDirectory::open(&data.inputs.current_directory)
                .map_err(io::Error::other)?,
            previous_journal: OriginalFile::open_original(&data.inputs.previous_journal)?,
            previous_witness: OriginalFile::open_original(&data.inputs.previous_witness)?,
            target_journal: OriginalFile::open_original(&data.inputs.target_journal)?,
            target_witness: OriginalFile::open_original(&data.inputs.target_witness)?,
            withdrawal: OriginalFile::open_original(&data.inputs.withdrawal_file)?,
        };
        let material = RetainedMaterial::open_original(data.material, uid, gid)?;
        for file in [
            &inputs.previous_journal,
            &inputs.previous_witness,
            &inputs.target_journal,
            &inputs.target_witness,
            &inputs.withdrawal,
        ] {
            material.require_distinct(file)?;
        }
        let held = Arc::new(Self {
            descriptor,
            data: data.inputs,
            initial: data.initial,
            uid,
            inputs,
            directories,
            material,
        });
        held.require_original_files()?;
        Ok(held)
    }

    pub(in crate::authority_host_runtime::session) fn attach_original_route(
        self: &Arc<Self>,
        initial: &LearningIterationSnapshotV1,
        capability: RootGenerationPublicationEnrollmentCapabilityV1,
    ) -> io::Result<OriginalPostAPublicationDeployment> {
        original_root()?;
        self.require_original_files()?;
        if self.initial != initial.head_digest.to_string()
            || self.uid != capability.consumer_uid
            || capability.original_end.is_none()
            || std::process::id() != capability.root_pid
            || capability.phase.load(Ordering::Acquire) != PREPARED
        {
            return Err(io::Error::other(
                "original bounded post-A publication route required",
            ));
        }
        capability.operation_end()?;
        Ok(OriginalPostAPublicationDeployment {
            files: Arc::clone(self),
            capability,
        })
    }

    fn require_original_files(&self) -> io::Result<()> {
        original_root()?;
        self.descriptor.require_metadata_unchanged()?;
        for directory in &self.directories {
            directory.require_directory()?;
        }
        self.inputs.require_original_inputs()?;
        self.material.require_original()
    }
}

impl OriginalPostAPublicationDeployment {
    pub(in crate::authority_host_runtime::session) fn wait_and_register_original_material(
        self,
        stopping: &AtomicBool,
    ) -> io::Result<RootGenerationPublicationRegistrationV1> {
        original_root()?;
        let end = self.capability.operation_end()?;
        let observed = loop {
            self.files.require_original_files()?;
            if stopping.load(Ordering::Acquire) || std::time::Instant::now() >= end {
                return Err(io::Error::other(
                    "original post-A publication session ended",
                ));
            }
            match self.capability.phase.load(Ordering::Acquire) {
                PREPARED => {}
                ACTIVE => {
                    if let Some(material) = self.files.material.observe_ready()? {
                        break material;
                    }
                }
                CONSUMED | CLOSED => {
                    return Err(io::Error::other("original publication slot closed"));
                }
                _ => return Err(io::Error::other("original publication phase differs")),
            }
            std::thread::sleep(Duration::from_millis(5));
        };
        let material: LateMaterial =
            serde_json::from_slice(observed.bytes()).map_err(io::Error::other)?;
        if serde_json::to_vec(&material).map_err(io::Error::other)? != observed.bytes() {
            return Err(io::Error::other(
                "canonical original publication material required",
            ));
        }
        let (inputs, artifacts) = OriginalInputs::enrollment_inputs(
            &self.files.inputs,
            &self.files.data,
            &material,
            self.capability.consumer_uid,
        )?;
        self.files.require_original_files()?;
        observed.require_unchanged()?;
        for file in &artifacts {
            file.require_original_file()?;
        }
        if stopping.load(Ordering::Acquire) || std::time::Instant::now() >= end {
            return Err(io::Error::other(
                "original publication ended before registration",
            ));
        }
        let result =
            RootGenerationPublicationEnrollmentCapabilityV1::register(self.capability, inputs)?;
        // The same one-shot slot is consumed even when a physical postcheck
        // fails. Never retry enrollment or turn its uncertainty into success.
        self.files
            .require_original_files()
            .map_err(super::registration_uncertain)?;
        observed
            .require_unchanged()
            .map_err(super::registration_uncertain)?;
        for file in &artifacts {
            file.require_original_file()
                .map_err(super::registration_uncertain)?;
        }
        if stopping.load(Ordering::Acquire) || std::time::Instant::now() >= end {
            return Err(io::Error::other(
                "original publication registration outcome uncertain",
            ));
        }
        Ok(result)
    }
}
