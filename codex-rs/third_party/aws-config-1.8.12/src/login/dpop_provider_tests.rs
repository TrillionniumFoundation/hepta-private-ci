use super::KEY;
use crate::login::LoginCredentialsProvider;
use crate::provider_config::ProviderConfig;
use aws_credential_types::provider::ProvideCredentials;
use aws_sdk_signin::config::RuntimeComponents;
use aws_smithy_async::rt::sleep::TokioSleep;
use aws_smithy_async::time::SharedTimeSource;
use aws_smithy_async::time::TimeSource;
use aws_smithy_runtime_api::client::http::{HttpClient, HttpConnector, HttpConnectorFuture, HttpConnectorSettings, SharedHttpConnector};
use aws_smithy_runtime_api::client::orchestrator::{HttpRequest, HttpResponse};
use aws_smithy_types::body::SdkBody;
use aws_types::os_shim_internal::{Env, Fs};
use aws_types::region::Region;
use p256::ecdsa::signature::Verifier;
use p256::ecdsa::{Signature, VerifyingKey};
use p256::elliptic_curve::sec1::ToSec1Point;
use p256::SecretKey;
use pretty_assertions::assert_eq;
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

const SESSION: &str = "arn:aws:sts::012345678910:assumed-role/Admin/admin";
const NOW: u64 = 1_763_510_400;

#[derive(Debug, Clone)]
struct Clock(Arc<Mutex<SystemTime>>);

impl TimeSource for Clock {
    fn now(&self) -> SystemTime {
        *self.0.lock().unwrap()
    }
}

#[derive(Debug, Clone)]
struct RecordingHttpClient(SharedHttpConnector);

impl HttpClient for RecordingHttpClient {
    fn http_connector(&self, _settings: &HttpConnectorSettings, _components: &RuntimeComponents) -> SharedHttpConnector {
        self.0.clone()
    }
}

#[derive(Debug)]
struct RecordingConnector {
    requests: Arc<Mutex<Vec<HttpRequest>>>,
    response_status: u16,
    expires_in: u64,
}

impl HttpConnector for RecordingConnector {
    fn call(&self, request: HttpRequest) -> HttpConnectorFuture {
        self.requests.lock().unwrap().push(request);
        let body = if self.response_status == 200 {
            serde_json::json!({"accessToken":{"accessKeyId":"REFRESHED-KEY","secretAccessKey":"REFRESHED-SECRET","sessionToken":"REFRESHED-SESSION"},"expiresIn":self.expires_in,"refreshToken":"next-refresh-token"}).to_string()
        } else {
            serde_json::json!({"error":"token_expired","error_description":"Synthetic refresh failure"}).to_string()
        };
        HttpConnectorFuture::ready(Ok(HttpResponse::new(self.response_status.try_into().unwrap(), SdkBody::from(body))))
    }
}

enum CacheLifetime {
    Fresh,
    Due,
}

struct TestResponse {
    status: u16,
    expires_in: u64,
}

struct Scenario {
    config: ProviderConfig,
    fs: Fs,
    path: String,
    original: Vec<u8>,
    requests: Arc<Mutex<Vec<HttpRequest>>>,
    clock: Clock,
}

fn setup(lifetime: CacheLifetime, response: TestResponse) -> Scenario {
    let expiry = match lifetime {
        CacheLifetime::Fresh => "2025-11-19T01:00:00Z",
        CacheLifetime::Due => "2025-11-19T00:01:00Z",
    };
    let original = serde_json::to_vec(&serde_json::json!({"accessToken":{"accessKeyId":"CACHED-KEY","secretAccessKey":"CACHED-SECRET","sessionToken":"CACHED-SESSION","accountId":"012345678910","expiresAt":expiry},"tokenType":"aws_sigv4","refreshToken":"original-refresh-token","clientId":"arn:aws:signin:::devtools/same-device","dpopKey":KEY})).unwrap();
    let path = format!("/test/cache/{}.json", hex::encode(Sha256::digest(SESSION.as_bytes())));
    let fs = Fs::from_map(HashMap::from([(path.clone(), original.clone())]));
    let env = Env::from_slice(&[("HOME", "/test/home"), ("AWS_LOGIN_CACHE_DIRECTORY", "/test/cache")]);
    let requests = Arc::new(Mutex::new(Vec::new()));
    let connector = SharedHttpConnector::new(RecordingConnector { requests: requests.clone(), response_status: response.status, expires_in: response.expires_in });
    let clock = Clock(Arc::new(Mutex::new(UNIX_EPOCH + Duration::from_secs(NOW))));
    let config = ProviderConfig::empty()
        .with_env(env)
        .with_fs(fs.clone())
        .with_http_client(RecordingHttpClient(connector))
        .with_region(Some(Region::from_static("us-east-2")))
        .with_sleep_impl(TokioSleep::new())
        .with_time_source(SharedTimeSource::new(clock.clone()));
    Scenario { config, fs, path, original, requests, clock }
}

fn verify_actual_request(request: &HttpRequest, expected_refresh: &str, expected_iat: u64) {
    assert_eq!(request.method(), "POST");
    let body: serde_json::Value = serde_json::from_slice(request.body().bytes().unwrap()).unwrap();
    assert_eq!(body, serde_json::json!({"clientId":"arn:aws:signin:::devtools/same-device","grantType":"refresh_token","refreshToken":expected_refresh}));
    let dpop = request.headers().get("dpop").expect("actual refresh must carry DPoP");
    let (message, encoded_signature) = dpop.rsplit_once('.').unwrap();
    let (encoded_header, encoded_payload) = message.split_once('.').unwrap();
    let decode = |text| base64_simd::URL_SAFE_NO_PAD.decode_to_vec(text).unwrap();
    let header: serde_json::Value = serde_json::from_slice(&decode(encoded_header)).unwrap();
    let payload: serde_json::Value = serde_json::from_slice(&decode(encoded_payload)).unwrap();
    assert_eq!(header["alg"], "ES256");
    assert_eq!(payload["htm"], "POST");
    assert_eq!(payload["htu"], request.uri().to_string());
    assert_eq!(payload["iat"], expected_iat);
    assert_eq!(uuid::Uuid::parse_str(payload["jti"].as_str().unwrap()).unwrap().get_version_num(), 4);
    let bytes = decode(encoded_signature);
    assert_eq!(bytes.len(), 64);
    let key = SecretKey::from_sec1_pem(KEY).unwrap();
    let public = key.public_key().to_sec1_point(false);
    VerifyingKey::from_sec1_bytes(public.as_bytes()).unwrap().verify(message.as_bytes(), &Signature::from_slice(&bytes).unwrap()).unwrap();
    #[cfg(feature = "sso")]
    ring::signature::UnparsedPublicKey::new(&ring::signature::ECDSA_P256_SHA256_FIXED, public.as_bytes()).verify(message.as_bytes(), &bytes).unwrap();
}

#[tokio::test]
async fn fresh_login_cache_returns_existing_credentials_without_http() {
    let scenario = setup(CacheLifetime::Fresh, TestResponse { status: 200, expires_in: 3600 });
    let provider = LoginCredentialsProvider::builder(SESSION).configure(&scenario.config).build();
    let credentials = provider.provide_credentials().await.unwrap();
    assert_eq!((credentials.access_key_id(), credentials.secret_access_key(), credentials.session_token(), credentials.expiry()), ("CACHED-KEY", "CACHED-SECRET", Some("CACHED-SESSION"), Some(UNIX_EPOCH + Duration::from_secs(NOW + 3600))));
    assert!(scenario.requests.lock().unwrap().is_empty());
    assert_eq!(scenario.fs.read_to_end(&scenario.path).await.unwrap(), scenario.original);
}

#[tokio::test]
async fn signed_refresh_persists_tokens_and_survives_new_provider_then_refreshes_again() {
    let scenario = setup(CacheLifetime::Due, TestResponse { status: 200, expires_in: 3600 });
    let provider = LoginCredentialsProvider::builder(SESSION).configure(&scenario.config).build();
    let credentials = provider.provide_credentials().await.unwrap();
    assert_eq!((credentials.access_key_id(), credentials.secret_access_key(), credentials.session_token(), credentials.account_id().unwrap().as_str(), credentials.expiry()), ("REFRESHED-KEY", "REFRESHED-SECRET", Some("REFRESHED-SESSION"), "012345678910", Some(UNIX_EPOCH + Duration::from_secs(NOW + 3600))));
    let cached: serde_json::Value = serde_json::from_slice(&scenario.fs.read_to_end(&scenario.path).await.unwrap()).unwrap();
    assert_eq!(cached["refreshToken"], "next-refresh-token");
    assert_eq!(cached["dpopKey"], KEY);
    assert_eq!(cached["clientId"], "arn:aws:signin:::devtools/same-device");
    let restarted = LoginCredentialsProvider::builder(SESSION).configure(&scenario.config).build();
    assert_eq!(restarted.provide_credentials().await.unwrap().access_key_id(), "REFRESHED-KEY");
    assert_eq!(scenario.requests.lock().unwrap().len(), 1);
    *scenario.clock.0.lock().unwrap() = UNIX_EPOCH + Duration::from_secs(NOW + 3301);
    assert_eq!(restarted.provide_credentials().await.unwrap().expiry(), Some(UNIX_EPOCH + Duration::from_secs(NOW + 6901)));
    let requests = scenario.requests.lock().unwrap();
    assert_eq!(requests.len(), 2);
    verify_actual_request(&requests[0], "original-refresh-token", NOW);
    verify_actual_request(&requests[1], "next-refresh-token", NOW + 3301);
}

#[tokio::test]
async fn refresh_failure_keeps_existing_cache_bytes() {
    let scenario = setup(CacheLifetime::Due, TestResponse { status: 403, expires_in: 3600 });
    let provider = LoginCredentialsProvider::builder(SESSION).configure(&scenario.config).build();
    assert!(provider.provide_credentials().await.is_err());
    assert_eq!(scenario.fs.read_to_end(&scenario.path).await.unwrap(), scenario.original);
    let requests = scenario.requests.lock().unwrap();
    assert_eq!(requests.len(), 1);
    verify_actual_request(&requests[0], "original-refresh-token", NOW);
}

#[tokio::test]
async fn thirty_second_refresh_throttle_still_refuses_expired_credentials() {
    let scenario = setup(CacheLifetime::Due, TestResponse { status: 200, expires_in: 1 });
    let provider = LoginCredentialsProvider::builder(SESSION).configure(&scenario.config).build();
    assert!(provider.provide_credentials().await.is_ok());
    *scenario.clock.0.lock().unwrap() = UNIX_EPOCH + Duration::from_secs(NOW + 2);
    assert!(provider.provide_credentials().await.is_err());
    assert_eq!(scenario.requests.lock().unwrap().len(), 1);
    *scenario.clock.0.lock().unwrap() = UNIX_EPOCH + Duration::from_secs(NOW + 31);
    assert!(provider.provide_credentials().await.is_ok());
    let requests = scenario.requests.lock().unwrap();
    assert_eq!(requests.len(), 2);
    verify_actual_request(&requests[1], "next-refresh-token", NOW + 31);
}
