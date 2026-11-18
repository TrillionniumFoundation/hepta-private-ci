//! Complete dispatcher results and callback traces against the pinned old crate.

#[macro_use]
mod command_dispatch_fixtures;
use command_dispatch_fixtures::Case;
use command_dispatch_fixtures::scenarios;
use serde_json::json;
use std::os::unix::ffi::OsStringExt;

dispatch_owner!(old, original);
dispatch_owner!(new, candidate);

macro_rules! parsed {
    ($api:ident, $source:expr) => {{
        let mut parser = $api::PolicyParser::new();
        match parser.parse("dispatcher-fixture.rules", $source) {
            Err(error) => json!({"error": error.to_string()}),
            Ok(()) => {
                let policy = parser.build();
                let callback = |_: &[String]| $api::Decision::Prompt;
                let mut results = Vec::new();
                for tokens in [vec!["tool", "ok"], vec!["/opt/tool", "ok"], vec!["tool", "bad"], vec![]] {
                    let command = tokens.into_iter().map(str::to_string).collect::<Vec<_>>();
                    results.push(policy.check_with_options(&command, &callback,
                        &$api::MatchOptions { resolve_host_executables: true }));
                }
                json!({"results": results})
            }
        }
    }};
}

fn compare(case: &Case, label: &str) {
    assert_eq!(new::observe(case, 2), old::observe(case, 2), "{label}");
}

fn main() {
    let mut compared = 0_usize;
    let mut evaluations = 0_usize;
    let mut explicit = Vec::new();
    for (label, case) in scenarios() {
        compare(&case, label);
        compared += 1;
        assert_eq!(new::evaluations(&case), old::evaluations(&case), "{label}");
        evaluations += 1;
        explicit.push(label);
    }
    let commands: Vec<Vec<String>> = [
        vec![],
        vec![""],
        vec!["tool"],
        vec!["tool", ""],
        vec!["/opt/tool", "é\0汉"],
        vec!["/opt//./tool/", "e\u{301}"],
        vec!["./tool"],
        vec!["/"],
        vec!["unknown"],
        vec!["~", "tail"],
    ]
    .into_iter()
    .map(|values| values.into_iter().map(str::to_string).collect())
    .collect();
    // Every short exact/host sequence includes non-matches, both variants and
    // all decisions. Keep the actual invocation order visible in the trace.
    for size in 0..=3 {
        for mut encoding in 0..7_usize.pow(size) {
            let mut kinds = Vec::new();
            for _ in 0..size {
                kinds.push((encoding % 7) as u8);
                encoding /= 7;
            }
            for resolve in [false, true] {
                for fallback in [None, Some(0), Some(1), Some(2)] {
                    for command in &commands {
                        let case = Case {
                            command: command.clone(),
                            resolve,
                            fallback,
                            buckets: vec![
                                ("tool".into(), kinds.clone()),
                                ("/opt/tool".into(), vec![0]),
                            ],
                            ..Case::default()
                        };
                        compare(&case, "enumerated");
                        compared += 1;
                    }
                }
            }
        }
    }
    let mut seed = 0x4849_4144_d15c_a7c1_u64;
    for _ in 0..1024 {
        seed ^= seed << 13;
        seed ^= seed >> 7;
        seed ^= seed << 17;
        let allowed = match seed % 5 {
            0 => vec![],
            1 => vec![("tool".into(), vec![])],
            2 => vec![("tool".into(), vec!["/bad/tool".into(), "/opt/tool".into()])],
            3 => vec![(
                "tool".into(),
                vec!["/opt/tool".into(), "/later/tool".into()],
            )],
            _ => vec![(
                "tool".into(),
                vec!["/opt/tool-extra".into(), "/bad/tool".into()],
            )],
        };
        let kinds = (0..seed % 9)
            .map(|at| ((seed >> (at * 6)) % 9) as u8)
            .collect();
        let case = Case {
            command: commands[(seed as usize >> 16) % commands.len()].clone(),
            buckets: vec![("tool".into(), kinds)],
            host_paths: allowed,
            resolve: true,
            fallback: if seed & 16 == 0 {
                None
            } else {
                Some((seed % 3) as u8)
            },
            ..Case::default()
        };
        compare(&case, "deterministic-random");
        compared += 1;
    }
    let non_utf8 =
        std::path::PathBuf::from(std::ffi::OsString::from_vec(b"/opt/\xff/tool".to_vec()));
    for paths in [
        vec![non_utf8.clone(), "/opt/tool".into()],
        vec![non_utf8],
        vec![
            "/opt/tool".into(),
            format!("/giant{}", "x".repeat(1 << 20)).into(),
        ],
    ] {
        let case = Case {
            command: vec!["/opt/tool".into()],
            buckets: vec![("tool".into(), vec![1, 4])],
            host_paths: vec![("tool".into(), paths)],
            resolve: true,
            ..Case::default()
        };
        compare(&case, "non-utf8-or-unvisited-large-path");
        compared += 1;
    }
    for path in ["/é/tool", "/e\u{301}/tool", "/a/../tool", "//opt//./tool/"] {
        for allowed in ["/é/tool", "/e\u{301}/tool", "/tool", "/opt/tool"] {
            let case = Case {
                command: vec![path.into()],
                buckets: vec![("tool".into(), vec![1])],
                host_paths: vec![("tool".into(), vec![allowed.into()])],
                resolve: true,
                ..Case::default()
            };
            compare(&case, "path-component-semantics");
            compared += 1;
        }
    }
    let mutations = new::mutations_and_overlays();
    assert_eq!(mutations, old::mutations_and_overlays());
    let mut parser_cases = 0;
    for source in [
        "prefix_rule(pattern = [\"tool\", [\"ok\", \"good\"]], decision = \"allow\", match = [[\"tool\", \"ok\"]], not_match = [[\"tool\", \"bad\"]])",
        "prefix_rule(pattern = [\"tool\"], decision = \"forbidden\", match = [[\"/opt/tool\"]])",
        "prefix_rule(pattern = [\"tool\", \"ok\"], decision = \"allow\", match = [[\"tool\", \"bad\"]])",
        "prefix_rule(pattern = [\"tool\"], decision = \"allow\", not_match = [[\"/opt/tool\"]])",
    ] {
        assert_eq!(parsed!(candidate, source), parsed!(original, source));
        parser_cases += 1;
    }
    let case = Case {
        buckets: vec![("tool".into(), vec![1])],
        ..Case::default()
    };
    let mut old_policy = old::policy(&case, None);
    let mut new_policy = new::policy(&case, None);
    let old_owned = old::matches(&old_policy, &case);
    let new_owned = new::matches(&new_policy, &case);
    old_policy
        .add_prefix_rule(
            &["tool".into(), "later".into()],
            original::Decision::Forbidden,
        )
        .unwrap_or_else(|error| panic!("{error}"));
    new_policy
        .add_prefix_rule(
            &["tool".into(), "later".into()],
            candidate::Decision::Forbidden,
        )
        .unwrap_or_else(|error| panic!("{error}"));
    drop((old_policy, new_policy));
    assert_eq!(
        serde_json::to_value(new_owned).unwrap(),
        serde_json::to_value(old_owned).unwrap()
    );
    let concurrent = std::thread::scope(|scope| {
        (0..8)
            .map(|worker| {
                scope.spawn(move || {
                    let mut count = 0;
                    for iteration in 0..32 {
                        let case = Case {
                            command: vec!["/opt/tool".into()],
                            resolve: true,
                            buckets: vec![(
                                "tool".into(),
                                vec![(worker % 7) as u8, (iteration % 7) as u8],
                            )],
                            ..Case::default()
                        };
                        compare(&case, "concurrent");
                        count += 1;
                    }
                    count
                })
            })
            .collect::<Vec<_>>()
            .into_iter()
            .map(|thread| thread.join().unwrap())
            .sum::<usize>()
    });
    println!(
        "command_dispatch_public={}",
        json!({"passed": true, "comparisons": compared + concurrent,
        "sequential": compared, "concurrent": concurrent, "evaluation_cases": evaluations,
        "parser_cases": parser_cases, "owned_result_cases": 1, "mutations_and_overlays": mutations.as_array().unwrap().len(),
        "explicit": explicit, "skipped": 0,
        "scope": "actual default/native public dispatch, return ownership, full serialized variants/metadata, callbacks, parser example consumer"})
    );
}
