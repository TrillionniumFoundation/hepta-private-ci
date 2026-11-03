#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;
    use std::sync::atomic::{AtomicUsize, Ordering};
    const NAMES: [&str; 5] = ["manifest.json", "corpus.json", "constants.rs", "matrix.json", "supervisor.json"];
    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            static NEXT: AtomicUsize = AtomicUsize::new(0);
            let p = std::env::temp_dir().join(format!("hepta-backing-{}-{}", std::process::id(), NEXT.fetch_add(1, Ordering::Relaxed)));
            fs::create_dir(&p).unwrap();
            fs::create_dir(p.join("physical")).unwrap();
            for name in NAMES { fs::write(p.join("physical").join(name), name).unwrap(); }
            Self(p)
        }
        fn resources(&self) -> Vec<(&'static str, PathBuf)> {
            NAMES.into_iter().map(|n| (n, self.0.join("physical").join(n))).collect()
        }
    }
    impl Drop for Fixture { fn drop(&mut self) { fs::remove_dir_all(&self.0).unwrap(); } }
    #[test] fn regular_backing_passes() { let f=Fixture::new(); assert_eq!(validated_fixture_backing_root(&f.resources()).unwrap(), fs::canonicalize(f.0.join("physical")).unwrap()); }
    #[test] fn symlink_delivery_passes() {
        let f=Fixture::new(); fs::create_dir(f.0.join("delivery")).unwrap();
        let resources: Vec<_> = f.resources().into_iter().map(|(n,p)| { let link=f.0.join("delivery").join(n); std::os::unix::fs::symlink(p,&link).unwrap(); (n,link) }).collect();
        assert_eq!(validated_fixture_backing_root(&resources).unwrap(), fs::canonicalize(f.0.join("physical")).unwrap());
    }
    #[test] fn missing_resource_rejected_even_when_backing_exists() { let f=Fixture::new(); let mut r=f.resources(); r[1].1=f.0.join("missing-delivery"); assert!(validated_fixture_backing_root(&r).is_err()); }
    #[test] fn partial_declaration_rejected() { let f=Fixture::new(); assert!(validated_fixture_backing_root(&f.resources()[..4]).is_err()); }
    #[test] fn different_parent_rejected() { let f=Fixture::new(); fs::create_dir(f.0.join("other")).unwrap(); let mut r=f.resources(); let p=f.0.join("other").join(NAMES[1]); fs::write(&p,b"same").unwrap(); r[1].1=p; assert!(validated_fixture_backing_root(&r).is_err()); }
    #[test] fn extra_file_rejected() { let f=Fixture::new(); fs::write(f.0.join("physical/extra"),b"extra").unwrap(); assert!(validated_fixture_backing_root(&f.resources()).is_err()); }
    #[test] fn directory_entry_rejected() { let f=Fixture::new(); fs::create_dir(f.0.join("physical/extra")).unwrap(); assert!(validated_fixture_backing_root(&f.resources()).is_err()); }
    #[test] fn backing_symlink_entry_rejected() { let f=Fixture::new(); std::os::unix::fs::symlink("manifest.json",f.0.join("physical/extra")).unwrap(); assert!(validated_fixture_backing_root(&f.resources()).is_err()); }
    #[test] fn renamed_backing_rejected() { let f=Fixture::new(); let mut r=f.resources(); r[1].1=r[0].1.clone(); assert!(validated_fixture_backing_root(&r).is_err()); }
    #[test] fn nonregular_resource_rejected() { let f=Fixture::new(); fs::remove_file(f.0.join("physical/manifest.json")).unwrap(); fs::create_dir(f.0.join("physical/manifest.json")).unwrap(); assert!(validated_fixture_backing_root(&f.resources()).is_err()); }
}
