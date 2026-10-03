use super::*;
use std::process::Command;

#[test]
#[ignore = "requires actual Root parent and independent non-Root original-reader child"]
fn actual_root_public_configuration_is_readable_but_effect_slot_stays_private() -> Result<()> {
    const CHILD: &str = "HEPTA_ORIGINAL_PUBLIC_SOURCE_CHILD";
    if std::env::var_os(CHILD).is_some() {
        ensure!(
            rustix::process::geteuid().as_raw() == 65534,
            "actual independent child UID"
        );
        let source =
            std::path::PathBuf::from(std::env::var_os("HEPTA_PUBLIC_CONFIG").context("source")?);
        let private =
            std::path::PathBuf::from(std::env::var_os("HEPTA_PRIVATE_EFFECT").context("private")?);
        let bytes = read_root_review_input(&source, 64 * 1024)
            .map_err(|error| anyhow::anyhow!("{error}"))?;
        ensure!(bytes == br#"{"schema":"original-public-configuration","private_key_path":"/role/private.key"}"#, "complete original bytes");
        ensure!(
            std::fs::read(private)
                .is_err_and(|error| error.kind() == std::io::ErrorKind::PermissionDenied),
            "original effect remains denied"
        );
        return Ok(());
    }
    ensure!(rustix::process::geteuid().as_raw() == 0, "requires Root");
    let root = tempfile::Builder::new()
        .prefix("hepta-public-config-")
        .tempdir_in("/run")?;
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700))?;
    let public = root.path().join("public");
    std::fs::create_dir(&public)?;
    std::fs::set_permissions(&public, std::fs::Permissions::from_mode(0o755))?;
    let bytes =
        br#"{"schema":"original-public-configuration","private_key_path":"/role/private.key"}"#;
    ensure!(
        public_root_source(&public, "config.json", bytes, 64 * 1024).is_err(),
        "private ancestor cannot masquerade as public"
    );
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o755))?;
    let source = public_root_source(&public, "config.json", bytes, 64 * 1024)?;
    let repeated = public_root_source(&public, "config.json", bytes, 64 * 1024)?;
    ensure!(
        repeated.path == source.path && repeated.digest == source.digest,
        "same immutable publication"
    );
    ensure!(
        public_root_source(&public, "config.json", b"changed", 64 * 1024).is_err(),
        "whole conflict rejected"
    );
    let private_dir = root.path().join("private-effects");
    std::fs::DirBuilder::new()
        .mode(0o700)
        .create(&private_dir)?;
    let private = private_dir.join("original.output");
    let mut file = std::fs::File::options()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&private)?;
    file.write_all(b"private original effect receipt")?;
    file.sync_all()?;
    let before = std::fs::metadata(&private)?;
    // /run is mounted noexec on the actual installed host. Keep data there,
    // while the same immutable test program lives on a Root-controlled exec FS.
    let executable_directory = tempfile::Builder::new()
        .prefix("hepta-public-config-program-")
        .tempdir_in("/var/lib")?;
    std::fs::set_permissions(executable_directory.path(), std::fs::Permissions::from_mode(0o755))?;
    let executable = executable_directory.path().join("original-test-elf");
    std::fs::copy(std::env::current_exe()?, &executable)?;
    std::fs::set_permissions(&executable, std::fs::Permissions::from_mode(0o555))?;
    ensure!(Digest32::of_bytes(&std::fs::read(&executable)?) == Digest32::of_bytes(&std::fs::read(std::env::current_exe()?)?), "same original program bytes");
    let status = Command::new("/usr/bin/setpriv")
        .args(["--reuid=65534", "--regid=65534", "--clear-groups", "--no-new-privs", "--inh-caps=-all", "--bounding-set=-all", "--ambient-caps=-all"])
        .arg(&executable)
        .args(["--ignored", "--exact", "root_frozen_generator::independent_owners::roles::publication::public_sources::tests::actual_root_public_configuration_is_readable_but_effect_slot_stays_private", "--nocapture"])
        .env_clear().env(CHILD, "1").env("HEPTA_PUBLIC_CONFIG", &source.path).env("HEPTA_PRIVATE_EFFECT", &private)
        .status()?;
    ensure!(
        status.success(),
        "actual independent original protected-reader child"
    );
    let after = std::fs::metadata(&private)?;
    ensure!(
        before.mode() == after.mode() && after.mode() & 0o077 == 0,
        "private slot unchanged"
    );
    Ok(())
}
