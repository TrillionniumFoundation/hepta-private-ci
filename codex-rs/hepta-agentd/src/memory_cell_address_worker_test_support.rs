//! A real Python process with no learned dependencies, solely for wire tests.

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::time::Duration;

use codex_hepta_cognitive_types::hnmf::ContractIdV1;

use super::MemoryCellAddressWorkerConfigV1;
use super::wire::canonical;
use super::wire::hash;

pub(super) struct WorkerFixture {
    _root: tempfile::TempDir,
    pub config: MemoryCellAddressWorkerConfigV1,
}

impl WorkerFixture {
    pub fn new() -> Self {
        let root = tempfile::tempdir().unwrap();
        let root_path = root.path().canonicalize().unwrap();
        let qualification = root_path.join("qualification");
        let addressing = qualification.join("memory-cell-v7/addressing");
        let encoder_code = qualification.join("memory-cell-v6/v6");
        let model = root_path.join("model");
        let encoder = root_path.join("encoder");
        for path in [&addressing, &encoder_code, &model, &encoder] { std::fs::create_dir_all(path).unwrap(); }
        let script = addressing.join("worker.py");
        std::fs::write(&script, MOCK_WORKER).unwrap();
        let mut pins = BTreeMap::new();
        pins.insert(script.clone(), hash(MOCK_WORKER.as_bytes()));
        for path in [addressing.join("__init__.py"), addressing.join("model.py"), addressing.join("contracts.py"),
            addressing.join("planner.py"), addressing.join("capabilities.py"), encoder_code.join("__init__.py"), encoder_code.join("encoder.py")] {
            std::fs::write(&path, "# Explicit protocol mock; not production addressing.\n").unwrap();
            pins.insert(path.clone(), hash(&std::fs::read(path).unwrap()));
        }
        let policy: BTreeMap<_, _> = ["model.py", "contracts.py", "planner.py", "capabilities.py"].into_iter()
            .map(|name| (name, pins[&addressing.join(name)].to_string())).collect();
        let manifest = canonical(&serde_json::json!({"schema": "hepta.memory.v7.intent-model.v1", "policy_digest": hash(&canonical(&serde_json::to_value(policy).unwrap()).unwrap())})).unwrap();
        std::fs::write(model.join("manifest.json"), &manifest).unwrap();
        let python: PathBuf = std::env::split_paths(&std::env::var_os("PATH").expect("Python test PATH"))
            .map(|directory| directory.join("python3")).find(|path| path.is_absolute() && path.is_file())
            .expect("stdlib Python 3 is required for actual worker transport tests");
        let config = MemoryCellAddressWorkerConfigV1 {
            python, worker_script: script, worker_script_digest: hash(MOCK_WORKER.as_bytes()), code_pins: pins,
            model_directory: model, model_digest: hash(&manifest), encoder_directory: encoder,
            aliases: BTreeMap::from([(ContractIdV1::new("meter:agentd-cell").unwrap(), vec!["meter alpha".to_string(), "测试读数".to_string(), "station".to_string(), "station-2025-02-01".to_string()])]),
            request_timeout: Duration::from_millis(1_500), startup_timeout: Duration::from_secs(5),
        };
        Self { _root: root, config }
    }
}

const MOCK_WORKER: &str = r#"import argparse, hashlib, json, os, sys, time
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument('--model'); p.add_argument('--model-digest'); p.add_argument('--encoder')
args = p.parse_args()
canonical = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
digest = lambda value: hashlib.sha256(canonical(value)).hexdigest()
manifest = json.loads((Path(args.model) / 'manifest.json').read_bytes())
print(json.dumps({'schema':'hepta.memory.v7.address-worker-ready.v1','model_digest':args.model_digest,'policy_digest':manifest['policy_digest'],'max_frame_bytes':2097152,'max_response_bytes':32768}), file=sys.stderr, flush=True)
first_cut = None
for raw in sys.stdin.buffer:
    frame = json.loads(raw)
    request, registry = frame['request'], frame['registry']
    assert set(frame) == {'schema', 'request', 'registry'}
    assert 'schema' not in request and 'operation' not in request
    assert all(set(row) == {'entity', 'aliases'} for row in registry['entities'])
    text, cut, reg = request['text'], registry['source_cut'], digest(registry)
    if first_cut is None: first_cut = cut
    if text == 'hang': time.sleep(10)
    if text == 'exit': raise SystemExit(3)
    if text == 'stderr-flood': sys.stderr.write('x' * 70000); sys.stderr.flush()
    if text == 'oversize': sys.stdout.write('x' * 32769 + '\n'); sys.stdout.flush(); continue
    if text == 'needs-alias': assert 'meter alpha' in registry['entities'][0]['aliases']
    plan = {'operation':'apply','required_cells':['event','semantic','procedure'],'read_hops':3,'source_cut':cut,'registry_digest':reg}
    decision = {'raw_operation':'apply','score':0.9,'margin':0.8,'score_kind':'explicit process protocol mock','capability_reason':None,'operation':'apply','threshold':0.5,'required_margin':0.1}
    if text.startswith('date-history') or text.startswith('date-change'):
        operation = 'history' if text.startswith('date-history') else 'change'
        assert request['at' if operation == 'history' else 'since'] == 20250201
        plan.update(operation=operation, required_cells=['event'], read_hops=1 if operation == 'history' else 2)
        decision.update(operation=operation, raw_operation=operation)
    result = {'schema':'hepta.memory.v7.address-decision.v1','query_id':request['query_id'],'request_digest':digest(request),'status':'accepted','reason':None,'request':request,'plan':plan,'model_digest':args.model_digest,'registry_digest':reg,'source_cut':cut,'decision':decision,'authority':False,'cost':{'request_body_bytes':len(raw)-1,'processing_wall_seconds':0.002,'processing_cpu_seconds':0.001}}
    if text in ('decline', 'unavailable'):
        result.update(status='rejected' if text == 'decline' else 'unavailable', reason='explicit process mock', request=None, plan=None)
    if text == 'authority': result['authority'] = True
    if text == 'unknown': result['new_authority'] = True
    if text == 'wrong-query': result['query_id'] = 'query:substitution'
    if text == 'wrong-request': result['request_digest'] = '1' * 64
    if text == 'wrong-model': result['model_digest'] = '2' * 64
    if text == 'wrong-registry': result['registry_digest'] = '3' * 64
    if text == 'old-cut': result['source_cut'] = first_cut
    if text == 'bad-plan': result['plan']['required_cells'] = ['event']
    if text == 'substitute': result['request'] = {**request, 'entity':'entity:substitution'}
    if text.endswith('mutate-time'): result['request'] = {**request, 'at':1738368000}
    if text.endswith('mutate-text'): result['request'] = {**request, 'text':'substituted text'}
    if text == 'missing-nullable': del result['reason']
    if text == 'nonfinite': result['decision']['score'] = float('nan')
    output = canonical(result)
    if text == 'duplicate': output = b'{"schema":"hepta.memory.v7.address-decision.v1",' + output[1:]
    if text == 'duplicate-score': output = output.replace(b'"score":0.9', b'"score":0.9,"score":0.9')
    if text == 'incomplete': sys.stdout.buffer.write(output); sys.stdout.buffer.flush(); raise SystemExit(4)
    sys.stdout.buffer.write(output + b'\n')
    if text == 'unsolicited': sys.stdout.buffer.write(output + b'\n')
    sys.stdout.buffer.flush()
"#;
