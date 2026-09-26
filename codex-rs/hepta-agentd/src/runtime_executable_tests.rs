use std::io::Write;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::RuntimeExecutableIdentity;
use super::RuntimeExecutableOrigin;
use super::observe_cached;
use super::observe_file;

fn image(bytes: &[u8]) -> RuntimeExecutableIdentity {
    let mut file = tempfile::NamedTempFile::new().expect("image file");
    file.write_all(bytes).expect("image bytes");
    file.flush().expect("flush");
    observe_file(
        file.reopen().expect("reader"),
        RuntimeExecutableOrigin::ExecutablePath,
        1024,
    )
    .expect("bounded image observation")
}

#[test]
fn implementation_changes_when_code_changes_without_manifest_change() {
    let module = StableId::new("extension.optional").expect("module");
    let manifest = Digest32::of_bytes(b"same reviewed manifest");
    let before = image(b"executable A");
    let after = image(b"executable B");
    assert_ne!(before.artifact_digest(), after.artifact_digest());
    assert_ne!(
        before.implementation_digest(&module, manifest),
        after.implementation_digest(&module, manifest)
    );
    assert_ne!(before.artifact_digest(), manifest);
    assert_eq!(before.bytes(), 12);
}

#[test]
fn module_and_manifest_are_separate_from_shared_executable_identity() {
    let executable = image(b"shared agentd executable");
    let first = StableId::new("extension.first").expect("first");
    let second = StableId::new("extension.second").expect("second");
    let a = Digest32::of_bytes(b"manifest A");
    let b = Digest32::of_bytes(b"manifest B");
    assert_ne!(
        executable.implementation_digest(&first, a),
        executable.implementation_digest(&second, a)
    );
    assert_ne!(
        executable.implementation_digest(&first, a),
        executable.implementation_digest(&first, b)
    );
    assert_eq!(
        executable.implementation_digest(&first, a),
        image(b"shared agentd executable").implementation_digest(&first, a)
    );
}

#[test]
fn empty_or_oversized_images_never_produce_a_manifest_fallback() {
    for (bytes, maximum) in [(b"".as_slice(), 1024), (b"image".as_slice(), 4)] {
        let mut file = tempfile::NamedTempFile::new().expect("file");
        file.write_all(bytes).expect("write");
        let result = observe_file(
            file.reopen().expect("reader"),
            RuntimeExecutableOrigin::ExecutablePath,
            maximum,
        );
        assert_eq!(
            result.expect_err("invalid image").kind(),
            std::io::ErrorKind::InvalidData
        );
    }
}

#[test]
fn process_observation_cache_retains_the_exact_observed_bytes() {
    let mut file = tempfile::NamedTempFile::new().expect("image file");
    file.write_all(b"small executable fixture")
        .expect("image bytes");
    file.flush().expect("flush");
    let expected = Digest32::of_bytes(b"small executable fixture");
    let cache = std::sync::OnceLock::new();
    let first = observe_cached(&cache, || {
        observe_file(
            file.reopen()?,
            RuntimeExecutableOrigin::LinuxLoadedImage,
            1024,
        )
    })
    .expect("first observation");
    let second = observe_cached(&cache, || {
        panic!("a cached observation must not re-read the executable")
    })
    .expect("cached observation");
    assert!(std::ptr::eq(first, second));
    assert_eq!(first.origin(), RuntimeExecutableOrigin::LinuxLoadedImage);
    assert_eq!(first.artifact_digest(), expected);
    assert_eq!(first.bytes(), 24);
}
