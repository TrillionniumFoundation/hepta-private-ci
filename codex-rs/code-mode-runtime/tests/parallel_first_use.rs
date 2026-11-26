use std::sync::Arc;
use std::sync::Barrier;

use codex_code_mode_runtime::V8JitMode;
use codex_code_mode_runtime::initialize_v8;
use pretty_assertions::assert_eq;

// This separate integration-test process starts with an uninitialized V8 backend.
#[test]
fn concurrent_first_isolates_use_initialized_allocator() {
    let barrier = Arc::new(Barrier::new(/*n*/ 8));
    let workers = (0..8)
        .map(|_| {
            let barrier = Arc::clone(&barrier);
            std::thread::spawn(move || {
                barrier.wait();
                initialize_v8(V8JitMode::Enabled).expect("initialize V8");
                barrier.wait();
                let isolate = &mut v8::Isolate::new(Default::default());
                v8::scope!(let scope, isolate);
                let context = v8::Context::new(scope, Default::default());
                let scope = &mut v8::ContextScope::new(scope, context);
                let source = v8::String::new(
                    scope,
                    "const a = new Uint8Array(new ArrayBuffer(16)); a[0] = 3; a[0]",
                )
                .expect("source");
                let script = v8::Script::compile(scope, source, /*origin*/ None).expect("compile");
                script
                    .run(scope)
                    .expect("execute")
                    .to_rust_string_lossy(scope)
            })
        })
        .collect::<Vec<_>>();
    let results = workers
        .into_iter()
        .map(|worker| worker.join().expect("worker completes"))
        .collect::<Vec<_>>();
    assert_eq!(results, vec!["3".to_string(); 8]);
}
