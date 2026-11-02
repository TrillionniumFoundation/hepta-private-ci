//! Inference-only golden probe. Runtime/content/ACK qualification is separate.
#[path = "../store.rs"]
mod store;
#[path = "../joint_native_task.rs"]
mod task;
#[path = "../joint_native_policy.rs"]
mod policy;
use serde::Deserialize;
use std::io::Read;

#[derive(Deserialize)]
struct Request { public: task::Public, states: Vec<task::State> }

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let path=std::env::args().nth(1).ok_or("policy path required")?;
    let policy:policy::Policy=serde_json::from_slice(&std::fs::read(path)?)?;
    let mut input=String::new();std::io::stdin().read_to_string(&mut input)?;
    let request:Request=serde_json::from_str(&input)?;request.public.validate()?;policy.validate(&request.public)?;
    let predictions=request.states.iter().map(|state|policy.predict(&request.public,state)).collect::<Result<Vec<_>,_>>()?;
    println!("{}",serde_json::to_string(&serde_json::json!({"family":policy.family,"predictions":predictions,"scope":"inference-only"}))?);
    Ok(())
}
