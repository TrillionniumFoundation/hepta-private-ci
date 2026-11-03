#!/usr/bin/env python3
"""Qualify acknowledged recovery on the exact checked-owner candidate and original workspace."""
from pathlib import Path
import datetime
import hashlib
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
VALIDATION = ROOT / 'validation'
FROZEN = ROOT.parent / 'objective-owner'
TASK = Path('/dev/shm/organ-3d6a75235bcb-hepta3398')
SOURCE = TASK / 'source'
TARGET = TASK / 'target'
spec = importlib.util.spec_from_file_location('frozen_overlay_verifier', FROZEN / 'validation/owner_overlay.py')
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


def changes():
    frozen = json.loads((FROZEN / 'publication/manifest.json').read_text())
    rows = {row['path']: {k: row[k] for k in ('path', 'preimage_git_blob', 'preimage_sha256', 'candidate_git_blob', 'candidate_sha256', 'mode', 'bytes')} for row in frozen['files']}
    delta = []
    for path in sorted((ROOT / 'change').rglob('*')):
        if not path.is_file():
            continue
        name = path.relative_to(ROOT / 'change').as_posix()
        assert name.startswith('codex-rs/hepta-memory/'), name
        assert name in rows, 'New paths require an explicit original-tree provenance extension.'
        data = path.read_bytes()
        previous = rows[name].copy()
        base = FROZEN / 'change' / name
        assert verifier.digest(base.read_bytes()) == previous['candidate_sha256'], name
        rows[name].update(candidate_git_blob=verifier.blob(data), candidate_sha256=verifier.digest(data), bytes=len(data))
        delta.append({'path': name, 'frozen_preimage_git_blob': previous['candidate_git_blob'], 'frozen_preimage_sha256': previous['candidate_sha256'], 'candidate_git_blob': rows[name]['candidate_git_blob'], 'candidate_sha256': rows[name]['candidate_sha256'], 'bytes': len(data)})
    assert delta, 'No checked-append overlay.'
    return [rows[name] for name in sorted(rows)], delta


def resources():
    available = next(int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
    return {'at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'memory_available_bytes': available, 'shm_available_bytes': shutil.disk_usage(TASK).free, 'target_apparent_bytes': int(subprocess.check_output(['du','-sb',str(TARGET)],text=True).split()[0])}


def main():
    mode = sys.argv[1]
    rows, delta = changes()
    if mode == 'apply':
        original = json.loads((ROOT.parent/'owner-checked/validation/overlay-identity.json').read_text())['changes']
        immediate = json.loads((VALIDATION/'source-manifest.json').read_text())['files']
        for row in immediate:
            assert verifier.blob((SOURCE/row['path']).read_bytes()) == row['preimage_git_blob'], row['path']
        before = verifier.verify(original)
        for row in delta:
            (SOURCE/row['path']).write_bytes((ROOT/'change'/row['path']).read_bytes())
        after = verifier.verify(rows)
        record = {'original_base_head': verifier.BASELINE['head'], 'original_base_tree': verifier.BASELINE['tree'], 'frozen_source_manifest_sha256': verifier.digest((FROZEN/'publication/manifest.json').read_bytes()), 'changes': rows, 'ack_delta_from_frozen_owner': delta, 'immediate_preimages': immediate, 'verification_before':before, 'verification_after':after}
        output = VALIDATION/'overlay-identity.json'
        assert not output.exists()
        output.write_text(json.dumps(record,indent=2)+'\n')
        print(json.dumps({'operation':'apply','delta_files':len(delta),'verification':after}))
        return 0
    run = sys.argv[2]
    assert re.fullmatch('[a-z0-9-]+',run)
    prefix = VALIDATION/run
    assert not prefix.with_suffix('.json').exists(), 'Never replace a receipt.'
    identity = json.loads((VALIDATION/'overlay-identity.json').read_text())
    assert identity['changes'] == rows
    verified_before = verifier.verify(rows)
    if mode == 'memory-all':
        command = ['just','test','--locked','--cargo-profile','dev-small','--build-jobs','1','--test-threads','1','-p','codex-hepta-memory','--lib']
    elif mode == 'acknowledged':
        command = ['just','test','--locked','--cargo-profile','dev-small','--build-jobs','1','--test-threads','1','-p','codex-hepta-memory','--lib','-E','test(snapshot_acknowledged_)']
    elif mode == 'format-check':
        command = ['just','fmt','--check']
    elif mode == 'fix':
        command = ['just','fix','-p','codex-hepta-memory','--locked','--profile','dev-small','--lib']
    else:
        raise ValueError(mode)
    env = os.environ.copy()
    overrides = {'PATH':'/tmp/hepta-native-rustup/toolchains/1.95.0-x86_64-unknown-linux-gnu/bin:/tmp/hepta-native-cargo/bin:/tmp/hepta-output-portfolio-env/bin:/usr/local/bin:/usr/bin:/bin','CARGO_HOME':str(TASK/'cargo-home'),'CARGO_TARGET_DIR':str(TARGET),'TMPDIR':str(TASK/'tmp'),'RUSTUP_HOME':'/tmp/hepta-native-rustup','RUSTUP_TOOLCHAIN':'1.95.0','RUSTUP_AUTO_INSTALL':'0','CARGO_INCREMENTAL':'0','CARGO_BUILD_JOBS':'1','CARGO_HTTP_TIMEOUT':'30','CARGO_NET_RETRY':'1','OPENSSL_LIB_DIR':'/usr/lib/x86_64-linux-gnu','OPENSSL_INCLUDE_DIR':'/usr/include'}
    env.update(overrides)
    if mode == 'fix':
        overrides.update(GIT_DIR=str(FROZEN/'validation/format-baseline.git'), GIT_WORK_TREE=str(SOURCE))
        env.update(overrides)
        for row in rows:
            backup=VALIDATION/'quality-preimages'/run/row['path']
            backup.parent.mkdir(parents=True,exist_ok=True)
            backup.write_bytes((SOURCE/row['path']).read_bytes())
    tool_versions = {}
    for invocation in [['rustc','-Vv'],['cargo','-Vv'],['cargo','nextest','--version'],['just','--version']]:
        result = subprocess.run(invocation,env=env,capture_output=True,text=True)
        tool_versions[' '.join(invocation)] = {'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
    lock = SOURCE/'codex-rs/Cargo.lock'
    lock_before = verifier.digest(lock.read_bytes())
    measurements=[resources()]
    assert measurements[0]['memory_available_bytes'] >= 1536*1024**2
    assert measurements[0]['shm_available_bytes'] >= 256*1024**2
    stop=None
    started=datetime.datetime.now(datetime.timezone.utc).isoformat()
    junit=SOURCE/'codex-rs/target/nextest/local/junit.xml'
    junit_preimage=verifier.digest(junit.read_bytes()) if junit.exists() else None
    with prefix.with_suffix('.stdout').open('w') as stdout,prefix.with_suffix('.stderr').open('w') as stderr:
        process=subprocess.Popen(command,cwd=SOURCE,env=env,stdout=stdout,stderr=stderr,start_new_session=True)
        print(json.dumps({'command':command,'initial_resources':measurements[0],'ack_delta_from_frozen_owner':delta}),flush=True)
        last=time.monotonic()
        while process.poll() is None:
            time.sleep(1)
            if time.monotonic()-last<10:
                continue
            last=time.monotonic()
            measured=resources(); measurements.append(measured)
            print(json.dumps(measured),flush=True)
            if measured['memory_available_bytes']<1536*1024**2:
                stop='Available memory fell below the coordinated 1.5 GiB boundary.'
            elif measured['shm_available_bytes']<256*1024**2:
                stop='Shared-memory space fell below the coordinated 256 MiB boundary.'
            if stop:
                os.killpg(process.pid,signal.SIGTERM)
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL); process.wait()
                break
        code=process.wait()
    verification_error=None
    try: verified_after=verifier.verify(rows)
    except Exception as error:
        verification_error=repr(error); verified_after=None
    lock_after=verifier.digest(lock.read_bytes())
    receipt={'original_base_head':identity['original_base_head'],'original_base_tree':identity['original_base_tree'],'source_is_recorded_candidate_overlay':True,'frozen_source_manifest_sha256':identity['frozen_source_manifest_sha256'],'source_changes':rows,'ack_delta_from_frozen_owner':delta,'command':command,'cwd':str(SOURCE),'environment_overrides':overrides,'tool_versions':tool_versions,'started_at':started,'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'exit_code':code,'controlled_stop_reason':stop,'source_verification_before':verified_before,'source_verification_after':verified_after,'source_verification_error':verification_error,'Cargo_lock_sha256_before':lock_before,'Cargo_lock_sha256_after':lock_after,'resources':measurements+[resources()]}
    if mode in ('memory-all','acknowledged') and junit.exists():
        data=junit.read_bytes(); current=verifier.digest(data)
        receipt['junit_updated']=current!=junit_preimage
        if current!=junit_preimage:
            prefix.with_suffix('.junit.xml').write_bytes(data)
            receipt['junit_sha256']=current
    for extension in ('stdout','stderr'):
        path=prefix.with_suffix('.'+extension)
        receipt[extension+'_file']=path.name
        receipt[extension+'_sha256']=verifier.digest(path.read_bytes())
    prefix.with_suffix('.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'receipt':str(prefix.with_suffix('.json')),'exit_code':code,'controlled_stop_reason':stop,'source_verification_error':verification_error,'stderr_tail':prefix.with_suffix('.stderr').read_text()[-6500:]}),flush=True)
    if stop: return 130
    if verification_error or lock_before!=lock_after: return 3
    return code if code>=0 else 128-code

if __name__=='__main__':
    raise SystemExit(main())
