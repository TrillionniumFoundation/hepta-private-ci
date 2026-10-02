#![forbid(unsafe_code)]
//! Authority-free state and presentation decisions shared by UI host adapters.
//! No filesystem, transport, credential, durable execution or grant owner lives here.

pub mod canonical;
pub mod confirmation;
pub mod controller;
pub mod error;
pub mod ledger;
pub mod projection;
pub mod recovery;
pub mod scheduler;
pub mod theme;

#[path = "../../../../hepta-ui-shared/chat_transport.rs"]
pub mod chat_transport;
