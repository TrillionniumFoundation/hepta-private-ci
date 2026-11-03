use super::*;

struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Self {
        let nonce = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root =
            std::env::temp_dir().join(format!("hepta-shard-test-{}-{nonce}", std::process::id()));
        fs::create_dir(&root).unwrap();
        Self(root)
    }
    fn store(&self, relative: &str) -> Result<ShardStore, String> {
        let manifest = json!({"schema":"hepta.source-shard-manifest.v1", "source_commit":"a".repeat(40),
            "files":[{"path":relative, "bytes":4, "sha256":Digest32::of_bytes(b"a\nb\n").to_string()}]});
        self.store_manifest(manifest)
    }
    fn store_manifest(&self, manifest: Value) -> Result<ShardStore, String> {
        let path = self.0.join("manifest.json");
        fs::write(&path, serde_json::to_vec(&manifest).unwrap()).unwrap();
        let config = self.0.join("config.json");
        fs::write(
            &config,
            serde_json::to_vec(&json!({"schema":"hepta.source-shard-deployment.v1",
            "shards":[{"manifest":path,"root":self.0}]}))
            .unwrap(),
        )
        .unwrap();
        ShardStore::load(&config)
    }
}

#[test]
fn source_tree_identity_is_verified_and_cannot_claim_a_commit_at_the_same_time() {
    let fixture = Fixture::new();
    fs::write(fixture.0.join("source.rs"), b"a\nb\n").unwrap();
    let files = vec![FileSpec {
        path: "source.rs".to_string(),
        bytes: 4,
        sha256: Digest32::of_bytes(b"a\nb\n").to_string(),
    }];
    let tree = tree_digest(&files).unwrap().to_string();
    assert_eq!(
        tree,
        "9cf0ca7fafefd8f96785f0c7749f58ecc635def158c352e86851cdf3774a6734"
    );
    let mut manifest = json!({"schema":"hepta.source-shard-manifest.v2", "source_commit":null, "source_tree_sha256":tree,
        "files":[{"path":"source.rs", "bytes":4, "sha256":files[0].sha256}]});
    let store = fixture.store_manifest(manifest.clone()).unwrap();
    let audited = store.audit(store.identities()[0]).unwrap();
    assert!(audited["source_commit"].is_null());
    assert_eq!(audited["source_tree_sha256"], tree);
    manifest["source_commit"] = json!("a".repeat(40));
    assert!(fixture.store_manifest(manifest.clone()).is_err());
    manifest["source_commit"] = Value::Null;
    manifest["source_tree_sha256"] = Value::Null;
    assert!(fixture.store_manifest(manifest.clone()).is_err());
    manifest["source_tree_sha256"] = json!("0".repeat(64));
    assert!(fixture.store_manifest(manifest).is_err());
}

#[test]
fn mixed_source_identities_allow_an_empty_central_root_until_transfer_completes() {
    let fixture = Fixture::new();
    let main_root = fixture.0.join("main");
    let incoming = fixture.0.join("incoming");
    fs::create_dir(&main_root).unwrap();
    fs::create_dir(&incoming).unwrap();
    fs::write(main_root.join("main.rs"), b"a\nb\n").unwrap();
    let main_manifest = json!({"schema":"hepta.source-shard-manifest.v1", "source_commit":"a".repeat(40),
        "files":[{"path":"main.rs", "bytes":4, "sha256":Digest32::of_bytes(b"a\nb\n").to_string()}]});
    let files = vec![FileSpec {
        path: "remote.rs".to_string(),
        bytes: 6,
        sha256: Digest32::of_bytes(b"other\n").to_string(),
    }];
    let remote_manifest = json!({"schema":"hepta.source-shard-manifest.v2", "source_commit":null,
        "source_tree_sha256":tree_digest(&files).unwrap().to_string(),
        "files":[{"path":"remote.rs", "bytes":6, "sha256":files[0].sha256}]});
    let main_path = fixture.0.join("main-manifest.json");
    let remote_path = fixture.0.join("remote-manifest.json");
    let main_bytes = serde_json::to_vec(&main_manifest).unwrap();
    let remote_bytes = serde_json::to_vec(&remote_manifest).unwrap();
    fs::write(&main_path, &main_bytes).unwrap();
    fs::write(&remote_path, &remote_bytes).unwrap();
    let config = fixture.0.join("mixed-config.json");
    fs::write(
        &config,
        serde_json::to_vec(
            &json!({"schema":"hepta.source-shard-deployment.v1", "shards":[
        {"manifest":main_path, "root":main_root}, {"manifest":remote_path, "root":incoming}]}),
        )
        .unwrap(),
    )
    .unwrap();
    let store = ShardStore::load(&config).unwrap();
    assert_eq!(store.identities().len(), 2);
    assert_eq!(
        store
            .audit(&Digest32::of_bytes(&main_bytes).to_string())
            .unwrap()["bytes"],
        4
    );
    let remote_identity = Digest32::of_bytes(&remote_bytes).to_string();
    assert!(store.audit(&remote_identity).is_err());
    fs::write(incoming.join("remote.rs"), b"other\n").unwrap();
    let completed = store.audit(&remote_identity).unwrap();
    assert_eq!(completed["bytes"], 6);
    assert!(completed["source_commit"].is_null());
    assert_eq!(
        completed["source_tree_sha256"],
        remote_manifest["source_tree_sha256"]
    );
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn registered_shard_reads_actual_files_and_rejects_post_registration_changes() {
    let fixture = Fixture::new();
    fs::write(fixture.0.join("source.rs"), b"a\nb\n").unwrap();
    let store = fixture.store("source.rs").unwrap();
    let identity = store.identities()[0].to_string();
    let before = store.audit(&identity).unwrap();
    assert_eq!(before["files"], 1);
    assert_eq!(before["bytes"], 4);
    assert_eq!(before["newline_count"], 2);
    fs::write(fixture.0.join("source.rs"), b"c\nd\n").unwrap();
    assert!(store.audit(&identity).is_err());
    assert!(store.audit(&"0".repeat(64)).is_err());
}

#[test]
fn shard_paths_cannot_select_unregistered_parent_or_absolute_files() {
    let fixture = Fixture::new();
    for path in ["../source.rs", "/source.rs", "./source.rs", ""] {
        assert!(fixture.store(path).is_err(), "{path}");
    }
}
