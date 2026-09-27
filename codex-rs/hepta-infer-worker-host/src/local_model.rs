//! Experimental local-model execution boundary.
//!
//! Compiled only with `local-model-experimental`. The implementation verifies
//! externally signed grants, binds the exact model/input/device tuple, reserves
//! aggregate resources and reuses inference.control durability. It is not a
//! production activation or real-hardware qualification claim.

include!("local_model/grants.rs");
include!("local_model/contracts.rs");
include!("local_model/resources.rs");
include!("local_model/reservations.rs");
include!("local_model/worker.rs");
include!("local_model/helpers.rs");
include!("local_model/tests.rs");
