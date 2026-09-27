#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, value: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:120]!r}")
    write(path, text.replace(old, new, 1))


# The production invocation builder uses the normal supervised worker entry,
# not the test-only convenience wrapper.
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    "            let mut worker = self.spawn_owner_work(move || provider.build(&identity, &record))?;\n",
    "            let mut worker = self.spawn_owner_work_with_budget(\n                move || provider.build(&identity, &record),\n                Duration::from_millis(remaining_ms),\n            )?;\n",
)

replace_once(
    "codex-rs/hepta-agentd/Cargo.toml",
    "[dev-dependencies]\n",
    "[target.'cfg(unix)'.dependencies]\nlibc = { workspace = true }\n\n[dev-dependencies]\n",
)

replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product.rs",
    "const MAX_INTELLIGENCE_AUTHORITY_FILE_BYTES: u64 = 64 * 1024;\n",
    "const MAX_INTELLIGENCE_AUTHORITY_FILE_BYTES: u64 = 64 * 1024;\nconst MAX_INTELLIGENCE_AUTHORITY_FLOOR_BYTES: u64 = 1024 * 1024;\nconst MAX_INTELLIGENCE_AUTHORITY_FLOOR_RECORDS: usize = 4096;\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product.rs",
    "    telemetry: Option<Arc<crate::AgentdIntelligenceTelemetryV1>>,\n}\n",
    "    telemetry: Option<Arc<crate::AgentdIntelligenceTelemetryV1>>,\n    authority_floor_file: Option<PathBuf>,\n}\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product.rs",
    "        Self { path, verifier, telemetry: None }\n",
    "        Self { path, verifier, telemetry: None, authority_floor_file: None }\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product.rs",
    "        Self { path, verifier, telemetry: Some(telemetry) }\n    }\n\n    fn read(&self, requested: &StableId) -> Result<CurrentOwnerStateV1, CanonicalIntelligenceError> {\n",
    "        Self { path, verifier, telemetry: Some(telemetry), authority_floor_file: None }\n    }\n\n    fn with_authority_floor(mut self, path: Option<PathBuf>) -> Self {\n        self.authority_floor_file = path;\n        self\n    }\n\n    fn read(&self, requested: &StableId) -> Result<CurrentOwnerStateV1, CanonicalIntelligenceError> {\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product.rs",
    dedent(r'''
            let before = std::fs::symlink_metadata(&self.path).map_err(|_| unavailable())?;
            if before.file_type().is_symlink() || !before.is_file() {
                return Err(unavailable());
            }
            let mut handle = std::fs::File::open(&self.path).map_err(|_| unavailable())?;
            let metadata = handle.metadata().map_err(|_| unavailable())?;
            if !metadata.is_file() || metadata.len() == 0 || metadata.len() > MAX_INTELLIGENCE_AUTHORITY_FILE_BYTES {
                return Err(unavailable());
            }
            #[cfg(unix)]
            {
                use std::os::unix::fs::MetadataExt;
                if before.dev() != metadata.dev() || before.ino() != metadata.ino()
                    || metadata.mode() & 0o022 != 0
                {
                    return Err(unavailable());
                }
            }
    ''').lstrip(),
    dedent(r'''
            let mut handle = open_intelligence_regular_no_follow(&self.path)
                .map_err(|_| unavailable())?;
            let metadata = handle.metadata().map_err(|_| unavailable())?;
            if !metadata.is_file()
                || metadata.len() == 0
                || metadata.len() > MAX_INTELLIGENCE_AUTHORITY_FILE_BYTES
            {
                return Err(unavailable());
            }
            #[cfg(unix)]
            {
                use std::os::unix::fs::MetadataExt;
                if metadata.mode() & 0o022 != 0 {
                    return Err(unavailable());
                }
            }
    ''').lstrip(),
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product.rs",
    "        if file.schema_version != 1 || file.authority_epoch == 0 || file.owners.len() != 7 {\n            return Err(unavailable());\n        }\n",
    "        if file.schema_version != 1 || file.authority_epoch == 0 || file.owners.len() != 7 {\n            return Err(unavailable());\n        }\n        if let Some(floor_file) = self.authority_floor_file.as_deref() {\n            verify_and_advance_authority_floor_v1(\n                floor_file,\n                &self.verifier,\n                file.authority_epoch,\n                Digest32::of_bytes(&bytes),\n                requested,\n            )?;\n        }\n",
)

# Insert parent-anchored opens and append-only anti-rollback floor before the
# CanonicalFreshnessOracle implementation.
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product.rs",
    "impl CanonicalFreshnessOracleV1 for FileBackedFreshnessOracleV1 {\n",
    dedent(r'''
    #[cfg(unix)]
    fn open_absolute_no_follow_v1(
        path: &std::path::Path,
        final_flags: libc::c_int,
        mode: libc::mode_t,
    ) -> std::io::Result<std::fs::File> {
        use std::ffi::CString;
        use std::os::fd::AsRawFd;
        use std::os::fd::FromRawFd;
        use std::os::unix::ffi::OsStrExt;
        use std::path::Component;

        if !path.is_absolute() {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "path must be absolute",
            ));
        }
        let mut components = path.components();
        if !matches!(components.next(), Some(Component::RootDir)) {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "path root",
            ));
        }
        let mut names = Vec::new();
        for component in components {
            match component {
                Component::Normal(value) => names.push(value),
                _ => {
                    return Err(std::io::Error::new(
                        std::io::ErrorKind::InvalidInput,
                        "path traversal component",
                    ));
                }
            }
        }
        let Some(final_name) = names.pop() else {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "missing file name",
            ));
        };
        let mut directory = std::fs::File::open("/")?;
        for name in names {
            let name = CString::new(name.as_bytes()).map_err(|_| {
                std::io::Error::new(std::io::ErrorKind::InvalidInput, "NUL in path")
            })?;
            // SAFETY: `name` is a NUL-terminated component without embedded NUL;
            // the returned descriptor is checked before ownership transfer.
            let fd = unsafe {
                libc::openat(
                    directory.as_raw_fd(),
                    name.as_ptr(),
                    libc::O_RDONLY
                        | libc::O_DIRECTORY
                        | libc::O_CLOEXEC
                        | libc::O_NOFOLLOW,
                )
            };
            if fd < 0 {
                return Err(std::io::Error::last_os_error());
            }
            // SAFETY: `fd` is a newly owned successful `openat` descriptor.
            directory = unsafe { std::fs::File::from_raw_fd(fd) };
        }
        let final_name = CString::new(final_name.as_bytes()).map_err(|_| {
            std::io::Error::new(std::io::ErrorKind::InvalidInput, "NUL in file name")
        })?;
        // SAFETY: the parent descriptor is live and `final_name` is valid; the
        // successful descriptor is transferred exactly once to `File`.
        let fd = unsafe {
            libc::openat(
                directory.as_raw_fd(),
                final_name.as_ptr(),
                final_flags | libc::O_CLOEXEC | libc::O_NOFOLLOW | libc::O_NONBLOCK,
                mode,
            )
        };
        if fd < 0 {
            return Err(std::io::Error::last_os_error());
        }
        // SAFETY: `fd` is a newly owned successful `openat` descriptor.
        Ok(unsafe { std::fs::File::from_raw_fd(fd) })
    }

    #[cfg(unix)]
    fn open_intelligence_regular_no_follow(path: &std::path::Path) -> std::io::Result<std::fs::File> {
        open_absolute_no_follow_v1(path, libc::O_RDONLY, 0)
    }

    #[cfg(not(unix))]
    fn open_intelligence_regular_no_follow(path: &std::path::Path) -> std::io::Result<std::fs::File> {
        std::fs::OpenOptions::new().read(true).open(path)
    }

    #[cfg(unix)]
    fn open_intelligence_floor_no_follow(path: &std::path::Path) -> std::io::Result<std::fs::File> {
        open_absolute_no_follow_v1(path, libc::O_RDWR | libc::O_CREAT, 0o600)
    }

    #[cfg(not(unix))]
    fn open_intelligence_floor_no_follow(path: &std::path::Path) -> std::io::Result<std::fs::File> {
        std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .open(path)
    }

    #[cfg(unix)]
    struct IntelligenceFloorLockV1(libc::c_int);

    #[cfg(unix)]
    impl Drop for IntelligenceFloorLockV1 {
        fn drop(&mut self) {
            // SAFETY: this descriptor remains owned by the surrounding `File`.
            let _ = unsafe { libc::flock(self.0, libc::LOCK_UN) };
        }
    }

    #[cfg(unix)]
    fn lock_intelligence_floor_v1(
        file: &std::fs::File,
    ) -> std::io::Result<IntelligenceFloorLockV1> {
        use std::os::fd::AsRawFd;
        let fd = file.as_raw_fd();
        // SAFETY: `fd` is a valid live file descriptor; flock does not assume
        // ownership and the guard releases the advisory lock.
        if unsafe { libc::flock(fd, libc::LOCK_EX) } != 0 {
            return Err(std::io::Error::last_os_error());
        }
        Ok(IntelligenceFloorLockV1(fd))
    }

    fn intelligence_verifier_digest_v1(verifier: &IntelligenceAuthorityVerifierV1) -> Digest32 {
        let mut bytes = b"hepta.agentd.intelligence-authority-verifier.v1\0".to_vec();
        bytes.extend_from_slice(verifier.signer_id.as_bytes());
        bytes.extend_from_slice(&verifier.verifying_key);
        Digest32::of_bytes(&bytes)
    }

    fn verify_and_advance_authority_floor_v1(
        path: &std::path::Path,
        verifier: &IntelligenceAuthorityVerifierV1,
        authority_epoch: u64,
        manifest_digest: Digest32,
        requested: &StableId,
    ) -> Result<(), CanonicalIntelligenceError> {
        use std::io::Read;
        use std::io::Seek;
        use std::io::SeekFrom;
        use std::io::Write;
        use std::str::FromStr;

        let unavailable = || CanonicalIntelligenceError::FreshnessUnavailable(requested.clone());
        if !path.is_absolute() || authority_epoch == 0 || manifest_digest.is_zero() {
            return Err(unavailable());
        }
        let mut file = open_intelligence_floor_no_follow(path).map_err(|_| unavailable())?;
        let metadata = file.metadata().map_err(|_| unavailable())?;
        if !metadata.is_file() || metadata.len() > MAX_INTELLIGENCE_AUTHORITY_FLOOR_BYTES {
            return Err(unavailable());
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            if metadata.mode() & 0o077 != 0 {
                return Err(unavailable());
            }
        }
        #[cfg(unix)]
        let _lock = lock_intelligence_floor_v1(&file).map_err(|_| unavailable())?;

        file.seek(SeekFrom::Start(0)).map_err(|_| unavailable())?;
        let mut bytes = Vec::new();
        Read::take(&mut file, MAX_INTELLIGENCE_AUTHORITY_FLOOR_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| unavailable())?;
        if bytes.len() as u64 > MAX_INTELLIGENCE_AUTHORITY_FLOOR_BYTES {
            return Err(unavailable());
        }
        let complete_end = bytes
            .iter()
            .rposition(|byte| *byte == b'\n')
            .map(|index| index + 1)
            .unwrap_or(0);
        if complete_end == 0 && !bytes.is_empty() {
            return Err(unavailable());
        }
        let verifier_digest = intelligence_verifier_digest_v1(verifier);
        let mut last: Option<(u64, Digest32)> = None;
        let mut records = 0_usize;
        for raw in bytes[..complete_end].split(|byte| *byte == b'\n') {
            if raw.is_empty() {
                continue;
            }
            records = records.checked_add(1).ok_or_else(unavailable)?;
            if records > MAX_INTELLIGENCE_AUTHORITY_FLOOR_RECORDS {
                return Err(unavailable());
            }
            let line = std::str::from_utf8(raw).map_err(|_| unavailable())?;
            let mut fields = line.split_ascii_whitespace();
            let stored_verifier = Digest32::from_str(fields.next().ok_or_else(unavailable)?)
                .map_err(|_| unavailable())?;
            let stored_epoch = fields
                .next()
                .ok_or_else(unavailable)?
                .parse::<u64>()
                .map_err(|_| unavailable())?;
            let stored_manifest = Digest32::from_str(fields.next().ok_or_else(unavailable)?)
                .map_err(|_| unavailable())?;
            if fields.next().is_some()
                || stored_verifier != verifier_digest
                || stored_epoch == 0
                || stored_manifest.is_zero()
                || last.is_some_and(|(previous, _)| stored_epoch <= previous)
            {
                return Err(unavailable());
            }
            last = Some((stored_epoch, stored_manifest));
        }

        if let Some((highest_epoch, highest_manifest)) = last {
            if authority_epoch < highest_epoch
                || (authority_epoch == highest_epoch && manifest_digest != highest_manifest)
            {
                return Err(unavailable());
            }
            if authority_epoch == highest_epoch {
                return Ok(());
            }
        }
        if records >= MAX_INTELLIGENCE_AUTHORITY_FLOOR_RECORDS {
            return Err(unavailable());
        }
        if complete_end < bytes.len() {
            file.set_len(complete_end as u64).map_err(|_| unavailable())?;
        }
        file.seek(SeekFrom::End(0)).map_err(|_| unavailable())?;
        writeln!(
            file,
            "{} {} {}",
            verifier_digest, authority_epoch, manifest_digest
        )
        .and_then(|_| file.sync_all())
        .map_err(|_| unavailable())?;
        Ok(())
    }

    impl CanonicalFreshnessOracleV1 for FileBackedFreshnessOracleV1 {
    ''').lstrip(),
)

replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product.rs",
    "    authority_verifier: IntelligenceAuthorityVerifierV1,\n    evaluation_trust: Option<std::sync::Arc<codex_hepta_learning_ledger::ActivatedLearningTrustV1>>,\n",
    "    authority_verifier: IntelligenceAuthorityVerifierV1,\n    authority_floor_file: Option<PathBuf>,\n    evaluation_trust: Option<std::sync::Arc<codex_hepta_learning_ledger::ActivatedLearningTrustV1>>,\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product.rs",
    "#[cfg(test)]\n#[path = \"intelligence_product_tests.rs\"]\nmod tests;\n",
    "#[cfg(test)]\n#[path = \"intelligence_authority_floor_tests.rs\"]\nmod authority_floor_tests;\n\n#[cfg(test)]\n#[path = \"intelligence_product_tests.rs\"]\nmod tests;\n",
)

replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    "            authority_verifier,\n            evaluation_trust: None,\n",
    "            authority_verifier,\n            authority_floor_file: None,\n            evaluation_trust: None,\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    "    pub fn with_evaluation_trust(\n",
    dedent(r'''
        pub fn with_authority_rollback_floor(
            mut self,
            path: PathBuf,
        ) -> Result<Self, AgentdIntelligenceProductError> {
            if !path.is_absolute()
                || path == self.authority_file
                || self.authority_floor_file.is_some()
            {
                return Err(AgentdIntelligenceProductError::InvalidAuthorityVerifier);
            }
            self.authority_floor_file = Some(path);
            Ok(self)
        }

        #[must_use]
        pub const fn authority_rollback_floor_enabled(&self) -> bool {
            self.authority_floor_file.is_some()
        }

        pub fn with_evaluation_trust(
    ''').lstrip(),
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    "        bytes.extend_from_slice(&self.authority_verifier.verifying_key);\n        bytes.extend_from_slice(&(MAX_CANONICAL_OWNER_WORKERS as u64).to_be_bytes());\n",
    "        bytes.extend_from_slice(&self.authority_verifier.verifying_key);\n        match self.authority_floor_file.as_ref() {\n            Some(path) => {\n                bytes.push(1);\n                let value = path.to_string_lossy();\n                bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());\n                bytes.extend_from_slice(value.as_bytes());\n            }\n            None => bytes.push(0),\n        }\n        bytes.extend_from_slice(&(MAX_CANONICAL_OWNER_WORKERS as u64).to_be_bytes());\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    "        let authority_verifier = self.authority_verifier.clone();\n        let evaluation_trust = self.evaluation_trust.clone();\n",
    "        let authority_verifier = self.authority_verifier.clone();\n        let authority_floor_file = self.authority_floor_file.clone();\n        let evaluation_trust = self.evaluation_trust.clone();\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    "            let mut oracle = FileBackedFreshnessOracleV1::new_observed(\n                authority_file, authority_verifier, Arc::clone(&worker_telemetry),\n            );\n",
    "            let mut oracle = FileBackedFreshnessOracleV1::new_observed(\n                authority_file, authority_verifier, Arc::clone(&worker_telemetry),\n            )\n            .with_authority_floor(authority_floor_file);\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    "                let telemetry = Arc::clone(&self.telemetry);\n                let final_snapshot = snapshot.clone();\n",
    "                let telemetry = Arc::clone(&self.telemetry);\n                let authority_floor_file = self.authority_floor_file.clone();\n                let final_snapshot = snapshot.clone();\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_product_runner.rs",
    "                    let mut oracle = FileBackedFreshnessOracleV1::new_observed(\n                        authority_file, verifier, telemetry,\n                    );\n",
    "                    let mut oracle = FileBackedFreshnessOracleV1::new_observed(\n                        authority_file, verifier, telemetry,\n                    )\n                    .with_authority_floor(authority_floor_file);\n",
)

# A physically executable profile must carry the independently durable floor.
replace_once(
    "codex-rs/hepta-agentd/src/config.rs",
    "        if self.intelligence_closed_loop_host.is_some() {\n",
    "        let runner = self.intelligence_product_runner.as_ref().ok_or_else(|| {\n            AgentdError::Invalid(\"intelligence runner disappeared during closed-loop composition\".to_string())\n        })?;\n        if !runner.authority_rollback_floor_enabled() {\n            return Err(AgentdError::Invalid(\n                \"intelligence closed loop requires an independently durable authority rollback floor\"\n                    .to_string(),\n            ));\n        }\n        if self.intelligence_closed_loop_host.is_some() {\n",
)

write(
    "codex-rs/hepta-agentd/src/intelligence_authority_floor_tests.rs",
    dedent(r'''
    use std::io::Write;

    use codex_hepta_types::Digest32;
    use codex_hepta_types::StableId;

    use super::*;

    fn verifier() -> IntelligenceAuthorityVerifierV1 {
        let signing = ed25519_dalek::SigningKey::from_bytes(&[37_u8; 32]);
        IntelligenceAuthorityVerifierV1 {
            signer_id: "authority.floor.test".to_string(),
            verifying_key: signing.verifying_key().to_bytes(),
        }
    }

    #[test]
    fn authority_floor_rejects_rollback_and_same_epoch_substitution() {
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("authority-floor.log");
        let requested = StableId::new("objective.compiler").unwrap();
        let first = Digest32::of_bytes(b"manifest-one");
        let second = Digest32::of_bytes(b"manifest-two");
        verify_and_advance_authority_floor_v1(&path, &verifier(), 7, first, &requested)
            .unwrap();
        verify_and_advance_authority_floor_v1(&path, &verifier(), 7, first, &requested)
            .unwrap();
        assert!(
            verify_and_advance_authority_floor_v1(&path, &verifier(), 6, first, &requested)
                .is_err()
        );
        assert!(
            verify_and_advance_authority_floor_v1(&path, &verifier(), 7, second, &requested)
                .is_err()
        );
        verify_and_advance_authority_floor_v1(&path, &verifier(), 8, second, &requested)
            .unwrap();
    }

    #[test]
    fn authority_floor_recovers_only_an_incomplete_tail() {
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("authority-floor-tail.log");
        let requested = StableId::new("objective.compiler").unwrap();
        verify_and_advance_authority_floor_v1(
            &path,
            &verifier(),
            11,
            Digest32::of_bytes(b"eleven"),
            &requested,
        )
        .unwrap();
        std::fs::OpenOptions::new()
            .append(true)
            .open(&path)
            .unwrap()
            .write_all(b"partial-crash-record")
            .unwrap();
        verify_and_advance_authority_floor_v1(
            &path,
            &verifier(),
            12,
            Digest32::of_bytes(b"twelve"),
            &requested,
        )
        .unwrap();
        let text = std::fs::read_to_string(path).unwrap();
        assert!(!text.contains("partial-crash-record"));
        assert_eq!(text.lines().count(), 2);
    }

    #[cfg(unix)]
    #[test]
    fn authority_open_rejects_symlinked_parent_and_final_component() {
        use std::os::unix::fs::symlink;

        let root = tempfile::tempdir().unwrap();
        let real = root.path().join("real");
        std::fs::create_dir(&real).unwrap();
        let file = real.join("manifest.json");
        std::fs::write(&file, b"{}").unwrap();
        let parent_link = root.path().join("parent-link");
        symlink(&real, &parent_link).unwrap();
        assert!(open_intelligence_regular_no_follow(&parent_link.join("manifest.json")).is_err());
        let file_link = root.path().join("manifest-link.json");
        symlink(&file, &file_link).unwrap();
        assert!(open_intelligence_regular_no_follow(&file_link).is_err());
    }
    ''').lstrip(),
)
