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
    use std::sync::Once;

    use super::bazel_target;

    fn initialize_v8() {
        static INIT: Once = Once::new();

        INIT.call_once(|| {
            v8::V8::initialize_platform(v8::new_default_platform(0, false).make_shared());
            v8::V8::initialize();
            // The sandbox allocator must finish its lazy pool initialization
            // before the concurrent smoke tests create their first isolates.
            drop(v8::new_default_allocator());
        });
    }

    fn evaluate_expression(expression: &str) -> String {
        initialize_v8();

        let isolate = &mut v8::Isolate::new(Default::default());
        v8::scope!(let scope, isolate);

        let context = v8::Context::new(scope, Default::default());
        let scope = &mut v8::ContextScope::new(scope, context);
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
        let linked_sandbox = super::linked_v8_has_sandbox();
        // Cargo can unify v8's sandbox feature through another workspace crate,
        // even when this crate did not request it. A requested sandbox is still
        // mandatory; staged supplier smoke tests also assert their exact variant.
        assert!(
            !cfg!(feature = "sandbox") || linked_sandbox,
            "the requested V8 sandbox must be enabled in the linked library"
        );
        if let Some(expected) = std::env::var_os("RUSTY_V8_EXPECT_SANDBOX") {
            let expected = expected
                .into_string()
                .expect("RUSTY_V8_EXPECT_SANDBOX must be UTF-8")
                .parse::<bool>()
                .expect("RUSTY_V8_EXPECT_SANDBOX must be true or false");
            assert_eq!(linked_sandbox, expected);
        }
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
    fn parses_crdtp_dispatchable_messages() {
        let cbor = v8::crdtp::json_to_cbor(br#"{"id":7,"method":"Runtime.evaluate","params":{}}"#)
            .expect("JSON should convert to CBOR");
        let dispatchable = v8::crdtp::Dispatchable::new(&cbor);

        assert!(dispatchable.ok());
        assert_eq!(dispatchable.call_id(), 7);
        assert_eq!(dispatchable.method(), b"Runtime.evaluate");
    }
}
