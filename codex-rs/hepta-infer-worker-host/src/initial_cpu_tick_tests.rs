use super::*;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixListener;

fn protected_transport() -> HostResult<(tempfile::TempDir, TickProvider, UnixListener)> {
    if rustix::process::geteuid().as_raw() != 0 {
        return Err("this physical transport fixture requires true Root".into());
    }
    let directory = tempfile::Builder::new()
        .prefix("hepta-fixed-input-")
        .tempdir_in("/run")?;
    let path = directory.path().join("public-config.json");
    let bytes = b"{\"physical_transport_fixture\":true}";
    std::fs::write(&path, bytes)?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o444))?;
    let source = Source {
        path,
        digest: Digest32::of_bytes(bytes).to_string(),
    };
    let socket = directory.path().join("encoder.sock");
    let listener = UnixListener::bind(&socket)?;
    std::fs::set_permissions(&socket, std::fs::Permissions::from_mode(0o660))?;
    let provider = TickProvider {
        goal_mode: GoalMode::FixedObjective,
        source: source.clone(),
        configuration: Configuration {
            schema: "hepta.cpu-neuron.fixed-pair-tick-provider.v2".into(),
            encoder_socket: socket,
            encoder_configuration: source,
            pair_id: "public-fixed-pair".into(),
            source_row_sha256: Digest32::of_bytes(b"original-public-row").to_string(),
            objective_digest: Digest32::of_bytes(b"compiled-goal").to_string(),
            runtime_body_digest: Digest32::of_bytes(b"actual-body").to_string(),
            model_generation: 1,
            normalization_digest: Digest32::of_bytes(b"original-preprocessor").to_string(),
            tokenizer_digest: Digest32::of_bytes(b"original-tokenizer").to_string(),
            timeout_ms: 200,
        },
    };
    Ok((directory, provider, listener))
}

#[test]
#[ignore = "requires true Root and protected /run fixture"]
fn fixed_physical_transport_checks_root_peer_and_rejects_mutated_source() -> HostResult<()> {
    let (_directory, provider, listener) = protected_transport()?;
    let server = std::thread::spawn(move || -> std::io::Result<()> {
        let (mut stream, _) = listener.accept()?;
        let mut request = [0_u8; 128];
        if stream.read(&mut request)? == 0 {
            return Err(std::io::Error::new(
                std::io::ErrorKind::UnexpectedEof,
                "physical request absent",
            ));
        }
        stream.write_all(b"{\"physical_transport\":true}\n")
    });
    assert_eq!(
        provider.exchange(&serde_json::json!({"original_stage":true}))?,
        serde_json::json!({"physical_transport":true})
    );
    server
        .join()
        .map_err(|_| "physical transport server panicked")??;
    std::fs::set_permissions(
        &provider.source.path,
        std::fs::Permissions::from_mode(0o644),
    )?;
    std::fs::write(&provider.source.path, b"{\"mutated\":true}")?;
    assert!(
        provider
            .exchange(&serde_json::json!({"original_stage":true}))
            .is_err()
    );
    Ok(())
}

#[test]
#[ignore = "requires true Root and protected /run fixture"]
fn fixed_physical_transport_enforces_one_total_deadline_during_slow_frames() -> HostResult<()> {
    let (_directory, mut provider, listener) = protected_transport()?;
    provider.configuration.timeout_ms = 25;
    let server = std::thread::spawn(move || -> std::io::Result<()> {
        let (mut stream, _) = listener.accept()?;
        let mut request = [0_u8; 128];
        if stream.read(&mut request)? == 0 {
            return Err(std::io::Error::new(
                std::io::ErrorKind::UnexpectedEof,
                "physical request absent",
            ));
        }
        for _ in 0..20 {
            if stream.write_all(b" ").is_err() {
                break;
            }
            std::thread::sleep(Duration::from_millis(5));
        }
        Ok(())
    });
    let started = Instant::now();
    assert!(
        provider
            .exchange(&serde_json::json!({"original_stage":true}))
            .is_err()
    );
    assert!(started.elapsed() < Duration::from_millis(100));
    server
        .join()
        .map_err(|_| "slow physical transport server panicked")??;
    Ok(())
}
