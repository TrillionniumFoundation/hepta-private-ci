//! Opt-in composition for an existing authenticated same-origin HTTP server.
//! There is no listener and no default cookie verifier. Deployment retains its
//! credential/session owner and provides that verifier for every request.
use super::AgentChatSession;
use super::Result;
use super::invalid;
use super::wire::ChatRequest;
use super::wire::ChatResponse;

/// The deployment's existing cookie-session verifier. Implementations must
/// validate expiry/revocation and return the authenticated principal; never
/// return an identity copied from an unverified request header or JSON field.
pub trait ChatCookieAuthenticator {
    fn authenticate(&self, cookie: &str) -> std::result::Result<String, String>;
}

/// One principal's owner connection. Never share this between principals.
pub struct ChatHttpSession<A> {
    owner: AgentChatSession,
    boundary: HttpBoundary<A>,
    capacity: tokio::sync::Semaphore,
}

struct HttpBoundary<A> {
    authenticator: A,
    principal: String,
    origin: String,
    csrf: String,
    session: String,
    generation: u64,
}

impl AgentChatSession {
    /// Bind an already configured owner to one verified deployment principal.
    /// Values are supplied by trusted server configuration/session state only.
    pub fn into_http<A: ChatCookieAuthenticator>(
        self,
        authenticator: A,
        principal: String,
        origin: String,
        csrf: String,
    ) -> Result<ChatHttpSession<A>> {
        if principal.is_empty()
            || principal.len() > 256
            || csrf.len() < 32
            || csrf.len() > 256
            || origin.len() > 2048
            || !(origin.starts_with("https://")
                || origin.starts_with("http://localhost:")
                || origin.starts_with("http://127.0.0.1:"))
        {
            return Err(invalid("invalid browser chat binding"));
        }
        let boundary = HttpBoundary {
            authenticator,
            principal,
            origin,
            csrf,
            session: self.session_id.clone(),
            generation: self.generation,
        };
        Ok(ChatHttpSession {
            owner: self,
            boundary,
            capacity: tokio::sync::Semaphore::new(8),
        })
    }
}
impl<A: ChatCookieAuthenticator> ChatHttpSession<A> {
    /// Map this to same-origin POST chat/request. Do not pass proxy-synthesized
    /// Origin or principal headers as authentication. Errors are fail-closed;
    /// no fallback to an anonymous/local process owner is permitted.
    pub async fn handle(
        &self,
        method: &str,
        content_type: &str,
        cookie: &str,
        origin: &str,
        csrf: &str,
        body: &[u8],
    ) -> Result<ChatResponse> {
        let _permit = self
            .capacity
            .try_acquire()
            .map_err(|_| invalid("browser chat capacity exhausted"))?;
        let request = self
            .boundary
            .authorize(method, content_type, cookie, origin, csrf, body)?;
        self.owner.dispatch(request).await
    }
}
impl<A: ChatCookieAuthenticator> HttpBoundary<A> {
    fn authorize(
        &self,
        method: &str,
        content_type: &str,
        cookie: &str,
        origin: &str,
        csrf: &str,
        body: &[u8],
    ) -> Result<ChatRequest> {
        if method != "POST"
            || content_type != "application/json"
            || body.len() > 65_536
            || cookie.is_empty()
            || cookie.len() > 8192
            || origin != self.origin
            || !equal_secret(csrf.as_bytes(), self.csrf.as_bytes())
        {
            return Err(invalid("browser chat request rejected"));
        }
        let principal = self
            .authenticator
            .authenticate(cookie)
            .map_err(|_| invalid("browser chat authentication required"))?;
        if principal != self.principal {
            return Err(invalid("browser chat principal mismatch"));
        }
        let request: ChatRequest =
            serde_json::from_slice(body).map_err(|_| invalid("invalid chat request"))?;
        request.validate().map_err(invalid)?;
        if request.session_id != self.session || request.connection_generation != self.generation {
            return Err(invalid("stale browser chat session"));
        }
        Ok(request)
    }
}
fn equal_secret(left: &[u8], right: &[u8]) -> bool {
    if left.len() != right.len() {
        return false;
    }
    left.iter()
        .zip(right)
        .fold(0u8, |difference, (a, b)| difference | (a ^ b))
        == 0
}

#[cfg(test)]
#[path = "chat_http_tests.rs"]
mod tests;
