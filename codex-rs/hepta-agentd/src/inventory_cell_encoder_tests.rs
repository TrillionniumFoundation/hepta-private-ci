//! Actual stdlib Python transport only; synthetic vectors make no language claim.

use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_types::Digest32;
use super::{InventoryCellEncoderWorkerConfigV1, InventoryCellEncoderWorkerV1};
use crate::INVENTORY_CELL_SEMANTIC_ENCODER_V1;

struct Fixture { _directory: tempfile::TempDir, config: InventoryCellEncoderWorkerConfigV1 }
impl Fixture {
    fn new() -> Self {
        let directory = tempfile::tempdir().unwrap();
        let root = directory.path().canonicalize().unwrap();
        let worker_script = root.join("worker.py");
        let encoder_source = root.join("encoder.py");
        std::fs::write(&worker_script, MOCK).unwrap();
        std::fs::write(&encoder_source, "# Wire-test-only source; no language model.\n").unwrap();
        let python: PathBuf = std::env::split_paths(&std::env::var_os("PATH").expect("Python test PATH"))
            .map(|directory| directory.join("python3")).find(|path| path.is_absolute() && path.is_file())
            .expect("stdlib Python 3 is required for actual semantic worker transport tests");
        let config = InventoryCellEncoderWorkerConfigV1 { python, worker_script, worker_digest: Digest32::of_bytes(MOCK.as_bytes()),
            source_digest: Digest32::of_bytes(&std::fs::read(&encoder_source).unwrap()), encoder_source,
            encoder_directory: root, encoder_digest: ContractDigestV1::from_digest(INVENTORY_CELL_SEMANTIC_ENCODER_V1.parse().unwrap()).unwrap(),
            startup_timeout: Duration::from_secs(5), request_timeout: Duration::from_secs(2) };
        Self { _directory: directory, config }
    }
}

#[tokio::test]
async fn inventory_semantic_worker_reuses_one_session_and_serializes_shared_callers() {
    let fixture = Fixture::new();
    let worker = Arc::new(InventoryCellEncoderWorkerV1::start(fixture.config.clone()).await.unwrap());
    let a = Arc::clone(&worker); let b = Arc::clone(&worker);
    let (first, second) = tokio::join!(a.encode("first"), b.encode("second"));
    assert_eq!(first.unwrap().unwrap()[0], 1.0); assert_eq!(second.unwrap().unwrap()[0], 1.0);
    assert!(worker.encode("truncate").await.unwrap().is_none());
    assert!(worker.encode("stderr-flood").await.unwrap().is_some());
    let metrics = worker.metrics();
    assert_eq!(metrics.process_starts, 1); assert_eq!(metrics.validated_responses, 4);
    assert_eq!(metrics.truncated_responses, 1); assert!(metrics.stdin_bytes > 0 && metrics.stdout_bytes > 0);
}

#[tokio::test]
async fn inventory_semantic_worker_rejects_substitution_and_restarts_without_reusing_a_tail() {
    for mutation in ["wrong-request", "wrong-text", "wrong-encoder", "oversize", "bad-shape", "bad-norm", "duplicate", "missing", "unsolicited", "unknown-field"] {
        let fixture = Fixture::new();
        let worker = InventoryCellEncoderWorkerV1::start(fixture.config.clone()).await.unwrap();
        assert!(worker.encode(mutation).await.is_err(), "{mutation}");
        assert!(worker.encode("recovered").await.unwrap().is_some(), "{mutation}");
        assert_eq!(worker.metrics().process_starts, 2, "{mutation}");
    }
}

#[tokio::test]
async fn inventory_semantic_worker_cancellation_and_changed_pins_do_not_reuse_child() {
    let fixture = Fixture::new();
    let worker = InventoryCellEncoderWorkerV1::start(fixture.config.clone()).await.unwrap();
    assert!(tokio::time::timeout(Duration::from_millis(30), worker.encode("hang")).await.is_err());
    assert!(worker.encode("recovered").await.unwrap().is_some());
    assert_eq!(worker.metrics().process_starts, 2);
    assert!(tokio::time::timeout(Duration::from_millis(30), worker.encode("hang")).await.is_err());
    std::fs::write(&fixture.config.encoder_source, "# Changed after cancellation.\n").unwrap();
    assert!(worker.encode("must-not-spawn-changed-code").await.is_err());
    assert_eq!(worker.metrics().process_starts, 2);
}

const MOCK: &str = r#"import argparse, hashlib, json, os, sys, time
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--encoder-source'); p.add_argument('--source-sha256'); p.add_argument('--encoder'); p.add_argument('--encoder-digest')
args = p.parse_args()
encode = lambda value: json.dumps(value, separators=(',', ':')).encode()
print(json.dumps({'schema':'hepta.memory.inventory-encoder-ready.v1','encoder_digest':args.encoder_digest,'worker_digest':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'source_digest':args.source_sha256,'dimension':384,'native_batch':1,'max_request':16384,'max_response':32768,'base_bytes':127536988}), file=sys.stderr, flush=True)
for raw in sys.stdin.buffer:
    frame = json.loads(raw)
    assert set(frame) == {'schema','request_id','text','text_digest','encoder_digest'}
    text = frame['text']
    if text == 'hang': time.sleep(10)
    if text == 'stderr-flood': sys.stderr.write('x' * 70000); sys.stderr.flush()
    if text == 'oversize': sys.stdout.write('x' * 32769 + '\n'); sys.stdout.flush(); continue
    response = {'schema':'hepta.memory.inventory-encoder-response.v1','request_id':frame['request_id'],'text_digest':frame['text_digest'],'encoder_digest':args.encoder_digest,'features':[1] + [0] * 383,'truncated':False,'tokens':4,'cpu_ns':100,'wall_ns':200}
    if text == 'truncate': response.update(features=[], truncated=True)
    if text == 'wrong-request': response['request_id'] += 1
    if text == 'wrong-text': response['text_digest'] = '1' * 64
    if text == 'wrong-encoder': response['encoder_digest'] = '2' * 64
    if text == 'bad-shape': response['features'] = [1]
    if text == 'bad-norm': response['features'] = [0] * 384
    if text == 'missing': del response['truncated']
    if text == 'unknown-field': response['authority'] = True
    output = encode(response)
    if text == 'duplicate': output = output.replace(b'"truncated":false', b'"truncated":false,"truncated":false')
    if text == 'unsolicited':
        frames = output + b'\n' + output + b'\n'
        assert len(frames) <= os.fpathconf(sys.stdout.fileno(), 'PC_PIPE_BUF')
        assert os.write(sys.stdout.fileno(), frames) == len(frames)
        continue
    sys.stdout.buffer.write(output + b'\n'); sys.stdout.buffer.flush()
"#;
