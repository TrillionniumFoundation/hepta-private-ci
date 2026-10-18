use super::*;
use std::os::unix::fs::MetadataExt;
use std::process::Command;

struct Fixture(std::path::PathBuf);
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = Command::new("sudo")
            .args([
                "-n",
                "/usr/bin/python3",
                "-c",
                "import shutil,sys;shutil.rmtree(sys.argv[1])",
            ])
            .arg(&self.0)
            .status();
    }
}

#[test]
#[ignore = "requires sudo: independent root-owned bounded capability fixture, no live keyring"]
fn root_protected_capability_input_denies_writable_and_linked_files() -> Result<()> {
    let ordinary = tempfile::tempdir()?;
    let path = std::path::PathBuf::from(format!(
        "/var/lib/hepta-capability-fixture-{}-{}",
        std::process::id(),
        crate::native_mac::now_unix_ms()?
    ));
    let status=Command::new("sudo").args(["-n","/usr/bin/python3","-c",r#"import os,sys
p=sys.argv[1];gid=int(sys.argv[2]);os.mkdir(p,0o750);os.chown(p,0,gid)
for name,mode,data in [('good',0o640,'c'*64),('writable',0o660,'c'*64),('large',0o640,'c'*257),('invalid',0o640,'c'*64+'\n')]:
 q=p+'/'+name;open(q,'w').write(data);os.chown(q,0,gid);os.chmod(q,mode)
os.link(p+'/good',p+'/linked');os.symlink(p+'/invalid',p+'/symlink')
open(p+'/unique','w').write('c'*64);os.chown(p+'/unique',0,gid);os.chmod(p+'/unique',0o640)
"#]).arg(&path).arg(std::fs::metadata(ordinary.path())?.gid().to_string()).status()?;
    anyhow::ensure!(status.success(), "root capability fixture unavailable");
    let _fixture = Fixture(path.clone());
    assert_eq!(load(&path.join("unique"))?, "c".repeat(64));
    for name in ["good", "linked", "writable", "large", "invalid", "symlink"] {
        assert!(load(&path.join(name)).is_err(), "{name}");
    }
    let unprotected = ordinary.path().join("token");
    std::fs::write(&unprotected, "c".repeat(64))?;
    assert!(load(&unprotected).is_err());
    Ok(())
}
