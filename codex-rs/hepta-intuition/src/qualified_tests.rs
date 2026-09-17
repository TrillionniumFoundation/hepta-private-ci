#![allow(clippy::expect_used)]

use super::*;

use codex_hepta_types::FixedQ32;
use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;

include!("qualified_test_fixture.rs");
include!("qualified_test_cases.rs");
