//! Actual owner lifecycle and sourced-audio software qualification.
//! The model transport and temporary PCM are fixtures, never physical devices.
#![cfg(unix)]
#[path = "support/authbus_text.rs"]
mod authbus_fixture;
mod support;
#[path = "support/hmi_product.rs"]
mod hmi_fixture;
#[path = "hmi_owner_v3/audio_observation_tests.rs"]
mod audio;
#[path = "hmi_owner_v3/lifecycle_tests.rs"]
mod lifecycle;
