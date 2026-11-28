use super::StreamingSseChunk;
use super::StreamingSseServer;
use super::parse_request_line;
use super::start_streaming_sse_server_inner;
use crate::responses::ResponseMock;
use std::collections::VecDeque;
use std::sync::Arc;
use std::time::Duration;
use tokio::time::Sleep;
use wiremock::Match;
use wiremock::Request;
use wiremock::http::HeaderMap;
use wiremock::http::HeaderName;
use wiremock::http::HeaderValue;

/// A FIFO of response streams consumed only by requests matching this route.
pub struct StreamingSseRoute {
    pub matcher: Arc<dyn Match + Send + Sync>,
    pub responses: Vec<Vec<StreamingSseChunk>>,
}

/// Keeps independently matched streams live while a different route waits on a gate.
/// Captured requests retain headers, compressed bodies, and ResponseMock invariants.
pub async fn start_routed_streaming_sse_server(
    routes: Vec<StreamingSseRoute>,
) -> (StreamingSseServer, ResponseMock) {
    start_routed_streaming_sse_server_with_delays(
        routes.into_iter().map(|route| (route, None)).collect(),
    )
    .await
}

/// Delays each route's response headers from the instant its request is selected.
/// Delays are awaited by owned connection tasks after releasing the route lock.
pub async fn start_routed_streaming_sse_server_with_delays(
    routes: Vec<(StreamingSseRoute, Option<Duration>)>,
) -> (StreamingSseServer, ResponseMock) {
    let mut responses = Vec::new();
    let mut matchers = VecDeque::new();
    let mut delays = VecDeque::new();
    for (route, delay) in routes {
        for response in route.responses {
            matchers.push_back(Arc::clone(&route.matcher));
            delays.push_back(delay);
            responses.push(response);
        }
    }
    let recorded = ResponseMock::new();
    let (server, _) = start_streaming_sse_server_inner(
        responses,
        /*first_headers_gate*/ None,
        /*request_observer*/ None,
        Some(ResponseRoutes {
            matchers,
            delays,
            recorded: recorded.clone(),
        }),
    )
    .await;
    (server, recorded)
}

pub(super) struct ResponseRoutes {
    matchers: VecDeque<Arc<dyn Match + Send + Sync>>,
    delays: VecDeque<Option<Duration>>,
    recorded: ResponseMock,
}

impl ResponseRoutes {
    pub(super) fn select(
        &mut self,
        raw_headers: &str,
        body: Vec<u8>,
    ) -> Option<(usize, Option<Sleep>)> {
        let (method, path) = parse_request_line(raw_headers)?;
        let mut headers = HeaderMap::new();
        for line in raw_headers
            .lines()
            .skip(/*n*/ 1)
            .take_while(|line| !line.is_empty())
        {
            let (name, value) = line.split_once(':')?;
            headers.append(
                HeaderName::from_bytes(name.as_bytes()).ok()?,
                HeaderValue::from_str(value.trim()).ok()?,
            );
        }
        let host = headers.get("host")?.to_str().ok()?;
        let request = Request {
            url: format!("http://{host}{path}").parse().ok()?,
            method: method.parse().ok()?,
            headers,
            body,
        };
        self.recorded.matches(&request);
        let index = self
            .matchers
            .iter()
            .position(|matcher| matcher.matches(&request))?;
        self.matchers.remove(index)?;
        let delay = self.delays.remove(index)?.map(tokio::time::sleep);
        Some((index, delay))
    }
}

#[cfg(test)]
#[path = "streaming_sse_route_tests.rs"]
mod tests;
