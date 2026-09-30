use super::*;

use std::collections::BTreeSet;
use std::io::Read;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixListener;
use std::os::unix::net::UnixStream;
use std::sync::Arc;
use std::time::Instant;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use sha2::Digest;
use sha2::Sha256;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

fn fixture() -> Result<(tempfile::TempDir, UnixListener, UnixFinalUseTrustPort)> {
    let directory = tempfile::tempdir()?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let socket = directory.path().join("trust.sock");
    let listener = UnixListener::bind(&socket)?;
    std::fs::set_permissions(&socket, std::fs::Permissions::from_mode(0o660))?;
    let mut executable = std::fs::File::open(std::env::current_exe()?)?;
    let mut hash = Sha256::new();
    let mut buffer = [0; 64 * 1024];
    loop {
        let count = executable.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        hash.update(&buffer[..count]);
    }
    let text_digest = |path: &str| -> Result<String> {
        let mut bytes = std::fs::read(path)?;
        while bytes.last().is_some_and(u8::is_ascii_whitespace) {
            bytes.pop();
        }
        Ok(format!("{:x}", Sha256::digest(&bytes)))
    };
    let port = UnixFinalUseTrustPort {
        issuer_socket: socket,
        issuer_uid: rustix::process::geteuid().as_raw(),
        signer_id: "root-issuer".into(),
        timeout: Duration::from_secs(10),
        process_identity: Some(IssuerProcessIdentityConfig {
            executable_sha256: format!("{:x}", hash.finalize()),
            cgroup_sha256: text_digest("/proc/self/cgroup")?,
            boot_id_sha256: text_digest("/proc/sys/kernel/random/boot_id")?,
        }),
        process_attestation: None,
    };
    Ok((directory, listener, port))
}

fn response() -> Result<ModelTrustResponse> {
    let revocations = FinalUseRevocations {
        authority_epoch: 3,
        revision: 7,
        revoked_grant_ids: BTreeSet::new(),
    };
    Ok(ModelTrustResponse {
        schema_version: MODEL_ISSUER_SCHEMA_VERSION,
        frontier: FinalUseFrontier::for_initial_head(&revocations)?,
        revocations,
        now_unix_ms: 12_345,
    })
}

fn read_request(stream: &mut UnixStream) -> Result<ModelTrustRequest> {
    let mut length = [0; 4];
    stream.read_exact(&mut length)?;
    let length = u32::from_be_bytes(length) as usize;
    assert!((1..=MODEL_ISSUER_MAX_REQUEST_BYTES).contains(&length));
    let mut bytes = vec![0; length];
    stream.read_exact(&mut bytes)?;
    Ok(serde_json::from_slice(&bytes)?)
}

fn write_response(stream: &mut UnixStream, response: &ModelTrustResponse) -> Result<()> {
    let bytes = serde_json::to_vec(response)?;
    stream.write_all(&(bytes.len() as u32).to_be_bytes())?;
    stream.write_all(&bytes)?;
    Ok(())
}

#[test]
fn root_trust_clock_load_and_cas_use_the_same_exact_protocol() -> Result<()> {
    let (_directory, listener, port) = fixture()?;
    let initial = response()?;
    let mut next = initial.frontier;
    next.state_sha256 = [19; 32];
    let expected = initial.frontier;
    let server = std::thread::spawn(move || -> Result<()> {
        for index in 0..3 {
            let (mut stream, _) = listener.accept()?;
            let request = read_request(&mut stream)?;
            assert_eq!(request.schema_version, MODEL_ISSUER_SCHEMA_VERSION);
            assert_eq!(request.signer_id, "root-issuer");
            let mut result = response()?;
            if index == 2 {
                assert_eq!(request.operation, MODEL_TRUST_CAS);
                assert_eq!(request.expected, Some(expected));
                assert_eq!(request.next, Some(next));
                result.frontier = next;
            } else {
                assert_eq!(request.operation, MODEL_TRUST_LOAD);
                assert_eq!((request.expected, request.next), (None, None));
            }
            write_response(&mut stream, &result)?;
        }
        Ok(())
    });
    assert_eq!(port.now_unix_ms(), Ok(initial.now_unix_ms));
    assert_eq!(port.load("root-issuer"), Ok(expected));
    assert_eq!(
        port.compare_and_set("root-issuer", &expected, &next),
        Ok(())
    );
    assert_eq!(port.load("other-owner"), Err(AuthorityTrustError::Invalid));
    server.join().map_err(|_| "issuer thread panicked")??;
    Ok(())
}

#[test]
fn root_trust_rejects_a_cas_ack_for_a_different_frontier() -> Result<()> {
    let (_directory, listener, port) = fixture()?;
    let expected = response()?.frontier;
    let mut next = expected;
    next.state_sha256 = [21; 32];
    let server = std::thread::spawn(move || -> Result<()> {
        let (mut stream, _) = listener.accept()?;
        let request = read_request(&mut stream)?;
        assert_eq!(request.next, Some(next));
        write_response(&mut stream, &response()?)?;
        Ok(())
    });
    assert_eq!(
        port.compare_and_set("root-issuer", &expected, &next),
        Err(AuthorityTrustError::Conflict)
    );
    server.join().map_err(|_| "issuer thread panicked")??;
    Ok(())
}

#[test]
fn root_trust_rejects_oversized_or_inconsistent_frames() -> Result<()> {
    let (_directory, listener, port) = fixture()?;
    let server = std::thread::spawn(move || -> Result<()> {
        let (mut stream, _) = listener.accept()?;
        read_request(&mut stream)?;
        stream.write_all(&((MODEL_ISSUER_MAX_RESPONSE_BYTES + 1) as u32).to_be_bytes())?;
        let (mut stream, _) = listener.accept()?;
        read_request(&mut stream)?;
        let mut wrong = response()?;
        wrong.revocations.revision += 1;
        write_response(&mut stream, &wrong)?;
        Ok(())
    });
    assert_eq!(port.now_unix_ms(), Err(AuthorityTrustError::Invalid));
    assert_eq!(port.load("root-issuer"), Err(AuthorityTrustError::Invalid));
    server.join().map_err(|_| "issuer thread panicked")??;
    Ok(())
}

#[test]
fn root_trust_rejects_connected_process_identity_before_sending_a_request() -> Result<()> {
    let (_directory, listener, mut port) = fixture()?;
    port.process_identity
        .as_mut()
        .ok_or("fixture issuer identity missing")?
        .cgroup_sha256 = "1".repeat(64);
    let server = std::thread::spawn(move || -> Result<()> {
        let (mut stream, _) = listener.accept()?;
        let mut byte = [0];
        assert_eq!(stream.read(&mut byte)?, 0);
        Ok(())
    });
    assert_eq!(port.now_unix_ms(), Err(AuthorityTrustError::Invalid));
    server.join().map_err(|_| "issuer thread panicked")??;
    Ok(())
}

#[test]
fn root_trust_unknown_response_never_falls_back_to_local_time() -> Result<()> {
    let (_directory, listener, mut port) = fixture()?;
    port.timeout = Duration::from_secs(3);
    let server = std::thread::spawn(move || -> Result<()> {
        let (mut stream, _) = listener.accept()?;
        read_request(&mut stream)?;
        std::thread::sleep(Duration::from_secs(4));
        Ok(())
    });
    let started = Instant::now();
    assert_eq!(port.now_unix_ms(), Err(AuthorityTrustError::Unavailable));
    assert!(started.elapsed() < Duration::from_secs(4));
    server.join().map_err(|_| "issuer thread panicked")??;
    Ok(())
}

#[test]
fn root_trust_external_frontier_rejects_rollback_of_local_authority_state() -> Result<()> {
    let (directory, listener, port) = fixture()?;
    let snapshot = response()?;
    let expected = snapshot.frontier;
    let server = std::thread::spawn(move || -> Result<()> {
        let mut current = expected;
        let mut cas_count = 0;
        for _ in 0..7 {
            let (mut stream, _) = listener.accept()?;
            let request = read_request(&mut stream)?;
            if request.operation == MODEL_TRUST_CAS {
                assert_eq!(request.expected, Some(current));
                let next = request.next.ok_or("exact successor missing")?;
                assert_ne!(next.state_sha256, current.state_sha256);
                current = next;
                cas_count += 1;
            } else {
                assert_eq!(request.operation, MODEL_TRUST_LOAD);
            }
            let mut result = response()?;
            result.frontier = current;
            write_response(&mut stream, &result)?;
        }
        assert_eq!(cas_count, 1);
        Ok(())
    });
    let trust = Arc::new(port);
    let key = SigningKey::from_bytes(&rand::random());
    let state_dir = directory.path().join("local-state");
    let authority = FinalUseAuthority::open_state_dir_with_trust(
        &state_dir,
        "root-issuer".into(),
        key.verifying_key().to_bytes(),
        snapshot.revocations.clone(),
        trust.clone(),
        trust.clone(),
    )?;
    let initial = std::fs::read(state_dir.join("authority.json"))?;
    let initial_claims = std::fs::read(state_dir.join("authority.claims"))?;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "root-issuer".into(),
        authority_epoch: snapshot.revocations.authority_epoch,
        grant_id: "consumed-once".into(),
        nonce: [27; 32],
        binding: FinalUseBinding {
            subject_id: "enrolled-agent".into(),
            destination_id: "provider:codex-app-server".into(),
            request_sha256: [31; 32],
            scope_sha256: [32; 32],
            payload_sha256: [33; 32],
        },
        not_before_unix_ms: 1_000,
        expires_at_unix_ms: 30_000,
    };
    let signed = SignedFinalUseGrant {
        signature: key.sign(&grant.signing_bytes()?).to_bytes().to_vec(),
        grant,
    };
    drop(authority.claim(&signed, &signed.grant.binding)?);
    assert_eq!(authority.capacity()?.used_nonces, 1);
    drop(authority);
    std::fs::write(state_dir.join("authority.json"), initial)?;
    std::fs::write(state_dir.join("authority.claims"), initial_claims)?;
    assert!(matches!(
        FinalUseAuthority::open_state_dir_with_trust(
            &state_dir,
            "root-issuer".into(),
            key.verifying_key().to_bytes(),
            snapshot.revocations,
            trust.clone(),
            trust,
        ),
        Err(codex_hepta_contracts::FinalUseError::AntiRollbackViolation)
    ));
    server.join().map_err(|_| "issuer thread panicked")??;
    Ok(())
}
