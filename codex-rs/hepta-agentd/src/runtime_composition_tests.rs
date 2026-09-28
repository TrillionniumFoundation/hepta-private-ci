use super::*;

#[test]
fn canonical_runtime_profile_is_closed_world() {
    let accepted = [(false, false, false), (true, true, true)];
    for (runner, provider, runtime_codex) in accepted {
        assert!(
            require_intelligence_composition(runner, provider, runtime_codex).is_ok(),
            "complete profile ({runner}, {provider}, {runtime_codex}) was rejected"
        );
    }

    let rejected = [
        (true, false, false, "both a runner"),
        (false, true, false, "both a runner"),
        (true, false, true, "both a runner"),
        (false, true, true, "both a runner"),
        (true, true, false, "installed runtime.codex execution owner"),
        (
            false,
            false,
            true,
            "cannot start without canonical intelligence",
        ),
    ];
    for (runner, provider, runtime_codex, expected) in rejected {
        let error = require_intelligence_composition(runner, provider, runtime_codex)
            .expect_err("partial canonical profile must fail closed");
        assert!(
            error.to_string().contains(expected),
            "wrong rejection for ({runner}, {provider}, {runtime_codex}): {error}"
        );
    }
}
