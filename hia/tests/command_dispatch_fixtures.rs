//! Shared inputs for independent original/native public, effect and cost probes.

use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;

pub type Trace = Arc<Mutex<Vec<String>>>;

pub fn log(trace: &Option<Trace>, message: impl FnOnce() -> String) {
    if let Some(trace) = trace {
        trace
            .lock()
            .unwrap_or_else(|error| panic!("{error}"))
            .push(message());
    }
}

#[derive(Clone)]
pub struct Case {
    pub command: Vec<String>,
    pub buckets: Vec<(String, Vec<u8>)>,
    pub host_paths: Vec<(String, Vec<PathBuf>)>,
    pub resolve: bool,
    pub fallback: Option<u8>,
    pub move_cwd: Option<PathBuf>,
}

impl Default for Case {
    fn default() -> Self {
        Self {
            command: vec!["tool".into(), "é\0e\u{301}".into()],
            buckets: vec![],
            host_paths: vec![],
            resolve: false,
            fallback: Some(1),
            move_cwd: None,
        }
    }
}

macro_rules! dispatch_owner {
    ($module:ident, $api:ident) => {
        mod $module {
            use super::command_dispatch_fixtures::{Case, Trace, log};
            use $api as api;
            use std::any::Any;
            use std::sync::Arc;
            use std::sync::atomic::{AtomicUsize, Ordering};

            struct RecordedRule {
                label: String,
                kind: u8,
                calls: AtomicUsize,
                trace: Option<Trace>,
                move_cwd: Option<std::path::PathBuf>,
            }

            impl std::fmt::Debug for RecordedRule {
                fn fmt(&self, _: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                    panic!("unexpected Rule::Debug callback")
                }
            }

            impl api::Rule for RecordedRule {
                fn program(&self) -> &str {
                    panic!("unexpected Rule::program callback")
                }
                fn as_any(&self) -> &dyn Any {
                    panic!("unexpected Rule::as_any callback")
                }
                fn matches(&self, command: &[String]) -> Option<api::RuleMatch> {
                    let call = self.calls.fetch_add(1, Ordering::Relaxed);
                    log(&self.trace, || format!("rule:{}:{call}:{command:?}", self.label));
                    let kind = match self.kind {
                        7 if call == 0 => 0,
                        7 => 1,
                        8 => if call % 2 == 0 { 0 } else { 6 },
                        9 => panic!("rule sentinel"),
                        10 => {
                            let nested = api::Policy::empty().matches_for_command(
                                command, /*heuristics_fallback*/ None,
                            );
                            assert!(nested.is_empty());
                            log(&self.trace, || "nested-rule-return".into());
                            1
                        }
                        11 => {
                            let cwd = self.move_cwd.as_ref().unwrap_or_else(|| panic!("missing cwd fixture"));
                            std::env::set_current_dir(cwd).unwrap_or_else(|error| panic!("{error}"));
                            log(&self.trace, || "cwd-changed".into());
                            0
                        }
                        kind => kind,
                    };
                    if kind == 0 {
                        return None;
                    }
                    let decision = match (kind - 1) % 3 {
                        0 => api::Decision::Allow,
                        1 => api::Decision::Prompt,
                        _ => api::Decision::Forbidden,
                    };
                    Some(if kind <= 3 {
                        api::RuleMatch::PrefixRuleMatch {
                            matched_prefix: command.to_vec(),
                            decision,
                            resolved_program: Some("/old/metadata".try_into().unwrap_or_else(|error| panic!("{error}"))),
                            justification: Some(format!("理由\0{}:{call}", self.label)),
                        }
                    } else {
                        api::RuleMatch::HeuristicsRuleMatch { command: command.to_vec(), decision }
                    })
                }
            }

            pub fn policy(case: &Case, trace: Option<Trace>) -> api::Policy {
                let mut rules = multimap::MultiMap::new();
                for (key, kinds) in &case.buckets {
                    let bucket = kinds.iter().enumerate().map(|(index, kind)| {
                        Arc::new(RecordedRule {
                            label: format!("{key}:{index}"), kind: *kind,
                            calls: AtomicUsize::new(0), trace: trace.clone(),
                            move_cwd: case.move_cwd.clone(),
                        }) as api::RuleRef
                    }).collect::<Vec<_>>();
                    // Retain a key after explicitly clearing its Vec. This
                    // distinguishes a present empty bucket from a missing one.
                    if bucket.is_empty() {
                        rules.insert(key.clone(), Arc::new(RecordedRule {
                            label: "empty-bucket-fixture".into(), kind: 0,
                            calls: AtomicUsize::new(0), trace: None, move_cwd: None,
                        }) as api::RuleRef);
                        rules.get_vec_mut(key).unwrap_or_else(|| panic!("missing inserted bucket")).clear();
                    } else {
                        rules.insert_many(key.clone(), bucket);
                    }
                    assert!(rules.get_vec(key).is_some());
                }
                let paths = case.host_paths.iter().map(|(key, paths)| {
                    let values = paths.iter().cloned().map(|path| {
                        codex_utils_absolute_path::AbsolutePathBuf::try_from(path)
                            .unwrap_or_else(|error| panic!("{error}"))
                    }).collect::<Vec<_>>();
                    (key.clone(), Arc::from(values))
                }).collect();
                api::Policy::from_parts(rules, vec![], paths)
            }

            pub fn matches(policy: &api::Policy, case: &Case) -> Vec<api::RuleMatch> {
                let callback = |_: &[String]| match case.fallback.unwrap_or(1) {
                    0 => api::Decision::Allow,
                    1 => api::Decision::Prompt,
                    _ => api::Decision::Forbidden,
                };
                let fallback: Option<&dyn Fn(&[String]) -> api::Decision> =
                    case.fallback.map(|_| &callback as _);
                policy.matches_for_command_with_options(
                    &case.command, fallback,
                    &api::MatchOptions { resolve_host_executables: case.resolve },
                )
            }

            pub fn observe(case: &Case, repeats: usize) -> serde_json::Value {
                let trace = Trace::default();
                let policy = policy(case, Some(trace.clone()));
                let mut outputs = Vec::new();
                let callback = |command: &[String]| {
                    log(&Some(trace.clone()), || format!("fallback:{command:?}"));
                    match case.fallback.unwrap_or(1) {
                        0 => api::Decision::Allow,
                        1 => api::Decision::Prompt,
                        _ => api::Decision::Forbidden,
                    }
                };
                let fallback: Option<&dyn Fn(&[String]) -> api::Decision> =
                    case.fallback.map(|_| &callback as _);
                for _ in 0..repeats {
                    let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                        let result = policy.matches_for_command_with_options(
                            &case.command, fallback,
                            &api::MatchOptions { resolve_host_executables: case.resolve },
                        );
                        serde_json::to_value(result).unwrap_or_else(|error| panic!("{error}"))
                    }));
                    let value = match outcome {
                        Ok(result) => serde_json::json!({"matches": result}),
                        Err(error) => {
                            let message = error.downcast_ref::<String>().cloned()
                                .or_else(|| error.downcast_ref::<&str>().map(|text| text.to_string()));
                            serde_json::json!({"panic": message})
                        }
                    };
                    outputs.push(value);
                }
                let events = trace.lock().unwrap_or_else(|error| panic!("{error}")).clone();
                serde_json::json!({"outputs": outputs, "trace": events})
            }

            pub fn evaluations(case: &Case) -> serde_json::Value {
                let policy = policy(case, None);
                let callback = |_: &[String]| api::Decision::Prompt;
                let options = api::MatchOptions { resolve_host_executables: case.resolve };
                let single = policy.check_with_options(&case.command, &callback, &options);
                let multiple = policy.check_multiple_with_options(
                    [case.command.clone(), vec![], case.command.clone()], &callback, &options,
                );
                let default_matches = policy.matches_for_command(&case.command, Some(&callback));
                let default_check = policy.check(&case.command, &callback);
                serde_json::json!({"single": single, "multiple": multiple,
                                  "default_matches": default_matches, "default_check": default_check})
            }

            pub fn mutations_and_overlays() -> serde_json::Value {
                let case = Case { command: vec!["/opt/tool".into(), "".into()],
                    buckets: vec![("tool".into(), vec![1, 4])], resolve: true, ..Case::default() };
                let mut base = policy(&case, None);
                let mut observations = vec![serde_json::json!(matches(&base, &case))];
                for paths in [vec![], vec!["/opt/tool"], vec!["/bad/tool"], vec!["/opt/tool", "/opt/tool"]] {
                    base.set_host_executable_paths("tool".into(), paths.into_iter().map(|path| {
                        path.try_into().unwrap_or_else(|error| panic!("{error}"))
                    }).collect());
                    observations.push(serde_json::json!(matches(&base, &case)));
                }
                for paths in [vec![], vec!["/opt/tool"], vec!["/bad/tool"]] {
                    let overlay_case = Case { buckets: vec![("tool".into(), vec![3, 6])],
                        host_paths: vec![("tool".into(), paths.into_iter().map(std::path::PathBuf::from).collect())],
                        ..Case::default() };
                    let overlay = policy(&overlay_case, None);
                    let merged = base.merge_overlay(&overlay);
                    observations.push(serde_json::json!(matches(&merged, &case)));
                }
                serde_json::json!(observations)
            }
        }
    };
}

pub fn scenarios() -> Vec<(&'static str, Case)> {
    let base = Case::default();
    vec![
        (
            "empty-command",
            Case {
                command: vec![],
                fallback: None,
                ..base.clone()
            },
        ),
        (
            "empty-command-fallback",
            Case {
                command: vec![],
                ..base.clone()
            },
        ),
        ("unknown-exact", base.clone()),
        (
            "exact-prefix",
            Case {
                buckets: vec![("tool".into(), vec![1])],
                ..base.clone()
            },
        ),
        (
            "exact-no-short-circuit",
            Case {
                buckets: vec![("tool".into(), vec![3, 1, 6])],
                ..base.clone()
            },
        ),
        (
            "exact-none-host-same-bucket",
            Case {
                buckets: vec![("tool".into(), vec![7])],
                resolve: true,
                ..base.clone()
            },
        ),
        (
            "host-allowlist-missing",
            Case {
                command: vec!["/opt/tool".into(), "".into()],
                buckets: vec![("tool".into(), vec![1, 4])],
                resolve: true,
                ..base.clone()
            },
        ),
        (
            "host-allowlist-empty",
            Case {
                command: vec!["/opt/tool".into()],
                buckets: vec![("tool".into(), vec![1])],
                host_paths: vec![("tool".into(), vec![])],
                resolve: true,
                ..base.clone()
            },
        ),
        (
            "empty-host-bucket",
            Case {
                command: vec!["/opt/tool".into(), "tail".repeat(4096)],
                buckets: vec![("tool".into(), vec![])],
                resolve: true,
                ..base.clone()
            },
        ),
        (
            "absolute-root",
            Case {
                command: vec!["/".into()],
                resolve: true,
                ..base.clone()
            },
        ),
        (
            "reentrant-rule",
            Case {
                buckets: vec![("tool".into(), vec![10])],
                ..base.clone()
            },
        ),
        (
            "giant-tail-exact-miss",
            Case {
                command: vec!["tool".into(), "x".repeat(1 << 20)],
                buckets: vec![("tool".into(), vec![0])],
                fallback: None,
                ..base
            },
        ),
    ]
}
