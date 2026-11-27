//! Extension API compatibility root plus provider-tokenizer host capability.

#![forbid(unsafe_code)]

#[path = "lib.rs"]
mod compatibility;

pub use compatibility::*;

mod provider_tokenizer;

pub use provider_tokenizer::*;
