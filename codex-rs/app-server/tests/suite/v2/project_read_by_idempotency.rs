use super::*;
use codex_app_server_protocol::ProjectReadByIdempotencyKeyParams;

#[tokio::test]
async fn cold_project_key_read_observes_only_the_existing_binding() -> Result<()> {
    let home = TempDir::new()?;
    let responses =
        create_mock_responses_server_repeating_assistant("no input is dispatched").await;
    MockResponsesConfig::new(&responses.uri())
        .enable_feature(Feature::Sqlite)
        .write(home.path())?;
    let mut app = TestAppServer::builder()
        .with_codex_home(home.path())
        .build_initialized()
        .await?;
    let cwd = AbsolutePathBuf::from_absolute_path(home.path())?;
    let original: ProjectCreateResponse = app
        .request(|request_id| ClientRequest::ProjectCreate {
            request_id,
            params: ProjectCreateParams {
                name: "original project".into(),
                roots: vec![ProjectRoot { path: cwd }],
                metadata: None,
                idempotency_key: "original-idempotency".into(),
            },
        })
        .await?;
    drop(app);
    let mut app = TestAppServer::builder()
        .with_codex_home(home.path())
        .build_initialized()
        .await?;
    let before: ProjectListResponse = app
        .request(|request_id| ClientRequest::ProjectList {
            request_id,
            params: ProjectListParams {
                cursor: None,
                limit: None,
            },
        })
        .await?;
    let observed: ProjectReadResponse = app
        .request(|request_id| ClientRequest::ProjectReadByIdempotencyKey {
            request_id,
            params: ProjectReadByIdempotencyKeyParams {
                idempotency_key: "original-idempotency".into(),
            },
        })
        .await?;
    assert_eq!(observed.project, original.project);
    for key in ["absent-idempotency", ""] {
        let id = app
            .send_raw_request(
                "project/readByIdempotencyKey",
                Some(serde_json::json!({"idempotencyKey":key})),
            )
            .await?;
        let _: JSONRPCError = app
            .read_stream_until_error_message(RequestId::Integer(id))
            .await?;
    }
    let after: ProjectListResponse = app
        .request(|request_id| ClientRequest::ProjectList {
            request_id,
            params: ProjectListParams {
                cursor: None,
                limit: None,
            },
        })
        .await?;
    assert_eq!(after, before);
    Ok(())
}
