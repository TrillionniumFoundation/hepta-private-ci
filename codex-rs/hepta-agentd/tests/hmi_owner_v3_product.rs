//! Actual owner lifecycle and sourced-audio software qualification.
//! The model transport and temporary PCM are fixtures, never physical devices.
#![cfg(unix)]
#[path = "hmi_owner_v3/audio_observation_tests.rs"]
mod audio;
#[path = "support/authbus_text.rs"]
mod authbus_fixture;
#[path = "support/hmi_product.rs"]
mod hmi_fixture;
#[path = "hmi_owner_v3/lifecycle_tests.rs"]
mod lifecycle;
#[path = "hmi_owner_v3/pressure_tests.rs"]
mod pressure;
#[path = "hmi_owner_v3/review_tests.rs"]
mod review;
mod support;
