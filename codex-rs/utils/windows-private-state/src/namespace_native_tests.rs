use super::*;
use std::io::Write as _;
use std::os::windows::fs::OpenOptionsExt;

#[test]
fn native_inherited_directory_descriptor_preserves_namespace_admission() -> Result {
    let current = CurrentUser::capture_effective()?;
    let nonce = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
    let sequence = NEXT_FIXTURE.fetch_add(1, Ordering::Relaxed);
    let root_path = std::env::temp_dir().join(format!(
        "hepta-inherited-{}-{nonce}-{sequence}",
        std::process::id()
    ));
    // The same native CreateDirectory operation used by ordinary temporary
    // directories inherits the already private CI parent's actual descriptor.
    fs::create_dir(&root_path)?;
    let root = CleanupRoot(root_path);
    fs::create_dir(root.0.join("object"))?;
    let mut observations = Vec::new();
    for path in [&root.0, &root.0.join("object")] {
        let file = fs::OpenOptions::new()
            .read(true)
            .share_mode(/*share_mode*/ 3)
            .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
            .open(path)?;
        let descriptor = LocalDescriptor::read(&file)?;
        // SAFETY: these observations use the live LocalAlloc descriptor
        // returned for this exact held file, just like LocalDescriptor::bytes.
        let (allocated, length, valid) = unsafe {
            (
                LocalSize(descriptor.0.as_ptr()),
                GetSecurityDescriptorLength(descriptor.0.as_ptr()),
                IsValidSecurityDescriptor(descriptor.0.as_ptr()),
            )
        };
        let header = if allocated >= 20 {
            // SAFETY: the successful native read initialized the fixed
            // descriptor header, which fits the retained allocation.
            unsafe { std::slice::from_raw_parts(descriptor.0.as_ptr().cast::<u8>(), 20).to_vec() }
        } else {
            Vec::new()
        };
        let serialized = descriptor.bytes();
        let observed = crate::namespace_acl::observe_directory(&file, &current)
            .map(|_| ())
            .map_err(|error| error.to_string());
        writeln!(
            std::io::stderr().lock(),
            "HEPTA_NATIVE_INHERITED_DESCRIPTOR allocated={allocated} length={length} valid={valid} header={header:02x?} result={observed:?}"
        )?;
        match serialized {
            Ok(bytes) => {
                writeln!(
                    std::io::stderr().lock(),
                    "HEPTA_NATIVE_INHERITED_BYTES bytes={:02x?}",
                    &bytes[..bytes.len().min(4096)]
                )?;
            }
            Err(error) => {
                writeln!(
                    std::io::stderr().lock(),
                    "HEPTA_NATIVE_INHERITED_BYTES refusal={error}"
                )?;
            }
        }
        observations.push(observed);
    }
    assert!(
        observations.iter().all(std::result::Result::is_ok),
        "actual inherited private namespace was refused: {observations:?}"
    );
    Ok(())
}
