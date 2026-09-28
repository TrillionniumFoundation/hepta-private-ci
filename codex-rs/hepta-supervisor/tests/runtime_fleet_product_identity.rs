//! Compile the actual product module in a test target: hepta-supervisord has
//! test=false, so tests placed only in its module would otherwise never run.
#[allow(dead_code)]
#[path = "../src/fleet_runtime_product.rs"]
mod fleet_runtime_product;
