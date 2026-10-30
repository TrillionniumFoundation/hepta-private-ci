pub(crate) mod elevated;
// Raw token spawning is retained only for tests of its admission limitations.
#[cfg(test)]
pub(crate) mod legacy;
pub(crate) mod windows_common;
