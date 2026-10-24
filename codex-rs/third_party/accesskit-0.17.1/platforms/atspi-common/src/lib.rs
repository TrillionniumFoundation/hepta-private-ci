// Copyright 2022 The AccessKit Authors. All rights reserved.
// Licensed under the Apache License, Version 2.0 (found in
// the LICENSE-APACHE file) or the MIT license (found in
// the LICENSE-MIT file), at your option.

mod action;
mod adapter;
mod callback;
mod context;
mod error;
mod events;
mod filters;
mod node;
mod rect;
#[cfg(feature = "simplified-api")]
pub mod simplified;
mod util;

pub use atspi_common::CoordType;
pub use atspi_common::Granularity;
pub use atspi_common::InterfaceSet;
pub use atspi_common::Layer;
pub use atspi_common::Role;
pub use atspi_common::ScrollType;
pub use atspi_common::State;
pub use atspi_common::StateSet;

pub use action::*;
pub use adapter::next_adapter_id;
pub use adapter::Adapter;
pub use callback::AdapterCallback;
pub use context::ActionHandlerNoMut;
pub use context::ActionHandlerWrapper;
pub use context::AppContext;
pub use error::*;
pub use events::*;
pub use node::NodeIdOrRoot;
pub use node::PlatformNode;
pub use node::PlatformRoot;
pub use rect::*;
pub use util::WindowBounds;
