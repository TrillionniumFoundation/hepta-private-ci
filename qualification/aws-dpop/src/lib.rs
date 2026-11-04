//! Source-bound qualification of the actual AWS login DPoP implementation.
#![allow(dead_code)]

mod login {
    // Exact provider name from the unchanged upstream login module.
    const PROVIDER_NAME: &str = "Login";

    mod token {
        include!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../codex-rs/third_party/aws-config-1.8.12/src/login/token.rs"
        ));
    }

    mod dpop {
        // This compiles the real migrated implementation and its four existing
        // upstream tests, without copying or substituting the signing function.
        include!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../codex-rs/third_party/aws-config-1.8.12/src/login/dpop.rs"
        ));
    }

    #[cfg(test)]
    #[path = "dpop_migration_tests.rs"]
    mod migration_tests;
}
