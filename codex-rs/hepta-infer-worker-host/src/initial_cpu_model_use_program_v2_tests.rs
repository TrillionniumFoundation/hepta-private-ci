use super::*;

#[test]
fn retained_s_program_checks_the_actual_root_file_and_rejects_wrong_pin_or_identity()
-> HostResult<()> {
    let path = std::path::PathBuf::from("/usr/bin/true");
    let bytes = std::fs::read(&path)?;
    let source = Source {
        path,
        digest: Digest32::of_bytes(&bytes).to_string(),
    };
    let mut program = Program::open(source.clone())?;
    program.revalidate()?;
    program.original.1 = program.original.1.checked_add(1).ok_or("inode overflow")?;
    assert!(program.revalidate().is_err());
    let mut wrong = source;
    wrong.digest = Digest32::of_bytes(b"different actual implementation").to_string();
    assert!(Program::open(wrong).is_err());
    Ok(())
}
