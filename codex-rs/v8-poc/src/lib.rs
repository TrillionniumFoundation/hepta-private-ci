//! Bazel-wired proof-of-concept crate reserved for future V8 experiments.

/// Returns the Bazel label for this proof-of-concept crate.
#[must_use]
pub fn bazel_target() -> &'static str {
    "//codex-rs/v8-poc:v8-poc"
}

/// Returns the embedded V8 version.
#[must_use]
pub fn embedded_v8_version() -> &'static str {
    v8::V8::get_version()
}

/// Returns whether the linked V8 library was built with the in-process sandbox.
#[must_use]
pub fn linked_v8_has_sandbox() -> bool {
    unsafe extern "C" {
        fn v8__V8__IsSandboxEnabled() -> bool;
    }

    // `rusty_v8` exposes this symbol for its own sandbox verification tests.
    unsafe { v8__V8__IsSandboxEnabled() }
}

#[cfg(test)]
mod tests {
    use pretty_assertions::assert_eq;
    use std::sync::Arc;
    use std::sync::Barrier;
    use std::sync::Mutex;
    use std::sync::Once;

    use super::bazel_target;

    fn initialize_v8() {
        static INIT: Once = Once::new();

        INIT.call_once(|| {
            v8::V8::initialize_platform(v8::new_default_platform(0, false).make_shared());
            v8::V8::initialize();
        });
    }

    fn evaluate_expression(expression: &str) -> String {
        initialize_v8();

        // The sandboxed allocator initializes a process-wide pool lazily.
        // Protect its first backing-store allocation along with isolate setup;
        // expression execution remains independent after initialization.
        static ISOLATE_INITIALIZATION: Mutex<()> = Mutex::new(());
        let initialization = ISOLATE_INITIALIZATION
            .lock()
            .expect("V8 isolate initialization mutex must not be poisoned");
        let isolate = &mut v8::Isolate::new(Default::default());
        v8::scope!(let scope, isolate);

        let context = v8::Context::new(scope, Default::default());
        let scope = &mut v8::ContextScope::new(scope, context);
        let _initial_buffer = v8::ArrayBuffer::new(scope, /*byte_length*/ 1);
        drop(initialization);
        let source = v8::String::new(scope, expression).expect("expression should be valid UTF-8");
        let script = v8::Script::compile(scope, source, None).expect("expression should compile");
        let result = script.run(scope).expect("expression should evaluate");

        result.to_rust_string_lossy(scope)
    }

    #[test]
    fn exposes_expected_bazel_target() {
        assert_eq!(bazel_target(), "//codex-rs/v8-poc:v8-poc");
    }

    #[test]
    fn exposes_embedded_v8_version() {
        assert!(!super::embedded_v8_version().is_empty());
    }

    #[test]
    fn sandbox_feature_matches_linked_v8() {
        assert_eq!(super::linked_v8_has_sandbox(), cfg!(feature = "sandbox"));
    }

    #[test]
    fn evaluates_integer_addition() {
        assert_eq!(evaluate_expression("1 + 2"), "3");
    }

    #[test]
    fn evaluates_string_concatenation() {
        assert_eq!(evaluate_expression("'hello ' + 'world'"), "hello world");
    }

    #[test]
    fn parallel_expression_evaluation_keeps_isolates_independent() {
        let barrier = Arc::new(Barrier::new(/*n*/ 8));
        let workers = (0..8)
            .map(|value| {
                let barrier = Arc::clone(&barrier);
                std::thread::spawn(move || {
                    barrier.wait();
                    let expression = format!(
                        "const bytes = new Uint8Array(32); bytes.fill({value}); bytes[0] + bytes[31]"
                    );
                    assert_eq!(evaluate_expression(&expression), (value * 2).to_string());
                })
            })
            .collect::<Vec<_>>();
        for worker in workers {
            worker.join().expect("parallel V8 worker should complete");
        }
    }

    #[test]
    fn parses_crdtp_dispatchable_messages() {
        let cbor = v8::crdtp::json_to_cbor(br#"{"id":7,"method":"Runtime.evaluate","params":{}}"#)
            .expect("JSON should convert to CBOR");
        let dispatchable = v8::crdtp::Dispatchable::new(&cbor);

        assert!(dispatchable.ok());
        assert_eq!(dispatchable.call_id(), 7);
        assert_eq!(dispatchable.method(), b"Runtime.evaluate");
    }
}
