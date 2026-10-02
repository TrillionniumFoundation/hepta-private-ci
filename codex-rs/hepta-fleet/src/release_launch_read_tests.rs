use super::*;
use crate::AgentManifest;
use crate::ResourceBudget;
use crate::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

struct ReleaseFixture {
    _temporary: tempfile::TempDir,
    registry: FleetRegistry,
    release: RegisteredRelease,
    bytes: Vec<u8>,
}
impl ReleaseFixture {
    fn new() -> Result<Self, Box<dyn std::error::Error>> {
        let temporary = tempfile::tempdir()?;
        let source = temporary.path().join("source");
        let bytes: Vec<u8> = (0..70_001).map(|index| (index % 251) as u8).collect();
        std::fs::write(&source, &bytes)?;
        set_mode(&source, 0o555)?;
        let registry =
            FleetRegistry::initialize(HeptaFleetRoot::parse(temporary.path().join("fleet"))?)?;
        let release =
            registry.install_release(ReleaseId::parse("full-read")?, &source, Vec::new())?;
        Ok(Self {
            _temporary: temporary,
            registry,
            release,
            bytes,
        })
    }

    fn allow_agent(&self) -> Result<AgentId, Box<dyn std::error::Error>> {
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
        let workspace = self._temporary.path().join("workspace");
        std::fs::create_dir(&workspace)?;
        self.registry.register(AgentManifest::new(
            agent.clone(),
            WorkspaceBinding::new(&workspace, self.registry.layout().fleet_root())?,
            ResourceBudget::local_default(),
        )?)?;
        self.registry
            .allow_release(&agent, &self.release.release_id)?;
        Ok(agent)
    }
}

#[test]
fn prevalidation_and_physical_launch_each_read_all_bytes_without_cross_request_cache()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = ReleaseFixture::new()?;
    crate::registry::take_program_read_bytes();
    let pin = fixture
        .registry
        .prevalidate_release_for_launch(&fixture.release.release_id)?;
    assert_eq!(
        crate::registry::take_program_read_bytes(),
        fixture.bytes.len() as u64
    );
    let mut prefix = fixture
        .registry
        .launch_digest_prefix(&fixture.release.program, LaunchDigestDomain::Agent)?;
    assert_eq!(
        crate::registry::take_program_read_bytes(),
        fixture.bytes.len() as u64
    );
    let context = b"actual runtime context";
    prefix.update(context);
    let mut original = Sha256::new();
    original.update(&fixture.bytes);
    original.update(context);
    let expected: [u8; 32] = original.finalize().into();
    assert_eq!(prefix.finalize()?, expected);
    drop(pin);
    // Another request has no authority to reuse this ordinary program's bytes.
    fixture
        .registry
        .launch_digest_prefix(&fixture.release.program, LaunchDigestDomain::Agent)?
        .finalize()?;
    assert_eq!(
        crate::registry::take_program_read_bytes(),
        fixture.bytes.len() as u64
    );
    Ok(())
}

#[test]
fn ordinary_launch_rejects_changed_bytes_after_independent_prevalidation()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = ReleaseFixture::new()?;
    let _pin = fixture
        .registry
        .prevalidate_release_for_launch(&fixture.release.release_id)?;
    set_mode(&fixture.release.program, 0o755)?;
    std::fs::write(&fixture.release.program, vec![b'x'; fixture.bytes.len()])?;
    set_mode(&fixture.release.program, 0o555)?;
    assert!(
        fixture
            .registry
            .launch_digest_prefix(&fixture.release.program, LaunchDigestDomain::Agent)
            .is_err()
    );
    Ok(())
}

#[test]
fn owning_launch_fd_rejects_replaced_file_before_context_commit_and_wrong_role()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = ReleaseFixture::new()?;
    assert!(
        fixture
            .registry
            .launch_digest_prefix(&fixture.release.program, LaunchDigestDomain::Matrix)
            .is_err()
    );
    let prefix = fixture
        .registry
        .launch_digest_prefix(&fixture.release.program, LaunchDigestDomain::Agent)?;
    let replacement = fixture._temporary.path().join("replacement");
    std::fs::write(&replacement, &fixture.bytes)?;
    set_mode(&replacement, 0o555)?;
    let directory = fixture
        .release
        .program
        .parent()
        .ok_or("installed bin directory")?;
    set_mode(directory, 0o755)?;
    std::fs::rename(&replacement, &fixture.release.program)?;
    set_mode(directory, 0o555)?;
    assert!(prefix.commit().is_err());
    Ok(())
}

#[test]
fn intermediate_descriptor_uses_owning_read_and_final_resolve_independently_reads_all_bytes()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = ReleaseFixture::new()?;
    let agent = fixture.allow_agent()?;
    crate::registry::take_program_read_bytes();
    let pin = fixture
        .registry
        .prevalidate_release_for_launch(&fixture.release.release_id)?;
    assert_eq!(
        crate::registry::take_program_read_bytes(),
        fixture.bytes.len() as u64
    );
    let descriptor = fixture.registry.resolve_release_descriptor_from_read_pin(
        &agent,
        &fixture.release.release_id,
        &pin,
    )?;
    assert_eq!(descriptor.program, fixture.release.program);
    assert_eq!(
        crate::registry::take_program_read_bytes(),
        0,
        "same-request descriptor is not another byte read"
    );
    fixture
        .registry
        .resolve_release(&agent, &fixture.release.release_id)?;
    assert_eq!(
        crate::registry::take_program_read_bytes(),
        fixture.bytes.len() as u64,
        "physical admission still independently reads all bytes"
    );
    drop(pin);
    fixture
        .registry
        .prevalidate_release_for_launch(&fixture.release.release_id)?;
    assert_eq!(
        crate::registry::take_program_read_bytes(),
        fixture.bytes.len() as u64,
        "another request cannot reuse mutable program bytes"
    );
    Ok(())
}

#[test]
fn descriptor_pin_does_not_authorize_revocation_or_another_release()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = ReleaseFixture::new()?;
    let agent = fixture.allow_agent()?;
    let pin = fixture
        .registry
        .prevalidate_release_for_launch(&fixture.release.release_id)?;
    let another = fixture.registry.install_release(
        ReleaseId::parse("another")?,
        &fixture._temporary.path().join("source"),
        Vec::new(),
    )?;
    fixture
        .registry
        .allow_release(&agent, &another.release_id)?;
    assert!(
        fixture
            .registry
            .resolve_release_descriptor_from_read_pin(&agent, &another.release_id, &pin)
            .is_err()
    );
    fixture
        .registry
        .revoke_release(&agent, &fixture.release.release_id)?;
    assert!(matches!(
        fixture.registry.resolve_release_descriptor_from_read_pin(
            &agent,
            &fixture.release.release_id,
            &pin
        ),
        Err(FleetRegistryError::ReleaseRevoked { .. })
    ));
    Ok(())
}

#[test]
fn descriptor_pin_rejects_same_length_mutation_and_changed_parent_namespace()
-> Result<(), Box<dyn std::error::Error>> {
    use std::os::unix::fs::PermissionsExt;
    let fixture = ReleaseFixture::new()?;
    let agent = fixture.allow_agent()?;
    let pin = fixture
        .registry
        .prevalidate_release_for_launch(&fixture.release.release_id)?;
    let root = fixture.registry.layout().fleet_root().as_path();
    let mode = std::fs::metadata(root)?.permissions().mode();
    set_mode(root, (mode & 0o777) ^ 0o010)?;
    assert!(
        fixture
            .registry
            .resolve_release_descriptor_from_read_pin(&agent, &fixture.release.release_id, &pin)
            .is_err()
    );
    set_mode(root, mode & 0o777)?;
    let pin = fixture
        .registry
        .prevalidate_release_for_launch(&fixture.release.release_id)?;
    set_mode(&fixture.release.program, 0o755)?;
    std::fs::write(&fixture.release.program, vec![b'x'; fixture.bytes.len()])?;
    set_mode(&fixture.release.program, 0o555)?;
    assert!(
        fixture
            .registry
            .resolve_release_descriptor_from_read_pin(&agent, &fixture.release.release_id, &pin)
            .is_err()
    );
    assert!(
        fixture
            .registry
            .resolve_release(&agent, &fixture.release.release_id)
            .is_err()
    );
    Ok(())
}

#[test]
fn descriptor_pin_rejects_replaced_program_or_manifest_with_identical_bytes()
-> Result<(), Box<dyn std::error::Error>> {
    for replace_manifest in [false, true] {
        let fixture = ReleaseFixture::new()?;
        let agent = fixture.allow_agent()?;
        let pin = fixture
            .registry
            .prevalidate_release_for_launch(&fixture.release.release_id)?;
        let target = if replace_manifest {
            release_manifest_path(
                fixture.registry.layout().releases_root(),
                &fixture.release.release_id,
            )
        } else {
            fixture.release.program.clone()
        };
        let replacement = fixture._temporary.path().join("replacement");
        std::fs::copy(&target, &replacement)?;
        let parent = target.parent().ok_or("installed parent")?;
        set_mode(parent, 0o755)?;
        std::fs::rename(replacement, &target)?;
        set_mode(parent, 0o555)?;
        assert!(
            fixture
                .registry
                .resolve_release_descriptor_from_read_pin(&agent, &fixture.release.release_id, &pin)
                .is_err(),
            "an identical-byte inode substitution is a different plan"
        );
    }
    Ok(())
}
