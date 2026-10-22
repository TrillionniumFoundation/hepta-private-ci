use std::sync::Arc;
use std::sync::Barrier;

use codex_code_mode_runtime::V8JitMode;
use codex_code_mode_runtime::initialize_v8;
use pretty_assertions::assert_eq;

// A separate integration-test process keeps the first isolate creation from
// being hidden by another unit test that has already initialized the allocator.
#[test]
fn concurrent_isolates_after_process_initialization() -> Result<(), String> {
    initialize_v8(V8JitMode::Enabled)?;
    let start = Arc::new(Barrier::new(8));
    let workers: Vec<_> = (0..8)
        .map(|_| {
            let start = Arc::clone(&start);
            std::thread::spawn(move || -> Result<(), String> {
                start.wait();
                let isolate = &mut v8::Isolate::new(v8::CreateParams::default());
                v8::scope!(let scope, isolate);
                let context = v8::Context::new(scope, Default::default());
                let scope = &mut v8::ContextScope::new(scope, context);
                let source = v8::String::new(
                    scope,
                    "new Uint8Array(16).fill(7).reduce((a, b) => a + b, 0)",
                )
                .ok_or_else(|| "allocate ArrayBuffer test script".to_string())?;
                let script = v8::Script::compile(scope, source, /*origin*/ None)
                    .ok_or_else(|| "compile ArrayBuffer test script".to_string())?;
                let value = script
                    .run(scope)
                    .ok_or_else(|| "execute ArrayBuffer test script".to_string())?;
                assert_eq!(value.integer_value(scope), Some(112));
                Ok(())
            })
        })
        .collect();
    for worker in workers {
        worker
            .join()
            .map_err(|_| "concurrent isolate worker panicked".to_string())??;
    }
    Ok(())
}
