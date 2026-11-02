//! Pure task-pairing fixture. Full runtime/content qualification is separate.
use serde::{Deserialize, Serialize};
use std::io::{Read, Write};
use std::path::{Component, Path, PathBuf};

mod store {
    use super::*;
    pub fn relative_packet(root: &Path, name: &str) -> Result<PathBuf, String> {
        let parts = Path::new(name).components().collect::<Vec<_>>();
        if parts.len() != 1 || !matches!(parts[0], Component::Normal(_)) {
            return Err("one local packet name required".into());
        }
        Ok(root.join(name))
    }
}
#[path = "joint_native_task.rs"]
mod task;

#[derive(Deserialize)]
struct Case {
    state: task::State,
    action: usize,
    completion: Option<task::Completion>,
}
#[derive(Deserialize)]
struct Request {
    public: task::Public,
    cases: Vec<Case>,
}
#[derive(Serialize)]
struct Row {
    error: bool,
    due: Option<usize>,
    after: Option<task::State>,
    legal: [bool; 6],
    public_features: Vec<f64>,
    history_features: [f64; 12],
    fixed: Vec<usize>,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut input = String::new();
    std::io::stdin().read_to_string(&mut input)?;
    let request: Request = serde_json::from_str(&input)?;
    request.public.validate()?;
    let mut rows = vec![];
    for case in request.cases {
        case.state.validate(&request.public)?;
        let legal = case.state.legal(&request.public);
        let due = case.state.due(&request.public, case.action);
        let successor =
            case.state
                .successor(&request.public, case.action, case.completion.as_ref());
        rows.push(Row {
            error: successor.is_err(),
            due: due.ok().flatten(),
            after: successor.ok(),
            legal,
            public_features: case.state.public_features(&request.public),
            history_features: case.state.history_features(),
            fixed: [0.2, 0.5, 0.8]
                .iter()
                .map(|p| task::fixed_action(&case.state, legal, *p))
                .collect(),
        });
    }
    let output = serde_json::json!({"rows": rows, "public_names": task::public_names(), "actions": task::NAMES});
    std::io::stdout().write_all(serde_json::to_string(&output)?.as_bytes())?;
    Ok(())
}
