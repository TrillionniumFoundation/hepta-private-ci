// One root-provisioned kernel parent checker shared by the V3 Rust library
// and CLI. The CLI's network-namespace slots count processes locally but are
// NOT host-wide CPU limits: Linux network namespaces can be multiplied.
// A cgroup-v2 parent is an actual aggregate kernel CPU, memory and pids cap
// over all descendant services, including different network namespaces.
//
// This code is an unprivileged reader: it cannot create, replace, widen,
// delegate, remount or migrate an OS resource group. Only an administrator can
// provision/start the fixed parent and place the process inside it. The
// original continuous ledger still owns durable operation reconciliation.
/// Actual kernel counters for the *whole original parent*, not a guest,
/// a given V3 listener or the volatile CPU-credit epoch. Resource samples
/// must never grant W1/transaction/model authority.
#[derive(Clone, Copy, Debug, PartialEq, Eq, serde::Serialize)]
pub struct KernelResourceSample {
    pub cpu_usage_usec: u64,
    pub cpu_nr_periods: u64,
    pub cpu_nr_throttled: u64,
    pub cpu_throttled_usec: u64,
    pub memory_current_bytes: u64,
    pub pids_current: u64,
}

/// These are cumulative kernel CPU deltas; the current memory/task values
/// belong to independent point-in-time samples, not to a delta.
#[derive(Clone, Copy, Debug, PartialEq, Eq, serde::Serialize)]
pub struct KernelCpuDelta {
    pub usage_usec: u64,
    pub nr_periods: u64,
    pub nr_throttled: u64,
    pub throttled_usec: u64,
}

impl KernelResourceSample {
    pub fn cpu_delta_since(self, before: Self) -> crate::Result<KernelCpuDelta> {
        let changed = || crate::Error::from("PUBLIC_HOST_KERNEL_COUNTER_REWIND");
        Ok(KernelCpuDelta {
            usage_usec: self
                .cpu_usage_usec
                .checked_sub(before.cpu_usage_usec)
                .ok_or_else(changed)?,
            nr_periods: self
                .cpu_nr_periods
                .checked_sub(before.cpu_nr_periods)
                .ok_or_else(changed)?,
            nr_throttled: self
                .cpu_nr_throttled
                .checked_sub(before.cpu_nr_throttled)
                .ok_or_else(changed)?,
            throttled_usec: self
                .cpu_throttled_usec
                .checked_sub(before.cpu_throttled_usec)
                .ok_or_else(changed)?,
        })
    }
}

#[cfg(target_os = "linux")]
mod kernel_parent {
    use super::KernelResourceSample;
    use std::{
        borrow::Cow,
        fs,
        io::{self, Read},
        net::SocketAddr,
        os::unix::fs::{MetadataExt, PermissionsExt},
        path::{Path, PathBuf},
    };

    type Result<T> = crate::Result<T>;
    const CGROUP_ROOT: &str = "/sys/fs/cgroup";
    // systemd.slice(5): a no-dash slice name belongs directly to -.slice.
    // system.slice children must instead be named system-<child>.slice.
    // Keep the one original fixed name; do NOT admit caller-selectable slices.
    const PARENT_DIRECTORY: &str = "/sys/fs/cgroup";
    // This is ONE administrator-provisioned parent for all public V3
    // processes. Allowing caller-chosen trnmpon*.slice names would let
    // multiple independent 25%-CPU parents multiply the physical budget.
    const PARENT_NAME: &str = "trnmponpublic.slice";
    fn approved_parent_path(path: &Path) -> bool {
        path.parent() == Some(Path::new(PARENT_DIRECTORY))
            && path.file_name().and_then(|part| part.to_str()) == Some(PARENT_NAME)
    }
    const MAX_MEMORY_BYTES: u64 = 2 * 1024 * 1024 * 1024;
    const MAX_TASKS: u64 = 256;
    #[derive(Debug, Clone, Copy, PartialEq, Eq)]
    struct Limits {
        cpu_quota_us: u64,
        cpu_period_us: u64,
        memory_bytes: u64,
        tasks: u64,
    }

    fn numeric(text: &str, limit: u64) -> Option<u64> {
        let value = text.trim().parse::<u64>().ok()?;
        (value > 0 && value <= limit).then_some(value)
    }

    // The maximum CPU bandwidth is <= 250,000,000 ns per second per
    // entire host parent. Explicit finite ceilings only; never accept "max".
    fn validate_limits(
        cpu: &str,
        burst: &str,
        memory: &str,
        swap: &str,
        pids: &str,
    ) -> Result<Limits> {
        let mut parts = cpu.split_ascii_whitespace();
        let (quota, period) = match (parts.next(), parts.next(), parts.next()) {
            (Some(quota), Some(period), None) => (quota, period),
            _ => return Err("PUBLIC_HOST_KERNEL_LIMITS".into()),
        };
        let quota = numeric(quota, 250_000).ok_or("PUBLIC_HOST_KERNEL_LIMITS")?;
        let period = numeric(period, 1_000_000).ok_or("PUBLIC_HOST_KERNEL_LIMITS")?;
        let memory = numeric(memory, MAX_MEMORY_BYTES).ok_or("PUBLIC_HOST_KERNEL_LIMITS")?;
        let tasks = numeric(pids, MAX_TASKS).ok_or("PUBLIC_HOST_KERNEL_LIMITS")?;
        if quota.checked_mul(4).is_none_or(|value| value > period)
            || burst.trim() != "0"
            || swap.trim() != "0"
        {
            return Err("PUBLIC_HOST_KERNEL_LIMITS".into());
        }
        Ok(Limits {
            cpu_quota_us: quota,
            cpu_period_us: period,
            memory_bytes: memory,
            tasks,
        })
    }

    const MAX_LIMIT_BYTES: usize = 128;

    fn read_limit_text<'a>(
        reader: &mut impl Read,
        bytes: &'a mut [u8; MAX_LIMIT_BYTES + 1],
    ) -> Result<&'a str> {
        let mut used = 0;
        loop {
            // At least one byte remains until overflow is rejected. A short
            // read is not EOF, including at the original 128-byte boundary.
            let count = match reader.read(&mut bytes[used..]) {
                Ok(count) => count,
                Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
                Err(_) => return Err("PUBLIC_HOST_KERNEL_UNAVAILABLE".into()),
            };
            if count == 0 {
                return std::str::from_utf8(&bytes[..used])
                    .map_err(|_| crate::Error::from("PUBLIC_HOST_KERNEL_UNAVAILABLE"));
            }
            used += count;
            if used > MAX_LIMIT_BYTES {
                return Err("PUBLIC_HOST_KERNEL_UNAVAILABLE".into());
            }
        }
    }

    fn read_limit<'a>(path: &Path, bytes: &'a mut [u8; MAX_LIMIT_BYTES + 1]) -> Result<&'a str> {
        // Reopen the actual path on EVERY observation. No descriptor, file
        // contents or prior resource decision survives this read. The bounded
        // stack buffer needs no file-size metadata or heap String allocation.
        let mut file = fs::File::open(path)
            .map_err(|_| crate::Error::from("PUBLIC_HOST_KERNEL_UNAVAILABLE"))?;
        read_limit_text(&mut file, bytes)
    }

    fn limit_paths(parent: &Path) -> [PathBuf; 5] {
        [
            "cpu.max",
            "cpu.max.burst",
            "memory.max",
            "memory.swap.max",
            "pids.max",
        ]
        .map(|name| parent.join(name))
    }

    fn read_limits(paths: &[PathBuf; 5]) -> Result<Limits> {
        let [cpu, burst, memory, swap, pids] = &mut [[0; MAX_LIMIT_BYTES + 1]; 5];
        // Preserve the original read order and parse only AFTER all five
        // complete reads, including the original I/O-before-parse error order.
        validate_limits(
            read_limit(&paths[0], cpu)?,
            read_limit(&paths[1], burst)?,
            read_limit(&paths[2], memory)?,
            read_limit(&paths[3], swap)?,
            read_limit(&paths[4], pids)?,
        )
    }

    // This is a common-case stack size, NOT a new limit on boot or membership
    // text. Longer input continues from the same stream on the original heap
    // path. Unlike read_to_string(File), the short path needs no size metadata.
    const CONTEXT_STACK_BYTES: usize = 256;

    fn read_context_text<'a>(
        reader: &mut impl Read,
        bytes: &'a mut [u8; CONTEXT_STACK_BYTES + 1],
    ) -> io::Result<Cow<'a, str>> {
        let mut used = 0;
        loop {
            let count = match reader.read(&mut bytes[used..]) {
                Ok(count) => count,
                Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
                Err(error) => return Err(error),
            };
            if count == 0 {
                return std::str::from_utf8(&bytes[..used])
                    .map(Cow::Borrowed)
                    .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error));
            }
            used += count;
            if used > CONTEXT_STACK_BYTES {
                let mut complete = bytes[..used].to_vec();
                // Preserve the already consumed prefix and read errors before
                // UTF-8 validation, even when the prefix is malformed. Never
                // reopen here: that could combine two different live files.
                reader.read_to_end(&mut complete)?;
                return String::from_utf8(complete)
                    .map(Cow::Owned)
                    .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error));
            }
        }
    }

    fn read_context<'a>(
        path: &Path,
        bytes: &'a mut [u8; CONTEXT_STACK_BYTES + 1],
    ) -> Result<Cow<'a, str>> {
        // A fresh open and complete read on EVERY check, including the current
        // calling thread's procfs path. Neither a descriptor nor its contents
        // are retained. I/O and UTF-8 errors keep the original context error.
        let mut file =
            fs::File::open(path).map_err(|_| crate::Error::from("PUBLIC_HOST_KERNEL_CONTEXT"))?;
        read_context_text(&mut file, bytes)
            .map_err(|_| crate::Error::from("PUBLIC_HOST_KERNEL_CONTEXT"))
    }

    fn in_parent_cgroup(parent: &str) -> Result<bool> {
        // A process may have independently placed native worker threads in a
        // cgroup-v2 threaded subtree. /proc/self identifies the thread-group
        // leader and cannot attest the actual calling worker's CPU cgroup.
        // The kernel's /proc/thread-self resolves to the current TID.
        let mut bytes = [0; CONTEXT_STACK_BYTES + 1];
        let text = read_context(Path::new("/proc/thread-self/cgroup"), &mut bytes)?;
        cgroup_within_parent(&text, parent)
    }

    fn cgroup_within_parent(text: &str, parent: &str) -> Result<bool> {
        let mut entries = text.lines();
        let only = entries.next().ok_or("PUBLIC_HOST_KERNEL_CONTEXT")?;
        if entries.next().is_some() {
            return Err("PUBLIC_HOST_KERNEL_CONTEXT".into());
        }
        let relative = only
            .strip_prefix("0::/")
            .ok_or("PUBLIC_HOST_KERNEL_CONTEXT")?;
        if relative.is_empty()
            || relative
                .split('/')
                .any(|x| x.is_empty() || x == "." || x == "..")
        {
            return Err("PUBLIC_HOST_KERNEL_CONTEXT".into());
        }
        Ok(within_parent(relative, parent))
    }

    fn within_parent(current: &str, parent: &str) -> bool {
        current == parent
            || current
                .strip_prefix(parent)
                .is_some_and(|suffix| suffix.starts_with('/'))
    }

    /// Accept additional future kernel cpu.stat keys, but never fabricate the
    /// four required counters, accept duplicates or accept malformed/huge input.
    /// The actual sysfs files are read only after the fixed parent was checked.
    fn resource_sample(cpu: &str, memory: &str, tasks: &str) -> Result<KernelResourceSample> {
        const INVALID: &str = "PUBLIC_HOST_KERNEL_COUNTERS";
        if cpu.len() > 2048 || memory.len() > 64 || tasks.len() > 64 {
            return Err(INVALID.into());
        }
        let mut fields = std::collections::BTreeMap::<&str, u64>::new();
        for line in cpu.lines() {
            let mut words = line.split_ascii_whitespace();
            let key = words.next().ok_or(INVALID)?;
            let raw = words.next().ok_or(INVALID)?;
            if words.next().is_some() {
                return Err(INVALID.into());
            }
            let value = raw
                .parse::<u64>()
                .map_err(|_| crate::Error::from(INVALID))?;
            if fields.insert(key, value).is_some() {
                return Err(INVALID.into());
            }
        }
        let required = |key| {
            fields
                .get(key)
                .copied()
                .ok_or_else(|| crate::Error::from(INVALID))
        };
        let current = |raw: &str| -> Result<u64> {
            let mut parts = raw.split_ascii_whitespace();
            let value = parts
                .next()
                .ok_or(INVALID)?
                .parse::<u64>()
                .map_err(|_| crate::Error::from(INVALID))?;
            if parts.next().is_some() {
                return Err(INVALID.into());
            }
            Ok(value)
        };
        Ok(KernelResourceSample {
            cpu_usage_usec: required("usage_usec")?,
            cpu_nr_periods: required("nr_periods")?,
            cpu_nr_throttled: required("nr_throttled")?,
            cpu_throttled_usec: required("throttled_usec")?,
            memory_current_bytes: current(memory)?,
            pids_current: current(tasks)?,
        })
    }

    pub struct KernelBudget {
        parent: PathBuf,
        // Immutable names only. Every check still opens all five actual paths
        // afresh; no descriptor, contents or resource verdict is retained.
        limit_paths: [PathBuf; 5],
        parent_relative: String,
        identity: (u64, u64),
        boot_id: String,
        limits: Limits,
    }
    impl KernelBudget {
        fn check(&self) -> Result<()> {
            let mut boot_bytes = [0; CONTEXT_STACK_BYTES + 1];
            let now_boot = read_context(
                Path::new("/proc/sys/kernel/random/boot_id"),
                &mut boot_bytes,
            )?;
            if now_boot.trim() != self.boot_id {
                return Err("PUBLIC_HOST_KERNEL_REPLACED".into());
            }
            let meta = fs::symlink_metadata(&self.parent)
                .map_err(|_| crate::Error::from("PUBLIC_HOST_KERNEL_REPLACED"))?;
            if !meta.file_type().is_dir()
                || meta.uid() != 0
                || meta.mode() & 0o022 != 0
                || (meta.dev(), meta.ino()) != self.identity
            {
                return Err("PUBLIC_HOST_KERNEL_REPLACED".into());
            }
            if !in_parent_cgroup(&self.parent_relative)? {
                return Err("PUBLIC_HOST_KERNEL_CONTEXT".into());
            }
            let observed = read_limits(&self.limit_paths)?;
            if observed != self.limits {
                return Err("PUBLIC_HOST_KERNEL_LIMITS_CHANGED".into());
            }
            Ok(())
        }
        fn open(path: &str) -> Result<Self> {
            let user_path = Path::new(path);
            if !user_path.is_absolute() {
                return Err("PUBLIC_HOST_KERNEL_PARENT".into());
            }
            let parent = fs::canonicalize(user_path)
                .map_err(|_| crate::Error::from("PUBLIC_HOST_KERNEL_PARENT"))?;
            // A strict systemd-owned *single parent*, not the common cgroup
            // root, any child/service, or a caller-created user.slice.
            if !approved_parent_path(&parent) || parent != user_path {
                return Err("PUBLIC_HOST_KERNEL_PARENT".into());
            }
            if !Path::new("/sys/fs/cgroup/cgroup.controllers").is_file() {
                return Err("PUBLIC_HOST_KERNEL_UNSUPPORTED".into());
            }
            let meta = fs::symlink_metadata(&parent)?;
            if !meta.is_dir() || meta.uid() != 0 || meta.permissions().mode() & 0o022 != 0 {
                return Err("PUBLIC_HOST_KERNEL_PARENT".into());
            }
            let boot = fs::read_to_string("/proc/sys/kernel/random/boot_id")
                .map_err(|_| crate::Error::from("PUBLIC_HOST_KERNEL_CONTEXT"))?;
            // Only this already approved immutable path spelling is retained.
            // The boot, current inode/ownership, calling-thread membership and
            // all five current limits are still observed on every check.
            let parent_relative = parent
                .strip_prefix(CGROUP_ROOT)
                .map_err(|_| crate::Error::from("PUBLIC_HOST_KERNEL_CONTEXT"))?
                .to_str()
                .ok_or("PUBLIC_HOST_KERNEL_CONTEXT")?
                .trim_start_matches('/')
                .to_owned();
            let budget = Self {
                identity: (meta.dev(), meta.ino()),
                boot_id: boot.trim().to_owned(),
                limit_paths: limit_paths(&parent),
                parent_relative,
                parent,
                limits: Limits {
                    cpu_quota_us: 0,
                    cpu_period_us: 0,
                    memory_bytes: 0,
                    tasks: 0,
                },
            };
            let read = |name: &str| -> Result<String> {
                fs::read_to_string(budget.parent.join(name))
                    .map_err(|_| crate::Error::from("PUBLIC_HOST_KERNEL_UNAVAILABLE"))
            };
            let limits = validate_limits(
                &read("cpu.max")?,
                &read("cpu.max.burst")?,
                &read("memory.max")?,
                &read("memory.swap.max")?,
                &read("pids.max")?,
            )?;
            let checked = Self { limits, ..budget };
            checked.check()?;
            Ok(checked)
        }
        pub fn verify(&self) -> Result<()> {
            self.check()
        }

        /// Read-only aggregate kernel accounting. Verify the same fixed
        /// boot/inode/quotas/membership both before and after sampling; if any
        /// counter is unavailable or malformed, never issue a qualified receipt.
        pub fn resource_sample(&self) -> Result<KernelResourceSample> {
            self.check()?;
            let read = |name| -> Result<String> {
                fs::read_to_string(self.parent.join(name))
                    .map_err(|_| crate::Error::from("PUBLIC_HOST_KERNEL_COUNTERS"))
            };
            let sample = resource_sample(
                &read("cpu.stat")?,
                &read("memory.current")?,
                &read("pids.current")?,
            )?;
            self.check()?;
            Ok(sample)
        }
    }

    pub fn require(address: SocketAddr, parent: Option<&str>) -> Result<Option<KernelBudget>> {
        match parent {
            Some(path) => KernelBudget::open(path).map(Some),
            None if !address.ip().is_loopback() => Err("PUBLIC_HOST_KERNEL_REQUIRED".into()),
            None => Ok(None), // Retained loopback-only development tools.
        }
    }

    #[cfg(test)]
    mod tests {
        use super::*;

        struct ShortReads<'a> {
            remaining: &'a [u8],
            interrupts: usize,
            calls: usize,
            eof_seen: bool,
        }
        impl Read for ShortReads<'_> {
            fn read(&mut self, buffer: &mut [u8]) -> io::Result<usize> {
                assert!(!buffer.is_empty(), "empty buffer cannot establish EOF");
                self.calls += 1;
                if self.interrupts > 0 && !self.calls.is_multiple_of(2) {
                    self.interrupts -= 1;
                    return Err(io::ErrorKind::Interrupted.into());
                }
                if self.remaining.is_empty() {
                    self.eof_seen = true;
                    return Ok(0);
                }
                buffer[0] = self.remaining[0];
                self.remaining = &self.remaining[1..];
                Ok(1)
            }
        }

        struct ReadError(io::ErrorKind);
        impl Read for ReadError {
            fn read(&mut self, _: &mut [u8]) -> io::Result<usize> {
                Err(self.0.into())
            }
        }

        #[test]
        fn context_reader_keeps_complete_text_and_unbounded_original_long_input() {
            let mut inputs = vec![b"".to_vec(), b"boot-id\n".to_vec()];
            for length in [
                1,
                CONTEXT_STACK_BYTES - 1,
                CONTEXT_STACK_BYTES,
                CONTEXT_STACK_BYTES + 1,
                4096,
            ] {
                inputs.push(vec![b'x'; length]);
            }
            // A multi-byte character may straddle the stack/heap boundary.
            inputs.push(format!("{}λ", "x".repeat(CONTEXT_STACK_BYTES)).into_bytes());
            inputs.push(format!("{}λ", "x".repeat(CONTEXT_STACK_BYTES - 1)).into_bytes());
            for input in inputs {
                let mut reader = ShortReads {
                    remaining: &input,
                    interrupts: 3,
                    calls: 0,
                    eof_seen: false,
                };
                let mut bytes = [0; CONTEXT_STACK_BYTES + 1];
                let actual = read_context_text(&mut reader, &mut bytes).unwrap();
                let mut reference = String::new();
                io::Cursor::new(&input)
                    .read_to_string(&mut reference)
                    .unwrap();
                assert_eq!(actual.as_ref(), reference);
                assert_eq!(
                    matches!(actual, Cow::Borrowed(_)),
                    input.len() <= CONTEXT_STACK_BYTES
                );
                assert!(reader.eof_seen, "a short read or full stack is not EOF");
                assert!(reader.remaining.is_empty());
            }
        }

        #[test]
        fn context_reader_validates_all_utf8_after_real_eof_on_both_paths() {
            for input in [
                vec![0xff],
                b"0::/trnmponpublic.slice\n\xff".to_vec(),
                b"\xf0\x9f".to_vec(),
                [vec![b'x'; CONTEXT_STACK_BYTES - 1], vec![0xce]].concat(),
                [vec![b'x'; CONTEXT_STACK_BYTES], vec![0xff]].concat(),
                [vec![b'x'; 4096], vec![0xff]].concat(),
            ] {
                let mut reader = ShortReads {
                    remaining: &input,
                    interrupts: 2,
                    calls: 0,
                    eof_seen: false,
                };
                let mut bytes = [0; CONTEXT_STACK_BYTES + 1];
                let actual = read_context_text(&mut reader, &mut bytes).unwrap_err();
                let expected = io::Cursor::new(&input)
                    .read_to_string(&mut String::new())
                    .unwrap_err();
                assert_eq!(actual.kind(), expected.kind());
                assert_eq!(actual.kind(), io::ErrorKind::InvalidData);
                assert!(reader.eof_seen);
            }
        }

        #[test]
        fn context_reader_retains_late_io_error_before_utf8_or_prefix_acceptance() {
            for prefix in [
                b"".to_vec(),
                b"0::/trnmponpublic.slice\n".to_vec(),
                vec![b'x'; CONTEXT_STACK_BYTES],
                vec![b'x'; CONTEXT_STACK_BYTES + 1],
                vec![0xff],
                vec![0xff; 4096],
            ] {
                for kind in [
                    io::ErrorKind::PermissionDenied,
                    io::ErrorKind::UnexpectedEof,
                    io::ErrorKind::Other,
                ] {
                    let mut actual_reader = io::Cursor::new(&prefix).chain(ReadError(kind));
                    let mut expected_reader = io::Cursor::new(&prefix).chain(ReadError(kind));
                    let mut bytes = [0; CONTEXT_STACK_BYTES + 1];
                    let actual = read_context_text(&mut actual_reader, &mut bytes).unwrap_err();
                    let expected = expected_reader
                        .read_to_string(&mut String::new())
                        .unwrap_err();
                    assert_eq!(actual.kind(), expected.kind());
                    assert_eq!(actual.kind(), kind);
                }
            }
        }

        #[test]
        fn context_reader_reopens_actual_path_after_replacement_and_failure() {
            // These temporary bytes exercise only the reader, never Host
            // authority or the fixed root-owned cgroup admission.
            let dir = tempfile::tempdir().unwrap();
            let path = dir.path().join("context");
            let replacement = dir.path().join("replacement");
            let mut bytes = [0; CONTEXT_STACK_BYTES + 1];
            fs::write(&path, "0::/trnmponpublic.slice/first\n").unwrap();
            assert_eq!(
                read_context(&path, &mut bytes).unwrap(),
                fs::read_to_string(&path).unwrap()
            );
            let before = fs::metadata(&path).unwrap();
            let long = format!("0::/trnmponpublic.slice/{}\n", "child".repeat(100));
            fs::write(&replacement, &long).unwrap();
            fs::rename(&replacement, &path).unwrap();
            let after = fs::metadata(&path).unwrap();
            assert_ne!((before.dev(), before.ino()), (after.dev(), after.ino()));
            assert_eq!(read_context(&path, &mut bytes).unwrap(), long);
            fs::write(&path, b"valid-prefix\xff").unwrap();
            assert_eq!(
                read_context(&path, &mut bytes).unwrap_err().to_string(),
                "PUBLIC_HOST_KERNEL_CONTEXT"
            );
            fs::remove_file(&path).unwrap();
            assert_eq!(
                read_context(&path, &mut bytes).unwrap_err().to_string(),
                "PUBLIC_HOST_KERNEL_CONTEXT"
            );
        }

        #[test]
        fn real_proc_context_readers_keep_abba_stage_cost_samples() {
            use std::{hint::black_box, time::Instant};
            let paths = [
                Path::new("/proc/sys/kernel/random/boot_id"),
                Path::new("/proc/thread-self/cgroup"),
            ];
            let expected = paths.map(|path| fs::read_to_string(path).unwrap());
            // Fixed small component observation. No mutation, missing-source
            // skip, whole-Host cost claim or wall-time acceptance assertion.
            const PAIRS_PER_SAMPLE: usize = 64;
            let mut samples = Vec::new();
            let mut all_equal = true;
            for round in 0..16usize {
                for (slot, candidate) in [false, true, true, false].into_iter().enumerate() {
                    let started = Instant::now();
                    let mut observed_bytes = 0usize;
                    let mut errors = Vec::new();
                    let mut same = true;
                    for _ in 0..PAIRS_PER_SAMPLE {
                        for (path, expected) in paths.iter().zip(&expected) {
                            if candidate {
                                let mut bytes = [0; CONTEXT_STACK_BYTES + 1];
                                match read_context(path, &mut bytes) {
                                    Ok(value) => {
                                        same &= black_box(value.as_bytes()) == expected.as_bytes();
                                        observed_bytes += value.len();
                                    }
                                    Err(error) => errors.push(error.to_string()),
                                }
                            } else {
                                match fs::read_to_string(path) {
                                    Ok(value) => {
                                        same &= black_box(value.as_bytes()) == expected.as_bytes();
                                        observed_bytes += value.len();
                                    }
                                    Err(error) => errors.push(error.to_string()),
                                }
                            }
                        }
                    }
                    let wall_ns = started.elapsed().as_nanos();
                    same &= observed_bytes
                        == PAIRS_PER_SAMPLE * expected.iter().map(String::len).sum::<usize>();
                    all_equal &= same && errors.is_empty();
                    samples.push(serde_json::json!({
                        "round": round,
                        "slot": slot,
                        "implementation": if candidate { "candidate" } else { "reference" },
                        "wall_ns": wall_ns,
                        "thread_cpu_ns": null,
                        "complete_reads": PAIRS_PER_SAMPLE * paths.len() - errors.len(),
                        "observed_bytes": observed_bytes,
                        "original_complete_text_equal": same,
                        "errors": errors,
                    }));
                }
            }
            eprintln!(
                "{}",
                serde_json::json!({
                    "schema": "host-context-complete-read-stage-observation-v1",
                    "comparison_order": ["reference", "candidate", "candidate", "reference"],
                    "rounds": 16,
                    "paths": paths,
                    "pairs_per_sample": PAIRS_PER_SAMPLE,
                    "samples": samples,
                    "scope": "two fresh procfs complete text reads only; no authority decision, full Host budget check, Node throughput or CPU attribution",
                    "production_qualified": false,
                })
            );
            assert!(
                all_equal,
                "every fresh procfs read must preserve complete text"
            );
        }

        #[test]
        fn limit_reader_waits_for_real_eof_after_short_reads_and_interruptions() {
            for input in [b"".as_slice(), b"25000 100000\n", &[b' '; 128]] {
                let mut reader = ShortReads {
                    remaining: input,
                    interrupts: input.len() + 1,
                    calls: 0,
                    eof_seen: false,
                };
                let mut bytes = [0; MAX_LIMIT_BYTES + 1];
                assert_eq!(
                    read_limit_text(&mut reader, &mut bytes).unwrap().as_bytes(),
                    input
                );
                assert!(reader.eof_seen);
                assert_eq!(reader.interrupts, 0);
                assert_eq!(reader.calls, 2 * (input.len() + 1));
            }
        }

        #[test]
        fn limit_reader_keeps_exact_128_byte_bound_and_rejects_long_prefixes() {
            for length in [0, 1, 127, 128, 129, 130, 4096] {
                let input = vec![b' '; length];
                let mut reader = io::Cursor::new(input.as_slice());
                let mut bytes = [0; MAX_LIMIT_BYTES + 1];
                let result = read_limit_text(&mut reader, &mut bytes);
                if length <= MAX_LIMIT_BYTES {
                    assert_eq!(result.unwrap().as_bytes(), input);
                    assert_eq!(reader.position(), length as u64);
                } else {
                    assert_eq!(
                        result.unwrap_err().to_string(),
                        "PUBLIC_HOST_KERNEL_UNAVAILABLE"
                    );
                    assert_eq!(reader.position(), (MAX_LIMIT_BYTES + 1) as u64);
                }
            }
        }

        #[test]
        fn limit_reader_checks_complete_utf8_after_fragmented_reads() {
            let valid = format!("{}λ", " ".repeat(126));
            let invalid = [
                vec![0xff],
                b"25000 100000\xff".to_vec(),
                b"\xf0\x9f".to_vec(),
                [vec![b' '; 127], vec![0xce]].concat(),
            ];
            for input in std::iter::once(valid.as_bytes()).chain(invalid.iter().map(Vec::as_slice))
            {
                let mut reader = ShortReads {
                    remaining: input,
                    interrupts: 0,
                    calls: 0,
                    eof_seen: false,
                };
                let mut bytes = [0; MAX_LIMIT_BYTES + 1];
                let result = read_limit_text(&mut reader, &mut bytes);
                match std::str::from_utf8(input) {
                    Ok(expected) => assert_eq!(result.unwrap(), expected),
                    Err(_) => assert_eq!(
                        result.unwrap_err().to_string(),
                        "PUBLIC_HOST_KERNEL_UNAVAILABLE"
                    ),
                }
                assert!(reader.eof_seen);
            }
        }

        #[test]
        fn limit_reader_never_accepts_a_valid_prefix_before_a_read_error() {
            for prefix in [b"".as_slice(), b"25000 100000\n", &[b' '; 128]] {
                for kind in [
                    io::ErrorKind::PermissionDenied,
                    io::ErrorKind::UnexpectedEof,
                    io::ErrorKind::Other,
                ] {
                    let mut reader = io::Cursor::new(prefix).chain(ReadError(kind));
                    let mut bytes = [0; MAX_LIMIT_BYTES + 1];
                    assert_eq!(
                        read_limit_text(&mut reader, &mut bytes)
                            .unwrap_err()
                            .to_string(),
                        "PUBLIC_HOST_KERNEL_UNAVAILABLE"
                    );
                }
            }
        }

        #[test]
        fn limit_reader_reopens_the_current_path_and_propagates_open_failure() {
            // Ordinary temporary files exercise this reader only. They cannot
            // qualify as the fixed root-owned cgroup or its resource budget.
            let dir = tempfile::tempdir().unwrap();
            let path = dir.path().join("cpu.max");
            let replacement = dir.path().join("replacement");
            fs::write(&path, b"25000 100000\n").unwrap();
            let mut bytes = [0; MAX_LIMIT_BYTES + 1];
            assert_eq!(read_limit(&path, &mut bytes).unwrap(), "25000 100000\n");
            let before = fs::metadata(&path).unwrap();
            fs::write(&replacement, b"10000 100000\n").unwrap();
            fs::rename(&replacement, &path).unwrap();
            let after = fs::metadata(&path).unwrap();
            assert_ne!((before.dev(), before.ino()), (after.dev(), after.ino()));
            assert_eq!(read_limit(&path, &mut bytes).unwrap(), "10000 100000\n");
            fs::remove_file(&path).unwrap();
            assert_eq!(
                read_limit(&path, &mut bytes).unwrap_err().to_string(),
                "PUBLIC_HOST_KERNEL_UNAVAILABLE"
            );
        }

        #[test]
        fn limit_reader_keeps_all_five_reads_before_validation_and_observes_changes() {
            let dir = tempfile::tempdir().unwrap();
            // Reuse the exact immutable names across rewrites and removals.
            // This must never reuse the previous file or successful read.
            let paths = limit_paths(dir.path());
            let values = [
                ("cpu.max", "25000 100000\n"),
                ("cpu.max.burst", "0\n"),
                ("memory.max", "268435456\n"),
                ("memory.swap.max", "0\n"),
                ("pids.max", "32\n"),
            ];
            for (name, value) in values {
                fs::write(dir.path().join(name), value).unwrap();
            }
            let initial = read_limits(&paths).unwrap();
            assert_eq!(
                initial,
                validate_limits("25000 100000\n", "0\n", "268435456\n", "0\n", "32\n").unwrap()
            );
            for (name, value) in values {
                let path = dir.path().join(name);
                let mut padded = value.as_bytes().to_vec();
                padded.resize(MAX_LIMIT_BYTES, b' ');
                fs::write(&path, &padded).unwrap();
                assert_eq!(read_limits(&paths).unwrap(), initial);
                padded.push(b' ');
                fs::write(&path, &padded).unwrap();
                assert_eq!(
                    read_limits(&paths).unwrap_err().to_string(),
                    "PUBLIC_HOST_KERNEL_UNAVAILABLE"
                );
                fs::write(&path, value).unwrap();
            }
            fs::write(dir.path().join("cpu.max"), b"10000 100000\n").unwrap();
            assert_ne!(read_limits(&paths).unwrap(), initial);
            fs::write(dir.path().join("cpu.max"), b"malformed").unwrap();
            fs::remove_file(dir.path().join("pids.max")).unwrap();
            assert_eq!(
                read_limits(&paths).unwrap_err().to_string(),
                "PUBLIC_HOST_KERNEL_UNAVAILABLE",
                "late I/O failure still precedes parsing an early malformed value"
            );
            fs::write(dir.path().join("pids.max"), b"32\n").unwrap();
            assert_eq!(
                read_limits(&paths).unwrap_err().to_string(),
                "PUBLIC_HOST_KERNEL_LIMITS"
            );
        }

        const CPU_SAMPLE: &str = "usage_usec 600\nuser_usec 400\nsystem_usec 200\nnr_periods 16\nnr_throttled 4\nthrottled_usec 150\nnr_bursts 0\n";
        #[test]
        fn kernel_resource_counters_require_complete_bounded_real_format() {
            let normal = resource_sample(CPU_SAMPLE, "1000\n", "7\n").unwrap();
            assert_eq!(
                (
                    normal.cpu_usage_usec,
                    normal.cpu_nr_throttled,
                    normal.memory_current_bytes,
                    normal.pids_current
                ),
                (600, 4, 1000, 7)
            );
            for malformed in [
                "usage_usec 600\nnr_periods 16\nnr_throttled 4\n", // missing throttled_usec
                "usage_usec 600\nusage_usec 700\nnr_periods 16\nnr_throttled 4\nthrottled_usec 150\n",
                "usage_usec -1\nnr_periods 16\nnr_throttled 4\nthrottled_usec 150\n",
                "usage_usec 1 2\nnr_periods 16\nnr_throttled 4\nthrottled_usec 150\n",
                "usage_usec max\nnr_periods 16\nnr_throttled 4\nthrottled_usec 150\n",
            ] {
                assert!(resource_sample(malformed, "0", "0").is_err(), "{malformed}");
            }
            assert!(resource_sample(CPU_SAMPLE, "max", "7").is_err());
            assert!(resource_sample(CPU_SAMPLE, "7", "-1").is_err());
            assert!(resource_sample(CPU_SAMPLE, "8 9", "7").is_err());
            assert!(resource_sample(&"z".repeat(2049), "1", "1").is_err());
        }

        #[test]
        fn read_kernel_membership_from_current_os_thread_not_process_leader() {
            // No cgroup mutation: compare the two genuine procfs views for a
            // distinct Rust worker thread and the same kernel TID.
            let join = std::thread::spawn(|| {
                let path = fs::read_link("/proc/thread-self").unwrap();
                let by_tid =
                    fs::read_to_string(Path::new("/proc").join(path).join("cgroup")).unwrap();
                let mut bytes = [0; CONTEXT_STACK_BYTES + 1];
                let by_thread_self =
                    read_context(Path::new("/proc/thread-self/cgroup"), &mut bytes).unwrap();
                assert_eq!(by_thread_self.as_ref(), by_tid);
                assert!(by_tid.starts_with("0::/"), "unified v2 thread entry");
                assert_eq!(by_tid.lines().count(), 1);
            });
            join.join().unwrap();
        }
        #[test]
        fn membership_borrows_current_complete_text_and_keeps_path_boundaries() {
            let parent = "trnmponpublic.slice";
            for text in [
                "0::/trnmponpublic.slice\n",
                "0::/trnmponpublic.slice/child.service\n",
            ] {
                assert!(cgroup_within_parent(text, parent).unwrap());
            }
            for text in [
                "0::/trnmponpublic.slice-other/child.service\n",
                "0::/other/trnmponpublic.slice\n",
                "0::/other.slice/child.service\n",
            ] {
                assert!(!cgroup_within_parent(text, parent).unwrap());
            }
            for text in [
                "",
                "0::/\n",
                "0::/trnmponpublic.slice/\n",
                "0::/trnmponpublic.slice//child\n",
                "0::/trnmponpublic.slice/../child\n",
                "0::/trnmponpublic.slice/./child\n",
                "1::/trnmponpublic.slice\n",
                "0::/trnmponpublic.slice\n0::/other.slice\n",
            ] {
                assert_eq!(
                    cgroup_within_parent(text, parent).unwrap_err().to_string(),
                    "PUBLIC_HOST_KERNEL_CONTEXT",
                    "{text:?}",
                );
            }
        }
        #[test]
        fn real_linux_cgroup_v2_cpu_stat_is_parsed_without_claiming_a_quota() {
            let real = fs::read_to_string("/sys/fs/cgroup/cpu.stat").unwrap();
            // Root cgroup has no required memory.current or pids.current on
            // Linux; the test uses only the real cumulative cpu.stat input.
            let parsed = resource_sample(&real, "0", "0").unwrap();
            assert!(parsed.cpu_usage_usec > 0);
            // Zero nr_periods is expected if the root has no CPU bandwidth cap.
            // Never infer quota enforcement from a successfully parsed sample.
            println!("ACTUAL_KERNEL_CPU_STAT_PARSE_OK real_cpu_usage_positive=true quota_qualified=false");
        }

        #[test]
        fn two_aggregate_samples_never_accept_cpu_counter_rewind_or_mem_task_delta() {
            let first = resource_sample(CPU_SAMPLE, "100", "2").unwrap();
            let second = resource_sample(
                "usage_usec 900\nnr_periods 20\nnr_throttled 5\nthrottled_usec 180\n",
                "20",
                "4",
            )
            .unwrap();
            let delta = second.cpu_delta_since(first).unwrap();
            assert_eq!(
                (
                    delta.usage_usec,
                    delta.nr_periods,
                    delta.nr_throttled,
                    delta.throttled_usec
                ),
                (300, 4, 1, 30)
            );
            assert_eq!(second.memory_current_bytes, 20);
            assert_eq!(second.pids_current, 4);
            let rewind = resource_sample(
                "usage_usec 1000\nnr_periods 20\nnr_throttled 4\nthrottled_usec 180\n",
                "20",
                "4",
            )
            .unwrap();
            assert_eq!(
                rewind.cpu_delta_since(second).unwrap_err().to_string(),
                "PUBLIC_HOST_KERNEL_COUNTER_REWIND"
            );
        }
        #[test]
        fn shipped_systemd_slice_is_the_one_fixed_finite_kernel_parent() {
            // This validates the shipped operator package, not live kernel
            // enforcement. A live systemd service still needs independent
            // membership, controller and real CPU/quota observations.
            let unit = include_str!("../../../../config/systemd/trnmponpublic.slice");
            let mut section = "";
            let mut entries = std::collections::BTreeMap::new();
            for original in unit.lines() {
                let line = original.trim();
                if line.is_empty() || line.starts_with('#') {
                    continue;
                }
                if line.starts_with('[') {
                    assert!(line.ends_with(']'));
                    section = &line[1..line.len() - 1];
                    assert!(matches!(section, "Unit" | "Slice"));
                    continue;
                }
                let (name, value) = line.split_once('=').expect("unit property");
                assert!(
                    entries.insert((section, name), value).is_none(),
                    "duplicate systemd directive would override the audited parent"
                );
            }
            let expected = [
                (("Unit", "StopWhenUnneeded"), "no"),
                (("Slice", "CPUAccounting"), "yes"),
                (("Slice", "CPUQuota"), "25%"),
                (("Slice", "CPUQuotaPeriodSec"), "100ms"),
                (("Slice", "MemoryAccounting"), "yes"),
                (("Slice", "MemoryMax"), "2G"),
                (("Slice", "MemorySwapMax"), "0"),
                (("Slice", "TasksAccounting"), "yes"),
                (("Slice", "TasksMax"), "256"),
            ];
            for (name, expected_value) in expected {
                assert_eq!(
                    entries.get(&name).copied(),
                    Some(expected_value),
                    "{name:?}"
                );
            }
            assert_eq!(
                entries.len(),
                expected.len() + 2,
                "unexpected unit property"
            );
            assert_eq!(
                validate_limits("25000 100000", "0", "2147483648", "0", "256").unwrap(),
                Limits {
                    cpu_quota_us: 25_000,
                    cpu_period_us: 100_000,
                    memory_bytes: 2 * 1024 * 1024 * 1024,
                    tasks: 256,
                }
            );
        }

        #[test]
        fn fixed_parent_constant_is_exactly_the_canonical_directory_and_name() {
            assert_eq!(
                Path::new(super::super::FIXED_PUBLIC_KERNEL_PARENT),
                Path::new(PARENT_DIRECTORY).join(PARENT_NAME)
            );
        }
        #[test]
        fn no_public_nonloopback_without_root_owned_kernel_parent() {
            let any: SocketAddr = "0.0.0.0:31337".parse().unwrap();
            let loopback: SocketAddr = "127.0.0.1:31337".parse().unwrap();
            assert_eq!(
                require(any, None).err().unwrap().to_string(),
                "PUBLIC_HOST_KERNEL_REQUIRED"
            );
            assert!(require(loopback, None).unwrap().is_none());
            assert_eq!(
                require(loopback, Some("/tmp/none"))
                    .err()
                    .unwrap()
                    .to_string(),
                "PUBLIC_HOST_KERNEL_PARENT"
            );
        }
        #[test]
        fn finite_cpu_memory_process_limits_and_burst_required() {
            let good =
                validate_limits("25000 100000\n", "0\n", "268435456\n", "0\n", "32\n").unwrap();
            assert_eq!(good.cpu_quota_us, 25000);
            for cpu in [
                "max 100000",
                "100000 100000",
                "25001 100000",
                "0 100000",
                "25000 0",
                "25000 100000 1",
                "-1 100000",
                "1 1",
            ] {
                assert!(
                    validate_limits(cpu, "0", "268435456", "0", "32").is_err(),
                    "{cpu}"
                );
            }
            for (burst, mem, swap, pids) in [
                ("1", "268435456", "0", "32"),
                ("0", "max", "0", "32"),
                ("0", "268435456", "1", "32"),
                ("0", "268435456", "0", "max"),
                ("0", "268435456", "0", "257"),
            ] {
                assert!(validate_limits("25000 100000", burst, mem, swap, pids).is_err());
            }
            assert!(validate_limits("1000 10000", "0", "33554432", "0", "4").is_ok());
        }

        #[test]
        fn cpu_limit_requires_exactly_two_ascii_whitespace_tokens() {
            let expected = validate_limits("25000 100000", "0", "268435456", "0", "32").unwrap();
            for cpu in [
                "25000 100000",
                " \t25000\t100000 \r\n",
                "\u{c}25000\u{c}100000",
                // Original numeric() trims Unicode at each token's edges.
                "\u{a0}25000 100000\u{a0}",
            ] {
                assert_eq!(
                    validate_limits(cpu, "0", "268435456", "0", "32").unwrap(),
                    expected,
                    "{cpu:?}"
                );
            }
            for cpu in [
                "",
                " \t\r\n",
                "25000",
                "25000 100000 0",
                "25000 100000\tinvalid\nmore",
                "25000\u{b}100000",
                "25000\u{a0}100000",
                "25000 100000 \0",
            ] {
                assert_eq!(
                    validate_limits(cpu, "0", "268435456", "0", "32")
                        .unwrap_err()
                        .to_string(),
                    "PUBLIC_HOST_KERNEL_LIMITS",
                    "{cpu:?}"
                );
            }
        }

        #[test]
        fn membership_requires_exact_parent_or_slash_delimited_descendant() {
            for current in [
                "trnmponpublic.slice",
                "trnmponpublic.slice/worker.service",
                "trnmponpublic.slice/worker.service/thread",
            ] {
                assert!(within_parent(current, PARENT_NAME), "{current}");
            }
            for current in [
                "",
                "trnmponpublic.slic",
                "trnmponpublic.slice-other/worker.service",
                "trnmponpublic.slice2/worker.service",
                "other/trnmponpublic.slice",
                "trnmponpublic.slice\\worker.service",
                "/trnmponpublic.slice",
            ] {
                assert!(!within_parent(current, PARENT_NAME), "{current}");
            }
            // This helper preserves the original string relationship only.
            // cgroup_within_parent separately validates empty, dot and trailing segments.
            // These edge forms must not gain implicit path normalization.
            for (current, parent, expected) in [
                ("trnmponpublic.slice/", PARENT_NAME, true),
                ("trnmponpublic.slice//worker", PARENT_NAME, true),
                ("trnmponpublic.slice/worker", "trnmponpublic.slice/", false),
                ("trnmponpublic.slice//worker", "trnmponpublic.slice/", true),
                ("", "", true),
                ("worker", "", false),
                ("/worker", "", true),
            ] {
                assert_eq!(
                    within_parent(current, parent),
                    expected,
                    "{current:?} / {parent:?}"
                );
            }
        }
        #[test]
        fn canonical_systemd_slice_name_maps_to_the_actual_root_cgroup() {
            // systemd.slice(5): "foo-bar.slice" means /foo.slice/foo-bar.slice.
            // A name with no dash is a CHILD OF -.slice, not system.slice.
            // Existing PARENT_NAME must match the only actual systemd path.
            assert!(
                approved_parent_path(Path::new("/sys/fs/cgroup/trnmponpublic.slice")),
                "actual top-level systemd slice is otherwise impossible to select"
            );
            assert!(!approved_parent_path(Path::new(
                "/sys/fs/cgroup/system.slice/trnmponpublic.slice"
            )));
        }
        #[test]
        fn exactly_one_fixed_system_parent_name_is_eligible() {
            assert!(approved_parent_path(Path::new(
                "/sys/fs/cgroup/trnmponpublic.slice"
            )));
            for bad in [
                "/sys/fs/cgroup/system.slice/trnmponpublic.slice",
                "/sys/fs/cgroup/system-trnmponpublic.slice",
                "/sys/fs/cgroup/trnmponextra.slice",
                "/sys/fs/cgroup/system.slice/trnmponextra.slice",
                "/sys/fs/cgroup/system.slice/trnmponother.slice",
                "/sys/fs/cgroup/system.slice/trnmponpublic.service",
                "/sys/fs/cgroup/user.slice/trnmponpublic.slice",
                "/sys/fs/cgroup/system.slice/trnmponpublic.slice/child.service",
            ] {
                assert!(!approved_parent_path(Path::new(bad)), "{bad}");
            }
        }
        #[test]
        fn fake_root_or_wrong_parent_never_counts_as_root_kernel_budget() {
            let dir = tempfile::tempdir().unwrap();
            let path = dir.path().join("trnmponfake.slice");
            std::fs::create_dir(&path).unwrap();
            assert_eq!(
                KernelBudget::open(path.to_str().unwrap())
                    .err()
                    .unwrap()
                    .to_string(),
                "PUBLIC_HOST_KERNEL_PARENT"
            );
        }
    }
}
#[cfg(target_os = "linux")]
pub use kernel_parent::{require as require_host_kernel_budget, KernelBudget as HostKernelBudget};
#[cfg(not(target_os = "linux"))]
pub struct HostKernelBudget;
#[cfg(not(target_os = "linux"))]
impl HostKernelBudget {
    pub fn verify(&self) -> crate::Result<()> {
        Err("PUBLIC_HOST_KERNEL_UNSUPPORTED".into())
    }
    pub fn resource_sample(&self) -> crate::Result<KernelResourceSample> {
        Err("PUBLIC_HOST_KERNEL_UNSUPPORTED".into())
    }
}
#[cfg(not(target_os = "linux"))]
pub fn require_host_kernel_budget(
    address: std::net::SocketAddr,
    parent: Option<&str>,
) -> crate::Result<Option<HostKernelBudget>> {
    if parent.is_some() || !address.ip().is_loopback() {
        Err("PUBLIC_HOST_KERNEL_UNSUPPORTED".into())
    } else {
        Ok(None)
    }
}

/// Single protocol-neutral, administrator-provisioned host resource parent.
/// The public V3 library and development CLI use the EXACT same eligibility.
pub const FIXED_PUBLIC_KERNEL_PARENT: &str = "/sys/fs/cgroup/trnmponpublic.slice";
/// Direct library callers cannot bypass the CLI's kernel-parent requirement.
/// A loopback test service needs no administrator privileges; an externally
/// reachable service must already be placed under the one fixed parent.
pub fn require_for_listener(
    address: std::net::SocketAddr,
) -> crate::Result<Option<HostKernelBudget>> {
    require_host_kernel_budget(
        address,
        (!address.ip().is_loopback()).then_some(FIXED_PUBLIC_KERNEL_PARENT),
    )
}
