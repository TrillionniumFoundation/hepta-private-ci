#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

use tempfile::TempDir;

pub(crate) fn private_tempdir(label: &str) -> TempDir {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("{label}: {error}"));
    #[cfg(unix)]
    std::fs::set_permissions(temporary.path(), std::fs::Permissions::from_mode(0o700))
        .unwrap_or_else(|error| panic!("secure {label}: {error}"));
    temporary
}

// Fixture assertions preserve their call-site context while production code
// continues to reject direct unwrap/expect operations.
pub(crate) trait TestMust<T> {
    fn must(self, label: &str) -> T;
}

impl<T, E: std::fmt::Debug> TestMust<T> for Result<T, E> {
    fn must(self, label: &str) -> T {
        self.unwrap_or_else(|error| panic!("{label}: {error:?}"))
    }
}

impl<T> TestMust<T> for Option<T> {
    fn must(self, label: &str) -> T {
        self.unwrap_or_else(|| panic!("{label}: expected a value"))
    }
}

pub(crate) trait TestMustErr<E> {
    fn must_err(self, label: &str) -> E;
}

impl<T: std::fmt::Debug, E> TestMustErr<E> for Result<T, E> {
    fn must_err(self, label: &str) -> E {
        match self {
            Ok(value) => panic!("{label}: unexpectedly succeeded: {value:?}"),
            Err(error) => error,
        }
    }
}
