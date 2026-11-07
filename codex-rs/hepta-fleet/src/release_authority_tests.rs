use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;

use codex_hepta_contracts::AgentId;
use codex_hepta_paths::HeptaFleetRoot;

use crate::AgentManifest;
use crate::FleetRegistry;
use crate::FleetRegistryError;
use crate::PqReleaseQualification;
use crate::QualificationResult;
use crate::ReleaseId;
use crate::ResourceBudget;
use crate::WorkspaceBinding;
use crate::release_authority_set::record_bytes;
use crate::release_qualification_trust::NOW;

pub(crate) struct Fixture {
    pub _temp: tempfile::TempDir,
    pub root: HeptaFleetRoot,
    pub publisher: PqReleaseQualification,
    pub registry: FleetRegistry,
    pub agent: AgentId,
    pub source: PathBuf,
}

impl Fixture {
    pub fn new() -> QualificationResult<Self> {
        let temp = tempfile::Builder::new()
            .prefix("hpq-release-")
            .tempdir_in("/tmp")?;
        let base = temp.path().canonicalize()?;
        let root = HeptaFleetRoot::parse(base.join("fleet"))?;
        let (publisher, registry) =
            PqReleaseQualification::initialize(&base.join("external"), root.clone())?;
        let workspace = base.join("workspace");
        std::fs::create_dir(&workspace)?;
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
        registry.register(AgentManifest::new(
            agent.clone(),
            WorkspaceBinding::new(workspace, &root)?,
            ResourceBudget::local_default(),
        )?)?;
        let source = base.join("agentd-source");
        std::fs::write(&source, b"#!/bin/sh\nexit 0\n")?;
        std::fs::set_permissions(&source, std::fs::Permissions::from_mode(0o755))?;
        Ok(Self {
            _temp: temp,
            root,
            publisher,
            registry,
            agent,
            source,
        })
    }

    pub fn install(&mut self, name: &str) -> QualificationResult<ReleaseId> {
        let id = ReleaseId::parse(name)?;
        self.publisher.install_release(
            &self.registry,
            id.clone(),
            &self.source,
            vec!["--fixture".into()],
        )?;
        Ok(id)
    }

    pub fn allow(&self, id: &ReleaseId) -> QualificationResult<()> {
        Ok(self.registry.allow_release(&self.agent, id)?)
    }

    pub fn journal(&self) -> PathBuf {
        self.registry
            .layout()
            .state_root()
            .join("pq-release-authority-v1/journal.v1.json")
    }
}

#[test]
fn ordinary_registry_requires_configured_pq_publisher_and_roundtrips_real_signed_set()
-> QualificationResult<()> {
    let mut fixture = Fixture::new()?;
    let unconfigured = FleetRegistry::open_existing(fixture.root.clone())?;
    let id = ReleaseId::parse("unpublished")?;
    assert!(matches!(
        unconfigured.install_release(id.clone(), &fixture.source, Vec::new()),
        Err(FleetRegistryError::ReleaseAuthorityRequired)
    ));
    assert!(
        !fixture
            .registry
            .layout()
            .releases_root()
            .join(id.as_str())
            .exists()
    );
    let id = fixture.install("signed-v1")?;
    assert!(matches!(
        fixture.registry.resolve_release(&fixture.agent, &id),
        Err(FleetRegistryError::ReleaseNotAllowed { .. })
    ));
    fixture.allow(&id)?;
    let release = fixture.registry.resolve_release(&fixture.agent, &id)?;
    let reopened = FleetRegistry::open_existing_with_release_authority(
        fixture.root.clone(),
        fixture.publisher.config(),
    )?;
    assert_eq!(reopened.resolve_release(&fixture.agent, &id)?, release);
    assert_eq!(
        crate::FleetReleaseTrustConfig::read(fixture.publisher.config_path())?.initial_root_sha256,
        fixture.publisher.config().initial_root_sha256
    );
    assert!(matches!(
        unconfigured.resolve_release(&fixture.agent, &id),
        Err(FleetRegistryError::ReleaseAuthorityRequired)
    ));
    Ok(())
}

#[test]
fn ordinary_signed_set_rejects_missing_quorum_and_manifest_substitution_before_cas()
-> QualificationResult<()> {
    let mut fixture = Fixture::new()?;
    let id = fixture.install("signed-v1")?;
    fixture.allow(&id)?;
    let before = (
        fixture.publisher.frontier()?,
        fixture.publisher.cas_attempts(),
        std::fs::read(fixture.journal())?,
    );
    let signed = fixture
        .publisher
        .signed_members(fixture.publisher.members.clone(), NOW + 3600)?;
    let mut one_signer = signed.clone();
    one_signer.signatures.pop();
    assert!(
        fixture
            .registry
            .publish_release_set(&record_bytes(&one_signer)?)
            .is_err()
    );
    let mut substituted = signed.clone();
    substituted.release_set.members[0]
        .release
        .agentd
        .args
        .push("--unapproved".into());
    assert!(
        fixture
            .registry
            .publish_release_set(&record_bytes(&substituted)?)
            .is_err()
    );
    let mut missing_package = signed;
    missing_package.release_set.members[0]
        .build_record
        .sbom_packages
        .clear();
    assert!(
        fixture
            .registry
            .publish_release_set(&record_bytes(&missing_package)?)
            .is_err()
    );
    assert_eq!(
        (
            fixture.publisher.frontier()?,
            fixture.publisher.cas_attempts(),
            std::fs::read(fixture.journal())?
        ),
        before
    );
    assert!(
        fixture
            .registry
            .resolve_release(&fixture.agent, &id)
            .is_ok()
    );
    Ok(())
}

#[test]
fn current_signed_set_supports_rolling_restarts_and_withdrawal_denies_old_local_allow()
-> QualificationResult<()> {
    let mut fixture = Fixture::new()?;
    let first = fixture.install("signed-v1")?;
    fixture.allow(&first)?;
    let old = fixture.registry.resolve_release(&fixture.agent, &first)?;
    let second = fixture.install("signed-v2")?;
    fixture.allow(&second)?;
    assert_eq!(
        fixture.registry.resolve_release(&fixture.agent, &first)?,
        old
    );
    fixture.publisher.publish_member_ids(
        &fixture.registry,
        std::slice::from_ref(&second),
        NOW + 3600,
    )?;
    assert!(matches!(
        fixture.registry.admit_release(&fixture.agent, &first),
        Err(FleetRegistryError::ReleaseNotAllowed { .. })
    ));
    assert_eq!(
        fixture.registry.allowed_releases(&fixture.agent)?,
        vec![second.clone()]
    );
    let reopened = FleetRegistry::open_existing_with_release_authority(
        fixture.root.clone(),
        fixture.publisher.config(),
    )?;
    assert!(matches!(
        reopened.resolve_release(&fixture.agent, &first),
        Err(FleetRegistryError::ReleaseNotAllowed { .. })
    ));
    assert!(reopened.resolve_release(&fixture.agent, &second).is_ok());
    Ok(())
}

#[test]
fn ordinary_installer_rejects_actual_binary_and_argument_substitution_before_catalog_publish()
-> QualificationResult<()> {
    let fixture = Fixture::new()?;
    let id = ReleaseId::parse("exact-published-program")?;
    let original = std::fs::read(&fixture.source)?;
    let member = crate::release_qualification_bundle::member(
        id.clone(),
        &fixture.source,
        Vec::new(),
        /*matrixd*/ None,
        Vec::new(),
    )?;
    let signed = fixture.publisher.signed_members(vec![member], NOW + 3600)?;
    fixture
        .registry
        .publish_release_set(&record_bytes(&signed)?)?;
    let before = (
        fixture.publisher.frontier()?,
        fixture.publisher.cas_attempts(),
    );
    let catalog = fixture.registry.layout().releases_root().join(id.as_str());
    let arguments =
        fixture
            .registry
            .install_release(id.clone(), &fixture.source, vec!["--unpublished".into()]);
    assert!(matches!(arguments, Err(FleetRegistryError::Invalid(_))));
    assert!(!catalog.exists());
    std::fs::write(&fixture.source, b"#!/bin/sh\nexit 19\n")?;
    let binary = fixture
        .registry
        .install_release(id.clone(), &fixture.source, Vec::new());
    assert!(matches!(binary, Err(FleetRegistryError::Invalid(_))));
    assert!(!catalog.exists());
    assert_eq!(
        (
            fixture.publisher.frontier()?,
            fixture.publisher.cas_attempts()
        ),
        before
    );
    std::fs::write(&fixture.source, original)?;
    fixture
        .registry
        .install_release(id.clone(), &fixture.source, Vec::new())?;
    fixture.registry.allow_release(&fixture.agent, &id)?;
    assert!(
        fixture
            .registry
            .resolve_release(&fixture.agent, &id)
            .is_ok()
    );
    Ok(())
}

#[test]
fn dispatch_rechecks_trusted_clock_after_resolve_and_held_lock_does_not_extend_expiry()
-> QualificationResult<()> {
    let mut fixture = Fixture::new()?;
    let id = fixture.install("signed-v1")?;
    fixture.allow(&id)?;
    let admission = fixture.registry.admit_release(&fixture.agent, &id)?;
    admission.revalidate()?;
    let before = fixture.publisher.frontier()?;
    fixture.publisher.advance_clock_to(NOW + 3600);
    assert!(admission.revalidate().is_err());
    drop(admission);
    assert!(
        fixture
            .registry
            .resolve_release(&fixture.agent, &id)
            .is_err()
    );
    assert_eq!(fixture.publisher.frontier()?, before);
    Ok(())
}

#[test]
fn root_rotation_requires_current_generation_publication_after_cold_reopen()
-> QualificationResult<()> {
    let mut fixture = Fixture::new()?;
    let id = fixture.install("signed-v1")?;
    fixture.allow(&id)?;
    let release = fixture.registry.resolve_release(&fixture.agent, &id)?;
    fixture.publisher.rotate_publisher_root(&fixture.registry)?;
    let reopened = FleetRegistry::open_existing_with_release_authority(
        fixture.root.clone(),
        fixture.publisher.config(),
    )?;
    assert!(reopened.resolve_release(&fixture.agent, &id).is_err());
    fixture.publisher.publish_member_ids(
        &fixture.registry,
        std::slice::from_ref(&id),
        NOW + 3600,
    )?;
    assert_eq!(reopened.resolve_release(&fixture.agent, &id)?, release);
    Ok(())
}

#[test]
fn protocol_policy_uses_its_distinct_current_role_and_same_durable_owner() -> QualificationResult<()>
{
    use sha2::Digest;
    let mut fixture = Fixture::new()?;
    let id = fixture.install("signed-v1")?;
    fixture.allow(&id)?;
    let policy = b"explicit-qualification-policy-bytes";
    let digest: [u8; 32] = sha2::Sha256::digest(policy).into();
    assert!(
        fixture
            .registry
            .admit_protocol_configuration(digest)
            .is_err()
    );
    fixture
        .publisher
        .publish_protocol_configuration(&fixture.registry, policy, NOW + 60)?;
    assert!(
        fixture
            .registry
            .resolve_release(&fixture.agent, &id)
            .is_ok()
    );
    let release = fixture.registry.admit_release(&fixture.agent, &id)?;
    assert_eq!(
        release.revalidate_with_protocol_configuration(digest)?,
        NOW * 1000
    );
    assert!(
        release
            .revalidate_with_protocol_configuration([9; 32])
            .is_err()
    );
    drop(release);
    assert!(
        fixture
            .registry
            .admit_protocol_configuration([9; 32])
            .is_err()
    );
    let reopened = FleetRegistry::open_existing_with_release_authority(
        fixture.root.clone(),
        fixture.publisher.config(),
    )?;
    let guard = reopened.admit_protocol_configuration(digest)?;
    assert_eq!(guard.revalidate()?, NOW * 1000);
    fixture.publisher.advance_clock_to(NOW + 60);
    assert!(guard.revalidate().is_err());
    drop(guard);
    assert!(reopened.admit_protocol_configuration(digest).is_err());
    assert!(reopened.resolve_release(&fixture.agent, &id).is_ok());
    let unconfigured = FleetRegistry::open_existing(fixture.root.clone())?;
    assert!(matches!(
        unconfigured.admit_protocol_configuration(digest),
        Err(FleetRegistryError::ReleaseAuthorityRequired)
    ));
    Ok(())
}
