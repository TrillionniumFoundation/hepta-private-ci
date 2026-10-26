//! A controlled five-lane peer, never an Agentd or independent authority owner.
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CognitiveCheckpointRequest;
use codex_hepta_memory::CognitiveCheckpointResponse;
use pretty_assertions::assert_eq;
use serde::Deserialize;
use serde::Serialize;
use serde::de::DeserializeOwned;
use std::io::Read;
use std::io::Write;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::fs::MetadataExt;
use std::os::unix::net::UnixStream;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

#[derive(Serialize, Deserialize)]
enum PeerCommand {
    Exchange(CognitiveCheckpointRequest),
    CloseWithError,
}

pub(crate) struct Peer {
    control: UnixStream,
}

fn send(stream: &mut UnixStream, value: &impl Serialize) {
    let bytes = serde_json::to_vec(value).unwrap();
    assert!(bytes.len() <= 64 * 1024);
    stream
        .write_all(&(bytes.len() as u32).to_be_bytes())
        .unwrap();
    stream.write_all(&bytes).unwrap();
}

fn receive<T: DeserializeOwned>(stream: &mut UnixStream) -> T {
    let mut length = [0; 4];
    stream.read_exact(&mut length).unwrap();
    let length = u32::from_be_bytes(length) as usize;
    assert!((1..=64 * 1024).contains(&length));
    let mut bytes = vec![0; length];
    stream.read_exact(&mut bytes).unwrap();
    serde_json::from_slice(&bytes).unwrap()
}

impl Peer {
    pub(crate) fn spawn() -> (Child, Self) {
        let binary = PathBuf::from(std::env::var_os("HEPTA_NOTES_CAPTURE_PEER_BIN").unwrap());
        assert_eq!(binary.canonicalize().unwrap(), binary);
        let metadata = std::fs::symlink_metadata(&binary).unwrap();
        assert!(metadata.is_file());
        assert_eq!(
            (metadata.uid(), metadata.nlink(), metadata.mode() & 0o7777),
            (0, 1, 0o555)
        );
        assert_eq!(
            Sha256Digest::for_bytes(&std::fs::read(&binary).unwrap()).as_str(),
            std::env::var("HEPTA_NOTES_CAPTURE_PEER_SHA256").unwrap()
        );
        let (control, child_control) = UnixStream::pair().unwrap();
        control
            .set_read_timeout(Some(Duration::from_secs(15)))
            .unwrap();
        control
            .set_write_timeout(Some(Duration::from_secs(15)))
            .unwrap();
        let child = Command::new("/usr/bin/setpriv")
            .args([
                "--reuid=60001",
                "--regid=60001",
                "--clear-groups",
                "--bounding-set=-all",
                "--inh-caps=-all",
                "--ambient-caps=-all",
                "--no-new-privs",
            ])
            .arg(binary)
            .args([
                "--exact",
                "authority_host_service::notes_capture_peer::retained_notes_lane_peer",
                "--ignored",
                "--nocapture",
                "--test-threads=1",
            ])
            .current_dir("/")
            .stdin(Stdio::from(OwnedFd::from(child_control)))
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .env_clear()
            .env("PATH", "/usr/bin:/bin")
            .spawn()
            .unwrap();
        (child, Self { control })
    }

    pub(crate) fn connect(&mut self, paths: &[PathBuf; 5]) {
        send(&mut self.control, paths);
        assert_eq!(receive::<u8>(&mut self.control), 1);
    }

    pub(crate) fn exchange(
        &mut self,
        request: CognitiveCheckpointRequest,
    ) -> CognitiveCheckpointResponse {
        send(&mut self.control, &PeerCommand::Exchange(request));
        receive(&mut self.control)
    }

    pub(crate) fn close_with_error(&mut self) {
        send(&mut self.control, &PeerCommand::CloseWithError);
        assert_eq!(receive::<u8>(&mut self.control), 2);
    }
}

#[test]
#[ignore = "controlled UID60001 child entry, launched only by private Root capture fixtures"]
fn retained_notes_lane_peer() {
    // SAFETY: this observes the actual credential of this controlled child.
    assert_eq!(unsafe { libc::geteuid() }, 60001);
    // SAFETY: duplicate only the fixture's inherited private connected stdin.
    let raw = unsafe { libc::fcntl(0, libc::F_DUPFD_CLOEXEC, 3) };
    assert!(raw >= 0);
    // SAFETY: fcntl returned exactly one fresh owned UnixStream descriptor.
    let mut control = unsafe { UnixStream::from_raw_fd(raw) };
    let paths: [PathBuf; 5] = receive(&mut control);
    let mut lanes = Vec::new();
    let end = Instant::now() + Duration::from_secs(10);
    for path in paths {
        loop {
            match UnixStream::connect(&path) {
                Ok(stream) => {
                    stream
                        .set_read_timeout(Some(Duration::from_secs(5)))
                        .unwrap();
                    stream
                        .set_write_timeout(Some(Duration::from_secs(5)))
                        .unwrap();
                    lanes.push(stream);
                    break;
                }
                Err(_) => {
                    assert!(
                        Instant::now() < end,
                        "original five-lane listeners unavailable"
                    );
                    std::thread::sleep(Duration::from_millis(5));
                }
            }
        }
    }
    send(&mut control, &1_u8);
    loop {
        match receive(&mut control) {
            PeerCommand::Exchange(request) => {
                send(&mut lanes[2], &request);
                let response: CognitiveCheckpointResponse = receive(&mut lanes[2]);
                send(&mut control, &response);
            }
            PeerCommand::CloseWithError => {
                // An invalid original frame makes serve_result an actual error.
                // Closing the other four lanes lets every scoped worker join.
                lanes[1].write_all(&[0; 4]).unwrap();
                drop(lanes);
                send(&mut control, &2_u8);
                // Remain alive after serving stopped: timeout/EOF is not exit.
                let mut wait = [0];
                let _ = control.read(&mut wait);
                return;
            }
        }
    }
}
