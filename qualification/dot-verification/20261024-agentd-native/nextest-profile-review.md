# Nextest profile warning review

The repository-pinned cargo-nextest 0.9.103 emits `ignoring unknown configuration keys: profile.local.inherits`. The log is retained; no configuration or runner flags were changed to hide it.

Reviewed the exact upstream tag cargo-nextest-0.9.103, nextest-runner/src/config/core/imp.rs: `retries()` (lines 987–992) and `slow_timeout()` (1016–1019) use custom-profile optional values and fall back to `self.default_profile` via `unwrap_or`. Thus inheritance of these two defaults is implicit and does not depend on the ignored `inherits` key. This is upstream source review, not a runtime timeout injection experiment.

Source: https://github.com/nextest-rs/nextest/blob/cargo-nextest-0.9.103/nextest-runner/src/config/core/imp.rs#L987-L1019

The checked-in repository config retains `slow-timeout = { period = "30s", terminate-after = 2 }`, `retries = 1`, and the selected local profile. Target selection/ignored-test semantics are unchanged. Test execution outcome will be recorded separately.
