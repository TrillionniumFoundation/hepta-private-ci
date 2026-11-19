//! Actual original Root time for learning signature verification. This returns
//! a sampled value, never the clock owner or a caller-selected time source.

use super::HostAuthorityService;
use super::generation_initial::original_root;

impl HostAuthorityService {
    pub(crate) fn original_learning_unix_seconds(&self) -> std::io::Result<u64> {
        original_root()?;
        Ok(self
            .clock
            .refresh_projection()
            .map_err(std::io::Error::other)?
            .observed_unix_ms
            / 1_000)
    }
}
