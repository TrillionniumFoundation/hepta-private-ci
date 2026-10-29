use std::sync::Barrier;
use std::thread;

use codex_code_mode_runtime::ExecuteRequest;
use codex_code_mode_runtime::FunctionCallOutputContentItem;
use codex_code_mode_runtime::InProcessCodeModeSession;
use codex_code_mode_runtime::RuntimeResponse;
use codex_code_mode_runtime::V8JitMode;
use codex_code_mode_runtime::initialize_v8;
use pretty_assertions::assert_eq;

// Keep this in its own integration-test binary: another test must not warm up
// V8's lazily initialized sandbox allocator before the concurrent first cells.
#[test]
fn first_cells_start_concurrently_with_sandbox_array_buffers() {
    initialize_v8(V8JitMode::Enabled).expect("initialize V8 before starting workers");

    const WORKERS: usize = 8;
    let start = Barrier::new(WORKERS);
    thread::scope(|scope| {
        for worker in 0..WORKERS {
            let start = &start;
            scope.spawn(move || {
                let runtime = tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                    .expect("create worker runtime");
                runtime.block_on(async {
                    let service = InProcessCodeModeSession::new();
                    start.wait();

                    let started = service
                        .execute(ExecuteRequest {
                            tool_call_id: format!("startup_{worker}"),
                            enabled_tools: Vec::new(),
                            source: format!(
                                "const buffer = new Uint32Array(4096); \
                                 buffer[0] = {worker}; buffer[4095] = 42; \
                                 text(buffer[0] + buffer[4095]);"
                            ),
                            yield_time_ms: None,
                            max_output_tokens: None,
                        })
                        .await
                        .expect("start concurrent code-mode cell");
                    let cell_id = started.cell_id.clone();
                    let response = started
                        .initial_response()
                        .await
                        .expect("execute concurrent code-mode cell");

                    assert_eq!(
                        response,
                        RuntimeResponse::Result {
                            cell_id,
                            content_items: vec![FunctionCallOutputContentItem::InputText {
                                text: (worker + 42).to_string(),
                            }],
                            error_text: None,
                        }
                    );
                    service.shutdown().await.expect("stop worker session");
                });
            });
        }
    });
}
