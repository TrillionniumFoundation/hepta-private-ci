use std::fs::OpenOptions;

use pretty_assertions::assert_eq;

use super::VerificationInputs;

#[test]
fn verification_inputs_remain_exact_and_readable_while_writes_and_renames_are_blocked() {
    let allowed = b"operator@example ssh-ed25519 fixture-public-key\n";
    let signature = b"fixture signature bytes\n";
    let inputs = VerificationInputs::new(allowed, signature).expect("pin verification inputs");
    inputs
        .directory
        .validate()
        .expect("private verification directory");
    let root = inputs
        .allowed_signers_path()
        .parent()
        .expect("input parent")
        .to_path_buf();
    assert_eq!(
        std::fs::read(inputs.allowed_signers_path()).expect("read allowed signers"),
        allowed
    );
    assert_eq!(
        std::fs::read(inputs.signature_path()).expect("read signature"),
        signature
    );
    assert!(
        OpenOptions::new()
            .write(true)
            .open(inputs.allowed_signers_path())
            .is_err()
    );
    assert!(std::fs::remove_file(inputs.signature_path()).is_err());
    assert!(std::fs::rename(&root, root.with_extension("moved")).is_err());
    assert_eq!(
        std::fs::read(inputs.allowed_signers_path()).expect("read retained allowed signers"),
        allowed
    );
    assert_eq!(
        std::fs::read(inputs.signature_path()).expect("read retained signature"),
        signature
    );
    drop(inputs);
    assert!(
        !root.exists(),
        "owned empty verification directory is removed"
    );
}

#[test]
fn empty_and_maximum_bounded_verification_inputs_are_preserved() {
    let allowed = vec![b'a'; 64 * 1024];
    let inputs = VerificationInputs::new(&allowed, b"").expect("pin bounded verification inputs");
    let root = inputs
        .allowed_signers_path()
        .parent()
        .expect("input parent")
        .to_path_buf();
    assert_eq!(
        std::fs::read(inputs.allowed_signers_path()).expect("read maximum allowed signers"),
        allowed
    );
    assert_eq!(
        std::fs::read(inputs.signature_path()).expect("read empty signature"),
        Vec::<u8>::new()
    );
    drop(inputs);
    assert!(!root.exists());
}

#[test]
fn cleanup_preserves_an_unowned_directory_entry() {
    let inputs =
        VerificationInputs::new(b"allowed", b"signature").expect("pin verification inputs");
    let root = inputs
        .allowed_signers_path()
        .parent()
        .expect("input parent")
        .to_path_buf();
    let unrelated = root.join("unowned");
    std::fs::write(&unrelated, b"keep").expect("write separate entry");
    drop(inputs);
    assert_eq!(
        std::fs::read(&unrelated).expect("read preserved entry"),
        b"keep"
    );
    assert!(!root.join("allowed-signers").exists());
    assert!(!root.join("signature").exists());
    std::fs::remove_file(unrelated).expect("remove fixture entry");
    std::fs::remove_dir(root).expect("remove fixture directory");
}
