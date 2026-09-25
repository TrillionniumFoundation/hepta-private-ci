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
