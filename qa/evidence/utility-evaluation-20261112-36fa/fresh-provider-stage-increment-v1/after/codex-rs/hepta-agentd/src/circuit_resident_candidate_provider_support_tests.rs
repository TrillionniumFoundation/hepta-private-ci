//! Fresh same-A owner composition, separate from completed PublicationFixture.
//! These local mechanism ports execute the original owners. They are not public
//! cross-UID admission or Root deployment evidence; those are separate tests.
use super::*;

#[path = "circuit_resident_candidate_provider_material_support_tests.rs"]
mod original_material;
#[path = "circuit_resident_candidate_provider_stage_support_tests.rs"]
mod stages;
#[path = "circuit_resident_candidate_provider_stage_tests.rs"]
mod stage_tests;
