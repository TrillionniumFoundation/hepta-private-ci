use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use tempfile::NamedTempFile;

pub(super) fn stage_helper(source: &Path, destination: &Path) -> io::Result<()> {
    let directory = destination.parent().ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            "helper destination has no parent",
        )
    })?;
    let mut input = File::open(source)?;
    let mut temporary = NamedTempFile::new_in(directory)?;
    io::copy(&mut input, temporary.as_file_mut())?;
    temporary.flush()?;
    // Publish a complete same-directory file without replacing an executable
    // that another test process may already be using.
    match temporary.into_temp_path().persist_noclobber(destination) {
        Ok(()) => Ok(()),
        Err(error) => match same_bytes(&error.path, destination) {
            Ok(true) => Ok(()),
            Ok(false) => Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "existing helper differs from the complete runfile copy",
            )),
            Err(_) => Err(error.error),
        },
    }
}

fn same_bytes(expected: &Path, actual: &Path) -> io::Result<bool> {
    let mut expected = File::open(expected)?;
    let mut actual = File::open(actual)?;
    let mut expected_bytes = [0_u8; 65_536];
    let mut actual_bytes = [0_u8; 65_536];
    loop {
        let count = expected.read(&mut expected_bytes)?;
        if count == 0 {
            return Ok(actual.read(&mut actual_bytes[..1])? == 0);
        }
        match actual.read_exact(&mut actual_bytes[..count]) {
            Ok(()) => {}
            Err(error) if error.kind() == io::ErrorKind::UnexpectedEof => return Ok(false),
            Err(error) => return Err(error),
        }
        if expected_bytes[..count] != actual_bytes[..count] {
            return Ok(false);
        }
    }
}

#[cfg(test)]
#[path = "windows_sandbox_helpers_tests.rs"]
mod tests;
