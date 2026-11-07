//! Remove ambient Python and loader injection from the original worker tree.
//! This is not a held interpreter, standard-library or native-library closure.

use std::process::Command;

pub(super) fn configure_python_environment(command: &mut Command) -> Result<(), String> {
    configure_python_environment_from_ambient(command, std::env::vars_os())
}

// Keep the real ambient environment at the production entry point while tests
// provide an explicit input without mutating their process-wide environment.
fn configure_python_environment_from_ambient(
    command: &mut Command,
    mut ambient: impl Iterator<Item = (std::ffi::OsString, std::ffi::OsString)>,
) -> Result<(), String> {
    if ambient
        .any(|(name, _)| name.to_string_lossy().starts_with("LD_") || name == "GLIBC_TUNABLES")
        || command.get_envs().any(|(name, value)| {
            value.is_some()
                && (name.to_string_lossy().starts_with("LD_") || name == "GLIBC_TUNABLES")
        })
    {
        return Err("neural Python loader overrides are not allowed".to_owned());
    }
    // Both supervisor and descendant use isolated, no-site entry. The pinned
    // helper restores only the explicitly declared import roots afterwards.
    command.args(["-I", "-S", "-B"]);
    for name in [
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONUSERBASE",
        "PYTHONSTARTUP",
        "PYTHONINSPECT",
        "PYTHONPYCACHEPREFIX",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "LD_AUDIT",
        "DYLD_INSERT_LIBRARIES",
        "DYLD_LIBRARY_PATH",
    ] {
        command.env_remove(name);
    }
    command
        .env("PYTHONNOUSERSITE", "1")
        .env("PYTHONDONTWRITEBYTECODE", "1");
    Ok(())
}

#[cfg(test)]
#[path = "smollm_neural_environment_tests.rs"]
mod tests;
