use std::sync::Arc;
use std::sync::Barrier;

use codex_code_mode_runtime::ExecuteRequest;
use codex_code_mode_runtime::InProcessCodeModeSession;
use codex_code_mode_runtime::RuntimeResponse;
use codex_code_mode_runtime::V8JitMode;
use codex_code_mode_runtime::initialize_v8;
use pretty_assertions::assert_eq;

#[test]
fn concurrent_first_sessions_initialize_one_shared_array_buffer_pool() {
    initialize_v8(V8JitMode::Enabled).expect("initialize process V8");
    let barrier = Arc::new(Barrier::new(8));
    std::thread::scope(|threads| {
        let workers = (0..8)
            .map(|index| {
                let barrier = Arc::clone(&barrier);
                threads.spawn(move || {
                    let runtime = tokio::runtime::Builder::new_current_thread()
                        .enable_all()
                        .build()
                        .expect("session runtime");
                    barrier.wait();
                    runtime.block_on(async {
                        let session = InProcessCodeModeSession::new();
                        let started = session.execute(ExecuteRequest {
                            tool_call_id: format!("parallel-{index}"),
                            enabled_tools: Vec::new(),
                            source: format!(
                                "const sum = new Uint8Array(64).fill({index}).reduce((sum, value) => sum + value, 0); if (sum !== {}) throw new Error('cross-session allocation');",
                                64 * index,
                            ),
                            yield_time_ms: None,
                            max_output_tokens: None,
                        }).await.expect("start session cell");
                        let cell_id = started.cell_id.clone();
                        assert_eq!(
                            started.initial_response().await.expect("cell result"),
                            RuntimeResponse::Result {
                                cell_id,
                                content_items: Vec::new(),
                                error_text: None,
                            }
                        );
                    });
                })
            })
            .collect::<Vec<_>>();
        for worker in workers {
            worker.join().expect("session worker should finish");
        }
    });
}
