use std::path::{Path,PathBuf};
use zip::ZipArchive;
fn extract_zipball_to_dir(bytes: &[u8], destination: &Path) -> Result<(), String> {
    std::fs::create_dir_all(destination).map_err(|err| {
        format!(
            "failed to create curated plugins extraction directory {}: {err}",
            destination.display()
        )
    })?;

    let cursor = std::io::Cursor::new(bytes);
    let mut archive = ZipArchive::new(cursor)
        .map_err(|err| format!("failed to open curated plugins zip archive: {err}"))?;

    for index in 0..archive.len() {
        let mut entry = archive
            .by_index(index)
            .map_err(|err| format!("failed to read curated plugins zip entry: {err}"))?;
        let Some(relative_path) = entry.enclosed_name() else {
            let name = entry
                .name()
                .map_err(|err| format!("failed to decode curated plugins zip entry name: {err}"))?;
            return Err(format!(
                "curated plugins zip entry `{name}` escapes extraction root"
            ));
        };

        let mut components = relative_path.components();
        let Some(std::path::Component::Normal(_)) = components.next() else {
            continue;
        };

        let output_relative = components.fold(PathBuf::new(), |mut path, component| {
            if let std::path::Component::Normal(segment) = component {
                path.push(segment);
            }
            path
        });
        if output_relative.as_os_str().is_empty() {
            continue;
        }

        let output_path = destination.join(&output_relative);
        if entry.is_dir() {
            std::fs::create_dir_all(&output_path).map_err(|err| {
                format!(
                    "failed to create curated plugins directory {}: {err}",
                    output_path.display()
                )
            })?;
            continue;
        }

        if let Some(parent) = output_path.parent() {
            std::fs::create_dir_all(parent).map_err(|err| {
                format!(
                    "failed to create curated plugins directory {}: {err}",
                    parent.display()
                )
            })?;
        }
        let mut output = std::fs::File::create(&output_path).map_err(|err| {
            format!(
                "failed to create curated plugins file {}: {err}",
                output_path.display()
            )
        })?;
        std::io::copy(&mut entry, &mut output).map_err(|err| {
            format!(
                "failed to write curated plugins file {}: {err}",
                output_path.display()
            )
        })?;
        apply_zip_permissions(&entry, &output_path)?;
    }

    Ok(())
}

#[cfg(unix)]
fn apply_zip_permissions<R: std::io::Read + ?Sized>(
    entry: &zip::read::ZipFile<'_, R>,
    output_path: &Path,
) -> Result<(), String> {
    use std::os::unix::fs::PermissionsExt;

    let Some(mode) = entry.unix_mode() else {
        return Ok(());
    };
    std::fs::set_permissions(output_path, std::fs::Permissions::from_mode(mode & 0o777)).map_err(
        |err| {
            format!(
                "failed to set permissions on curated plugins file {}: {err}",
                output_path.display()
            )
        },
    )
}

#[cfg(not(unix))]
fn apply_zip_permissions<R: std::io::Read + ?Sized>(
    _entry: &zip::read::ZipFile<'_, R>,
    _output_path: &Path,
) -> Result<(), String> {
    Ok(())
}


#[cfg(test)]
mod tests {
use super::*;
use std::io::Write;
use tempfile::tempdir;
use zip::ZipWriter;
use zip::write::SimpleFileOptions;
use pretty_assertions::assert_eq;
#[cfg(unix)]
#[test]
fn extraction_strips_privilege_bits_and_preserves_bzip2_contents() {
    use std::os::unix::fs::PermissionsExt;

    for compression in [
        zip::CompressionMethod::Stored,
        zip::CompressionMethod::Bzip2,
    ] {
        let mut writer = ZipWriter::new(std::io::Cursor::new(Vec::new()));
        writer
            .start_file(
                "root/bin/plugin",
                SimpleFileOptions::default()
                    .compression_method(compression)
                    .unix_permissions(0o755),
            )
            .expect("start entry");
        writer.write_all(b"plugin payload").expect("write entry");
        let mut bytes = writer.finish().expect("finish archive").into_inner();
        // The safe writer masks these bits. Modify the on-disk central-directory
        // attributes to exercise an untrusted archive that sets both set-ID bits.
        let signature = b"PK\x01\x02";
        let central = bytes
            .windows(signature.len())
            .position(|window| window == signature)
            .expect("central directory");
        bytes[central + 38..central + 42].copy_from_slice(&(0o106755_u32 << 16).to_le_bytes());
        let destination = tempdir().expect("destination");
        extract_zipball_to_dir(&bytes, destination.path()).expect("extract archive");
        let output = destination.path().join("bin/plugin");
        assert_eq!(
            std::fs::read(&output).expect("read output"),
            b"plugin payload"
        );
        assert_eq!(
            std::fs::metadata(&output)
                .expect("output metadata")
                .permissions()
                .mode()
                & 0o7777,
            0o755
        );
    }
}


}
