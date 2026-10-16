//! Actual OS Unix socket-pair data-only RTT research benchmark.
//! Two threads, SAME process. Not MCP, CPU JIT, GPU or UI effects.
#[cfg(unix)]
mod unix {
    use codex_hepta_compiled_use::{
        ActionArgumentsV1, ActionFrameV1, ActionVerifierV1, CapabilityGrantV1, FrameDuplexV1,
    };
    use codex_hepta_types::Digest32;
    use std::hint::black_box;
    use std::os::unix::net::UnixStream;
    use std::time::{Duration, Instant};

    pub fn run() -> Result<(), Box<dyn std::error::Error>> {
        let count: u64 = if std::env::args().any(|arg| arg == "--smoke") {
            64
        } else {
            1024
        };
        let grant = CapabilityGrantV1 {
            digest: Digest32::of_bytes(b"fastcell-unix-untrusted-grant"),
            allowed: 1 | 2 | 4 | 8 | 16,
        };
        let verifier = ActionVerifierV1 {
            generation: 12,
            grant,
        };
        let (first, second) = UnixStream::pair()?;
        for io in [&first, &second] {
            io.set_read_timeout(Some(Duration::from_secs(5)))?;
            io.set_write_timeout(Some(Duration::from_secs(5)))?;
        }
        let worker = std::thread::spawn(
            move || -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
                let mut stream = FrameDuplexV1::new(second, verifier, count)?;
                for _ in 0..count {
                    let verified = stream.receive()?;
                    stream.send(verified.frame())?;
                }
                if stream.is_poisoned() {
                    return Err("data-only frame stream unexpectedly poisoned".into());
                }
                Ok(())
            },
        );
        let mut client = FrameDuplexV1::new(first, verifier, count)?;
        let mut samples = Vec::with_capacity(count as usize);
        for sequence in 1..=count {
            let frame = ActionFrameV1 {
                generation: 12,
                sequence,
                capability_digest: grant.digest,
                arguments: ActionArgumentsV1::Click {
                    target_digest: Digest32::of_bytes(b"bench-element"),
                    x: 3,
                    y: 4,
                },
            };
            let started = Instant::now();
            client.send(&frame)?;
            let reply = client.receive()?;
            if reply.frame() != &frame {
                return Err("roundtrip data mismatch".into());
            }
            black_box(reply.frame().sequence);
            samples.push(started.elapsed().as_nanos());
        }
        worker
            .join()
            .map_err(|_| std::io::Error::other("benchmark worker panicked"))?
            .map_err(std::io::Error::other)?;
        samples.sort_unstable();
        let quantile = |percent: usize| samples[(samples.len() - 1) * percent / 100];
        println!(
            "{{\"schema\":\"hepta.fastcell.unix-duplex-rtt.v1\",\"roundtrips\":{},\"payload_bytes_per_direction\":256,\"p50_ns\":{},\"p95_ns\":{},\"p99_ns\":{},\"same_process_two_threads\":true,\"kernel_socket_syscalls\":true,\"separate_process\":false,\"mcp_comparison\":false,\"external_effects\":false,\"production_authorized\":false}}",
            count,
            quantile(50),
            quantile(95),
            quantile(99),
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
        Err("unix-only benchmark".into())
    }
}
