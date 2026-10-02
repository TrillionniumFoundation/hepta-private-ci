#![forbid(unsafe_code)]
//! Authority-free state and presentation decisions shared by UI host adapters.
//! No filesystem, transport, credential, durable execution or grant owner lives here.

pub mod canonical;
#[path = "../../../../hepta-ui-shared/chat.rs"]
pub mod chat;
pub mod confirmation;
pub mod controller;
pub mod error;
pub mod ledger;
pub mod projection;
pub mod recovery;
pub mod scheduler;
pub mod theme;
