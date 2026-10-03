//! Run the original finite G/O purposes for one complete prepared owner input.
//! Pre-registration and final admission keep distinct consumed purpose slots.
use super::*;
use crate::ParameterRoleExecutionPurposeV1;
use crate::ParameterRoleExecutionV1;
use crate::RootSelfIterationRoleRouteV1;
use codex_hepta_agent_components::intelligence_eval::*;
use codex_hepta_agent_components::learning_ledger::*;
use codex_hepta_agent_components::plasticity::*;
use codex_hepta_agentd::AgentdPlasticityAdmissionInputV1;
use codex_hepta_neuron::NeuronGenerationMaterialV2;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;

#[derive(Clone, Copy)]
pub(super) enum AdmissionPhase {
    BeforeRegistration,
    AfterRegistration,
}
impl AdmissionPhase {
    fn directory(self) -> &'static str {
        match self {
            Self::BeforeRegistration => "pre-registration-admission",
            Self::AfterRegistration => "registered-admission",
        }
    }
}

pub(super) struct OriginalParameterRolePreparation<'a> {
    pub round: &'a AgentdSelfIterationRoundV1,
    pub canonical: &'a codex_hepta_agentd::CanonicalIterationEnvelopeV1,
    pub baseline: &'a NeuronGenerationMaterialV2,
    pub input: &'a AgentdPlasticityAdmissionInputV1,
    pub admission: &'a PlasticityAdmissionEvidenceV1,
    pub sources: [ParameterRoleSourceV3; 3],
    pub current: crate::RootParameterObserverCurrentV1<'a>,
    pub trust: &'a InstalledCpuSourceV1,
    pub routes: [&'a RootSelfIterationRoleRouteV1; 2],
    pub public_directory: &'a Path,
    pub effects_directory: &'a Path,
    pub phase: AdmissionPhase,
}

fn public_directory(parent: &Path, name: &str) -> Result<PathBuf> {
    execution::protected_directory(parent)?;
    for ancestor in parent.ancestors() {
        ensure!(
            std::fs::symlink_metadata(ancestor)?.mode() & 0o001 != 0,
            "original public role Source parent is not traversable"
        );
    }
    let directory = parent.join(name);
    match std::fs::create_dir(&directory) {
        Ok(()) => std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o755))?,
        Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {}
        Err(error) => return Err(error.into()),
    }
    execution::protected_directory(&directory)?;
    ensure!(
        std::fs::symlink_metadata(&directory)?.mode() & 0o777 == 0o755,
        "original role public Source directory custody"
    );
    Ok(directory)
}

fn publish(directory: &Path, name: &str, bytes: &[u8]) -> Result<ParameterRoleSourceV3> {
    publish_bounded(directory, name, bytes, 64 * 1024)
}

fn publish_bounded(
    directory: &Path,
    name: &str,
    bytes: &[u8],
    maximum: usize,
) -> Result<ParameterRoleSourceV3> {
    let path = directory.join(name);
    execution::immutable(&path, bytes, maximum)?;
    Ok(ParameterRoleSourceV3 {
        path,
        digest: codex_hepta_types::Digest32::of_bytes(bytes).to_string(),
    })
}

/// Publish the complete pinned public input, including every source the
/// unprivileged process must reopen. Its private effect directory stays private.
fn publish_role_materials(
    directory: &Path,
    sources: &[ParameterRoleSourceV3; 3],
) -> Result<[ParameterRoleSourceV3; 3]> {
    let mut published = Vec::new();
    for (source, name, maximum) in [
        (&sources[0], "profile.json", 1024 * 1024),
        (
            &sources[1],
            "baseline-material.json",
            codex_hepta_neuron::MAX_NEURON_GENERATION_MATERIAL_BYTES_V2,
        ),
        (&sources[2], "admission.json", 1024 * 1024),
    ] {
        let original = InstalledCpuSourceV1 {
            path: source.path.clone(),
            digest: source.digest.clone(),
        };
        let bytes = configuration::source(&original, maximum)?;
        let public = publish_bounded(directory, name, &bytes, maximum)?;
        ensure!(
            public.digest == source.digest && configuration::source(&original, maximum)? == bytes,
            "whole original role input changed during public publication"
        );
        published.push(public);
    }
    published
        .try_into()
        .map_err(|_| anyhow::anyhow!("whole original G/O material frontier"))
}

fn route_configuration(
    route: &RootSelfIterationRoleRouteV1,
    source: &ParameterRoleSourceV3,
) -> Result<Vec<u8>> {
    let mut template: serde_json::Value = serde_json::from_slice(&configuration::source(
        &route.configuration_template,
        32 * 1024,
    )?)?;
    ensure!(
        template.is_object(),
        "complete original finite role template"
    );
    template["source"] = serde_json::to_value(source)?;
    template["program_digest"] = route.program.digest.clone().into();
    Ok(serde_json::to_vec(&template)?)
}

impl OriginalParameterRolePreparation<'_> {
    fn validate(&self) -> Result<()> {
        ensure!(
            self.routes[0].uid > 0
                && self.routes[0].gid > 0
                && self.routes[1].uid == 0
                && self.routes[1].gid == 0
                && self.routes[0].inaccessible_paths.len() == 5
                && self.routes[1].inaccessible_paths.is_empty(),
            "original independently enrolled finite G/O process identities"
        );
        let generated = validate_parameter_generator_baseline_v3(
            &self.input.generator_profile,
            self.baseline,
            self.baseline.scope.scope_digest,
            self.baseline.scope.objective_digest,
        )
        .map_err(|e| anyhow::anyhow!("{e}"))?;
        ensure!(
            generated == self.input.generated
                && self.input.baseline_id == self.admission.baseline_id
                && self.input.baseline_generation == self.baseline.runtime.generation,
            "actual whole prepared owner input/profile/baseline changed"
        );
        validate_parameter_admission_binding_v1(
            &self.input.generator_profile,
            &self.input.generated,
            self.admission,
        )
        .map_err(|e| anyhow::anyhow!("{e}"))?;
        self.current
            .facts
            .revalidate_current(now_ms()?)
            .map_err(|e| anyhow::anyhow!("{e}"))?;
        ensure!(
            now_ms()? >= self.round.admitted_at_ms() && now_ms()? < self.round.deadline_ms(),
            "original role preparation crossed the sealed Round window"
        );
        for source in &self.sources {
            configuration::source(
                &InstalledCpuSourceV1 {
                    path: source.path.clone(),
                    digest: source.digest.clone(),
                },
                codex_hepta_neuron::MAX_NEURON_GENERATION_MATERIAL_BYTES_V2,
            )?;
        }
        Ok(())
    }

    /// Returns only the actual original signed outputs. Missing or UNKNOWN
    /// retained output remains pending; the original slot never launches twice.
    pub(super) fn execute(self) -> Result<Option<[SignedLearningEvidenceV1; 2]>> {
        self.validate()?;
        let public = public_directory(self.public_directory, self.phase.directory())?;
        let public_sources = publish_role_materials(&public, &self.sources)?;
        let effects = self.effects_directory.join(self.phase.directory());
        super::super::independent_owners::roles::prepare_effect_directory(&effects)?;
        let trust_bytes = configuration::source(self.trust, 64 * 1024)?;
        let wire: ReviewTrustWireV1 = serde_json::from_slice(&trust_bytes)?;
        let (root, distribution) = wire.native().map_err(|e| anyhow::anyhow!("{e}"))?;
        let trust = activate_learning_trust(&root, distribution, None, now_ms()?)?;
        let generator_inputs = crate::prepare_root_parameter_generator_inputs_v3(
            self.round,
            self.canonical,
            self.baseline,
            &self.input.generator_profile,
            wire,
            public_sources[0].clone(),
            public_sources[1].clone(),
        )
        .map_err(|e| anyhow::anyhow!("{e}"))?;
        let generator_source = publish(
            &public,
            "generator-inputs.json",
            &serde_json::to_vec(&generator_inputs)?,
        )?;
        let gconfig = route_configuration(self.routes[0], &generator_source)?;
        let config: FixedParameterGeneratorConfigV3 = serde_json::from_slice(&gconfig)?;
        ensure!(
            config.uid == self.routes[0].uid
                && config.gid == self.routes[0].gid
                && config.inaccessible_paths == self.routes[0].inaccessible_paths,
            "original G template changed enrolled UID/GID/denials"
        );
        let gsource = publish(&public, "generator.json", &gconfig)?;
        let verify_g = |bytes: &[u8]| -> std::result::Result<(), Box<dyn std::error::Error>> {
            self.validate().map_err(|e| format!("{e}"))?;
            trust.revalidate_at(now_ms()?)?;
            let evidence: ReviewEvidenceWireV1 = serde_json::from_slice(bytes)?;
            trust.verifier().verify(
                LearningEvidenceRoleV1::Generator,
                &evidence.native()?,
                &parameter_generator_signing_payload_v3(&self.input.generated),
                now_ms()?,
            )?;
            Ok(())
        };
        let request =
            |index: usize, source: ParameterRoleSourceV3, purpose| ParameterRoleExecutionV1 {
                purpose,
                program: ParameterRoleSourceV3 {
                    path: self.routes[index].program.path.clone(),
                    digest: self.routes[index].program.digest.clone(),
                },
                original_effect_digest: codex_hepta_types::Digest32::of_parts(&[
                    self.round.identity_digest().as_array(),
                    source.digest.as_bytes(),
                ]),
                configuration: source,
                uid: self.routes[index].uid,
                gid: self.routes[index].gid,
                inaccessible_paths: self.routes[index].inaccessible_paths.clone(),
            };
        let Some(generator_bytes) = crate::execute_retained_parameter_role_v1(
            &request(
                0,
                gsource,
                ParameterRoleExecutionPurposeV1::GeneratorProfile,
            ),
            &effects.join("generator.output"),
            verify_g,
        )
        .map_err(|e| anyhow::anyhow!("{e}"))?
        else {
            return Ok(None);
        };
        let generator: ReviewEvidenceWireV1 = serde_json::from_slice(&generator_bytes)?;
        let original_g = generator.native().map_err(|e| anyhow::anyhow!("{e}"))?;
        let current_facts = self.current.facts;
        let observer_inputs = crate::prepare_root_parameter_observer_current_inputs_v1(
            self.round,
            self.canonical,
            crate::RootParameterObserverBaselineV1 {
                material: self.baseline,
                profile: &self.input.generator_profile,
                admission: self.admission,
            },
            serde_json::from_slice(&trust_bytes)?,
            public_sources,
            generator,
            self.current,
        )
        .map_err(|e| anyhow::anyhow!("{e}"))?;
        let observer_source = publish(
            &public,
            "observer-inputs.json",
            &serde_json::to_vec(&observer_inputs)?,
        )?;
        let osource = publish(
            &public,
            "observer.json",
            &route_configuration(self.routes[1], &observer_source)?,
        )?;
        let verify_o = |bytes: &[u8]| -> std::result::Result<(), Box<dyn std::error::Error>> {
            let now = now_ms()?;
            if now < self.round.admitted_at_ms() || now >= self.round.deadline_ms() {
                return Err("original O result crossed the sealed Round window".into());
            }
            current_facts.revalidate_current(now)?;
            for source in &self.sources {
                configuration::source(
                    &InstalledCpuSourceV1 {
                        path: source.path.clone(),
                        digest: source.digest.clone(),
                    },
                    codex_hepta_neuron::MAX_NEURON_GENERATION_MATERIAL_BYTES_V2,
                )?;
            }
            trust.revalidate_at(now_ms()?)?;
            let generator = trust.verifier().verify(
                LearningEvidenceRoleV1::Generator,
                &original_g,
                &parameter_generator_signing_payload_v3(&self.input.generated),
                now_ms()?,
            )?;
            let evidence: ReviewEvidenceWireV1 = serde_json::from_slice(bytes)?;
            let observer = trust.verifier().verify(
                LearningEvidenceRoleV1::Observer,
                &evidence.native()?,
                &plasticity_admission_signing_payload_v1(self.admission),
                now_ms()?,
            )?;
            verify_signed_role_separation(&generator, &observer, now_ms()?)?;
            Ok(())
        };
        let Some(observer_bytes) = crate::execute_retained_parameter_role_v1(
            &request(
                1,
                osource,
                ParameterRoleExecutionPurposeV1::ObserverAdmission,
            ),
            &effects.join("observer.output"),
            verify_o,
        )
        .map_err(|e| anyhow::anyhow!("{e}"))?
        else {
            return Ok(None);
        };
        Ok(Some([
            original_g,
            serde_json::from_slice::<ReviewEvidenceWireV1>(&observer_bytes)?
                .native()
                .map_err(|e| anyhow::anyhow!("{e}"))?,
        ]))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    #[ignore = "requires actual Root and isolated protected /run Sources"]
    fn actual_root_public_role_source_is_readable_without_private_effect_access() -> Result<()> {
        ensure!(
            rustix::process::geteuid().as_raw() == 0,
            "actual Root required"
        );
        let root = tempfile::Builder::new()
            .prefix("hepta-original-role-source-")
            .tempdir_in("/run")?;
        std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o755))?;
        let before = public_directory(root.path(), AdmissionPhase::BeforeRegistration.directory())?;
        let after = public_directory(root.path(), AdmissionPhase::AfterRegistration.directory())?;
        let source = publish(&before, "public.json", b"{\"original_public_pin\":true}")?;
        publish(&after, "public.json", b"{\"original_final_pin\":true}")?;
        let effects = root.path().join("original-private-effects");
        super::super::super::independent_owners::roles::prepare_effect_directory(&effects)?;
        let private = effects.join("output");
        std::fs::write(&private, b"private original effect")?;
        std::fs::set_permissions(&private, std::fs::Permissions::from_mode(0o600))?;
        let child = |path: &Path| {
            std::process::Command::new("/usr/bin/setpriv")
                .args([
                    "--reuid=65534",
                    "--regid=65534",
                    "--clear-groups",
                    "--bounding-set=-all",
                    "--no-new-privs",
                    "/usr/bin/cat",
                ])
                .arg(path)
                .output()
        };
        let public_read = child(&source.path)?;
        ensure!(
            public_read.status.success() && public_read.stdout == b"{\"original_public_pin\":true}",
            "actual unprivileged role failed to read original public Source"
        );
        let private_read = child(&private)?;
        ensure!(
            !private_read.status.success() && private_read.stdout.is_empty(),
            "actual unprivileged role obtained private original effect"
        );
        let originals = [
            publish_bounded(&effects, "profile.json", &vec![b'p'; 65_537], 1024 * 1024)?,
            publish_bounded(
                &effects,
                "baseline-material.json",
                &vec![b'b'; 65_538],
                codex_hepta_neuron::MAX_NEURON_GENERATION_MATERIAL_BYTES_V2,
            )?,
            publish_bounded(&effects, "admission.json", &vec![b'a'; 65_539], 1024 * 1024)?,
        ];
        for original in &originals {
            ensure!(
                !child(&original.path)?.status.success(),
                "actual unprivileged role traversed original private input directory"
            );
        }
        let published = publish_role_materials(&before, &originals)?;
        for (original, source) in originals.iter().zip(&published) {
            let read = child(&source.path)?;
            let bytes = std::fs::read(&original.path)?;
            ensure!(
                read.status.success() && read.stdout == bytes && source.digest == original.digest,
                "actual unprivileged role cannot read a complete independently pinned material"
            );
        }
        ensure!(
            serde_json::to_vec(&publish_role_materials(&before, &originals)?)?
                == serde_json::to_vec(&published)?,
            "identical complete input recovery changed the public Sources"
        );
        std::fs::write(&originals[0].path, b"changed original input")?;
        ensure!(
            publish_role_materials(&after, &originals).is_err(),
            "changed original bytes were accepted under an old public input pin"
        );
        std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700))?;
        ensure!(
            public_directory(root.path(), "blocked").is_err(),
            "Root private parent was incorrectly admitted as a public Source route"
        );
        Ok(())
    }
}
