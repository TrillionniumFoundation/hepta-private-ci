//! Research-only matched REAL CPU Q24-dot work in-process vs over a bounded
//! Unix socket to a separately spawned native Rust process. Not MCP / UI / JIT.

#[cfg(not(unix))]
fn main() {
    eprintln!("native_compute_paired needs Unix; no CPU execution performed");
    std::process::exit(64);
}

#[cfg(unix)]
mod unix {
    use codex_hepta_compiled_use::{
        NATIVE_COMPUTE_FRAME_BYTES_V1, NATIVE_COMPUTE_MAX_LANES_V1,
        NATIVE_COMPUTE_RESULT_BYTES_V1, NativeComputeFrameV1, NativeComputeVerifierV1,
        approved_q24_dot_kernel_digest_v1, decode_shadow_native_result_v1,
        run_shadow_native_compute_v1,
    };
    use codex_hepta_types::Digest32;
    use std::env;
    use std::error::Error;
    use std::fs::{self, DirBuilder};
    use std::io::{self, Read, Write};
    use std::os::unix::fs::DirBuilderExt;
    use std::os::unix::net::{UnixListener, UnixStream};
    use std::path::{Path, PathBuf};
    use std::process::{Child, Command, Stdio};
    use std::thread;
    use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

    const WARMUP: usize = 16;
    const FULL: usize = 1024;
    const SMOKE: usize = 64;
    const IO_TIMEOUT: Duration = Duration::from_secs(5);
    const RUN_LIMIT: Duration = Duration::from_secs(15);

    fn verifier() -> NativeComputeVerifierV1 {
        NativeComputeVerifierV1 {
            generation: 19,
            task_digest: Digest32::of_bytes(b"hepta-native-compute-same-source-and-work"),
            kernel_digest: approved_q24_dot_kernel_digest_v1(),
            maximum_lanes: 16,
        }
    }

    fn request(sequence: u64) -> NativeComputeFrameV1 {
        let mut features_q24 = [0_i32; NATIVE_COMPUTE_MAX_LANES_V1];
        let mut weights_q24 = [0_i32; NATIVE_COMPUTE_MAX_LANES_V1];
        for i in 0..NATIVE_COMPUTE_MAX_LANES_V1 {
            let sign = if (i as u64 + sequence) % 2 == 0 { 1 } else { -1 };
            features_q24[i] = sign * ((i as i32 + 1) << 19);
            weights_q24[i] = (((sequence % 7) as i32 + 1) * (i as i32 + 1)) << 15;
        }
        NativeComputeFrameV1 {
            generation: verifier().generation,
            sequence,
            task_digest: verifier().task_digest,
            kernel_digest: verifier().kernel_digest,
            lanes: 16,
            features_q24,
            weights_q24,
        }
    }

    struct Trial {
        original: NativeComputeFrameV1,
        wire: [u8; NATIVE_COMPUTE_FRAME_BYTES_V1],
        expected_result: [u8; NATIVE_COMPUTE_RESULT_BYTES_V1],
    }
    fn build_trials(measured: usize) -> Result<Vec<Trial>, Box<dyn Error>> {
        let mut trials = Vec::with_capacity(WARMUP + measured);
        for i in 0..(WARMUP + measured) {
            let original = request(u64::try_from(i + 1)?);
            let wire = original.encode()?;
            let expected_result = run_shadow_native_compute_v1(verifier(), &original)?.encode()?;
            trials.push(Trial { original, wire, expected_result });
        }
        Ok(trials)
    }

    #[derive(Clone, Copy)]
    struct Stats {
        setup_ns: u64,
        p50_ns: u64,
        p95_ns: u64,
        p99_ns: u64,
    }
    fn percentile(sorted: &[u64], percentile: usize) -> u64 {
        let position = (sorted.len() * percentile).div_ceil(100).saturating_sub(1);
        sorted[position.min(sorted.len() - 1)]
    }
    fn report(mut samples: Vec<u64>, setup_ns: u64) -> Stats {
        samples.sort_unstable();
        Stats {
            setup_ns,
            p50_ns: percentile(&samples, 50),
            p95_ns: percentile(&samples, 95),
            p99_ns: percentile(&samples, 99),
        }
    }
    fn elapsed_ns(when: Instant) -> Result<u64, Box<dyn Error>> {
        Ok(u64::try_from(when.elapsed().as_nanos())?.max(1))
    }
    fn local(trials: &[Trial]) -> Result<Stats, Box<dyn Error>> {
        let mut samples = Vec::with_capacity(trials.len().saturating_sub(WARMUP));
        for (i, trial) in trials.iter().enumerate() {
            let start = Instant::now();
            let decoded = NativeComputeFrameV1::decode(&trial.wire)?;
            verifier().verify(&decoded)?;
            let result = run_shadow_native_compute_v1(verifier(), &decoded)?.encode()?;
            let observed = decode_shadow_native_result_v1(&trial.original, &result)?;
            if decoded != trial.original
                || result != trial.expected_result
                || observed.authority.grants_any()
            {
                return Err("in-process original work/result mismatch".into());
            }
            if i >= WARMUP {
                samples.push(elapsed_ns(start)?);
            }
        }
        Ok(report(samples, 0))
    }

    struct PrivateSocket {
        dir: PathBuf,
        path: PathBuf,
    }
    impl PrivateSocket {
        fn create() -> io::Result<Self> {
            let nanos = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_err(io::Error::other)?
                .as_nanos();
            for suffix in 0..16_u8 {
                let dir = env::temp_dir().join(format!(
                    "hepta-native-cell-{}-{nanos}-{suffix}",
                    std::process::id()
                ));
                let mut builder = DirBuilder::new();
                builder.mode(0o700);
                match builder.create(&dir) {
                    Ok(()) => return Ok(Self { path: dir.join("cpu.sock"), dir }),
                    Err(e) if e.kind() == io::ErrorKind::AlreadyExists => {}
                    Err(e) => return Err(e),
                }
            }
            Err(io::Error::new(io::ErrorKind::AlreadyExists, "no private directory"))
        }
    }
    impl Drop for PrivateSocket {
        fn drop(&mut self) {
            let _ = fs::remove_file(&self.path);
            let _ = fs::remove_dir(&self.dir);
        }
    }
    struct Worker(Child);
    impl Drop for Worker {
        fn drop(&mut self) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }
    fn bounded_accept(listener: &UnixListener) -> io::Result<UnixStream> {
        listener.set_nonblocking(true)?;
        let deadline = Instant::now() + IO_TIMEOUT;
        loop {
            match listener.accept() {
                Ok((stream, _)) => {
                    stream.set_nonblocking(false)?;
                    stream.set_read_timeout(Some(IO_TIMEOUT))?;
                    stream.set_write_timeout(Some(IO_TIMEOUT))?;
                    return Ok(stream);
                }
                Err(e) if e.kind() == io::ErrorKind::WouldBlock && Instant::now() < deadline => {
                    thread::sleep(Duration::from_millis(1));
                }
                Err(e) if e.kind() == io::ErrorKind::WouldBlock => {
                    return Err(io::Error::new(io::ErrorKind::TimedOut, "no native worker"));
                }
                Err(e) => return Err(e),
            }
        }
    }
    fn wait_bounded(worker: &mut Child) -> io::Result<()> {
        let deadline = Instant::now() + RUN_LIMIT;
        loop {
            if let Some(status) = worker.try_wait()? {
                if status.success() {
                    return Ok(());
                }
                return Err(io::Error::other("native CPU child failed"));
            }
            if Instant::now() >= deadline {
                let _ = worker.kill();
                let _ = worker.wait();
                return Err(io::Error::new(io::ErrorKind::TimedOut, "child not reaped"));
            }
            thread::sleep(Duration::from_millis(1));
        }
    }
    fn child(path: &Path) -> Result<(), Box<dyn Error>> {
        let mut stream = UnixStream::connect(path)?;
        stream.set_read_timeout(Some(IO_TIMEOUT))?;
        stream.set_write_timeout(Some(IO_TIMEOUT))?;
        let mut expected_sequence = 1_u64;
        loop {
            let mut input = [0_u8; NATIVE_COMPUTE_FRAME_BYTES_V1];
            if stream.read(&mut input[..1])? == 0 {
                break;
            }
            stream.read_exact(&mut input[1..])?;
            let original = NativeComputeFrameV1::decode(&input)?;
            if original.sequence != expected_sequence {
                return Err("out-of-order native CPU sequence".into());
            }
            expected_sequence = expected_sequence.checked_add(1).ok_or("sequence overflow")?;
            let result = run_shadow_native_compute_v1(verifier(), &original)?.encode()?;
            stream.write_all(&result)?;
        }
        if expected_sequence <= WARMUP as u64 {
            return Err("no measured native compute workload".into());
        }
        Ok(())
    }
    fn ipc(trials: &[Trial]) -> Result<Stats, Box<dyn Error>> {
        let sock = PrivateSocket::create()?;
        let listener = UnixListener::bind(&sock.path)?;
        let setup = Instant::now();
        let mut worker = Worker( Command::new(env::current_exe()?)
            .arg("--child")
            .arg(&sock.path)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .spawn()? );
        let mut stream = bounded_accept(&listener)?;
        let setup_ns = elapsed_ns(setup)?;
        let mut samples = Vec::with_capacity(trials.len().saturating_sub(WARMUP));
        for (i, trial) in trials.iter().enumerate() {
            let start = Instant::now();
            stream.write_all(&trial.wire)?;
            let mut result = [0_u8; NATIVE_COMPUTE_RESULT_BYTES_V1];
            stream.read_exact(&mut result)?;
            let observed = decode_shadow_native_result_v1(&trial.original, &result)?;
            if observed.authority.grants_any() || result != trial.expected_result {
                return Err("cross-process original CPU result mismatch".into());
            }
            if i >= WARMUP {
                samples.push(elapsed_ns(start)?);
            }
        }
        stream.shutdown(std::net::Shutdown::Write)?;
        wait_bounded(&mut worker.0)?;
        Ok(report(samples, setup_ns))
    }

    fn stats_json(s: Stats) -> String {
        format!(
            "{{\"setup_ns\":{},\"p50_ns\":{},\"p95_ns\":{},\"p99_ns\":{}}}",
            s.setup_ns, s.p50_ns, s.p95_ns, s.p99_ns
        )
    }

    pub fn entry() -> Result<(), Box<dyn Error>> {
        let args: Vec<String> = env::args().skip(1).collect();
        if let [mode, path] = args.as_slice() {
            if mode == "--child" {
                return child(Path::new(path));
            }
        }
        let count = match args.as_slice() {
            [] => FULL,
            [flag] if flag == "--smoke" => SMOKE,
            _ => return Err("unsupported native CPU benchmark argument".into()),
        };
        let trials = build_trials(count)?;
        // Two repetitions per arm and reverse order to expose warm/cache drift.
        let a = local(&trials)?;
        let b = ipc(&trials)?;
        let c = ipc(&trials)?;
        let d = local(&trials)?;
        println!(
            "{{\"schema\":\"hepta.nativecell.cpu-local-vs-ipc.v1\",\"measured_calls_per_repetition\":{},\"warmup_calls\":{},\"repetitions_per_arm\":2,\"input_frame_bytes\":256,\"result_frame_bytes\":64,\"kernel\":\"compiled-q24-dot16\",\"in_process\":[{},{}],\"two_process\":[{},{}],\"same_original_input_and_kernel\":true,\"all_original_outputs_match\":true,\"separate_processes\":true,\"mcp_comparison\":false,\"os_ui_effect\":false,\"model_executed\":false,\"jit_or_executable_memory\":false,\"peer_authentication_verified\":false,\"production_authorized\":false}}",
            count,
            WARMUP,
            stats_json(a),
            stats_json(d),
            stats_json(b),
            stats_json(c),
        );
        Ok(())
    }

    #[cfg(test)]
    mod tests {
        use super::*;
        #[test]
        fn source_workload_has_exact_original_digests_and_real_different_inputs() {
            let tasks = build_trials(64).unwrap();
            assert_eq!(tasks.len(), 80);
            assert_ne!(tasks[0].wire, tasks[1].wire);
            for item in tasks {
                let actual = run_shadow_native_compute_v1(verifier(), &item.original).unwrap();
                assert_eq!(actual.encode().unwrap(), item.expected_result);
                assert!(!actual.authority.grants_any());
            }
        }
        #[test]
        fn bounded_percentile_orders_samples() {
            let output = report(vec![10, 50, 20, 40, 30], 100);
            assert_eq!((output.p50_ns, output.p95_ns, output.p99_ns), (30, 50, 50));
        }
    }
}

#[cfg(unix)]
fn main() {
    if let Err(error) = unix::entry() {
        eprintln!("shadow native CPU benchmark rejected: {error}");
        std::process::exit(1);
    }
}
