/*
 * Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#![cfg(all(
    feature = "client",
    any(feature = "test-util", feature = "legacy-test-util")
))]
// Extra imports are used by stalled_stream_download and stalled_stream_upload as conveniences
#![allow(unused_imports)]

pub use aws_smithy_async::test_util::tick_advance_sleep::tick_advance_time_and_sleep;
pub use aws_smithy_async::test_util::tick_advance_sleep::TickAdvanceSleep;
pub use aws_smithy_async::test_util::tick_advance_sleep::TickAdvanceTime;
pub use aws_smithy_async::time::TimeSource;
pub use aws_smithy_runtime::assert_str_contains;
pub use aws_smithy_runtime::client::orchestrator::operation::Operation;
pub use aws_smithy_runtime::client::stalled_stream_protection::StalledStreamProtectionInterceptor;
pub use aws_smithy_runtime::test_util::capture_test_logs::show_test_logs;
pub use aws_smithy_runtime_api::box_error::BoxError;
pub use aws_smithy_runtime_api::client::http::HttpClient;
pub use aws_smithy_runtime_api::client::http::HttpConnector;
pub use aws_smithy_runtime_api::client::http::HttpConnectorFuture;
pub use aws_smithy_runtime_api::client::http::HttpConnectorSettings;
pub use aws_smithy_runtime_api::client::http::SharedHttpConnector;
pub use aws_smithy_runtime_api::client::interceptors::context::Error;
pub use aws_smithy_runtime_api::client::interceptors::context::Output;
pub use aws_smithy_runtime_api::client::orchestrator::HttpRequest;
pub use aws_smithy_runtime_api::client::orchestrator::HttpResponse;
pub use aws_smithy_runtime_api::client::orchestrator::OrchestratorError;
pub use aws_smithy_runtime_api::client::result::SdkError;
pub use aws_smithy_runtime_api::client::runtime_components::RuntimeComponents;
pub use aws_smithy_runtime_api::client::ser_de::DeserializeResponse;
pub use aws_smithy_runtime_api::client::stalled_stream_protection::StalledStreamProtectionConfig;
pub use aws_smithy_runtime_api::http::Response;
pub use aws_smithy_runtime_api::http::StatusCode;
pub use aws_smithy_runtime_api::shared::IntoShared;
pub use aws_smithy_types::body::SdkBody;
pub use aws_smithy_types::config_bag::ConfigBag;
pub use aws_smithy_types::error::display::DisplayErrorContext;
pub use aws_smithy_types::timeout::TimeoutConfig;
pub use bytes::Bytes;
pub use std::collections::VecDeque;
pub use std::convert::Infallible;
pub use std::future::poll_fn;
pub use std::mem;
pub use std::pin::Pin;
pub use std::sync::Arc;
pub use std::sync::Mutex;
pub use std::task::Context;
pub use std::task::Poll;
pub use std::time::Duration;
pub use tracing::info;
pub use tracing::Instrument as _;

/// No really, it's 42 bytes long... super neat
pub const NEAT_DATA: Bytes = Bytes::from_static(b"some really neat data");

/// Ticks time forward by the given duration, and logs the current time for debugging.
#[macro_export]
macro_rules! tick {
    ($ticker:ident, $duration:expr) => {
        $ticker.tick($duration).await;
        let now = $ticker
            .now()
            .duration_since(std::time::SystemTime::UNIX_EPOCH)
            .unwrap();
        tracing::info!("ticked {:?}, now at {:?}", $duration, now);
    };
}

#[derive(Debug)]
pub struct FakeServer(pub SharedHttpConnector);
impl HttpClient for FakeServer {
    fn http_connector(
        &self,
        _settings: &HttpConnectorSettings,
        _components: &RuntimeComponents,
    ) -> SharedHttpConnector {
        self.0.clone()
    }
}

struct ChannelBody {
    receiver: tokio::sync::mpsc::Receiver<Bytes>,
}

impl http_body_1x::Body for ChannelBody {
    type Data = Bytes;
    type Error = Infallible;

    fn poll_frame(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
    ) -> Poll<Option<Result<http_body_1x::Frame<Self::Data>, Self::Error>>> {
        match self.receiver.poll_recv(cx) {
            Poll::Ready(value) => Poll::Ready(value.map(|b| Ok(http_body_1x::Frame::data(b)))),
            Poll::Pending => Poll::Pending,
        }
    }
}

pub fn channel_body() -> (SdkBody, tokio::sync::mpsc::Sender<Bytes>) {
    let (sender, receiver) = tokio::sync::mpsc::channel(1000);
    (SdkBody::from_body_1_x(ChannelBody { receiver }), sender)
}
