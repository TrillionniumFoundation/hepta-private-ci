use std::sync::Barrier;

use codex_code_mode_runtime::V8JitMode;
use codex_code_mode_runtime::initialize_v8;
use pretty_assertions::assert_eq;

// Keep this regression in its own integration-test process: another test's
// isolate could otherwise initialize the shared allocator before the race.
#[test]
fn first_isolates_initialize_array_buffers_concurrently() -> Result<(), String> {
    const WORKERS: usize = 8;
    let barrier = Barrier::new(WORKERS);
    let results = std::thread::scope(|thread_scope| -> Result<Vec<String>, String> {
        let workers = (0..WORKERS)
            .map(|_| {
                let barrier = &barrier;
                thread_scope.spawn(move || -> Result<String, String> {
                    barrier.wait();
                    let initialized = initialize_v8(V8JitMode::Enabled);
                    barrier.wait();
                    initialized?;

                    let isolate = &mut v8::Isolate::new(v8::CreateParams::default());
                    v8::scope!(let scope, isolate);
                    let context = v8::Context::new(scope, Default::default());
                    let scope = &mut v8::ContextScope::new(scope, context);
                    let source = v8::String::new(scope, "new Uint8Array([1, 2, 3]).join(',')")
                        .ok_or("create ArrayBuffer test source")?;
                    let script = v8::Script::compile(scope, source, /*origin*/ None)
                        .ok_or("compile ArrayBuffer test source")?;
                    let result = script
                        .run(scope)
                        .ok_or("evaluate ArrayBuffer test source")?;
                    Ok(result.to_rust_string_lossy(scope))
                })
            })
            .collect::<Vec<_>>();
        let mut results = Vec::with_capacity(WORKERS);
        for worker in workers {
            results.push(
                worker
                    .join()
                    .map_err(|_| "isolate startup thread panicked".to_string())??,
            );
        }
        Ok(results)
    })?;
    assert_eq!(results, vec!["1,2,3"; WORKERS]);
    Ok(())
}
