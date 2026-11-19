use codex_code_mode_runtime::ExecuteRequest;
use codex_code_mode_runtime::InProcessCodeModeSession;
use codex_code_mode_runtime::RuntimeResponse;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::sync::Barrier;

// Keep this in its own integration-test executable: the first sessions must
// race in a fresh process before any other test initializes V8 or its allocator.
#[test]
fn concurrent_first_sessions_allocate_sandboxed_array_buffers() {
    let start = Arc::new(Barrier::new(/*n*/ 8));
    let workers = (0..8)
        .map(|worker| {
            let start = Arc::clone(&start);
            std::thread::spawn(move || {
                let runtime = tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .expect("build worker runtime");
                start.wait();
                runtime.block_on(async {
                    for iteration in 0..4 {
                        let session = InProcessCodeModeSession::new();
                        let started = session
                            .execute(ExecuteRequest {
                                tool_call_id: format!("startup-{worker}-{iteration}"),
                                enabled_tools: Vec::new(),
                                source: "const values = new Uint8Array(16).fill(42); if (values.reduce((sum, value) => sum + value, 0) !== 672) { throw new Error('array buffer corrupted'); }".to_string(),
                                yield_time_ms: None,
                                max_output_tokens: None,
                            })
                            .await
                            .expect("start concurrent cell");
                        let cell_id = started.cell_id.clone();
                        let response = started
                            .initial_response()
                            .await
                            .expect("execute concurrent cell");
                        assert_eq!(
                            response,
                            RuntimeResponse::Result {
                                cell_id,
                                content_items: Vec::new(),
                                error_text: None,
                            }
                        );
                    }
                });
            })
        })
        .collect::<Vec<_>>();
    for worker in workers {
        worker.join().expect("concurrent worker should finish");
    }
}
