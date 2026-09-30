use std::fmt::Debug;

pub(crate) trait FixtureValue<T> {
    fn fixture(self, context: &str) -> T;
}

impl<T, E: Debug> FixtureValue<T> for Result<T, E> {
    fn fixture(self, context: &str) -> T {
        match self {
            Ok(value) => value,
            Err(error) => panic!("{context}: {error:?}"),
        }
    }
}

impl<T> FixtureValue<T> for Option<T> {
    fn fixture(self, context: &str) -> T {
        match self {
            Some(value) => value,
            None => panic!("{context}"),
        }
    }
}

pub(crate) trait FixtureError<E> {
    fn fixture_error(self, context: &str) -> E;
}

impl<T, E> FixtureError<E> for Result<T, E> {
    fn fixture_error(self, context: &str) -> E {
        match self {
            Ok(_) => panic!("{context}: expected error"),
            Err(error) => error,
        }
    }
}

#[cfg(test)]
mod temporary_directory {
    use std::path::PathBuf;
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;

    static NEXT_TEST_DIR: AtomicU64 = AtomicU64::new(1);

    #[derive(Debug)]
    pub(crate) struct TestDir(pub(crate) PathBuf);

    impl TestDir {
        pub(crate) fn new() -> Self {
            let sequence = NEXT_TEST_DIR.fetch_add(1, Ordering::Relaxed);
            let path = std::env::temp_dir().join(format!(
                "hepta-learning-artifacts-{}-{sequence}",
                std::process::id()
            ));
            let _ = std::fs::remove_dir_all(&path);
            std::fs::create_dir_all(&path).expect("create isolated test directory");
            Self(path)
        }
    }

    impl Drop for TestDir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }
}

#[cfg(test)]
pub(crate) use temporary_directory::TestDir;
