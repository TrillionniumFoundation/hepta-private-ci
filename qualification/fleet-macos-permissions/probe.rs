//! Observe the actual immutable-publication operations without accepting failures.
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

type FleetRegistryError = io::Error;
include!(env!("HEPTA_FLEET_FUNCTIONS"));

fn step<T>(name: &str, result: io::Result<T>) -> io::Result<T> {
    match &result {
        Ok(_) => println!("{{\"step\":{name:?},\"ok\":true}}"),
        Err(error) => println!(
            "{{\"step\":{name:?},\"ok\":false,\"errno\":{},\"kind\":{:?},\"error\":{:?}}}",
            error
                .raw_os_error()
                .map_or("null".to_owned(), |code| code.to_string()),
            format!("{:?}", error.kind()),
            error.to_string()
        ),
    }
    result
}

fn case(name: &str, operation: impl FnOnce() -> io::Result<()>) {
    let result = operation();
    println!(
        "{{\"case\":{name:?},\"completed_without_error\":{}}}",
        result.is_ok()
    );
}

fn main() -> io::Result<()> {
    let root = std::path::PathBuf::from(std::env::args_os().nth(1).expect("fresh output path"));
    std::fs::create_dir(&root)?;
    let source = root.join("readonly-source");
    std::fs::write(&source, b"reviewed immutable program bytes")?;
    set_mode(&source, /*mode*/ 0o555)?;
    case("exact_production_copy", || {
        step(
            "copy_immutable_program",
            copy_immutable_program(&source, &root.join("copied")),
        )
    });
    case("copy_operations", || {
        let mut input = step("copy.open_source", File::open(&source))?;
        let destination = root.join("stepwise-copy");
        let mut output = step(
            "copy.create_destination",
            OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&destination),
        )?;
        step("copy.io_copy", io::copy(&mut input, &mut output))?;
        println!(
            "{{\"observation\":\"mode_after_copy\",\"mode\":{}}}",
            output.metadata()?.permissions().mode() & 0o777
        );
        step("copy.chmod_0555", set_mode(&destination, /*mode*/ 0o555))?;
        step("copy.sync_retained_writer", output.sync_all())?;
        Ok(())
    });
    case("readonly_file_sync", || {
        let file = step("readonly_file.open", File::open(&source))?;
        step("readonly_file.sync_all", file.sync_all())
    });
    case("directory_sync", || {
        let path = root.join("sync-directory");
        std::fs::create_dir(&path)?;
        set_mode(&path, /*mode*/ 0o755)?;
        step("directory.sync_0755", sync_directory(&path))?;
        let retained = step("directory.open_before_chmod", File::open(&path))?;
        step("directory.chmod_0555", set_mode(&path, /*mode*/ 0o555))?;
        let retained_result = step("directory.sync_retained_after_chmod", retained.sync_all());
        let reopened_result = step("directory.sync_reopened_after_chmod", sync_directory(&path));
        set_mode(&path, /*mode*/ 0o755)?;
        retained_result.and(reopened_result)
    });
    case("readonly_directory_rename", || {
        let staging = root.join("rename-staging");
        std::fs::create_dir(&staging)?;
        step(
            "rename.chmod_staging_0555",
            set_mode(&staging, /*mode*/ 0o555),
        )?;
        step(
            "rename.same_parent",
            std::fs::rename(&staging, root.join("renamed")),
        )?;
        step("rename.sync_parent", sync_directory(&root))
    });
    case("exact_production_directory_publication", || {
        use std::os::unix::fs::DirBuilderExt;

        let staging = root.join("private-staging");
        std::fs::DirBuilder::new().mode(0o700).create(&staging)?;
        let published = root.join("sealed-publication");
        step(
            "publication.rename_and_seal",
            publish_release_directory(&staging, &published),
        )?;
        step("publication.sync_parent", sync_directory(&root))?;
        let mode = std::fs::metadata(&published)?.permissions().mode() & 0o777;
        println!("{{\"observation\":\"published_mode\",\"mode\":{mode}}}");
        assert_eq!(mode, 0o555);
        Ok(())
    });
    case("full_publication_sequence", || {
        let staging = root.join("publish-staging");
        std::fs::create_dir(&staging)?;
        let bin = staging.join("bin");
        std::fs::create_dir(&bin)?;
        step(
            "publish.copy_program",
            copy_immutable_program(&source, &bin.join("program")),
        )?;
        let manifest_path = staging.join("manifest.json");
        let mut manifest = step(
            "publish.create_manifest",
            OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&manifest_path),
        )?;
        step("publish.write_manifest", manifest.write_all(b"{}\n"))?;
        step("publish.sync_manifest", manifest.sync_all())?;
        drop(manifest);
        step(
            "publish.chmod_manifest_0444",
            set_mode(&manifest_path, /*mode*/ 0o444),
        )?;
        step("publish.chmod_bin_0555", set_mode(&bin, /*mode*/ 0o555))?;
        step("publish.sync_bin", sync_directory(&bin))?;
        step("publish.sync_staging", sync_directory(&staging))?;
        step(
            "publish.chmod_staging_0555",
            set_mode(&staging, /*mode*/ 0o555),
        )?;
        step(
            "publish.rename",
            std::fs::rename(&staging, root.join("published")),
        )?;
        step("publish.sync_parent", sync_directory(&root))
    });
    let lexical = std::env::temp_dir().join(format!(
        "hepta-fleet-canonical-probe-{}",
        std::process::id()
    ));
    std::fs::create_dir(&lexical)?;
    let canonical = lexical.canonicalize()?;
    println!(
        "{{\"observation\":\"temp_path\",\"lexical\":{:?},\"canonical\":{:?},\"equal\":{}}}",
        lexical,
        canonical,
        lexical == canonical
    );
    std::fs::remove_dir(&lexical)?;
    println!("{{\"probe_complete\":true,\"acceptance_claim\":false}}");
    Ok(())
}
