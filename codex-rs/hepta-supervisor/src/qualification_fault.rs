use std::io;
use std::path::Path;

const FAULT_ROOT_ENV: &str = "HEPTA_SUPERVISOR_QUALIFICATION_FAULT_DIR";
const MAX_DELAY_MILLIS: u64 = 60_000;

#[cfg(feature = "qualification")]
pub(crate) fn maybe_fail(stage: &str, target: &Path) -> io::Result<()> {
    let Some(root) = std::env::var_os(FAULT_ROOT_ENV) else {
        return Ok(());
    };
    let marker = Path::new(&root).join(format!(
        "{}.{stage}.fail-once",
        target_name(target)
    ));
    let claimed = Path::new(&root).join(format!(
        "{}.{stage}.claimed.{}",
        target_name(target),
        std::process::id()
    ));
    match std::fs::rename(&marker, &claimed) {
        Ok(()) => Err(io::Error::other(format!(
            "qualification failpoint {stage} for {}",
            target.display()
        ))),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(error),
    }
}

#[cfg(not(feature = "qualification"))]
pub(crate) fn maybe_fail(_stage: &str, _target: &Path) -> io::Result<()> {
    Ok(())
}

#[cfg(feature = "qualification")]
pub(crate) fn maybe_delay(stage: &str, target: &Path) -> io::Result<()> {
    let Some(root) = std::env::var_os(FAULT_ROOT_ENV) else {
        return Ok(());
    };
    let marker = Path::new(&root).join(format!(
        "{}.{stage}.delay-ms",
        target_name(target)
    ));
    let bytes = match std::fs::read(&marker) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(()),
        Err(error) => return Err(error),
    };
    if bytes.len() > 16 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "qualification delay marker exceeds its bound",
        ));
    }
    let millis = std::str::from_utf8(&bytes)
        .map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "delay marker is not UTF-8"))?
        .trim()
        .parse::<u64>()
        .map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "delay marker is not an integer"))?;
    if millis == 0 || millis > MAX_DELAY_MILLIS {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "qualification delay is outside its bound",
        ));
    }
    std::thread::sleep(std::time::Duration::from_millis(millis));
    Ok(())
}

#[cfg(not(feature = "qualification"))]
pub(crate) fn maybe_delay(_stage: &str, _target: &Path) -> io::Result<()> {
    Ok(())
}

#[cfg(feature = "qualification")]
fn target_name(target: &Path) -> String {
    target
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("unnamed")
        .chars()
        .map(|value| {
            if value.is_ascii_alphanumeric() || matches!(value, '.' | '-' | '_') {
                value
            } else {
                '_'
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    #[test]
    fn production_build_has_no_environment_driven_failure() {
        #[cfg(not(feature = "qualification"))]
        {
            let target = std::path::Path::new("state.json");
            assert!(super::maybe_fail("write", target).is_ok());
            assert!(super::maybe_delay("write", target).is_ok());
        }
    }
}
