//! Remove ambient Python and loader injection from the original worker tree.
//! This is not a held interpreter, standard-library or native-library closure.

use std::process::Command;

pub(super) fn configure_python_environment(command: &mut Command) {
    // The supervisor must retain its verified script directory for project
    // imports. Its original child uses sys.executable without these switches,
    // so enforce the same user-site/bytecode policy in the inherited environment.
    command.args(["-E", "-s", "-B"]);
    for name in [
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONUSERBASE",
        "PYTHONSTARTUP",
        "PYTHONINSPECT",
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
}

#[cfg(test)]
#[path = "smollm_neural_environment_tests.rs"]
mod tests;
