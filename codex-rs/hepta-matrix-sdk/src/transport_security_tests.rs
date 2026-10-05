use matrix_sdk::Client;
use matrix_sdk::ClientBuildError;
use matrix_sdk::HttpError;
use matrix_sdk::ruma::api::MatrixVersion;

#[tokio::test]
async fn explicit_certificate_verification_disable_is_rejected_by_client_build() {
    let result = Client::builder()
        .homeserver_url("https://certificate-policy.example.invalid")
        .server_versions([MatrixVersion::V1_16])
        .disable_ssl_verification()
        .build()
        .await;

    assert!(
        matches!(
            result,
            Err(ClientBuildError::Http(
                HttpError::TlsCertificateVerificationRequired
            ))
        ),
        "an explicit certificate verification bypass must fail during client build: {result:?}"
    );
}
