// Copyright 2020 Damir Jelić
// Copyright 2020 The Matrix.org Foundation C.I.C.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#![recursion_limit = "256"]
#![doc = include_str!("../README.md")]
#![warn(missing_debug_implementations, missing_docs)]
#![cfg_attr(target_family = "wasm", allow(clippy::arc_with_non_send_sync))]
#![cfg_attr(docsrs, feature(doc_cfg))]

pub use async_trait::async_trait;
pub use bytes;
pub use matrix_sdk_base::CallIntentConsensus;
pub use matrix_sdk_base::ComposerDraft;
pub use matrix_sdk_base::ComposerDraftType;
pub use matrix_sdk_base::DraftAttachment;
pub use matrix_sdk_base::DraftAttachmentContent;
pub use matrix_sdk_base::DraftThumbnail;
pub use matrix_sdk_base::EncryptionState;
pub use matrix_sdk_base::PredecessorRoom;
pub use matrix_sdk_base::QueueWedgeError;
pub use matrix_sdk_base::Room as BaseRoom;
pub use matrix_sdk_base::RoomCreateWithCreatorEventContent;
pub use matrix_sdk_base::RoomDisplayName;
pub use matrix_sdk_base::RoomHero;
pub use matrix_sdk_base::RoomHeroWithProfile;
pub use matrix_sdk_base::RoomInfo;
pub use matrix_sdk_base::RoomMember as BaseRoomMember;
pub use matrix_sdk_base::RoomMemberships;
pub use matrix_sdk_base::RoomRecencyStamp;
pub use matrix_sdk_base::RoomState;
pub use matrix_sdk_base::SessionMeta;
pub use matrix_sdk_base::StateChanges;
pub use matrix_sdk_base::StateStore;
pub use matrix_sdk_base::StoreError;
pub use matrix_sdk_base::SuccessorRoom;
pub use matrix_sdk_base::ThreadingSupport;
pub use matrix_sdk_base::deserialized_responses;
pub use matrix_sdk_base::store::DynStateStore;
pub use matrix_sdk_base::store::MemoryStore;
pub use matrix_sdk_base::store::StateStoreExt;
pub use matrix_sdk_base::store::{self};
pub use matrix_sdk_common::*;
pub use reqwest;

mod account;
pub mod attachment;
pub mod authentication;
mod client;
pub mod config;
mod deduplicating_handler;
#[cfg(feature = "e2e-encryption")]
pub mod encryption;
mod error;
pub mod event_cache;
pub mod event_handler;
mod http_client;
pub mod latest_events;
pub mod media;
pub mod notification_settings;
pub mod paginators;
pub mod pusher;
pub mod room;
pub mod room_directory_search;
pub mod room_preview;
pub mod send_queue;
pub mod utils;
pub mod futures {
    //! Named futures returned from methods on types in [the crate root][crate].

    pub use super::client::futures::SendRequest;
}
pub mod sliding_sync;
pub mod sync;
#[cfg(feature = "experimental-widgets")]
pub mod widget;

#[cfg(feature = "experimental-search")]
pub mod message_search;

pub use account::Account;
pub use authentication::AuthApi;
pub use authentication::AuthSession;
pub use authentication::SessionTokens;
pub use client::homeserver_capabilities::HomeserverCapabilities;
#[cfg(feature = "experimental-search")]
pub mod search_index;
pub use client::Client;
pub use client::ClientBuildError;
pub use client::ClientBuilder;
pub use client::LoopCtrl;
pub use client::ServerVendorInfo;
pub use client::SessionChange;
pub use client::StoreSizes;
pub use client::TileServerInfo;
pub use client::sanitize_server_name;
pub use error::BeaconError;
pub use error::Error;
pub use error::HttpError;
pub use error::HttpResult;
pub use error::NotificationSettingsError;
pub use error::RefreshTokenError;
pub use error::Result;
pub use error::RumaApiError;
pub use http_client::SupportedAuthScheme;
pub use http_client::SupportedPathBuilder;
pub use http_client::TransmissionProgress;
#[cfg(feature = "sqlite")]
pub use matrix_sdk_sqlite::STATE_STORE_DATABASE_NAME;
#[cfg(all(feature = "e2e-encryption", feature = "sqlite"))]
pub use matrix_sdk_sqlite::SqliteCryptoStore;
#[cfg(feature = "sqlite")]
pub use matrix_sdk_sqlite::SqliteEventCacheStore;
#[cfg(feature = "sqlite")]
pub use matrix_sdk_sqlite::SqliteMediaStore;
#[cfg(feature = "sqlite")]
pub use matrix_sdk_sqlite::SqliteStateStore;
#[cfg(feature = "sqlite")]
pub use matrix_sdk_sqlite::SqliteStoreConfig;
pub use media::Media;
pub use pusher::Pusher;
pub use room::Room;
pub use ruma::IdParseError;
pub use ruma::OwnedServerName;
pub use ruma::ServerName;
pub use sliding_sync::SlidingSync;
pub use sliding_sync::SlidingSyncBuilder;
pub use sliding_sync::SlidingSyncList;
pub use sliding_sync::SlidingSyncListBuilder;
pub use sliding_sync::SlidingSyncListLoadingState;
pub use sliding_sync::SlidingSyncMode;
pub use sliding_sync::UpdateSummary;

#[cfg(feature = "uniffi")]
uniffi::setup_scaffolding!();

pub mod live_locations_observer;

#[cfg(feature = "unstable-msc4426")]
mod automatic_call_status;

#[cfg(any(test, feature = "testing"))]
pub mod test_utils;

#[cfg(test)]
matrix_sdk_test_utils::init_tracing_for_tests!();
