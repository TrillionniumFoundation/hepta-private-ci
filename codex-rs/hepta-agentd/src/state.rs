// Retain the reviewed Agentd state implementation and add one narrow product
// continuation boundary. The continuation runs only after the exact prepared
// envelope is durably frozen as ContextAttached by the existing coordinator.
include!("state_base.rs");

#[path = "state_intelligence_product_loop.rs"]
mod intelligence_product_loop;
