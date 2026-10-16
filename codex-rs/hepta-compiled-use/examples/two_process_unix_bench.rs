//! Original two-process Unix-domain-socket 256-byte frame RTT, data only.
//! No OS UI effect, model call, JIT, GPU, MCP comparison or capability issuer.
#![forbid(unsafe_code)]

#[cfg(unix)]
mod unix {
    use codex_hepta_compiled_use::{
        ActionArgumentsV1, ActionFrameV1, ActionVerifierV1, CapabilityGrantV1, FrameDuplexV1,
    };
    use codex_hepta_types::Digest32;
    use std::env;
    use std::error::Error;
    use std::fs::{self, DirBuilder};
    use std::hint::black_box;
    use std::io;
    use std::os::unix::fs::DirBuilderExt;
    use std::os::unix::net::{UnixListener, UnixStream};
    use std::path::{Path, PathBuf};
    use std::process::{Child, Command, Stdio};
    use std::thread;
    use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

    const MAX_CALLS: u64 = 1024;
    const IO_TIMEOUT: Duration = Duration::from_secs(5);

    fn verifier() -> ActionVerifierV1 {
        ActionVerifierV1 {
            generation: 17,
            grant: CapabilityGrantV1 {
                digest: Digest32::of_bytes(b"two-process-original-data-only"),
                allowed: 1 | 2 | 4 | 8 | 16,
            },
        }
    }

    fn action(sequence: u64) -> ActionFrameV1 {
        ActionFrameV1 {
            generation: 17,
            sequence,
            capability_digest: verifier().grant.digest,
            arguments: ActionArgumentsV1::Click {
                target_digest: Digest32::of_bytes(b"nonexecuting-observed-element"),
                x: 2,
                y: 5,
            },
        }
    }

    fn bounded_count(value: &str) -> Result<u64, Box<dyn Error>> {
        let n: u64 = value.parse()?;
        if !(1..=MAX_CALLS).contains(&n) {
            return Err("count outside bounded data-only pilot".into());
        }
        Ok(n)
    }

    fn set_deadlines(io: &UnixStream) -> io::Result<()> {
        io.set_read_timeout(Some(IO_TIMEOUT))?;
        io.set_write_timeout(Some(IO_TIMEOUT))
    }

    struct PrivateSocket {
        dir: PathBuf,
        path: PathBuf,
    }
    impl PrivateSocket {
        fn new() -> io::Result<Self> {
            let ns = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_err(io::Error::other)?
                .as_nanos();
            for suffix in 0..16_u64 {
                let dir = env::temp_dir()
                    .join(format!("hepta-duplex-{}-{ns}-{suffix}", std::process::id()));
                let mut builder = DirBuilder::new();
                builder.mode(0o700);
                match builder.create(&dir) {
                    Ok(()) => {
                        return Ok(Self {
                            path: dir.join("frame.sock"),
                            dir,
                        });
                    }
                    Err(e) if e.kind() == io::ErrorKind::AlreadyExists => {}
                    Err(e) => return Err(e),
                }
            }
            Err(io::Error::new(
                io::ErrorKind::AlreadyExists,
                "cannot exclusively create a private socket directory",
            ))
        }
    }
    impl Drop for PrivateSocket {
        fn drop(&mut self) {
            let _ = fs::remove_file(&self.path);
            let _ = fs::remove_dir(&self.dir);
        }
    }

    struct WorkerChild(Child);
    impl Drop for WorkerChild {
        fn drop(&mut self) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }

    fn child(path: &Path, count: u64) -> Result<(), Box<dyn Error>> {
        let socket = UnixStream::connect(path)?;
        set_deadlines(&socket)?;
        let mut wire = FrameDuplexV1::new(socket, verifier(), count)?;
        for _ in 0..count {
            let verified = wire.receive()?;
            wire.send(verified.frame())?;
        }
        if wire.is_poisoned() {
            return Err("verified worker stream poisoned".into());
        }
        Ok(())
    }

    fn accept_bounded(listener: &UnixListener) -> io::Result<UnixStream> {
        listener.set_nonblocking(true)?;
        let deadline = Instant::now() + IO_TIMEOUT;
        loop {
            match listener.accept() {
                Ok((socket, _)) => {
                    socket.set_nonblocking(false)?;
                    return Ok(socket);
                }
                Err(e) if e.kind() == io::ErrorKind::WouldBlock && Instant::now() < deadline => {
                    thread::sleep(Duration::from_millis(1));
                }
                Err(e) if e.kind() == io::ErrorKind::WouldBlock => {
                    return Err(io::Error::new(
                        io::ErrorKind::TimedOut,
                        "worker did not connect",
                    ));
                }
                Err(e) => return Err(e),
            }
        }
    }

    fn quantile(sorted: &[u128], pct: usize) -> u128 {
        sorted[(sorted.len() - 1) * pct / 100]
    }

    fn parent(count: u64) -> Result<(), Box<dyn Error>> {
        let private = PrivateSocket::new()?;
        let listener = UnixListener::bind(&private.path)?;
        let setup_start = Instant::now();
        let mut worker = WorkerChild(
            Command::new(env::current_exe()?)
                .arg("--worker")
                .arg(&private.path)
                .arg(count.to_string())
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .spawn()?,
        );
        let socket = accept_bounded(&listener)?;
        let process_setup_ns = setup_start.elapsed().as_nanos();
        set_deadlines(&socket)?;
        let mut wire = FrameDuplexV1::new(socket, verifier(), count)?;
        let mut samples = Vec::with_capacity(count as usize);
        for sequence in 1..=count {
            let original = action(sequence);
            let begin = Instant::now();
            wire.send(&original)?;
            let echoed = wire.receive()?;
            if echoed.frame() != &original {
                return Err("two-process response did not reproduce exact original frame".into());
            }
            black_box(echoed.frame().sequence);
            samples.push(begin.elapsed().as_nanos());
        }
        let status = worker.0.wait()?;
        if !status.success() || wire.is_poisoned() {
            return Err("two-process worker failed or transport was poisoned".into());
        }
        samples.sort_unstable();
        println!(
            "{{\"schema\":\"hepta.fastcell.two-process-unix-rtt.v1\",\"roundtrips\":{count},\"payload_bytes_per_direction\":256,\"p50_ns\":{},\"p95_ns\":{},\"p99_ns\":{},\"process_setup_ns\":{process_setup_ns},\"separate_processes\":true,\"same_process_two_threads\":false,\"peer_authentication_verified\":false,\"mcp_comparison\":false,\"external_effects\":false,\"production_authorized\":false}}",
            quantile(&samples, 50),
            quantile(&samples, 95),
            quantile(&samples, 99),
        );
        Ok(())
    }

    pub fn run() -> Result<(), Box<dyn Error>> {
        let args: Vec<_> = env::args_os().collect();
        if args.len() == 4 && args[1] == "--worker" {
            let path = PathBuf::from(&args[2]);
            let count = bounded_count(args[3].to_str().ok_or("invalid two-process worker count")?)?;
            return child(&path, count);
        }
        if args.len() != 1 && !(args.len() == 2 && args[1] == "--smoke") {
            return Err("only --smoke or the internal bounded worker protocol is supported".into());
        }
        parent(if args.len() == 2 { 64 } else { MAX_CALLS })
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    #[cfg(unix)]
    {
        unix::run()
    }
    #[cfg(not(unix))]
    {
        Err("two-process Unix socket pilot requires Unix".into())
    }
}
