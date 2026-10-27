//! Native controls for the original-byte Windows OpenSSH backend.
//! Every object and signing key belongs to this newly created scratch fixture.
//! These cases require real Windows; no unsupported-API result counts as a
//! successful cryptographic rejection, and no deployed Root is represented.

use crate::AcceptanceError;
use crate::durable::sha256;
use crate::sshsig_strict::verify_ed25519_sshsig;
use crate::test_support::PrivateTempDir;
use crate::test_support::openssh_keygen;
use crate::test_support::private_tempdir;
use crate::test_support::sign_private_fixture;
use crate::windows_openssh::WindowsVerifierOwner;
use codex_utils_path::PrivateFile;
use codex_utils_path::PrivateSecurityIdentity;
use codex_utils_path::RetainedPrivateDirectory;
use codex_utils_path::WindowsFileId;
use pretty_assertions::assert_eq;
use std::ffi::OsStr;
use std::fs::OpenOptions;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::path::PathBuf;
use std::process::Command;
use windows_sys::Win32::Security::ACCESS_ALLOWED_ACE;
use windows_sys::Win32::Security::ACE_HEADER;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GetAce;
use windows_sys::Win32::Security::GetSecurityDescriptorDacl;
use windows_sys::Win32::Security::SetKernelObjectSecurity;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_WRITE_DATA;
use windows_sys::Win32::Storage::FileSystem::READ_CONTROL;
use windows_sys::Win32::Storage::FileSystem::WRITE_DAC;

const PRINCIPAL: &str = "windows-native-control@example";
const NAMESPACE: &str = "hepta-windows-native-control-v1";
const STATEMENT: &[u8] = b"original Windows verifier bytes\0\r\nopaque:\xff\n";
const POLICY: &[u8] = b"{\"schema\":\"windows-native-openssh-test-only\",\"schema_version\":1}\n";

struct Fixture {
    policy: PathBuf,
    allowed: Vec<u8>,
    signature: Vec<u8>,
    // Retire held directory handles before the owning temporary directory.
    _directory: RetainedPrivateDirectory,
    _temporary: PrivateTempDir,
}

impl Fixture {
    fn new() -> Self {
        let temporary = private_tempdir("native OpenSSH backend controls");
        let root = temporary.path().canonicalize().expect("own canonical root");
        let directory = RetainedPrivateDirectory::open_existing(&root)
            .expect("retain original private scratch directory");
        let key = root.join("own-ed25519-key");
        let generated = Command::new(openssh_keygen())
            .args(["-q", "-t", "ed25519", "-N", "", "-f"])
            .arg(&key)
            .output()
            .expect("generate a new test-only key with real OpenSSH");
        assert!(
            generated.status.success(),
            "fixture key generation failed: {}",
            String::from_utf8_lossy(&generated.stderr)
        );
        let public = std::fs::read_to_string(key.with_extension("pub"))
            .expect("read own generated PUBLIC key only");
        let fields = public.split_ascii_whitespace().collect::<Vec<_>>();
        assert_eq!(fields.first().copied(), Some("ssh-ed25519"));
        assert!(fields.len() >= 2);
        let allowed = format!("{PRINCIPAL} {} {}\n", fields[0], fields[1]).into_bytes();
        directory
            .write_new_child(OsStr::new("allowed_signers"), &allowed)
            .expect("create own canonical private allowed_signers");
        directory
            .write_new_child(OsStr::new("policy.json"), POLICY)
            .expect("create own small private policy without repairing an existing ACL");
        directory
            .write_new_child(OsStr::new("statement"), STATEMENT)
            .expect("create original binary statement bytes");
        let mut signer = Command::new(openssh_keygen());
        signer
            .args(["-Y", "sign", "-f"])
            .arg(&key)
            .args(["-n", NAMESPACE, "-O", "hashalg=sha512"]);
        let signature_path = sign_private_fixture(signer, &root.join("statement"));
        let signature = PrivateFile::open_existing(&signature_path)
            .expect("admit original private filename output")
            .read_bounded(16 * 1024)
            .expect("read original SSHSIG bytes without normalizing");
        assert!(signature.starts_with(b"-----BEGIN SSH SIGNATURE-----\n"));
        assert!(signature.ends_with(b"-----END SSH SIGNATURE-----\n"));
        let retained_statement = directory
            .open_child(OsStr::new("statement"))
            .expect("retain original statement after signer");
        assert_eq!(retained_statement.read_bounded(1024).unwrap(), STATEMENT);
        drop(retained_statement);
        Self {
            policy: root.join("policy.json"),
            allowed,
            signature,
            _directory: directory,
            _temporary: temporary,
        }
    }

    fn owner(&self) -> WindowsVerifierOwner {
        WindowsVerifierOwner::capture(&self.policy, &sha256(POLICY))
            .expect("capture the actual canonical policy and installed System32 verifier")
    }

    fn require_original_pair(&self, owner: &WindowsVerifierOwner) {
        verify_ed25519_sshsig(
            STATEMENT,
            &self.signature,
            &self.allowed,
            PRINCIPAL,
            NAMESPACE,
        )
        .expect("strict Rust verifies original bytes");
        owner
            .verify_openssh(
                STATEMENT,
                &self.signature,
                &self.allowed,
                PRINCIPAL,
                NAMESPACE,
            )
            .expect("actual native OpenSSH independently verifies the SAME original bytes");
        eprintln!(
            "native-openssh-control original_pair=true statement_sha256={} signature_sha256={} allowed_sha256={}",
            sha256(STATEMENT),
            sha256(&self.signature),
            sha256(&self.allowed)
        );
    }
}

#[test]
#[ignore = "independent native Windows verifier controls; preserve original26 scope"]
fn real_system32_child_and_strict_rust_accept_identical_original_bytes() {
    let fixture = Fixture::new();
    let owner = fixture.owner();
    fixture.require_original_pair(&owner);
}

#[test]
#[ignore = "independent native Windows verifier controls; preserve original26 scope"]
fn changed_body_is_rejected_by_strict_rust_and_actual_native_child() {
    let fixture = Fixture::new();
    let owner = fixture.owner();
    fixture.require_original_pair(&owner);
    let mut changed = STATEMENT.to_vec();
    changed[0] ^= 1;
    assert!(
        verify_ed25519_sshsig(
            &changed,
            &fixture.signature,
            &fixture.allowed,
            PRINCIPAL,
            NAMESPACE
        )
        .is_err()
    );
    let error = owner
        .verify_openssh(
            &changed,
            &fixture.signature,
            &fixture.allowed,
            PRINCIPAL,
            NAMESPACE,
        )
        .expect_err("actual native child must reject changed original body");
    assert!(matches!(error, AcceptanceError::Invalid(message)
        if message == "native OpenSSH SSHSIG verification failed"));
    eprintln!(
        "native-openssh-control changed_body=true strict_refused=true actual_child_nonzero=true"
    );
}

#[test]
#[ignore = "independent native Windows verifier controls; preserve original26 scope"]
fn wrong_namespace_is_rejected_by_actual_native_child() {
    let fixture = Fixture::new();
    let owner = fixture.owner();
    fixture.require_original_pair(&owner);
    let error = owner
        .verify_openssh(
            STATEMENT,
            &fixture.signature,
            &fixture.allowed,
            PRINCIPAL,
            "hepta-windows-native-wrong-namespace",
        )
        .expect_err("actual native child must reject the wrong namespace");
    assert!(matches!(error, AcceptanceError::Invalid(message)
        if message == "native OpenSSH SSHSIG verification failed"));
    eprintln!("native-openssh-control wrong_namespace=true actual_child_nonzero=true");
}

#[test]
#[ignore = "independent native Windows verifier controls; preserve original26 scope"]
fn captured_original_policy_dacl_change_is_refused_on_the_same_full_file_id() {
    let fixture = Fixture::new();
    let owner = fixture.owner();
    fixture.require_original_pair(&owner);
    // Only this test's newly created policy is changed. WRITE_DAC is a separate
    // kernel permission, not FILE_WRITE_DATA, and does not bypass held-file sharing.
    let maintenance = OpenOptions::new()
        .access_mode(READ_CONTROL | WRITE_DAC | FILE_READ_ATTRIBUTES)
        .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)
        .open(&fixture.policy)
        .expect("hold our own policy metadata handle before changing its DACL");
    let identity = WindowsFileId::inspect(&maintenance).expect("original full 128-bit policy ID");
    let security = PrivateSecurityIdentity::inspect(&maintenance)
        .expect("original canonical private policy DACL");
    let bytes = security.descriptor_bytes();
    let mut changed = vec![0usize; bytes.len().div_ceil(std::mem::size_of::<usize>())];
    // SAFETY: bounded aligned destination covers the complete validated descriptor.
    unsafe {
        std::ptr::copy_nonoverlapping(bytes.as_ptr(), changed.as_mut_ptr().cast(), bytes.len());
    }
    let descriptor = changed.as_mut_ptr().cast();
    let mut present = 0;
    let mut defaulted = 0;
    let mut dacl = std::ptr::null_mut();
    // SAFETY: aligned copy holds the same validated self-relative descriptor.
    assert_ne!(
        unsafe { GetSecurityDescriptorDacl(descriptor, &mut present, &mut dacl, &mut defaulted) },
        0
    );
    assert_ne!(present, 0);
    assert!(!dacl.is_null());
    let mut changed_masks = 0;
    // SAFETY: the canonical predicate already validated the ACL/ACE bounds.
    for index in 0..unsafe { (*dacl).AceCount } {
        let mut ace = std::ptr::null_mut();
        assert_ne!(unsafe { GetAce(dacl, u32::from(index), &mut ace) }, 0);
        assert!(!ace.is_null());
        let header = unsafe { &*ace.cast::<ACE_HEADER>() };
        if header.AceType == 0 {
            assert!(usize::from(header.AceSize) >= std::mem::size_of::<ACCESS_ALLOWED_ACE>());
            let allowed = unsafe { &mut *ace.cast::<ACCESS_ALLOWED_ACE>() };
            let prior = allowed.Mask;
            allowed.Mask &= !FILE_WRITE_DATA;
            changed_masks += u32::from(allowed.Mask != prior);
        }
    }
    assert!(changed_masks > 0, "actual fixture write grant must change");
    // SAFETY: update only the held newly created scratch policy's existing DACL.
    // No owner/SID is added, no foreign grant is introduced, and cleanup/delete
    // rights remain. Production performs no ACL repair; this is the negative input.
    assert_ne!(
        unsafe {
            SetKernelObjectSecurity(
                maintenance.as_raw_handle() as _,
                DACL_SECURITY_INFORMATION,
                descriptor,
            )
        },
        0
    );
    assert_eq!(WindowsFileId::inspect(&maintenance).unwrap(), identity);
    let after = PrivateSecurityIdentity::inspect(&maintenance)
        .expect("reduced own grant still satisfies the canonical private predicate");
    assert_ne!(after, security);
    let error = owner
        .verify_openssh(
            STATEMENT,
            &fixture.signature,
            &fixture.allowed,
            PRINCIPAL,
            NAMESPACE,
        )
        .expect_err("changed retained canonical DACL must refuse before bytes are served");
    assert!(matches!(error, AcceptanceError::Invalid(message)
        if message.starts_with("native verifier owner policy changed:")));
    eprintln!(
        "native-openssh-control policy_changed=true same_full_file_id=true actual_dacl_changed=true canonical_private=true refused_before_service=true"
    );
}
