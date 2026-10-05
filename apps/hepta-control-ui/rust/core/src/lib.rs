#![forbid(unsafe_code)]
//! Authority-free state and presentation decisions shared by UI host adapters.
//! No filesystem, transport, credential, durable execution or grant owner lives here.

pub mod canonical;
pub mod chat;
pub mod chat_owner;
pub mod chat_timeline;
pub mod confirmation;
pub mod controller;
pub mod error;
pub mod ledger;
pub mod projection;
pub mod recovery;
pub mod scheduler;
pub mod theme;

/// Read-only runtime status projection; no business authority.
pub mod runtime_view;
