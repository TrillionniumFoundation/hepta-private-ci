// Same genuine CLI source as the hepta binary. Keep the recursion bound
// at the binary crate root rather than in main.rs: hepta.rs includes main.rs
// and Rust does not permit an inner crate attribute inside include! text.
#![recursion_limit = "256"]

include!("main.rs");
