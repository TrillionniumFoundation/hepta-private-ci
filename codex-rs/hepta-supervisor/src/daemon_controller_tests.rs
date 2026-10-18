use anyhow::Result;

use super::*;

#[test]
fn controller_wire_excludes_administrator_mutations() -> Result<()> {
    for kind in [
        "register_agent",
        "kill",
        "drain",
        "signed_upgrade",
        "upgrade",
        "rollback",
    ] {
        assert!(
            serde_json::from_value::<SupervisorControllerRequest>(serde_json::json!({
                "schema_version": 1, "request_id": 55, "method": { "type": kind }
            }))
            .is_err()
        );
    }
    Ok(())
}
