from pathlib import Path
import hashlib, json, os, shutil, subprocess, tempfile, time

BASE = Path(__file__).resolve().parents[1]
DATA = Path('/data/asterinas-audit-build.8tdrjboi')
SOURCE = DATA / 'native-authority-five-lane-source'
OUT = DATA / 'native-authority-static-b182-five-lane-04'
HEAD = 'b182ce0c7b137f76c7d2126535fbdc4273fa1882'
OUT.mkdir(mode=0o700, exist_ok=False)
target = DATA / 'native-authority-static-196-target'
temporary = Path(tempfile.mkdtemp(prefix='native-authority-tmp.', dir='/data'))
toolchain = Path.home() / '.rustup/toolchains/1.96.0-x86_64-unknown-linux-gnu'

def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()

def git(*args):
    return subprocess.check_output(['git', *args], cwd=SOURCE, text=True).strip()

def snapshot():
    assert git('rev-parse', 'HEAD') == HEAD
    assert not git('status', '--porcelain=v1', '--untracked-files=all')
    records = []
    for entry in subprocess.check_output(['git', 'ls-files', '-s', '-z'], cwd=SOURCE).split(b'\0'):
        if not entry:
            continue
        attributes, pathbytes = entry.split(b'\t', 1)
        mode, blob, stage = attributes.decode().split()
        assert stage == '0'
        path = SOURCE / os.fsdecode(pathbytes)
        content = os.readlink(path).encode() if mode == '120000' else path.read_bytes()
        assert hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest() == blob
        records.append({'path': os.fsdecode(pathbytes), 'mode': mode, 'blob': blob,
                        'sha256': hashlib.sha256(content).hexdigest()})
    return {'head': HEAD, 'tree': git('rev-parse', 'HEAD^{tree}'), 'tracked_files': records}

before = snapshot()
(OUT / 'source-before.json').write_text(json.dumps(before, indent=2) + '\n')
pair = Path('/data/hepta-dependency-v8-pair/rusty-v8-150.4.0-x86_64-unknown-linux-gnu')
archive = pair / 'librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz'
bindings = pair / 'src_binding_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.rs'
assert sha(archive) == 'a35c75d1f26e6a983885a45b33490a4ebe54f05050568b32b89cfb421b30b583'
assert sha(bindings) == '7727826ae479bdb645e807239fb12d1f8e2e23de7a6cf16f5ee592690d1d8506'
assert target.is_dir()
previous_build=json.loads((DATA/'native-authority-static-5a2-clock-03/result.json').read_text())
assert previous_build['packaged'] and previous_build['source_inputs_unchanged']
env = os.environ.copy()
env.update(PATH=str(toolchain / 'bin') + ':/usr/bin:/bin:/usr/sbin:/sbin',
           RUSTUP_TOOLCHAIN='1.96.0', RUSTC=str(toolchain / 'bin/rustc'),
           CARGO_TARGET_DIR=str(target), TMPDIR=str(temporary), CARGO_NET_OFFLINE='true',
           CARGO_INCREMENTAL='0', CARGO_BUILD_JOBS='2', OPENSSL_STATIC='1',
           LANG='C.UTF-8', LC_ALL='C.UTF-8',
           RUSTY_V8_ARCHIVE=str(archive), RUSTY_V8_SRC_BINDING_PATH=str(bindings),
           CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_RUSTFLAGS='-C target-feature=+crt-static -C relocation-model=static -C link-arg=-no-pie')
command = [str(toolchain / 'bin/cargo'), 'build', '--manifest-path', 'codex-rs/Cargo.toml',
           '--locked', '--offline', '--release', '--target', 'x86_64-unknown-linux-gnu',
           '-p', 'codex-hepta-agentd', '--bin', 'hepta-authority-host',
           '--example', 'authority_host_peer_qualification', '-j2']
report = {'schema': 'hepta.native-authority-static-build.v1', 'source_head': HEAD,
          'source_tree': before['tree'], 'commands': [command], 'target': str(target),
          'temporary': str(temporary), 'profile_overridden': False, 'features_disabled': False,
          'fresh_target': False, 'cache_reused': 'completed original5a2 clock static1.96 target, exclusive subsequent use; no qualification transferred', 'cold_supplier_cache_claimed': False,
          'v8_archive_sha256': sha(archive), 'v8_bindings_sha256': sha(bindings),
          'environment': {key: env[key] for key in ['RUSTUP_TOOLCHAIN', 'RUSTC', 'CARGO_TARGET_DIR',
            'TMPDIR', 'CARGO_NET_OFFLINE', 'CARGO_INCREMENTAL', 'CARGO_BUILD_JOBS', 'OPENSSL_STATIC',
            'RUSTY_V8_ARCHIVE', 'RUSTY_V8_SRC_BINDING_PATH', 'CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_RUSTFLAGS']},
          'built': False, 'packaged': False, 'executed_binary': False,
          'production_authority': False, 'g2_complete': False}
def save():
    (OUT / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
save()
start = time.monotonic()
try:
    with (OUT / 'build.log').open('xb') as log:
        result = subprocess.run(command, cwd=SOURCE, env=env, stdout=log,
                                stderr=subprocess.STDOUT, timeout=7200)
    report['build_exit'] = result.returncode
    assert result.returncode == 0, 'actual original static build failed'
    release = target / 'x86_64-unknown-linux-gnu/release'
    products = {'hepta-authority-host': release / 'hepta-authority-host',
                'authority_host_peer_qualification': release / 'examples/authority_host_peer_qualification'}
    packaged = OUT / 'packaged'
    packaged.mkdir(mode=0o700)
    report['products'] = {}
    for name, binary in products.items():
        shutil.copyfile(binary, OUT / (name + '.unstripped'))
        shutil.copyfile(binary, packaged / name)
        (packaged / name).chmod(0o755)
        report['products'][name] = {'unstripped_bytes': binary.stat().st_size, 'unstripped_sha256': sha(binary)}
    report['built'] = True
    save()
    script = SOURCE / '.github/scripts/archive-release-symbols-and-strip-binaries.sh'
    packaging = ['/bin/bash', str(script), '--target', 'x86_64-unknown-linux-gnu',
        '--artifact-name', 'hepta-authority-b182-five-lane-static-04', '--release-dir', str(packaged),
        '--archive-dir', str(OUT / 'symbols-dist'), '--binaries', ' '.join(products)]
    report['commands'].append(packaging)
    with (OUT / 'original-packaging.log').open('xb') as log:
        result = subprocess.run(packaging, cwd=SOURCE, env=dict(env, RUNNER_TEMP=str(temporary)),
                                stdout=log, stderr=subprocess.STDOUT, timeout=600)
    report['packaging_exit'] = result.returncode
    assert result.returncode == 0
    for name in products:
        binary = packaged / name
        report['products'][name].update(packaged_bytes=binary.stat().st_size, packaged_sha256=sha(binary))
        with (OUT / (name + '-readelf.txt')).open('xb') as log:
            subprocess.run(['/usr/bin/readelf', '-W', '-h', '-l', '-d', str(binary)],
                           stdout=log, stderr=subprocess.STDOUT, timeout=30, check=True)
    report['packaged'] = True
    import sys
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(DATA / 'inline-signal-rtqueue/tests/kernel/control'))
    from run_g1c_guest import inspect_probe_elf
    report['original_shape'] = {}
    report['original_shape_passed'] = False
    save()
    for name in products:
        report['original_shape'][name] = inspect_probe_elf((packaged / name).read_bytes())
        save()
    report['original_shape_passed'] = True
finally:
    after = snapshot()
    (OUT / 'source-after.json').write_text(json.dumps(after, indent=2) + '\n')
    assert after == before
    report['source_inputs_unchanged'] = True
    report['elapsed_seconds'] = round(time.monotonic() - start, 3)
    save()
