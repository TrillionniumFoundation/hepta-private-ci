//! Explicit fixture CLI: recompute a receipt; no signer, acceptance, or effects.
use codex_hepta_evidence::Verify1FixtureGoal;
use codex_hepta_evidence::Verify1Scope;
use codex_hepta_evidence::check_verify1_sqlite;
use codex_hepta_evidence::verify1_receipt_payload;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 4 {
        return Err("usage: verify1_fixture_check DATABASE GOAL_JSON SCOPE_JSON".into());
    }
    let goal: Verify1FixtureGoal = serde_json::from_str(&args[2])?;
    let scope: Verify1Scope = serde_json::from_str(&args[3])?;
    let receipt = check_verify1_sqlite(std::path::Path::new(&args[1]), &goal, &scope).await?;
    let payload = verify1_receipt_payload(&receipt).map_err(std::io::Error::other)?;
    println!("{}", serde_json::to_string(&payload)?);
    Ok(())
}
