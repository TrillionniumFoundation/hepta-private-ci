use super::*;

#[test]
fn initial_cpu_roles_reject_mixed_saved_ids_capabilities_and_shared_groups() -> HostResult<()> {
    let role = Role {
        id: "independent-selector".into(),
        uid: 985,
        gid: 974,
        public_key_hex: "unused-public-field".into(),
        credential_digest: "unused-public-field".into(),
        private_key_path: "/unused-private-path".into(),
    };
    let status = "Uid:\t985 985 985 985\nGid:\t974 974 974 974\nNoNewPrivs:\t1\nCapEff:\t0000000000000000\nCapPrm:\t0000000000000000\nGroups:\t974\n";
    require_actual_status(status, &role)?;
    for changed in [
        status.replace("985 985 985 985", "985 994 985 985"),
        status.replace("974 974 974 974", "974 978 974 974"),
        status.replace("NoNewPrivs:\t1", "NoNewPrivs:\t0"),
        status.replace("CapEff:\t0000000000000000", "CapEff:\t0000000000000001"),
        status.replace("CapPrm:\t0000000000000000", "CapPrm:\t0000000000000001"),
        status.replace("Groups:\t974", "Groups:\t974 978"),
        status.replace("Uid:\t985 985 985 985", "Uid:\t985 985 985"),
    ] {
        assert!(require_actual_status(&changed, &role).is_err());
    }
    Ok(())
}
