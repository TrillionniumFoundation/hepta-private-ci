//! Inspect unmodified public fixture signatures, never production credentials.

use super::*;
use crate::windows_signature_trace;
use codex_utils_path::RetainedPrivateDirectory;
use serde_json::Value;
use serde_json::json;
use std::fs::File;
use std::process::Output;
use std::process::Stdio;

const STATEMENT: &[u8] = b"canonical operator acceptance statement";

fn raw_bytes(bytes: &[u8]) -> Value {
    assert!(bytes.len() <= 16 * 1024, "bounded public fixture bytes");
    json!({
        "bytes": bytes.len(),
        "sha256": sha256(bytes),
        "public_fixture_bytes_base64": STANDARD.encode(bytes),
        "cr_bytes": bytes.iter().filter(|byte| **byte == b'\r').count(),
        "lf_bytes": bytes.iter().filter(|byte| **byte == b'\n').count(),
        "crlf_pairs": bytes.windows(2).filter(|pair| *pair == b"\r\n").count(),
        "exact_lf_header": bytes.starts_with(b"-----BEGIN SSH SIGNATURE-----\n"),
        "exact_lf_footer": bytes.ends_with(b"-----END SSH SIGNATURE-----\n"),
    })
}

fn output_facts(output: &Output) -> Value {
    json!({"success": output.status.success(), "exit_code": output.status.code(),
        "stdout": raw_bytes(&output.stdout), "stderr": raw_bytes(&output.stderr)})
}

fn signature_facts(fixture: &TrustFixture, path: &Path) -> Value {
    let before = windows_signature_trace::inspect(path);
    let read = std::fs::read(path);
    let observations = match read {
        Ok(bytes) => {
            let allowed = std::fs::read(&fixture.allowed_signers).expect("own public signer line");
            let strict = crate::sshsig_strict::verify_ed25519_sshsig(
                STATEMENT,
                &bytes,
                &allowed,
                "operator@example",
                SSHSIG_NAMESPACE,
            );
            let original = fixture.load_anchor().verify(STATEMENT, path);
            json!({"read_ok": true, "raw": raw_bytes(&bytes),
                "strict_rust": {"ok": strict.is_ok(), "result": format!("{strict:?}")},
                "original_production_verify": {"ok": original.is_ok(),
                    "result": format!("{:?}", original.as_ref().map(|value| &value.detached_signature_sha256))}})
        }
        Err(error) => json!({"read_ok": false, "raw_win32_error": error.raw_os_error(),
            "kind": format!("{:?}", error.kind()), "error": error.to_string()}),
    };
    json!({"before_read": before, "observations": observations,
        "after_read": windows_signature_trace::inspect(path)})
}

#[test]
#[ignore = "native public-fixture capability diagnostic; never a functional qualification"]
fn records_unmodified_openssh_stream_and_private_file_output() {
    let fixture = TrustFixture::new();
    let executable = openssh_keygen();
    let exe_before = windows_signature_trace::inspect(executable);
    let directory = RetainedPrivateDirectory::open_existing(&fixture.root)
        .expect("retain original exclusively created fixture directory");
    let mut modes = Vec::new();
    for mode in [
        "stdin_stdout",
        "filename_new",
        "filename_precreated_private",
    ] {
        let name = format!("probe-{mode}");
        let statement_path = fixture.root.join(&name);
        directory
            .write_new_child(statement_path.file_name().unwrap(), STATEMENT)
            .expect("create original statement through canonical backend");
        let signature_path = fixture.root.join(format!("{name}.sig"));
        let before = if mode == "filename_precreated_private" {
            directory
                .write_new_child(signature_path.file_name().unwrap(), b"")
                .expect("create absent private empty signature; never repair output ACL");
            windows_signature_trace::inspect(&signature_path)
        } else {
            json!({"absent": !signature_path.exists()})
        };
        let mut signer = Command::new(executable);
        signer.args(["-Y", "sign", "-f"]).arg(&fixture.key).args([
            "-n",
            SSHSIG_NAMESPACE,
            "-O",
            "hashalg=sha512",
        ]);
        if mode == "stdin_stdout" {
            signer.stdin(Stdio::from(File::open(&statement_path).unwrap()));
        } else {
            signer.arg(&statement_path);
            if mode == "filename_precreated_private" {
                let confirmation = fixture.root.join("own-overwrite-confirmation");
                directory
                    .write_new_child(confirmation.file_name().unwrap(), b"y\n")
                    .expect("own fixture confirmation only");
                signer.stdin(Stdio::from(File::open(confirmation).unwrap()));
            } else {
                signer.stdin(Stdio::null());
            }
        }
        let output = signer
            .output()
            .expect("run original installed OpenSSH signer");
        if mode == "stdin_stdout" && output.stdout.len() <= 16 * 1024 {
            directory
                .write_new_child(signature_path.file_name().unwrap(), &output.stdout)
                .expect("preserve exact original stdout bytes; no normalization");
        }
        modes.push(json!({"mode": mode, "signature_before_sign": before,
            "original_process": output_facts(&output),
            "signature_after_sign": signature_facts(&fixture, &signature_path),
            "statement_after": raw_bytes(&std::fs::read(&statement_path).unwrap())}));
    }
    windows_signature_trace::save(
        "openssh-native-contract.json",
        json!({
            "schema": "hepta.windows-openssh-native-contract-probe.v1",
            "diagnostic_only": true, "functional_qualification": false,
            "production_authority_granted": false,
            "public_fixture_statement": raw_bytes(STATEMENT),
            "namespace": SSHSIG_NAMESPACE, "fixture_signer": executable,
            "fixture_signer_before": exe_before,
            "fixture_signer_after": windows_signature_trace::inspect(executable),
            "effective_token": windows_signature_trace::effective_token(),
            "modes": modes
        }),
    )
    .expect("save unmodified public-fixture observations");
}
