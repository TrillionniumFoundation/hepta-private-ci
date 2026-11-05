//! A stateful loopback provider: durably applies once, then loses the response.
//! Only this controlled provider's record supplies the later operation ID.
use super::*;
use std::io::Write;
use std::net::Shutdown;
use std::net::TcpListener;
use std::sync::OnceLock;
use std::sync::atomic::AtomicBool;
use std::thread::JoinHandle;

pub(super) struct LostAckProvider {
    pub(super) uri: String,
    pub(super) record_path: PathBuf,
    pub(super) posts: Arc<AtomicUsize>,
    pub(super) applies: Arc<AtomicUsize>,
    pub(super) lookups: Arc<AtomicUsize>,
    expected: Arc<OnceLock<ProviderEffectIntent>>,
    stop: Arc<AtomicBool>,
    join: Option<JoinHandle<anyhow::Result<()>>>,
    _directory: tempfile::TempDir,
}

impl LostAckProvider {
    pub(super) fn start() -> anyhow::Result<Self> {
        let directory = tempfile::tempdir()?;
        let record_path = directory.path().join("applied-operation.json");
        let record = record_path.clone();
        let listener = TcpListener::bind("127.0.0.1:0")?;
        let uri = format!("http://{}", listener.local_addr()?);
        listener.set_nonblocking(true)?;
        let expected = Arc::new(OnceLock::<ProviderEffectIntent>::new());
        let configured = Arc::clone(&expected);
        let posts = Arc::new(AtomicUsize::new(0));
        let post_count = Arc::clone(&posts);
        let applies = Arc::new(AtomicUsize::new(0));
        let apply_count = Arc::clone(&applies);
        let lookups = Arc::new(AtomicUsize::new(0));
        let lookup_count = Arc::clone(&lookups);
        let stop = Arc::new(AtomicBool::new(false));
        let stopping = Arc::clone(&stop);
        let join = thread::spawn(move || -> anyhow::Result<()> {
            let deadline = Instant::now() + Duration::from_secs(120);
            while !stopping.load(Ordering::SeqCst) && Instant::now() < deadline {
                let (mut stream, _) = match listener.accept() {
                    Ok(pair) => pair,
                    Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(1));
                        continue;
                    }
                    Err(error) => return Err(error.into()),
                };
                stream.set_read_timeout(Some(Duration::from_secs(2)))?;
                stream.set_write_timeout(Some(Duration::from_secs(2)))?;
                let mut request = Vec::new();
                let header_end = loop {
                    let mut part = [0; 1024];
                    let read = stream.read(&mut part)?;
                    anyhow::ensure!(read > 0, "provider request ended before headers");
                    request.extend_from_slice(&part[..read]);
                    anyhow::ensure!(request.len() <= 16 * 1024, "bounded provider request");
                    if let Some(at) = request.windows(4).position(|b| b == b"\r\n\r\n") {
                        break at + 4;
                    }
                };
                let headers = std::str::from_utf8(&request[..header_end])?;
                let mut lines = headers.split("\r\n");
                let request_line = lines.next().unwrap().to_string();
                let values: BTreeMap<String, String> = lines
                    .filter_map(|line| line.split_once(':'))
                    .map(|(k, v)| (k.to_ascii_lowercase(), v.trim().to_string()))
                    .collect();
                let length = values
                    .get("content-length")
                    .map(|v| v.parse::<usize>())
                    .transpose()?
                    .unwrap_or(0);
                anyhow::ensure!(length <= 1024, "bounded test provider body");
                while request.len() < header_end + length {
                    let mut part = [0; 1024];
                    let read = stream.read(&mut part)?;
                    anyhow::ensure!(read > 0, "provider request body incomplete");
                    request.extend_from_slice(&part[..read]);
                }
                let intent = configured
                    .get()
                    .ok_or_else(|| anyhow::anyhow!("provider has no expected operation"))?;
                anyhow::ensure!(
                    values
                        .get(PROVIDER_EFFECT_IDEMPOTENCY_KEY_HEADER)
                        .map(String::as_str)
                        == Some(intent.key.as_str()),
                    "provider received wrong operation key"
                );
                anyhow::ensure!(
                    values
                        .get(PROVIDER_EFFECT_PAYLOAD_SHA256_HEADER)
                        .map(String::as_str)
                        == Some(intent.payload_sha256.as_str()),
                    "provider received wrong payload digest"
                );
                if request_line.starts_with("POST /dispatch ") {
                    post_count.fetch_add(1, Ordering::SeqCst);
                    anyhow::ensure!(
                        &request[header_end..header_end + length] == WIRE,
                        "provider received different effect bytes"
                    );
                    if !record.exists() {
                        let mut material = b"actual-loopback-provider-application-v1\0".to_vec();
                        material.extend_from_slice(intent.key.as_str().as_bytes());
                        material.extend_from_slice(WIRE);
                        let operation = Sha256Digest::for_bytes(&material);
                        let body = serde_json::json!({"effect_key":intent.key.as_str(),"payload_sha256":intent.payload_sha256.as_str(),"provider_operation_id_sha256":operation.as_str(),"status":"completed"});
                        let mut file = fs::OpenOptions::new()
                            .write(true)
                            .create_new(true)
                            .open(&record)?;
                        file.write_all(&serde_json::to_vec(&body)?)?;
                        file.sync_all()?;
                        fs::File::open(record.parent().unwrap())?.sync_all()?;
                        apply_count.fetch_add(1, Ordering::SeqCst);
                    }
                    // The side effect is durable. Deliberately send no HTTP
                    // response bytes, so the client cannot know it completed.
                    stream.shutdown(Shutdown::Both)?;
                } else if request_line.starts_with("GET /status/") {
                    let index = lookup_count.fetch_add(1, Ordering::SeqCst);
                    if index == 0 {
                        stream.write_all(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")?;
                    } else {
                        let body = fs::read(&record)?;
                        let header = format!(
                            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                            body.len()
                        );
                        stream.write_all(header.as_bytes())?;
                        stream.write_all(&body)?;
                    }
                } else {
                    anyhow::bail!("unexpected provider request: {request_line}");
                }
            }
            Ok(())
        });
        Ok(Self {
            uri,
            record_path,
            posts,
            applies,
            lookups,
            expected,
            stop,
            join: Some(join),
            _directory: directory,
        })
    }

    pub(super) fn expect(&self, intent: ProviderEffectIntent) -> anyhow::Result<()> {
        self.expected
            .set(intent)
            .map_err(|_| anyhow::anyhow!("provider expectation already fixed"))
    }
}

impl Drop for LostAckProvider {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::SeqCst);
        if let Some(join) = self.join.take() {
            match join.join() {
                Ok(Ok(())) => {}
                Ok(Err(error)) => panic!("lost-ACK provider failed: {error}"),
                Err(panic) => std::panic::resume_unwind(panic),
            }
        }
    }
}
