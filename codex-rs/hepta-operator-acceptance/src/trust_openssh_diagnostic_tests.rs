//! Explicitly selected diagnostics, separate from the original trust assertions.

use std::error::Error;
use std::ffi::OsStr;
use std::ffi::OsString;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::os::windows::ffi::OsStrExt as _;
use std::os::windows::ffi::OsStringExt as _;
use std::os::windows::fs::FileExt as _;
use std::os::windows::fs::OpenOptionsExt as _;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;
use std::path::Prefix;
use std::process::Command;
use std::process::Output;
use std::process::Stdio;

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use sha2::Digest as _;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_DIRECTORY;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::GetFileVersionInfoSizeW;
use windows_sys::Win32::Storage::FileSystem::GetFileVersionInfoW;
use windows_sys::Win32::Storage::FileSystem::VS_FFI_SIGNATURE;
use windows_sys::Win32::Storage::FileSystem::VS_FIXEDFILEINFO;
use windows_sys::Win32::Storage::FileSystem::VerQueryValueW;
use windows_sys::Win32::System::SystemInformation::GetSystemDirectoryW;

use super::SSHSIG_NAMESPACE;
use super::TRUST_POLICY_SCHEMA;
use super::TRUST_POLICY_SCOPE;
use super::TrustAnchor;
use super::TrustInputs;
use super::TrustPolicy;
use crate::durable::canonical_json;
use crate::durable::sha256;
use crate::durable::write_private_new;
use crate::test_support::openssh_command;
use crate::test_support::openssh_keygen;
use crate::test_support::private_generated_signature;
use crate::test_support::private_tempdir;

#[derive(Clone, Copy, Debug)]
enum ProgramDataMode {
    Absent,
    OsBound,
}

#[derive(Clone, Copy, Debug)]
enum KeyPathForm {
    Extended,
    PlainDriveAbsolute,
}

fn child_command(mode: ProgramDataMode, os_program_data: &OsStr) -> Command {
    // Deliberately use the original resolver, not openssh_command: the latter
    // would supply ProgramData before the absent arm is constructed.
    let mut command = Command::new(openssh_keygen());
    match mode {
        ProgramDataMode::Absent => command.env_remove("ProgramData"),
        ProgramDataMode::OsBound => command.env("ProgramData", os_program_data),
    };
    command
}

fn capture(cell: &str, stage: &str, command: &mut Command) -> io::Result<Output> {
    let argv = std::iter::once(command.get_program())
        .chain(command.get_args())
        .map(|argument| argument.to_string_lossy().into_owned())
        .collect::<Vec<_>>();
    eprintln!(
        "HEPTA_OPENSSH_MATRIX {}",
        json!({"cell": cell, "stage": stage, "event": "before_spawn", "argv": argv})
    );
    let output = command.output()?;
    // These commands never print or export a private key. Preserve exact bytes
    // of bounded public diagnostics, not just a lossy stderr interpretation.
    eprintln!(
        "HEPTA_OPENSSH_MATRIX {}",
        json!({
            "cell": cell, "stage": stage, "event": "terminal",
            "exit_code": output.status.code(), "success": output.status.success(),
            "stdout_bytes": output.stdout.len(), "stderr_bytes": output.stderr.len(),
            "stdout_sha256": sha256(&output.stdout), "stderr_sha256": sha256(&output.stderr),
        })
    );
    if output.stdout.len() > 64 * 1024 || output.stderr.len() > 64 * 1024 {
        return Err(io::Error::other(
            "diagnostic output exceeds its evidence bound",
        ));
    }
    eprintln!(
        "HEPTA_OPENSSH_MATRIX {}",
        json!({
            "cell": cell, "stage": stage, "event": "output",
            "stdout_base64": STANDARD.encode(&output.stdout),
            "stderr_base64": STANDARD.encode(&output.stderr),
        })
    );
    Ok(output)
}

fn file_id(file: &File) -> io::Result<[u64; 2]> {
    let information = winapi_util::file::information(file)?;
    Ok([information.volume_serial_number(), information.file_index()])
}

fn describe_executable(file: &File) -> io::Result<Value> {
    let current_path = OpenOptions::new()
        .read(true)
        .share_mode(FILE_SHARE_READ)
        .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT)
        .open(openssh_keygen())?;
    if file_id(&current_path)? != file_id(file)? {
        return Err(io::Error::other(
            "OS signer path no longer names the pinned file",
        ));
    }
    let information = winapi_util::file::information(file)?;
    let size = information.file_size();
    if !(2..=64 * 1024 * 1024).contains(&size)
        || information.file_attributes()
            & u64::from(FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)
            != 0
    {
        return Err(io::Error::other(
            "OS signer is not a bounded regular executable",
        ));
    }
    let mut digest = sha2::Sha256::new();
    let mut offset = 0;
    let mut buffer = [0_u8; 64 * 1024];
    while offset < size {
        let length = (size - offset).min(buffer.len() as u64) as usize;
        let count = file.seek_read(&mut buffer[..length], offset)?;
        if count == 0 || (offset == 0 && !buffer[..count].starts_with(b"MZ")) {
            return Err(io::Error::other(
                "OS signer ended early or lacks its PE header",
            ));
        }
        digest.update(&buffer[..count]);
        offset += count as u64;
    }
    Ok(json!({
        "file_id": file_id(file)?, "bytes": size, "links": information.number_of_links(),
        "attributes": information.file_attributes(),
        "last_write_time": format!("{:?}", information.last_write_time()),
        "sha256": format!("{:x}", digest.finalize()),
    }))
}

fn verify_generated_key(
    cell: &str,
    root: &Path,
    key: &Path,
    mode: ProgramDataMode,
    os_program_data: &OsStr,
) -> Result<Value, Box<dyn Error>> {
    let public = std::fs::read_to_string(key.with_extension("pub"))?;
    let fields = public.split_ascii_whitespace().collect::<Vec<_>>();
    if fields.first().copied() != Some("ssh-ed25519") || fields.len() < 2 {
        return Err(io::Error::other("generated public key is not Ed25519").into());
    }
    let allowed_signers = root.join("allowed_signers");
    write_private_new(
        &allowed_signers,
        format!("operator@example {} {}\n", fields[0], fields[1]).as_bytes(),
    )?;
    let fingerprint_output = capture(
        cell,
        "fingerprint",
        child_command(mode, os_program_data)
            .args(["-E", "sha256", "-lf"])
            .arg(key.with_extension("pub")),
    )?;
    if !fingerprint_output.status.success() {
        return Err(io::Error::other("fingerprint command failed; see exact terminal row").into());
    }
    let fingerprint = std::str::from_utf8(&fingerprint_output.stdout)?
        .split_ascii_whitespace()
        .nth(1)
        .ok_or_else(|| io::Error::other("OpenSSH fingerprint field missing"))?
        .to_owned();
    let policy = TrustPolicy {
        acceptance_store_root: root.to_string_lossy().into_owned(),
        allowed_signers_sha256: sha256(&std::fs::read(&allowed_signers)?),
        key_fingerprint: fingerprint.clone(),
        maximum_lifetime_seconds: 900,
        principal: "operator@example".to_owned(),
        schema: TRUST_POLICY_SCHEMA.to_owned(),
        schema_version: 1,
        trust_policy_scope: TRUST_POLICY_SCOPE.to_owned(),
        trust_root_id: "test-operator-root".to_owned(),
        trust_root_revision: 1,
    };
    let policy_bytes = canonical_json(&policy)?;
    let policy_path = root.join("trust-policy.json");
    write_private_new(&policy_path, &policy_bytes)?;
    let statement = b"synthetic ProgramData/path diagnostic; grants no authority";
    let statement_path = root.join("diagnostic-statement");
    write_private_new(&statement_path, statement)?;
    let signed = capture(
        cell,
        "sign",
        child_command(mode, os_program_data)
            .args(["-Y", "sign", "-f"])
            .arg(key)
            .args(["-n", SSHSIG_NAMESPACE, "-O", "hashalg=sha512"])
            .arg(&statement_path)
            .stdin(Stdio::inherit()),
    )?;
    if !signed.status.success() {
        return Err(io::Error::other("sign command failed; see exact terminal row").into());
    }
    let mut signature_path = statement_path.into_os_string();
    signature_path.push(".sig");
    let signature = private_generated_signature(&PathBuf::from(signature_path));
    let anchor = TrustAnchor::load(TrustInputs {
        acceptance_store_root: root,
        allowed_signers_path: &allowed_signers,
        externally_pinned_trust_policy_sha256: &sha256(&policy_bytes),
        trust_policy_path: &policy_path,
    })?;
    // This is the unchanged production verifier, including its independent
    // system-executable and ProgramData policy. The matrix changes no gate.
    let verified = anchor.verify(statement, &signature)?;
    Ok(
        json!({"fingerprint": fingerprint, "production_verify": "PASS",
        "signature_sha256": verified.detached_signature_sha256}),
    )
}

#[test]
#[ignore = "DIAGNOSTIC_ONLY: explicitly select under the original Windows Bazel rust_test"]
fn collect_openssh_programdata_path_matrix() -> Result<(), Box<dyn Error>> {
    let inherited_program_data = std::env::var_os("ProgramData");
    let environment_presence = ["ProgramData", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATH",
        "PATHEXT", "TEMP", "TMP", "TEST_TMPDIR", "TEST_WORKSPACE", "RUNFILES_DIR"]
        .map(|name| {
            let value = std::env::var_os(name);
            json!({"name": name, "present": value.is_some(), "nonempty": value.is_some_and(|value| !value.is_empty())})
        });
    // Constructing this command queries the OS but starts no process. Take only
    // its one OS-derived value, never its pre-populated command for an arm.
    let os_binding = openssh_command();
    let os_program_data = os_binding
        .get_envs()
        .find_map(|(name, value)| {
            (name == OsStr::new("ProgramData"))
                .then_some(value)
                .flatten()
        })
        .ok_or_else(|| io::Error::other("OS ProgramData binding missing"))?
        .to_os_string();
    let mut system_buffer = vec![0_u16; 32_768];
    // SAFETY: the output buffer remains valid with the supplied UTF-16 capacity.
    let length =
        unsafe { GetSystemDirectoryW(system_buffer.as_mut_ptr(), system_buffer.len() as u32) };
    if length == 0 || length as usize >= system_buffer.len() {
        return Err(
            io::Error::other("OS system directory query failed or exceeded its bound").into(),
        );
    }
    let system_directory = PathBuf::from(OsString::from_wide(&system_buffer[..length as usize]));
    let os_executable = system_directory
        .join("OpenSSH")
        .join("ssh-keygen.exe")
        .canonicalize()?;
    assert_eq!(
        openssh_keygen(),
        os_executable.as_path(),
        "diagnostic requires the original resolver to choose the OS signer"
    );
    let executable_pin = OpenOptions::new()
        .read(true)
        .share_mode(FILE_SHARE_READ)
        .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT)
        .open(openssh_keygen())?;
    let executable_before = describe_executable(&executable_pin)?;
    let version = (|| -> io::Result<Value> {
        let filename = openssh_keygen()
            .as_os_str()
            .encode_wide()
            .chain([0])
            .collect::<Vec<_>>();
        // SAFETY: the filename is a live, NUL-terminated UTF-16 string. The
        // obsolete handle out-parameter is documented as optional.
        let size = unsafe { GetFileVersionInfoSizeW(filename.as_ptr(), std::ptr::null_mut()) };
        if size == 0 || size > 1024 * 1024 {
            return Err(io::Error::other(
                "PE version resource is absent or exceeds 1 MiB",
            ));
        }
        let mut bytes = vec![0_u8; size as usize];
        // SAFETY: the buffer is live and has the size returned by the OS.
        if unsafe {
            GetFileVersionInfoW(
                filename.as_ptr(),
                /*dwhandle*/ 0,
                size,
                bytes.as_mut_ptr().cast(),
            )
        } == 0
        {
            return Err(io::Error::last_os_error());
        }
        let mut value = std::ptr::null_mut();
        let mut value_size = 0;
        let root_query = [u16::from(b'\\'), 0];
        // SAFETY: query a fixed structure inside the live version buffer. Do
        // not dereference the returned pointer until length and range checks.
        let found = unsafe {
            VerQueryValueW(
                bytes.as_ptr().cast(),
                root_query.as_ptr(),
                &mut value,
                &mut value_size,
            )
        };
        let structure_size = std::mem::size_of::<VS_FIXEDFILEINFO>();
        let in_buffer = (value as usize)
            .checked_sub(bytes.as_ptr() as usize)
            .and_then(|offset| offset.checked_add(structure_size))
            .is_some_and(|end| end <= bytes.len());
        if found == 0 || value.is_null() || (value_size as usize) < structure_size || !in_buffer {
            return Err(io::Error::other(
                "PE fixed version resource is unavailable or out of bounds",
            ));
        }
        // SAFETY: all bytes of the Copy structure are within the live buffer;
        // unaligned access is explicit rather than assumed from Vec<u8>.
        let fixed = unsafe { std::ptr::read_unaligned(value.cast::<VS_FIXEDFILEINFO>()) };
        if fixed.dwSignature != VS_FFI_SIGNATURE as u32 {
            return Err(io::Error::other("PE version resource signature is invalid"));
        }
        Ok(
            json!({"file_version": [fixed.dwFileVersionMS >> 16, fixed.dwFileVersionMS & 65535,
            fixed.dwFileVersionLS >> 16, fixed.dwFileVersionLS & 65535],
            "product_version": [fixed.dwProductVersionMS >> 16, fixed.dwProductVersionMS & 65535,
            fixed.dwProductVersionLS >> 16, fixed.dwProductVersionLS & 65535]}),
        )
    })();
    eprintln!(
        "HEPTA_OPENSSH_MATRIX {}",
        json!({"event": "preflight", "diagnostic_only": true,
        "executable": openssh_keygen(), "executable_identity": executable_before,
        "pe_version": version.as_ref().ok(), "pe_version_error": version.as_ref().err().map(ToString::to_string),
        "environment_presence_only": environment_presence,
        "inherited_programdata_matches_os_exact": inherited_program_data.as_deref() == Some(os_program_data.as_os_str()),
        "absent_arm_is_explicit_child_intervention": true,
        "historical_test_environment_reconstructed": false})
    );
    let mut results = Vec::new();
    for (cell, mode, form) in [
        (
            "absent_extended",
            ProgramDataMode::Absent,
            KeyPathForm::Extended,
        ),
        (
            "os_bound_extended",
            ProgramDataMode::OsBound,
            KeyPathForm::Extended,
        ),
        (
            "absent_plain",
            ProgramDataMode::Absent,
            KeyPathForm::PlainDriveAbsolute,
        ),
        (
            "os_bound_plain",
            ProgramDataMode::OsBound,
            KeyPathForm::PlainDriveAbsolute,
        ),
    ] {
        // Fresh per-cell destinations prevent overwrite prompts or previous
        // key material from changing the command. No private key is read.
        let temporary = private_tempdir("OpenSSH diagnostic private directory");
        let root = temporary.path().canonicalize()?;
        let mut components = root.components();
        let drive = match components.next() {
            Some(Component::Prefix(prefix)) => match prefix.kind() {
                Prefix::VerbatimDisk(drive) => drive,
                _ => {
                    return Err(
                        io::Error::other("diagnostic requires a local verbatim drive path").into(),
                    );
                }
            },
            _ => {
                return Err(io::Error::other("diagnostic private root has no drive prefix").into());
            }
        };
        assert_eq!(components.next(), Some(Component::RootDir));
        assert!(
            components
                .clone()
                .all(|component| matches!(component, Component::Normal(_))),
            "plain-path conversion requires only normal components"
        );
        let plain_root =
            PathBuf::from(format!("{}:\\", char::from(drive))).join(components.as_path());
        assert_eq!(plain_root.canonicalize()?, root);
        let root_pin = codex_utils_path::open_existing_private_state_directory(&root)?;
        let plain_pin = codex_utils_path::open_existing_private_state_directory(&plain_root)?;
        assert_eq!(file_id(&root_pin)?, file_id(&plain_pin)?);
        let key = match form {
            KeyPathForm::Extended => root.join("operator-key"),
            KeyPathForm::PlainDriveAbsolute => plain_root.join("operator-key"),
        };
        assert!(
            key.is_absolute() && key.as_os_str().encode_wide().count() < 240,
            "keep the path-format experiment below the legacy length bound"
        );
        assert!(!key.try_exists()? && !key.with_extension("pub").try_exists()?);
        eprintln!(
            "HEPTA_OPENSSH_MATRIX {}",
            json!({"event": "cell", "cell": cell,
            "programdata_mode": format!("{mode:?}"), "path_form": format!("{form:?}"),
            "key_path": key, "private_directory_id": file_id(&root_pin)?,
            "plain_and_extended_parent_same_id": true, "fresh_destination": true})
        );
        let generated = capture(
            cell,
            "keygen",
            child_command(mode, &os_program_data)
                .args(["-q", "-t", "ed25519", "-N", "", "-f"])
                .arg(&key)
                .stdin(Stdio::inherit()),
        )?;
        let verification = if generated.status.success() {
            Some(verify_generated_key(
                cell,
                &root,
                &key,
                mode,
                &os_program_data,
            ))
        } else {
            None
        };
        let verified = verification.as_ref().is_some_and(Result::is_ok);
        let row = json!({"cell": cell, "generation_exit_code": generated.status.code(),
            "generation_success": generated.status.success(), "post_generation_verified": verified,
            "verification": verification.as_ref().and_then(|result| result.as_ref().ok()),
            "verification_error": verification.as_ref().and_then(|result| result.as_ref().err()).map(ToString::to_string)});
        eprintln!(
            "HEPTA_OPENSSH_MATRIX {}",
            json!({"event": "cell_complete", "result": row})
        );
        results.push(row);
        assert_eq!(
            file_id(&root_pin)?,
            file_id(&codex_utils_path::open_existing_private_state_directory(
                &root
            )?)?
        );
        assert_eq!(describe_executable(&executable_pin)?, executable_before);
        // Pins drop before TempDir's cleanup. The next arm never reuses a key.
    }
    assert!(
        std::env::var_os("ProgramData") == inherited_program_data,
        "diagnostic must not alter parent ProgramData"
    );
    assert_eq!(results.len(), 4);
    eprintln!(
        "HEPTA_OPENSSH_MATRIX {}",
        json!({"event": "matrix_complete", "results": results,
        "diagnostic_only": true, "original_33_tests_executed_by_this_case": false,
        "product_qualification": false, "executable_after": describe_executable(&executable_pin)?})
    );
    assert!(
        results
            .iter()
            .all(|row| row["generation_success"].as_bool() == Some(false)
                || row["post_generation_verified"].as_bool() == Some(true)),
        "a generated key did not complete fingerprint/sign/production verification; see diagnostic rows"
    );
    Ok(())
}
