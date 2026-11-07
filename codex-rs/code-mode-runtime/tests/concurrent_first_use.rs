use std::sync::Arc;
use std::sync::Barrier;
use std::thread;
use std::time::Duration;

use codex_code_mode_runtime::ExecuteRequest;
use codex_code_mode_runtime::FunctionCallOutputContentItem;
use codex_code_mode_runtime::InProcessCodeModeSession;
use codex_code_mode_runtime::RuntimeResponse;
use codex_code_mode_runtime::V8JitMode;
use codex_code_mode_runtime::initialize_v8;
use pretty_assertions::assert_eq;

// Keep this as the only test in its integration-test binary so another test
// cannot initialize the process-wide allocator before the first worker wave.
#[test]
fn concurrent_first_code_mode_cells_use_the_sandbox_allocator() {
    const WORKERS: usize = 8;

    // Initialize before spawning threads, including on platforms where V8's
    // thread-local memory-protection state is inherited at thread creation.
    initialize_v8(V8JitMode::Enabled).expect("initialize V8 before concurrent first use");
    unsafe extern "C" {
        fn v8__V8__IsSandboxEnabled() -> bool;
    }
    assert!(
        unsafe { v8__V8__IsSandboxEnabled() },
        "concurrent code mode must link against sandbox-enabled V8"
    );

    for wave in 0..2 {
        let barrier = Arc::new(Barrier::new(WORKERS));
        thread::scope(|scope| {
            let workers = (0..WORKERS)
                .map(|worker_index| {
                    let barrier = Arc::clone(&barrier);
                    scope.spawn(move || {
                        let runtime = tokio::runtime::Builder::new_current_thread()
                            .enable_all()
                            .build()
                            .expect("build code-mode test runtime");
                        let value = wave * WORKERS + worker_index + 1;
                        let last_byte = 255 - value;

                        barrier.wait();
                        runtime.block_on(async {
                            tokio::time::timeout(Duration::from_secs(/*secs*/ 30), async {
                                let session = InProcessCodeModeSession::new();
                                let started = session
                                    .execute(ExecuteRequest {
                                        tool_call_id: format!("wave_{wave}_worker_{worker_index}"),
                                        enabled_tools: Vec::new(),
                                        source: format!(
                                            "const buffer = new ArrayBuffer(4096);\n\
                                             const bytes = new Uint8Array(buffer);\n\
                                             bytes[0] = {value};\n\
                                             bytes[4095] = {last_byte};\n\
                                             text([buffer.byteLength, bytes[0], bytes[4095]].join(':'));"
                                        ),
                                        yield_time_ms: Some(30_000),
                                        max_output_tokens: None,
                                    })
                                    .await
                                    .expect("start concurrent code-mode cell");
                                let cell_id = started.cell_id.clone();
                                let response = started
                                    .initial_response()
                                    .await
                                    .expect("finish concurrent code-mode cell");
                                session.shutdown().await.expect("shut down session");

                                assert_eq!(
                                    response,
                                    RuntimeResponse::Result {
                                        cell_id,
                                        content_items: vec![
                                            FunctionCallOutputContentItem::InputText {
                                                text: format!("4096:{value}:{last_byte}"),
                                            },
                                        ],
                                        error_text: None,
                                    }
                                );
                            })
                            .await
                            .expect("concurrent code-mode session exceeded its deadline");
                        });
                    })
                })
                .collect::<Vec<_>>();

            for worker in workers {
                worker.join().expect("concurrent code-mode worker panicked");
            }
        });
        // The second wave exercises repeated session use. Session shutdown does
        // not join detached native runtime threads, so this is not proof that
        // every first-wave isolate has been dropped.
    }
}
