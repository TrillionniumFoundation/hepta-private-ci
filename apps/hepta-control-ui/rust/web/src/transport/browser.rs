use super::deadline::Deadline;
use super::*;
use js_sys::{Reflect, Uint8Array};
use std::rc::Rc;
use wasm_bindgen::{JsCast, JsValue};
use wasm_bindgen_futures::{JsFuture, spawn_local};
use web_sys::{
    AbortSignal, Headers, ReadableStreamDefaultReader, ReferrerPolicy, Request, RequestCache,
    RequestCredentials, RequestInit, RequestMode, RequestRedirect, Response, Url, UrlSearchParams,
    Window,
};

/// Cookie-authenticated browser I/O. No retry, authority, credential store or CORS escape.
#[derive(Clone)]
pub struct SameOriginHttpTransport {
    window: Window,
    origin: String,
    base: String,
    csrf_provider: Rc<dyn Fn() -> Option<String>>,
    timeout_ms: u32,
}

#[derive(Clone, Copy)]
enum Kind {
    Read,
    Lifecycle,
    Mutation,
}

impl SameOriginHttpTransport {
    pub fn new(
        base_url: &str,
        csrf_provider: Rc<dyn Fn() -> Option<String>>,
        timeout_ms: u32,
    ) -> Result<Self, ControlError> {
        if !(100..=120_000).contains(&timeout_ms) {
            return Err(unsent(ControlError::invalid()));
        }
        let window = web_sys::window().ok_or_else(|| unsent(ControlError::invalid()))?;
        let origin = window
            .location()
            .origin()
            .map_err(|_| unsent(ControlError::invalid()))?;
        let url = Url::new_with_base(base_url, &format!("{origin}/"))
            .map_err(|_| unsent(ControlError::invalid()))?;
        if url.origin() != origin
            || !matches!(url.protocol().as_str(), "http:" | "https:")
            || !url.pathname().ends_with('/')
            || !url.username().is_empty()
            || !url.password().is_empty()
            || !url.search().is_empty()
            || !url.hash().is_empty()
        {
            return Err(unsent(ControlError::invalid()));
        }
        Ok(Self {
            window,
            origin,
            base: url.href(),
            csrf_provider,
            timeout_ms,
        })
    }

    pub fn endpoint(&self) -> &str {
        &self.base
    }

    pub async fn connect(
        &self,
        manifest: &Value,
        signal: Option<AbortSignal>,
    ) -> Result<Value, ControlError> {
        self.fetch_json(
            "session/connect",
            Some(manifest),
            Kind::Lifecycle,
            None,
            signal,
        )
        .await
    }
    pub async fn read_snapshot(
        &self,
        input: &Value,
        signal: Option<AbortSignal>,
    ) -> Result<Value, ControlError> {
        self.fetch_json("view", Some(input), Kind::Read, None, signal)
            .await
    }
    pub async fn request(
        &self,
        method: &str,
        input: &Value,
        signal: Option<AbortSignal>,
    ) -> Result<Value, ControlError> {
        let body = mutation_body(method, input)?;
        let operation_id = identifier(&body, "operationId")?;
        self.fetch_json(
            "operations",
            Some(&body),
            Kind::Mutation,
            Some(&operation_id),
            signal,
        )
        .await
        .map_err(|error| mutation_outcome(error, &operation_id))
    }
    pub async fn lookup(
        &self,
        input: &Value,
        signal: Option<AbortSignal>,
    ) -> Result<Value, ControlError> {
        let (operation, session, generation, digest) = lookup_identity(input)?;
        let query = UrlSearchParams::new().map_err(|_| unsent(ControlError::invalid()))?;
        query.append("sessionId", &session);
        query.append("connectionGeneration", &generation.to_string());
        query.append("semanticDigest", &digest);
        let encoded = js_sys::encode_uri_component(&operation)
            .as_string()
            .ok_or_else(|| unsent(ControlError::invalid()))?;
        let path = format!("operations/{encoded}?{}", String::from(query.to_string()));
        self.fetch_json(&path, None, Kind::Read, None, signal).await
    }
    pub async fn refresh(
        &self,
        session: &Value,
        signal: Option<AbortSignal>,
    ) -> Result<Value, ControlError> {
        let body = session_body(
            session,
            &["sessionId", "connectionGeneration", "permissionRevision"],
        )?;
        self.fetch_json(
            "session/refresh",
            Some(&body),
            Kind::Lifecycle,
            None,
            signal,
        )
        .await
    }
    pub async fn revoke(
        &self,
        session: &Value,
        signal: Option<AbortSignal>,
    ) -> Result<(), ControlError> {
        let body = session_body(session, &["sessionId", "connectionGeneration"])?;
        let request_id = format!("revoke:{}", identifier(session, "sessionId")?);
        self.fetch_json(
            "session/revoke",
            Some(&body),
            Kind::Mutation,
            Some(&request_id),
            signal,
        )
        .await?;
        Ok(())
    }
    pub async fn close(
        &self,
        session: &Value,
        signal: Option<AbortSignal>,
    ) -> Result<(), ControlError> {
        let body = session_body(session, &["sessionId", "connectionGeneration"])?;
        self.fetch_json("session/close", Some(&body), Kind::Lifecycle, None, signal)
            .await?;
        Ok(())
    }

    async fn fetch_json(
        &self,
        path: &str,
        body: Option<&Value>,
        kind: Kind,
        request_id: Option<&str>,
        signal: Option<AbortSignal>,
    ) -> Result<Value, ControlError> {
        let url =
            Url::new_with_base(path, &self.base).map_err(|_| unsent(ControlError::invalid()))?;
        if url.origin() != self.origin || !url.href().starts_with(&self.base) {
            return Err(unsent(ControlError::invalid()));
        }
        let csrf = if matches!(kind, Kind::Lifecycle | Kind::Mutation) {
            let token = (self.csrf_provider)()
                .filter(|token| !token.is_empty())
                .ok_or_else(|| ControlError::unsent(ErrorCode::PermissionDenied))?;
            assert_canonical_text(&token, 512, EmptyText::Forbidden).map_err(unsent)?;
            Some(token)
        } else {
            None
        };
        if signal.as_ref().is_some_and(AbortSignal::aborted) {
            return Err(ControlError::unsent(ErrorCode::Aborted).retryable(true));
        }
        let body = body.map(encode_body).transpose()?;
        let request_id = match request_id {
            Some(id) => id.to_owned(),
            None => self
                .window
                .crypto()
                .map_err(|_| unsent(ControlError::invalid()))?
                .random_uuid(),
        };
        if request_id.is_empty()
            || request_id.len() > 192
            || !request_id
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"._:-".contains(&b))
        {
            return Err(unsent(ControlError::invalid()));
        }
        let headers = Headers::new().map_err(|_| unsent(ControlError::invalid()))?;
        for (key, value) in [
            ("accept", "application/json"),
            ("x-hepta-request-id", request_id.as_str()),
        ] {
            headers
                .set(key, value)
                .map_err(|_| unsent(ControlError::invalid()))?;
        }
        if body.is_some() {
            headers
                .set("content-type", "application/json")
                .map_err(|_| unsent(ControlError::invalid()))?;
        }
        if let Some(token) = csrf {
            headers
                .set("x-hepta-csrf-token", &token)
                .map_err(|_| unsent(ControlError::invalid()))?;
        }
        let deadline =
            Deadline::new(signal, self.timeout_ms).map_err(|_| unsent(ControlError::invalid()))?;
        let options = RequestInit::new();
        options.set_method(if body.is_some() { "POST" } else { "GET" });
        options.set_credentials(RequestCredentials::Include);
        options.set_cache(RequestCache::NoStore);
        options.set_mode(RequestMode::SameOrigin);
        options.set_redirect(RequestRedirect::Error);
        options.set_referrer_policy(ReferrerPolicy::NoReferrer);
        options.set_headers_headers(&headers);
        options.set_body_opt_str(body.as_deref());
        options.set_signal(Some(&deadline.signal()));
        let request = Request::new_with_str_and_init(&url.href(), &options)
            .map_err(|_| unsent(ControlError::invalid()))?;
        let mutation = matches!(kind, Kind::Mutation);
        let result = async {
            let response = deadline
                .race(self.window.fetch_with_request(&request))
                .await
                .map_err(|_| {
                    ControlError::new(ErrorCode::Transport)
                        .retryable(true)
                        .with_dispatch(true)
                })?
                .dyn_into::<Response>()
                .map_err(|_| transport_error(0))?;
            let bytes = read_response(&response, &deadline).await?;
            parse_response(&bytes, response.status())
        }
        .await;
        if deadline.signal().aborted() {
            return Err(ControlError::new(if mutation {
                ErrorCode::AmbiguousSubmission
            } else {
                ErrorCode::Aborted
            })
            .retryable(true)
            .with_dispatch(true)
            .detail("mutation", json!(mutation)));
        }
        result
    }
}

fn session_body(session: &Value, fields: &[&str]) -> Result<Value, ControlError> {
    let mut body = serde_json::Map::new();
    for field in fields {
        body.insert(
            (*field).into(),
            session
                .get(field)
                .cloned()
                .ok_or_else(|| unsent(ControlError::invalid()))?,
        );
    }
    Ok(Value::Object(body))
}

async fn read_response(response: &Response, deadline: &Deadline) -> Result<Vec<u8>, ControlError> {
    let status = response.status();
    let headers = response.headers();
    let header_check = (|| {
        let content_type = headers
            .get("content-type")
            .map_err(|_| transport_error(status))?
            .unwrap_or_default();
        let length = headers
            .get("content-length")
            .map_err(|_| transport_error(status))?;
        validate_headers(&content_type, length.as_deref(), status)
    })();
    if let Err(error) = header_check {
        if let Some(body) = response.body() {
            observe_cancel(body.cancel());
        }
        return Err(error);
    }
    let Some(body) = response.body() else {
        return Ok(Vec::new());
    };
    let reader = ReadableStreamDefaultReader::new(&body).map_err(|_| transport_error(status))?;
    let mut bytes = ResponseBytes::default();
    let result = async {
        loop {
            let next = deadline
                .race(reader.read())
                .await
                .map_err(|_| transport_error(status))?;
            let done = Reflect::get(&next, &JsValue::from_str("done"))
                .map_err(|_| transport_error(status))?;
            if done.as_bool() == Some(true) {
                break;
            }
            let chunk = Reflect::get(&next, &JsValue::from_str("value"))
                .map_err(|_| transport_error(status))?
                .dyn_into::<Uint8Array>()
                .map_err(|_| transport_error(status))?;
            if chunk.length() as usize > MAX_RESPONSE_BYTES - bytes.bytes.len() {
                return Err(too_large(status));
            }
            bytes.append(&chunk.to_vec(), status)?;
        }
        bytes.finish(status)
    }
    .await;
    if result.is_err() {
        observe_cancel(reader.cancel());
    }
    reader.release_lock();
    result
}

fn observe_cancel(promise: js_sys::Promise) {
    spawn_local(async move {
        let _ = JsFuture::from(promise).await;
    });
}
