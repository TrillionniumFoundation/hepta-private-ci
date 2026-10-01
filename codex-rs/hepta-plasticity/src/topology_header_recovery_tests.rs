use super::*;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

struct TestFile(PathBuf);

impl TestFile {
    fn prefix(bytes: &[u8]) -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "hepta-topology-header-{}-{nonce}.journal",
            std::process::id()
        ));
        let mut file = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&path)
            .expect("create");
        file.write_all(bytes).expect("prefix");
        file.sync_all().expect("sync prefix");
        Self(path)
    }

    fn open(&self) -> File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(&self.0)
            .expect("open")
    }
}

impl Drop for TestFile {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.0);
    }
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

#[test]
fn resume_repairs_every_exact_partial_enrollment_header() {
    let scope = digest(b"partial-topology-header-scope");
    let header = encode_header(scope, 41, 8).expect("header");
    for prefix_len in 1..HEADER_SIZE {
        let fixture = TestFile::prefix(&header[..prefix_len]);
        assert_eq!(
            DurableTopologyProposalRegistryV1::reopen_anchored(
                fixture.open(),
                scope,
                41,
                8,
                DurableTopologyRegistryAnchorV1 {
                    sequence: 1,
                    frame_digest: digest(b"acknowledged")
                },
            )
            .err(),
            Some(DurableTopologyRegistryErrorV1::Corrupt)
        );
        assert_eq!(
            DurableTopologyProposalRegistryV1::bootstrap_empty(fixture.open(), scope, 41, 8).err(),
            Some(DurableTopologyRegistryErrorV1::BootstrapRequiresEmptyFile)
        );
        assert_eq!(
            std::fs::read(&fixture.0).expect("preserved prefix"),
            header[..prefix_len]
        );
        let store = DurableTopologyProposalRegistryV1::resume_unacknowledged_bootstrap(
            fixture.open(),
            scope,
            41,
            8,
        )
        .expect("resume enrollment");
        assert_eq!(store.current_anchor(), Ok(None));
        assert_eq!(store.record_count(), Ok(0));
        drop(store);
        assert_eq!(std::fs::read(&fixture.0).expect("repaired header"), header);
    }
}

#[test]
fn resume_rejects_partial_enrollment_context_drift_without_modifying_bytes() {
    let scope = digest(b"partial-topology-header-scope");
    let header = encode_header(scope, 41, 8).expect("header");
    for (label, requested_scope, requested_fence, requested_limit) in [
        ("wrong-scope", digest(b"other-scope"), 41, 8),
        ("wrong-fence", scope, 42, 8),
        ("wrong-limit", scope, 41, 9),
        ("corrupt-prefix", scope, 41, 8),
    ] {
        let mut prefix = header[..HEADER_SIZE - 1].to_vec();
        if label == "corrupt-prefix" {
            prefix[0] ^= 1;
        }
        let fixture = TestFile::prefix(&prefix);
        assert_eq!(
            DurableTopologyProposalRegistryV1::resume_unacknowledged_bootstrap(
                fixture.open(),
                requested_scope,
                requested_fence,
                requested_limit,
            )
            .err(),
            Some(DurableTopologyRegistryErrorV1::ContextMismatch)
        );
        assert_eq!(std::fs::read(&fixture.0).expect("preserved prefix"), prefix);
    }
}
