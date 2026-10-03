use super::*;

fn agent(suffix: u8) -> AgentId {
    AgentId::parse(format!("00000000-0000-4000-8000-{suffix:012x}")).unwrap()
}

#[test]
fn explicit_map_never_falls_back_to_another_agents_identity() {
    let agents = BTreeMap::from([(agent(1), 65532), (agent(2), 65531)]);
    validate(65534, 65534, Some(&agents)).unwrap();
    assert_eq!(uid_for(65534, Some(&agents), &agent(1)).unwrap(), 65532);
    assert_eq!(uid_for(65534, Some(&agents), &agent(2)).unwrap(), 65531);
    assert!(uid_for(65534, Some(&agents), &agent(3)).is_err());
    assert_eq!(
        enrolled_uids(65534, Some(&agents)),
        BTreeSet::from([65531, 65532])
    );
    assert_eq!(uid_for(65534, None, &agent(3)).unwrap(), 65534);
    assert_eq!(enrolled_uids(65534, None), BTreeSet::from([65534]));
}

#[test]
fn map_rejects_root_shared_empty_and_unbounded_identity_sets() {
    for agents in [
        BTreeMap::new(),
        BTreeMap::from([(agent(1), 0)]),
        BTreeMap::from([(agent(1), 65532), (agent(2), 65532)]),
        (1..=1025)
            .map(|index| {
                (
                    AgentId::parse(format!("00000000-0000-4000-8000-{index:012x}")).unwrap(),
                    index,
                )
            })
            .collect(),
    ] {
        assert!(validate(65534, 65534, Some(&agents)).is_err());
    }
    assert!(validate(0, 65534, None).is_err());
    assert!(validate(65534, 0, None).is_err());
}

#[test]
#[ignore = "requires sudo: independent kernel UIDs, private directory reads and signal permission"]
fn actual_private_files_and_signals_reject_other_agent_uid() -> anyhow::Result<()> {
    use std::io::BufRead;
    use std::os::unix::fs::PermissionsExt;
    use std::process::Command;
    use std::process::Stdio;
    if unsafe { libc::geteuid() } != 0 {
        let output = Command::new("sudo").arg("-n").arg(std::env::current_exe()?)
            .args(["--exact", "workload_principal::tests::actual_private_files_and_signals_reject_other_agent_uid", "--ignored", "--nocapture"]).output()?;
        anyhow::ensure!(
            output.status.success() && String::from_utf8_lossy(&output.stdout).contains("1 passed"),
            "root qualification failed: {} {}",
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
        return Ok(());
    }
    let temp = tempfile::Builder::new()
        .prefix("hepta-agent-uids-")
        .tempdir_in("/var/lib")?;
    std::fs::set_permissions(temp.path(), std::fs::Permissions::from_mode(0o755))?;
    for (name, uid) in [("a", 65532), ("b", 65531)] {
        let directory = temp.path().join(name);
        std::fs::create_dir(&directory)?;
        std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o700))?;
        std::os::unix::fs::chown(&directory, Some(uid), Some(65534))?;
        let file = directory.join("private");
        std::fs::write(&file, name)?;
        std::fs::set_permissions(&file, std::fs::Permissions::from_mode(0o600))?;
        std::os::unix::fs::chown(&file, Some(uid), Some(65534))?;
    }
    let code_b = "import os,select,sys;os.setgroups([]);os.setgid(65534);os.setuid(65531);assert open(sys.argv[1]).read()=='b';print('ready',flush=True);select.select([sys.stdin],[],[],20)";
    let mut b = Command::new("/usr/bin/python3")
        .args(["-c", code_b])
        .arg(temp.path().join("b/private"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()?;
    let mut ready = String::new();
    std::io::BufReader::new(b.stdout.take().unwrap()).read_line(&mut ready)?;
    let code_a = r#"import os,sys
os.setgroups([]);os.setgid(65534);os.setuid(65532)
assert open(sys.argv[1]).read()=='a'
try:open(sys.argv[2]).read();raise AssertionError('cross-Agent read allowed')
except PermissionError:pass
try:os.kill(int(sys.argv[3]),0);raise AssertionError('cross-Agent signal allowed')
except PermissionError:pass
print('own-read cross-read-denied signal-denied')
"#;
    let output = Command::new("/usr/bin/python3")
        .args(["-c", code_a])
        .arg(temp.path().join("a/private"))
        .arg(temp.path().join("b/private"))
        .arg(b.id().to_string())
        .output();
    drop(b.stdin.take());
    let b_status = b.wait()?;
    let output = output?;
    assert_eq!(ready.trim(), "ready");
    assert!(b_status.success());
    anyhow::ensure!(
        output.status.success(),
        "UID child failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(
        String::from_utf8(output.stdout)?.trim(),
        "own-read cross-read-denied signal-denied"
    );
    Ok(())
}
