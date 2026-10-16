//! Matched research control: canonical 256B binary vs canonical JSON-hex
//! framing of the SAME verified 256B action in separate Unix processes.
//! Does NOT benchmark MCP, LLM inference, native code emission or UI effects.
#![forbid(unsafe_code)]

#[cfg(unix)]
mod unix {
    use codex_hepta_compiled_use::{
        ActionArgumentsV1, ActionFrameV1, ActionVerifierV1, CapabilityGrantV1, FrameDuplexV1,
        ACTION_FRAME_BYTES_V1,
    };
    use codex_hepta_types::Digest32;
    use std::env;
    use std::error::Error;
    use std::fs::{self, DirBuilder};
    use std::hint::black_box;
    use std::io::{self, Read, Write};
    use std::os::unix::fs::DirBuilderExt;
    use std::os::unix::net::{UnixListener, UnixStream};
    use std::path::{Path, PathBuf};
    use std::process::{Child, Command, Stdio};
    use std::thread;
    use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

    const MAX_MEASURED: u64 = 1024;
    const WARMUP: u64 = 16;
    const TIMEOUT: Duration = Duration::from_secs(5);
    const JSON_PREFIX: &[u8] = b"{\"frame_hex\":\"";
    const JSON_SUFFIX: &[u8] = b"\",\"schema\":\"hepta.fastcell.json-hex-control.v1\"}";
    const HEX: &[u8; 16] = b"0123456789abcdef";
    const JSON_BODY_BYTES: usize =
        JSON_PREFIX.len() + 2 * ACTION_FRAME_BYTES_V1 + JSON_SUFFIX.len();

    #[derive(Clone, Copy, Debug, Eq, PartialEq)]
    enum Mode {
        Binary,
        JsonHex,
    }
    impl Mode {
        fn label(self) -> &'static str {
            match self {
                Self::Binary => "binary",
                Self::JsonHex => "json-hex",
            }
        }
        fn parse(value: &str) -> Result<Self, Box<dyn Error>> {
            match value {
                "binary" => Ok(Self::Binary),
                "json-hex" => Ok(Self::JsonHex),
                _ => Err("unregistered data-only wire control".into()),
            }
        }
    }

    fn verifier() -> ActionVerifierV1 {
        ActionVerifierV1 {
            generation: 23,
            grant: CapabilityGrantV1 {
                digest: Digest32::of_bytes(b"matched-untrusted-data-only-control"),
                allowed: 1 | 2 | 4 | 8 | 16,
            },
        }
    }
    fn action(sequence: u64) -> ActionFrameV1 {
        ActionFrameV1 {
            generation: 23,
            sequence,
            capability_digest: verifier().grant.digest,
            arguments: ActionArgumentsV1::Click {
                target_digest: Digest32::of_bytes(b"same-nonexecuting-original-element"),
                x: 2,
                y: 5,
            },
        }
    }
    fn parse_count(value: &str) -> Result<u64, Box<dyn Error>> {
        let n: u64 = value.parse()?;
        if !(1..=MAX_MEASURED).contains(&n) {
            return Err("invalid bounded matched workload".into());
        }
        Ok(n)
    }
    fn bounded_deadlines(stream: &UnixStream) -> io::Result<()> {
        stream.set_read_timeout(Some(TIMEOUT))?;
        stream.set_write_timeout(Some(TIMEOUT))
    }

    struct PrivateSocket {
        dir: PathBuf,
        socket: PathBuf,
    }
    impl PrivateSocket {
        fn create() -> io::Result<Self> {
            let n = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map_err(io::Error::other)?
                .as_nanos();
            for suffix in 0..16_u8 {
                let dir = env::temp_dir().join(format!(
                    "hepta-json-control-{}-{n}-{suffix}",
                    std::process::id()
                ));
                let mut builder = DirBuilder::new();
                builder.mode(0o700);
                match builder.create(&dir) {
                    Ok(()) => {
                        return Ok(Self {
                            socket: dir.join("frame.sock"),
                            dir,
                        });
                    }
                    Err(e) if e.kind() == io::ErrorKind::AlreadyExists => {}
                    Err(e) => return Err(e),
                }
            }
            Err(io::Error::new(
                io::ErrorKind::AlreadyExists,
                "cannot exclusively create benchmark socket directory",
            ))
        }
    }
    impl Drop for PrivateSocket {
        fn drop(&mut self) {
            let _ = fs::remove_file(&self.socket);
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
    fn accept_bounded(listener: &UnixListener) -> io::Result<UnixStream> {
        listener.set_nonblocking(true)?;
        let deadline = Instant::now() + TIMEOUT;
        loop {
            match listener.accept() {
                Ok((stream, _)) => {
                    stream.set_nonblocking(false)?;
                    return Ok(stream);
                }
                Err(e) if e.kind() == io::ErrorKind::WouldBlock && Instant::now() < deadline => {
                    thread::sleep(Duration::from_millis(1));
                }
                Err(e) if e.kind() == io::ErrorKind::WouldBlock => {
                    return Err(io::Error::new(io::ErrorKind::TimedOut, "no worker connection"));
                }
                Err(e) => return Err(e),
            }
        }
    }
    fn wait_bounded(worker: &mut Child) -> io::Result<std::process::ExitStatus> {
        let deadline = Instant::now() + TIMEOUT;
        loop {
            if let Some(status) = worker.try_wait()? {
                return Ok(status);
            }
            if Instant::now() >= deadline {
                let _ = worker.kill();
                let _ = worker.wait();
                return Err(io::Error::new(
                    io::ErrorKind::TimedOut,
                    "benchmark child failed to exit within time budget",
                ));
            }
            thread::sleep(Duration::from_millis(1));
        }
    }

    fn nibble(byte: u8) -> Result<u8, Box<dyn Error>> {
        match byte {
            b'0'..=b'9' => Ok(byte - b'0'),
            b'a'..=b'f' => Ok(byte - b'a' + 10),
            _ => Err("noncanonical JSON hex digit".into()),
        }
    }
    fn send_json(
        io: &mut UnixStream,
        original: &ActionFrameV1,
        expected_sequence: u64,
    ) -> Result<(), Box<dyn Error>> {
        verifier().verify(original)?;
        if original.sequence != expected_sequence {
            return Err("JSON-control send sequence mismatch".into());
        }
        let encoded = original.encode()?;
        let mut body = Vec::with_capacity(JSON_BODY_BYTES);
        body.extend_from_slice(JSON_PREFIX);
        for byte in encoded {
            body.push(HEX[usize::from(byte >> 4)]);
            body.push(HEX[usize::from(byte & 15)]);
        }
        body.extend_from_slice(JSON_SUFFIX);
        if body.len() != JSON_BODY_BYTES {
            return Err("wrong canonical JSON-control byte length".into());
        }
        let length = u32::try_from(body.len())?;
        io.write_all(&length.to_be_bytes())?;
        io.write_all(&body)?;
        io.flush()?;
        Ok(())
    }
    fn receive_json(
        io: &mut UnixStream,
        expected_sequence: u64,
    ) -> Result<ActionFrameV1, Box<dyn Error>> {
        let mut length = [0_u8; 4];
        io.read_exact(&mut length)?;
        if u32::from_be_bytes(length) as usize != JSON_BODY_BYTES {
            return Err("unregistered or oversized JSON-control frame".into());
        }
        let mut body = vec![0_u8; JSON_BODY_BYTES];
        io.read_exact(&mut body)?;
        if !body.starts_with(JSON_PREFIX) || !body.ends_with(JSON_SUFFIX) {
            return Err("noncanonical JSON-control schema/framing".into());
        }
        let mut bytes = [0_u8; ACTION_FRAME_BYTES_V1];
        let hex = &body[JSON_PREFIX.len()..JSON_PREFIX.len() + 2 * ACTION_FRAME_BYTES_V1];
        for (index, pair) in hex.chunks_exact(2).enumerate() {
            bytes[index] = nibble(pair[0])? * 16 + nibble(pair[1])?;
        }
        let frame = ActionFrameV1::decode(&bytes)?;
        verifier().verify(&frame)?;
        if frame.sequence != expected_sequence {
            return Err("JSON-control receive sequence mismatch".into());
        }
        Ok(frame)
    }

    fn child(mode: Mode, path: &Path, measured: u64) -> Result<(), Box<dyn Error>> {
        let stream = UnixStream::connect(path)?;
        bounded_deadlines(&stream)?;
        let total = measured + WARMUP;
        match mode {
            Mode::Binary => {
                let mut wire = FrameDuplexV1::new(stream, verifier(), total)?;
                for _ in 0..total {
                    let action = wire.receive()?;
                    wire.send(action.frame())?;
                }
                if wire.is_poisoned() {
                    return Err("binary echo session poisoned".into());
                }
            }
            Mode::JsonHex => {
                let mut stream = stream;
                for sequence in 1..=total {
                    let source = receive_json(&mut stream, sequence)?;
                    send_json(&mut stream, &source, sequence)?;
                }
            }
        }
        Ok(())
    }

    #[derive(Clone, Copy)]
    struct Stats {
        setup_ns: u128,
        p50_ns: u128,
        p95_ns: u128,
        p99_ns: u128,
    }
    fn percentile(sorted: &[u128], percent: usize) -> u128 {
        sorted[(sorted.len() - 1) * percent / 100]
    }
    fn measure(mode: Mode, measured: u64) -> Result<Stats, Box<dyn Error>> {
        let socket = PrivateSocket::create()?;
        let listener = UnixListener::bind(&socket.socket)?;
        let init = Instant::now();
        let mut worker = Worker(
            Command::new(env::current_exe()?)
                .arg("--worker")
                .arg(mode.label())
                .arg(&socket.socket)
                .arg(measured.to_string())
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .spawn()?,
        );
        let mut stream = accept_bounded(&listener)?;
        let setup_ns = init.elapsed().as_nanos();
        bounded_deadlines(&stream)?;
        let total = measured + WARMUP;
        let mut times = Vec::with_capacity(measured as usize);
        match mode {
            Mode::Binary => {
                let mut wire = FrameDuplexV1::new(stream, verifier(), total)?;
                for sequence in 1..=total {
                    let original = action(sequence);
                    let start = Instant::now();
                    wire.send(&original)?;
                    let returned = wire.receive()?;
                    if returned.frame() != &original {
                        return Err("binary original frame changed".into());
                    }
                    black_box(returned.frame().sequence);
                    if sequence > WARMUP {
                        times.push(start.elapsed().as_nanos());
                    }
                }
                if wire.is_poisoned() {
                    return Err("binary session unexpectedly poisoned".into());
                }
            }
            Mode::JsonHex => {
                for sequence in 1..=total {
                    let original = action(sequence);
                    let start = Instant::now();
                    send_json(&mut stream, &original, sequence)?;
                    let returned = receive_json(&mut stream, sequence)?;
                    if returned != original {
                        return Err("JSON-control original frame changed".into());
                    }
                    black_box(returned.sequence);
                    if sequence > WARMUP {
                        times.push(start.elapsed().as_nanos());
                    }
                }
            }
        }
        let status = wait_bounded(&mut worker.0)?;
        if !status.success() || times.len() != measured as usize {
            return Err("incomplete physical matched-control run".into());
        }
        times.sort_unstable();
        Ok(Stats {
            setup_ns,
            p50_ns: percentile(&times, 50),
            p95_ns: percentile(&times, 95),
            p99_ns: percentile(&times, 99),
        })
    }
    fn stats_json(pair: &[Stats]) -> String {
        let rows: Vec<_> = pair
            .iter()
            .map(|x| {
                format!(
                    "{{\"setup_ns\":{},\"p50_ns\":{},\"p95_ns\":{},\"p99_ns\":{}}}",
                    x.setup_ns, x.p50_ns, x.p95_ns, x.p99_ns
                )
            })
            .collect();
        format!("[{}]", rows.join(","))
    }
    pub fn run() -> Result<(), Box<dyn Error>> {
        let args: Vec<_> = env::args_os().collect();
        if args.len() == 5 && args[1] == "--worker" {
            let mode = Mode::parse(args[2].to_str().ok_or("bad mode")?)?;
            let path = PathBuf::from(&args[3]);
            let count = parse_count(args[4].to_str().ok_or("bad worker count")?)?;
            return child(mode, &path, count);
        }
        if args.len() != 1 && !(args.len() == 2 && args[1] == "--smoke") {
            return Err("only --smoke and internal bounded worker mode are accepted".into());
        }
        let measured = if args.len() == 2 { 64 } else { MAX_MEASURED };
        // Reverse order in repeat #2 to expose simple thermal/first-arm bias.
        let mut binaries = Vec::with_capacity(2);
        let mut jsons = Vec::with_capacity(2);
        for mode in [Mode::Binary, Mode::JsonHex, Mode::JsonHex, Mode::Binary] {
            let stats = measure(mode, measured)?;
            match mode {
                Mode::Binary => binaries.push(stats),
                Mode::JsonHex => jsons.push(stats),
            }
        }
        if binaries.len() != 2 || jsons.len() != 2 {
            return Err("missing matched physical arm".into());
        }
        println!(
            "{{\"schema\":\"hepta.fastcell.paired-binary-json-control.v1\",\"measured_roundtrips_per_replica\":{measured},\"warmup_roundtrips\":{WARMUP},\"replicas_per_arm\":2,\"binary_payload_bytes\":256,\"json_control_payload_bytes\":{},\"binary\":{},\"json_hex\":{},\"separate_processes\":true,\"same_verified_original_action\":true,\"same_capability_verifier\":true,\"mcp_comparison\":false,\"model_executed\":false,\"external_effects\":false,\"peer_authentication_verified\":false,\"production_authorized\":false}}",
            JSON_BODY_BYTES + 4,
            stats_json(&binaries),
            stats_json(&jsons),
        );
        Ok(())
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    #[cfg(unix)]
    {
        unix::run()
    }
    #[cfg(not(unix))]
    {
        Err("paired binary/JSON Unix benchmark requires Unix".into())
    }
}
