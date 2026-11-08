//! Source drift through the real owner and native transport contact boundary.

use super::*;
use codex_hepta_automation::AuthorizedProviderEffectLookup;

const HELPER: &str = "qualification/hcsn/helper.py";
const ORIGINAL: &[u8] = b"value = 1\n";

async fn signed_helper_fixture() -> anyhow::Result<(PqFixture, PathBuf)> {
    let mut fixture = PqFixture::new().await?;
    let repository = fixture.config["deployment"]["repository_root"]
        .as_str()
        .ok_or_else(|| anyhow::anyhow!("repository path"))?;
    let helper = Path::new(repository).join(HELPER);
    fs::write(&helper, ORIGINAL)?;
    fixture.config["deployment"]["source_manifest"][HELPER] =
        serde_json::json!(Sha256Digest::for_bytes(ORIGINAL));
    fixture.sign_deployment()?;
    Ok((fixture, helper))
}

#[tokio::test]
async fn source_drift_refuses_host_open_before_external_trust_or_nonce_state() -> anyhow::Result<()>
{
    for fault in ["changed", "missing", "extra", "symlink"] {
        let (fixture, helper) = signed_helper_fixture().await?;
        let supervisor = fs::read(&fixture.script)?;
        match fault {
            "changed" => fs::write(&helper, b"value = 2\n")?,
            "missing" => fs::remove_file(&helper)?,
            "extra" => fs::write(helper.with_file_name("extra.py"), b"")?,
            "symlink" => {
                let alias = fixture.root.path().join("same-helper.py");
                fs::rename(&helper, &alias)?;
                std::os::unix::fs::symlink(&alias, &helper)?;
            }
            _ => anyhow::bail!("unknown source fault"),
        }
        assert!(
            AgentdAutomationEffectHost::open(&fixture.agent.identity, &fixture.config_path)
                .is_err(),
            "accepted {fault}"
        );
        assert_eq!(fixture.trust_requests(), 0);
        assert!(
            !fixture
                .agent
                .identity
                .layout
                .automation_root()
                .join("final-use-authority")
                .exists()
        );
        assert!(!fixture.marker.exists());
        assert_eq!(fs::read(&fixture.script)?, supervisor);
        fixture.agent.store.close().await;
    }
    Ok(())
}

#[tokio::test]
async fn source_drift_after_claim_blocks_native_dispatch_and_status_contact() -> anyhow::Result<()>
{
    let (fixture, helper) = signed_helper_fixture().await?;
    let host = AgentdAutomationEffectHost::open(&fixture.agent.identity, &fixture.config_path)?;
    let (intent, fence) = fixture.prepare().await?;
    let grant = fixture.grant(&intent)?;
    let gate = host
        .pq_gate
        .as_ref()
        .ok_or_else(|| anyhow::anyhow!("PQ gate"))?;
    let lease = gate.authenticate(&host.authority, &fixture.feed_path, &grant)?;
    let EffectProvider::Hcsn(provider) = &host.adapter else {
        anyhow::bail!("HCSN provider");
    };
    let inner = provider.driver_with_lease(
        &intent.operation_id,
        lease,
        Arc::clone(gate),
        host.authority.clone(),
        fixture.feed_path.clone(),
        grant.clone(),
    )?;
    let changed = helper.clone();
    let mut driver = ChangeAfterEntry {
        inner,
        change: Box::new(move || {
            fs::write(&changed, b"value = 2\n").expect("mutate signed helper after entry")
        }),
        entered: false,
    };
    let result = fixture
        .agent
        .store
        .execute_authorized_taskflow_effect(
            &host.authority,
            &mut driver,
            &intent,
            WIRE,
            &fence,
            &grant,
            &intent.final_use_binding()?,
            COMMAND,
            NOW,
        )
        .await;
    assert!(
        driver.entered,
        "must mutate inside the admitted token callback"
    );
    assert!(matches!(
        result,
        Err(AuthorizedEffectError::Driver(
            AuthorizedEffectDriverError::BeforeProviderContact
        ))
    ));
    assert!(!fixture.marker.exists());
    assert_eq!(host.authority.capacity()?.used_nonces, 1);
    assert_eq!(
        fs::read_dir(&provider.requests_root)?.count(),
        1,
        "must reach retained native dispatch"
    );
    let pending = fixture
        .agent
        .store
        .authorized_taskflow_effect_attempt(&intent.run_id, &intent.step_id, intent.attempt)
        .await?
        .ok_or_else(|| anyhow::anyhow!("durable attempt"))?;
    // Isolate the source pin from the additional authority guard. Even a
    // permissive caller guard cannot bypass this provider's source check.
    assert_eq!(
        provider.lookup(&pending, || Ok(())),
        AuthorizedProviderEffectLookup::Unresolved
    );
    assert!(!fixture.marker.exists());
    fs::write(&helper, ORIGINAL)?;
    assert!(matches!(
        provider.lookup(&pending, || Ok(())),
        AuthorizedProviderEffectLookup::Observed(_)
    ));
    let contact: HcsnSupervisorCommandV1 = serde_json::from_slice(&fs::read(&fixture.marker)?)?;
    let expected = HcsnSupervisorCommandV1::start(
        HcsnJobIdentityV1::for_taskflow(
            SCOPE,
            &intent.run_id,
            &intent.step_id,
            intent.payload_digest.clone(),
        )?,
        String::from_utf8(WIRE.to_vec())?,
    )?
    .status();
    assert_eq!(contact, expected);
    assert_eq!(
        host.authority.capacity()?.used_nonces,
        1,
        "status lookup consumes no new grant"
    );
    fixture.agent.store.close().await;
    Ok(())
}
