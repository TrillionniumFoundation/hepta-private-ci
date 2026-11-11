"""New post-reset preparation: explicit assembly, then separately authorized audit.
No network, model, E, or production input is accessed at import time.
"""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import resource
import stat
import sys
import time
import traceback
import zipfile
from os_processes import observe, read_stat
HERE = Path(__file__).resolve().parent
CORE = {'bytes': 73473, 'sha256': '87bedabde7f37ec8d70a80305691f1116e80493174a5cd33bf7058f635230b3a'}
MANIFEST = '4cc126ad4cf11e12c80408a868f8c673be70bccdce95a02228fda9d1543ef8d2'
PLAN = '1fc0d941bc9d96544c8caa5740aaba130685fed74b620f6e62dc22bec4a715ad'
ACK = '88bbf74d557296ef351d7e4e6b697c5a8d5dbbcb1e336aabf7e275bd02a3a972'
FIRST = 'cb53a28e0b43acf0dfddb76c67dfc0042c4d0b5dc33b2ab3e9e1856add08a55c'
JOB, KEY = '1a1c74f3308-be2a-75', 'hcsn-c2-native-execution-c385-v1'
REQUEST = '0f1c7c91dfd667d6965e38fb20c584da94dca5918b17778c08153f7027b2b6ee'
RESOURCES = dict(whole_hard_wall_seconds=1800, metadata_soft_wall_seconds=360, per_full_D_hard_wall_seconds=210,
                final_reserve_seconds=60, RSS_bytes=2147483648, address_space_bytes=8589934592, workers=1, threads=1)
NAMES = [f'hcsn-s{s}-lr{lr}' for s in (101, 211, 307) for lr in ('0.001', '0.003')]
def require(ok, message):
    if not ok: raise ValueError(message)
def ident(raw): return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
def save(path, value):
    raw = value if isinstance(value, bytes) else (json.dumps(value, indent=2, allow_nan=False)+'\n').encode()
    with Path(path).open('xb') as f:
        f.write(raw)
    return {'path': str(Path(path).resolve()), **ident(raw)}
class Reader:
    def __init__(self, deadline):
        self.deadline, self.inputs, self.bytes = deadline, {}, 0
    def read(self, spec):
        require(time.monotonic() <= self.deadline, 'setup deadline exhausted')
        p = Path(spec['path'])
        require(p.is_absolute() and not p.is_symlink() and stat.S_ISREG(p.stat().st_mode), 'nonregular input')
        size = p.stat().st_size
        self.bytes += size+1
        require(self.bytes <= 32*1024**2, 'metadata/source read allowance exhausted')
        with p.open('rb') as f:
            raw = f.read(size+1)
        require(ident(raw) == {k: spec[k] for k in ('bytes', 'sha256')}, 'input identity changed: '+str(p))
        require(str(p) not in self.inputs or self.inputs[str(p)] == ident(raw), 'input changed between reads')
        self.inputs[str(p)] = ident(raw)
        return raw
    def verify(self):
        for p, info in list(self.inputs.items()):
            self.read({'path': p, **info})
def payload(raw):
    for _ in range(5):
        obj = json.loads(raw)
        wrappers = [k for k in ('raw','result') if k in obj]
        require(len(wrappers) <= 1 and not obj.get('isError'), 'ambiguous/error response wrapper')
        if wrappers:
            raw = json.dumps(obj[wrappers[0]], ensure_ascii=False).encode()
        elif 'content' in obj:
            texts = [x['text'] for x in obj['content'] if x.get('type') == 'text']
            require(len(texts) == 1 and not obj.get('isError'), 'ambiguous/error MCP payload')
            raw = texts[0].encode()
        else:
            return obj, raw
    raise ValueError('excessive response wrapping')
def capsule(raw, target):
    import io
    require(ident(raw) == CORE, 'frozen auditor capsule changed')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = z.namelist()
        require(len(names) == len(set(names)) and sum(i.file_size for i in z.infolist()) < 4*1024**2, 'bad capsule roster/size')
        require(all(not Path(n).is_absolute() and '..' not in Path(n).parts and '\\' not in n
                    and not i.is_dir() and not stat.S_ISLNK(i.external_attr >> 16) for n, i in zip(names, z.infolist())), 'unsafe capsule')
        require(z.testzip() is None and ident(z.read('MANIFEST.json'))['sha256'] == MANIFEST, 'capsule CRC/manifest')
        files = json.loads(z.read('MANIFEST.json'))['files']
        require(set(names) == set(files)|{'MANIFEST.json'} and all(ident(z.read(n)) == v for n, v in files.items()), 'capsule member mismatch')
        require(ident(z.read('PLAN.json'))['sha256'] == PLAN, 'auditor plan changed')
        plan = json.loads(z.read('PLAN.json')); plan['_prepared_root'] = json.loads(z.read('original-replay-plan.json'))['prepared']
        if target is not None:
            target.mkdir()
            for n in names: save(target/n, z.read(n))
    return plan
def probe(pid):
    try: return read_stat(pid)
    except (FileNotFoundError, ProcessLookupError): return None
def quiescent(pids, needles):
    require(len(pids) == 7 and len(set(pids)) == 7 and all(type(p) is int and p > 1 for p in pids), 'seven distinct original PIDs required')
    records = {str(p): probe(p) for p in pids}
    require(all(v is None or v['state'] == 'Z' for v in records.values()), 'original process remains active')
    for p in Path('/proc').iterdir():
        if not p.name.isdigit() or int(p.name) == os.getpid():
            continue
        try:
            if p.stat().st_uid == os.getuid():
                command = (p/'cmdline').read_bytes().split(b'\0')
                is_python = command[0] and Path(os.fsdecode(command[0])).name.startswith('python')
                require(not (is_python and any(n.encode() in command[1:3] for n in needles)), 'matching original process remains')
        except (FileNotFoundError, ProcessLookupError):
            pass
    return {'known_process_records': records, 'same_UID_matching_command_lines': [], 'unreadable': [],
            'observed_monotonic': time.monotonic(), 'scope': 'actual current /proc observations; unknown/unreadable raises'}
def terminal_inputs(auth, reader, plan, output, barrier):
    inputs, paths = auth['inputs'], plan['native_paths']
    ack_raw, first_raw = reader.read(inputs['launch_ack']), reader.read(inputs['first_commands'])
    require(ident(ack_raw)['sha256'] == ACK and ident(first_raw)['sha256'] == FIRST, 'original launch bytes differ')
    ack, _ = payload(ack_raw)
    require((ack['job']['id'], ack['job']['idempotency_key'], ack['job']['request_digest']) == (JOB, KEY, REQUEST), 'original durable job identity')
    terminal, terminal_raw = payload(reader.read(inputs['daemon_status']))
    require(terminal['job_id'] == JOB and terminal['state'] in ('succeeded', 'failed', 'cancelled')
            and all(terminal[k] is True for k in ('output_complete', 'output_durable', 'terminal_publication_confirmed'))
            and terminal['automatic_retry'] is False and type(terminal['exit_code']) is int, 'no durable terminal')
    streams = {s: bytearray() for s in ('stdout', 'stderr')}
    require(inputs['daemon_read_pages'], 'complete raw daemon pages required')
    for spec in inputs['daemon_read_pages']:
        page, _ = payload(reader.read(spec))
        require(page['job_id'] == JOB, 'output belongs to another job')
        for name, raw in streams.items():
            part, total = page[name], terminal['log_bytes'][name]
            chunk = bytes.fromhex(part['bytes_hex'])
            require(part['offset'] == len(raw) and part['next_offset'] == len(raw)+len(chunk)
                    and part['size'] == total['stored'] == total['seen'] and part['next_offset'] <= part['size'], 'log cursor/length mismatch')
            require(terminal['log_synced'][name] is True and terminal['log_errors'][name] is None
                    and terminal['log_truncated'][name] is False, 'incomplete native log')
            raw.extend(chunk)
    require(all(page[n]['eof'] is True and len(v) == terminal['log_bytes'][n]['stored'] for n,v in streams.items()), 'native logs not fully read')
    prints = [json.loads(line) for line in streams['stdout'].splitlines() if line.startswith(b'{')]
    ready_prints = [r for r in prints if r.get('status') == 'verified_ready_to_exec_once']
    require(len(ready_prints) == 1, 'unique exec witness missing')
    witness = ready_prints[0]
    require(witness['ready_receipt'] == inputs['ready']['path'] == paths['bootstrap']+'/READY.json'
            and witness['controller_output'] == paths['controller'], 'exec witness path mismatch')
    starts = [r for r in map(json.loads, first_raw.splitlines()) if r.get('status') == 'running']
    require(len(starts) == 6 and {r['name'] for r in starts} == set(NAMES), 'original dispatch roster')
    pids = [witness['pid']]+[r['pid'] for r in starts]
    observation = quiescent(pids, [paths['program']+'/'+n+'.py' for n in ('c2_controller','c2_runner')])
    ready = json.loads(reader.read(inputs['ready']))
    require(ready['status'] == witness['status'] and ready['bootstrap_program']['sha256'] == '0216804222e042df1b7d21dc989840bf5d56cf279e72ba79eedeefd022691dc6'
            and ready['source_capsule']['sha256'] == plan['fixed_identities']['C2_program_capsule_sha256'], 'ready source differs')
    decision_raw = reader.read(inputs['decision'])
    require(ident(decision_raw)['sha256'] == plan['fixed_identities']['root_decision_sha256']
            and ready['decision'] == ident(decision_raw), 'original C2 decision differs')
    require(inputs['controller_result']['path'] == paths['controller']+'/RESULT.json'
            and inputs['commands']['path'] == paths['controller']+'/commands.jsonl', 'final output paths differ')
    controller = json.loads(reader.read(inputs['controller_result']))
    commands_raw = reader.read(inputs['commands'])
    commands = list(map(json.loads, commands_raw.splitlines()))
    require(commands_raw.startswith(first_raw) and ident(commands_raw) == controller['commands']
            and {r['name'] for r in commands} == set(NAMES), 'command prefix/roster/source differs')
    require({r['pid'] for r in controller['attempts']} == set(pids[1:]), 'final PIDs differ from original dispatch')
    barrier(controller, commands, NAMES, lambda p: 'absent' if observation['known_process_records'][str(p)] is None else 'zombie')
    native = save(output/'NATIVE-TERMINAL.json', terminal_raw)
    for name, raw in streams.items():
        save(output/('native-'+name), bytes(raw))
    return {'schema': 'independent-c2-terminal-binding-v1', 'all_attempts_terminal': True,
        'controller_result': {k: inputs['controller_result'][k] for k in ('bytes','sha256')},
        'native_job_id': JOB, 'controller_pid': witness['pid'], 'decision_path': inputs['decision']['path'],
        'native_terminal': {'path': native['path'], 'identity': {k:native[k] for k in ('bytes','sha256')}}}, pids, observation
def main(args):
    start, output, owned = time.monotonic(), Path(args.output).resolve(), False
    row = dict(schema='c2-auditor-bootstrap-recovery-v3', mode=args.mode, status='failed_or_incomplete',
               automatic_retry=False, scientific_admission='HOLD', confirmation_E_access=False)
    reader, audit_end = Reader(start+120), None
    try:
        raw = Path(args.authorization).read_bytes()
        require(len(raw) <= 131072 and ident(raw)['sha256'] == args.authorization_sha, 'root authorization identity')
        reader.inputs[str(Path(args.authorization).resolve())] = ident(raw)
        auth = json.loads(raw)
        require(auth['bootstrap_sources'] == {n:ident((HERE/n).read_bytes()) for n in ('bootstrap.py','os_processes.py')}, 'bootstrap source pin')
        require(auth['confirmation_E_access'] is False and auth['core_zip']['sha256'] == CORE['sha256'], 'scope/core pin')
        core_raw = reader.read(auth['core_zip']); plan = capsule(core_raw, None)
        paths = plan['native_paths']
        protected = [plan['_prepared_root']]+[paths[k] for k in ('controller','program','bootstrap','original_campaign','model_source')]
        require(str(output) == auth['output_directory'] and not any(output.is_relative_to(Path(p)) or Path(p).is_relative_to(output) for p in protected), 'unbound output or production/data overlap')
        output.mkdir(exist_ok=False); owned=True; capsule(core_raw, output/'core')
        sys.path.insert(0, str(output/'core'))
        bound = importlib.import_module('bound_io')
        if args.mode == 'assemble':
            require(auth['assembly_authorized'] is True and auth['execution_authorized'] is False
                    and auth['scope'] == 'independent-c2-terminal-input-assembly-only' and auth['assembly_resources'] == {'whole_wall_seconds':120,'RSS_bytes':268435456,'workers':1,'threads':1,'automatic_retry':False}, 'assembly permission or limits')
            binding, pids, observation = terminal_inputs(auth, reader, plan, output, bound.terminal_barrier)
            row.update(binding=save(output/'BINDING.json', binding), original_pids=pids, before=observation)
        else:
            require(auth['execution_authorized'] is True and auth['scope'] == 'independent-c2-terminal-audit-only'
                    and auth['resources'] == RESOURCES and sys.executable == paths['python'], 'native audit permission/runtime/envelope')
            assembly = json.loads(reader.read(auth['assembly_receipt']))
            require(assembly['status'] == 'assembled_not_executed' and assembly['inputs_unchanged'] is True, 'no verified assembly')
            pids = assembly['original_pids']
            for path, info in assembly['inputs'].items(): reader.read({'path':path, **info})
            binding_raw = reader.read(auth['binding'])
            require(ident(binding_raw)['sha256'] == auth['binding_sha256'], 'binding identity')
            row['before'] = quiescent(assembly['original_pids'], [paths['program']+'/'+n+'.py' for n in ('c2_controller','c2_runner')])
            bound.read_authorization(args.authorization, args.authorization_sha, auth['binding']['path'], auth['binding_sha256'])
            env = dict(os.environ, OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1', CUDA_VISIBLE_DEVICES='', PYTHONDONTWRITEBYTECODE='1')
            os.chdir(output/'core'); (output/'preflight').mkdir()
            preflight, _ = observe([sys.executable,'-B','-m','unittest','test_synthetic','test_controller_closure','test_recording_links','-v'], output/'preflight', env, min(90, reader.deadline-time.monotonic()), 2147483648, launch_deadline=reader.deadline)
            row['preflight'] = save(output/'PREFLIGHT-OS.json', preflight)
            require(preflight['process_gate_passed'] and b'Ran 28 tests' in (output/'preflight/stderr').read_bytes(), 'native software preflight failed')
            reader.verify(); require(bound.verify_program(output/'core') == MANIFEST, 'auditor source changed'); require(time.monotonic() <= reader.deadline, 'setup exceeded 120 seconds')
            (output/'audit-os').mkdir()
            argv = [sys.executable,'-B','launch.py','--authorization',args.authorization,'--authorization-sha',args.authorization_sha,
                    '--binding',auth['binding']['path'],'--binding-sha',auth['binding_sha256'],'--output',str(output/'audit'),'--launch-directory',str(output/'audit-launch')]
            actual, _ = observe(argv, output/'audit-os', env, 1800, 2147483648, launch_deadline=reader.deadline)
            audit_end = actual.get('wait4_completed_monotonic') or time.monotonic(); reader.deadline = audit_end+30
            row['audit_complete_OS'] = save(output/'AUDIT-OS.json', actual)
            row['setup_wall_seconds'] = actual['popen_started_monotonic']-start if actual.get('popen_started_monotonic') is not None else None
            require(actual['process_gate_passed'] and row['setup_wall_seconds'] is not None and 0 <= row['setup_wall_seconds'] <= 120, 'actual audit/startup envelope not admitted')
            inner = json.loads((output/'audit-launch/RECEIPT.json').read_bytes())
            require(inner['status'] == 'completed' and inner.get('archive_finalized') is True and inner.get('CPU_is_lower_bound') is False, 'core terminal evidence incomplete')
            row['archive'] = importlib.import_module('launch').verify_archive(output/'audit.zip', MANIFEST,
                max(actual['sampled_peak_RSS_bytes'],actual['wait4_peak_RSS_bytes']),actual['whole_child_wall_seconds'])
        reader.verify()
        require(bound.verify_program(output/'core') == MANIFEST, 'auditor source changed')
        row['after'] = quiescent(pids, [paths['program']+'/'+n+'.py' for n in ('c2_controller','c2_runner')])
        require(auth['bootstrap_sources'] == {n:ident((HERE/n).read_bytes()) for n in ('bootstrap.py','os_processes.py')}, 'bootstrap source changed')
        require(time.monotonic() <= reader.deadline and resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024 <= (268435456 if args.mode=='assemble' else 2147483648), 'finalization time/own RSS exceeded')
        row.update(status='assembled_not_executed' if args.mode=='assemble' else 'completed_audit_envelope', inputs_unchanged=True)
    except Exception:
        row.update(error=traceback.format_exc(), inputs_unchanged=False, archive_admitted=False)
    finally:
        row.update(inputs=reader.inputs, whole_bootstrap_wall_prefix_seconds=time.monotonic()-start,
            own_CPU_prefix_seconds=time.process_time(), own_peak_RSS_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
            limits={'setup_seconds':120,'native_software_tests_seconds':90 if args.mode=='execute' else 0,'audit_seconds':1800 if args.mode=='execute' else 0,'finalization_seconds':30 if args.mode=='execute' else 0,'native_outer_seconds':1950 if args.mode=='execute' else 120,'own_RSS_bytes':268435456 if args.mode=='assemble' else 2147483648},
            complete_native_exit_required=True, cost_scope='Child wait4 rows are disjoint; bootstrap own prefix excludes receipt save/exit. Native 1950-second full terminal remains independently required.')
        if owned: save(output/'RECEIPT.json', row)
        else: print(json.dumps(row), flush=True)
    return 0 if row['status'] in ('assembled_not_executed','completed_audit_envelope') else 2
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('authorization','authorization-sha','output'): parser.add_argument('--'+key, required=True)
    parser.add_argument('--mode', choices=('assemble','execute'), required=True)
    raise SystemExit(main(parser.parse_args()))
