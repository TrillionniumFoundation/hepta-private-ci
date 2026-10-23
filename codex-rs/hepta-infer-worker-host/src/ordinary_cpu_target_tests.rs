use super::*;
use codex_hepta_contracts::FinalUseRevocations;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use std::collections::BTreeSet;
use std::time::Duration;
use tempfile::TempDir;

fn registration(temp: &TempDir) -> OrdinaryCpuRegistration {
    let mut registration = crate::ordinary_cpu_owner::tests::registration(temp);
    #[cfg(unix)]
    {
        registration.program = std::path::PathBuf::from("/bin/sh");
        registration.arguments = vec![
            "-c".to_owned(),
            "printf ordinary-child > child-marker".to_owned(),
        ];
    }
    #[cfg(windows)]
    {
        registration.program =
            std::path::PathBuf::from(std::env::var_os("SystemRoot").expect("Windows root"))
                .join("System32/cmd.exe");
        registration.arguments = vec![
            "/D".to_owned(),
            "/C".to_owned(),
            "echo ordinary-child>child-marker".to_owned(),
        ];
    }
    registration
}

struct Fixture {
    temp: TempDir,
    authority: FinalUseAuthority,
    pool: SqlitePool,
    target: OrdinaryCpuTarget,
    request: ProductionDispatchRequest,
}

impl Fixture {
    async fn new() -> Self {
        let temp = TempDir::new().expect("private fixture");
        let authority_dir = temp.path().join("authority");
        std::fs::create_dir(&authority_dir).expect("authority directory");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&authority_dir, std::fs::Permissions::from_mode(0o700))
                .expect("private authority");
        }
        let authority = FinalUseAuthority::open_state_dir(
            &authority_dir,
            "ordinary-control-issuer".to_owned(),
            SigningKey::from_bytes(&[113; 32])
                .verifying_key()
                .to_bytes(),
            FinalUseRevocations {
                authority_epoch: 1,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )
        .expect("real FinalUse owner");
        let pool = crate::ordinary_cpu_owner::tests::pool(&temp).await;
        let registration = registration(&temp);
        let request =
            crate::ordinary_cpu_registration::tests::request(&registration, "observer-control");
        let target =
            OrdinaryCpuTarget::from_migrated_pool(registration, authority.clone(), pool.clone())
                .await
                .expect("target");
        Self {
            temp,
            authority,
            pool,
            target,
            request,
        }
    }
}

#[tokio::test]
async fn unsigned_dispatch_and_missing_entry_never_spawn_or_complete() {
    let fixture = Fixture::new().await;
    assert_eq!(
        fixture.target.dispatch(fixture.request.clone()).await,
        ProductionTargetOutcome::Rejected {
            reason: "ordinary CPU target requires the original sealed FinalUse dispatch".to_owned()
        }
    );
    let intent = fixture
        .target
        .registration
        .validate(&fixture.request)
        .expect("registered bytes");
    assert_eq!(
        fixture
            .target
            .owner
            .entry(&intent)
            .await
            .expect("owner read"),
        None
    );
    assert!(matches!(
        fixture.target.observe_terminal(&fixture.request).await,
        ProductionTerminalObservation::Indeterminate { .. }
    ));
    assert!(!fixture.temp.path().join("child-marker").exists());
    assert!(
        fixture
            .target
            .children
            .lock()
            .expect("children")
            .iter()
            .all(Option::is_none)
    );
}

#[tokio::test]
async fn original_child_observer_keeps_durability_failure_and_disk_only_recreation_unknown() {
    let fixture = Fixture::new().await;
    let intent = fixture
        .target
        .registration
        .validate(&fixture.request)
        .expect("intent");
    assert!(matches!(
        fixture
            .target
            .owner
            .enter(&intent)
            .await
            .expect("fixture admission"),
        Entry::New(0)
    ));
    sqlx::raw_sql("CREATE TRIGGER fail_terminal BEFORE UPDATE ON ordinary_cpu_entries BEGIN SELECT RAISE(ABORT, 'observer durability cut'); END;").execute(&fixture.pool).await.expect("cut");
    // This actual OS Child is an observer-component fixture, not a signed
    // source-route dispatch qualification. The production boundary stays sealed.
    let started_at = Instant::now();
    let child = Command::new(&fixture.target.registration.program)
        .args(&fixture.target.registration.arguments)
        .current_dir(&fixture.target.registration.binding.working_directory)
        .env_clear()
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .expect("actual fixed Child");
    fixture.target.children.lock().expect("children")[0] = Some(OwnedChild {
        child,
        semantic: intent.semantic_digest(),
        started_at,
        exit: None,
    });
    let observation = tokio::time::timeout(Duration::from_secs(2), async {
        loop {
            let observation = fixture.target.observe_terminal(&fixture.request).await;
            if fixture.target.children.lock().expect("children")[0]
                .as_ref()
                .expect("owned Child")
                .exit
                .is_some()
            {
                break observation;
            }
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    })
    .await
    .expect("ordinary fixed Child must exit");
    assert!(matches!(
        observation,
        ProductionTerminalObservation::Indeterminate { .. }
    ));
    assert_eq!(
        fixture
            .target
            .owner
            .entry(&intent)
            .await
            .expect("retained row"),
        Some((0, None))
    );
    sqlx::query("DROP TRIGGER fail_terminal")
        .execute(&fixture.pool)
        .await
        .expect("remove cut");
    let receipt = format!("ordinary-child-exit-v1:{}:exit0", intent.semantic_digest());
    assert_eq!(
        fixture.target.observe_terminal(&fixture.request).await,
        ProductionTerminalObservation::Applied {
            receipt: receipt.clone()
        }
    );
    #[cfg(unix)]
    let expected_marker = b"ordinary-child".as_slice();
    #[cfg(windows)]
    let expected_marker = b"ordinary-child\r\n".as_slice();
    assert_eq!(
        std::fs::read(fixture.temp.path().join("child-marker")).expect("actual cwd marker"),
        expected_marker
    );
    assert_eq!(
        fixture
            .target
            .owner
            .entry(&intent)
            .await
            .expect("terminal row"),
        Some((0, Some(receipt)))
    );
    assert!(matches!(
        fixture
            .target
            .owner
            .enter(&intent)
            .await
            .expect("retained operation"),
        Entry::Retained
    ));
    drop(fixture.target);
    let recreated = OrdinaryCpuTarget::from_migrated_pool(
        registration(&fixture.temp),
        fixture.authority,
        fixture.pool.clone(),
    )
    .await
    .expect("owner recreation without original Child");
    assert!(matches!(
        recreated.observe_terminal(&fixture.request).await,
        ProductionTerminalObservation::Indeterminate { .. }
    ));
    let counts: (i64, i64) = sqlx::query_as("SELECT (SELECT COUNT(*) FROM ordinary_cpu_entries), (SELECT COUNT(*) FROM destination_operation_dedupe)").fetch_one(&fixture.pool).await.expect("permanent slots");
    assert_eq!(counts, (1, 1));
}
