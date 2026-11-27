//! Run path environment effects in a dedicated child process, never in parallel.

#[macro_use]
mod command_dispatch_fixtures;
use command_dispatch_fixtures::Case;
use command_dispatch_fixtures::Trace;
use command_dispatch_fixtures::log;
use serde_json::json;

dispatch_owner!(old, original);
dispatch_owner!(new, candidate);

struct Commands {
    next: usize,
    trace: Trace,
    mode: String,
}

struct Command {
    index: usize,
    value: Vec<String>,
    trace: Trace,
    panic_as_ref: bool,
}

impl Iterator for Commands {
    type Item = Command;
    fn next(&mut self) -> Option<Self::Item> {
        log(&Some(self.trace.clone()), || format!("next:{}", self.next));
        assert!(
            self.mode != "iterator-panic" || self.next != 1,
            "iterator sentinel"
        );
        if self.mode == "empty" || self.next == 3 {
            return None;
        }
        let index = self.next;
        self.next += 1;
        Some(Command {
            index,
            value: if index == 1 {
                vec![]
            } else {
                vec!["tool".into(), "".into()]
            },
            trace: self.trace.clone(),
            panic_as_ref: self.mode == "as-ref-panic" && index == 1,
        })
    }
}

impl Drop for Commands {
    fn drop(&mut self) {
        log(&Some(self.trace.clone()), || "iterator-drop".into());
    }
}

impl AsRef<[String]> for Command {
    fn as_ref(&self) -> &[String] {
        log(&Some(self.trace.clone()), || {
            format!("as-ref:{}", self.index)
        });
        assert!(!self.panic_as_ref, "as-ref sentinel");
        &self.value
    }
}

impl Drop for Command {
    fn drop(&mut self) {
        log(&Some(self.trace.clone()), || {
            format!("command-drop:{}", self.index)
        });
    }
}

macro_rules! effects {
    ($api:ident, $owner:ident, $mode:expr) => {{
        let mode = $mode;
        let trace = Trace::default();
        let case = Case { buckets: vec![("tool".into(), if mode == "rule-panic" { vec![3, 9, 1] } else { vec![3, 1, 6] })],
            ..Case::default() };
        let policy = $owner::policy(&case, Some(trace.clone()));
        let callback = |command: &[String]| {
            log(&Some(trace.clone()), || format!("fallback:{command:?}"));
            assert!(mode != "fallback-panic", "fallback sentinel");
            let nested = $api::Policy::empty().matches_for_command(command, /*heuristics_fallback*/ None);
            assert!(nested.is_empty());
            log(&Some(trace.clone()), || "nested-fallback-return".into());
            $api::Decision::Prompt
        };
        let iterator = Commands { next: 0, trace: trace.clone(), mode: mode.into() };
        let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            policy.check_multiple_with_options(iterator, &callback,
                &$api::MatchOptions { resolve_host_executables: true })
        }));
        let result = match outcome {
            Ok(value) => json!({"evaluation": value}),
            Err(error) => json!({"panic": error.downcast_ref::<String>().cloned()
                .or_else(|| error.downcast_ref::<&str>().map(|value| value.to_string()))}),
        };
        let events = trace.lock().unwrap_or_else(|error| panic!("{error}")).clone();
        json!({"result": result, "trace": events})
    }};
}

fn main() {
    let root = std::path::PathBuf::from(
        std::env::args()
            .nth(1)
            .unwrap_or_else(|| panic!("isolated effects directory required")),
    );
    assert!(root.is_absolute());
    let start = root.join("start");
    let changed = root.join("changed");
    let home = root.join("home");
    for directory in [&start, &changed, &home] {
        std::fs::create_dir_all(directory).unwrap_or_else(|error| panic!("{error}"));
    }
    assert_eq!(
        std::env::var_os("HOME"),
        Some(home.clone().into_os_string()),
        "the runner must provide HOME only to this isolated process"
    );
    let mut observations = Vec::new();
    let cases = [
        (
            "relative-cwd-after-callback",
            Case {
                command: vec!["tool".into()],
                buckets: vec![("tool".into(), vec![11, 7])],
                host_paths: vec![("tool".into(), vec![changed.join("tool")])],
                move_cwd: Some(changed.clone()),
                resolve: true,
                ..Case::default()
            },
        ),
        (
            "relative-dot",
            Case {
                command: vec!["./tool".into()],
                buckets: vec![("tool".into(), vec![1])],
                host_paths: vec![("tool".into(), vec![start.join("tool")])],
                resolve: true,
                ..Case::default()
            },
        ),
        (
            "tilde-home",
            Case {
                command: vec!["~/tool".into()],
                buckets: vec![("tool".into(), vec![1])],
                host_paths: vec![("tool".into(), vec![home.join("tool")])],
                resolve: true,
                ..Case::default()
            },
        ),
        (
            "empty-token-resolves-cwd",
            Case {
                command: vec!["".into()],
                buckets: vec![("start".into(), vec![1])],
                resolve: true,
                ..Case::default()
            },
        ),
        (
            "exact-rule-panic-after-forbidden",
            Case {
                buckets: vec![("tool".into(), vec![3, 9, 1])],
                ..Case::default()
            },
        ),
        (
            "host-rule-panic",
            Case {
                command: vec!["/opt/tool".into()],
                buckets: vec![("tool".into(), vec![1, 9])],
                resolve: true,
                ..Case::default()
            },
        ),
    ];
    for (name, case) in cases {
        std::env::set_current_dir(&start).unwrap_or_else(|error| panic!("{error}"));
        let expected = old::observe(&case, 1);
        std::env::set_current_dir(&start).unwrap_or_else(|error| panic!("{error}"));
        let actual = new::observe(&case, 1);
        assert_eq!(actual, expected, "{name}");
        observations.push(json!({"case": name, "actual": actual}));
    }
    // A removed current directory makes relative resolution fail while an
    // absolute path still resolves. Both observations use actual path service.
    for absolute in [false, true] {
        let case = Case {
            command: vec![if absolute { "/opt/tool" } else { "tool" }.into()],
            buckets: vec![("tool".into(), if absolute { vec![1] } else { vec![7] })],
            resolve: true,
            ..Case::default()
        };
        let mut outputs = Vec::new();
        for side in ["original", "native"] {
            let deleted = root.join(format!("deleted-{side}-{absolute}"));
            std::env::set_current_dir(&start).unwrap_or_else(|error| panic!("{error}"));
            std::fs::create_dir(&deleted).unwrap_or_else(|error| panic!("{error}"));
            std::env::set_current_dir(&deleted).unwrap_or_else(|error| panic!("{error}"));
            std::fs::remove_dir(&deleted).unwrap_or_else(|error| panic!("{error}"));
            outputs.push(if side == "original" {
                old::observe(&case, 1)
            } else {
                new::observe(&case, 1)
            });
        }
        assert_eq!(outputs[0], outputs[1]);
        observations
            .push(json!({"case": "deleted-cwd", "absolute": absolute, "actual": outputs[1]}));
    }
    std::env::set_current_dir(&start).unwrap_or_else(|error| panic!("{error}"));
    for mode in [
        "normal",
        "empty",
        "rule-panic",
        "fallback-panic",
        "iterator-panic",
        "as-ref-panic",
    ] {
        let expected = effects!(original, old, mode);
        let actual = effects!(candidate, new, mode);
        assert_eq!(actual, expected, "{mode}");
        observations.push(json!({"case": mode, "actual": actual}));
    }
    println!(
        "command_dispatch_effects={}",
        json!({"passed": true, "cases": observations.len(),
        "observations": observations, "skipped": 0,
        "scope": "isolated process cwd/HOME path service, callback/panic ordering, iterator AsRef/Drop, nested sessions"})
    );
}
