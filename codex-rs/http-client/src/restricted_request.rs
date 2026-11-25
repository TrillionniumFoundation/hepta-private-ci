//! Request-local clients keep each connector's policy out of unrestricted caches.

use http::header::PROXY_AUTHORIZATION;

use super::RouteAwareClientPool;
use super::RouteAwareRequestError;
use crate::HttpAddressPolicy;
use crate::route_aware_redirect::MAX_REDIRECTS;
use crate::route_aware_redirect::insert_referer;
use crate::route_aware_redirect::is_redirect;
use crate::route_aware_redirect::redirect_request;
use crate::route_aware_redirect::redirect_url;
use crate::route_aware_redirect::remove_sensitive_headers;

impl RouteAwareClientPool {
    pub(super) async fn send_restricted(
        &self,
        mut request: reqwest::Request,
        policy: &HttpAddressPolicy,
    ) -> Result<reqwest::Response, RouteAwareRequestError> {
        let deadline = request
            .timeout()
            .copied()
            .map(|timeout| tokio::time::Instant::now() + timeout);
        let mut redirects = 0;
        let mut previous_route = None;
        loop {
            let current_url = request.url().clone();
            let resolver = policy.resolver_for(&current_url)?;
            let building = self
                .client_builder
                .clone()
                .without_redirects()
                .without_request_retries()
                .build_for_restricted_destination(
                    &self.http_client_factory,
                    &current_url,
                    self.route_class,
                    resolver,
                );
            let (client, current_route) = match deadline {
                Some(deadline) => tokio::time::timeout_at(deadline, building)
                    .await
                    .map_err(|_| RouteAwareRequestError::Timeout)??,
                None => building.await?,
            };
            // Preserve the existing owner's initial configured gateway header.
            // A different original factory route cannot inherit that credential;
            // cross-origin redirects also use the existing sensitive-header rule.
            if previous_route
                .as_ref()
                .is_some_and(|route| route != &current_route)
            {
                request.headers_mut().remove(PROXY_AUTHORIZATION);
            }
            previous_route = Some(current_route);
            if let Some(deadline) = deadline {
                let remaining = deadline
                    .checked_duration_since(tokio::time::Instant::now())
                    .filter(|remaining| !remaining.is_zero())
                    .ok_or(RouteAwareRequestError::Timeout)?;
                *request.timeout_mut() = Some(remaining);
            }
            let method = request.method().clone();
            let headers = request.headers().clone();
            let version = request.version();
            let timeout = request.timeout().copied();
            let replay = request.try_clone();
            let sending = client.execute_without_request_logging(request);
            let response = match deadline {
                Some(deadline) => tokio::time::timeout_at(deadline, sending)
                    .await
                    .map_err(|_| RouteAwareRequestError::Timeout)??,
                None => sending.await?,
            };
            let status = response.status();
            if !self.client_builder.follows_redirects() || !is_redirect(status) {
                return Ok(response);
            }
            let Some(next_url) = redirect_url(&response) else {
                return Ok(response);
            };
            let Some(mut next_request) =
                redirect_request(status, method, headers, version, timeout, replay, next_url)
            else {
                return Ok(response);
            };
            if redirects >= MAX_REDIRECTS {
                return Err(RouteAwareRequestError::TooManyRedirects);
            }
            let next_url = next_request.url().clone();
            remove_sensitive_headers(next_request.headers_mut(), &current_url, &next_url);
            insert_referer(next_request.headers_mut(), &current_url, &next_url);
            // Explicitly release the old response before constructing the next
            // request's route and actual DNS policy. There is no pooled fallback.
            drop(response);
            request = next_request;
            redirects += 1;
        }
    }
}
