"""Independent read-only verification of existing keyring port evidence."""

from pathlib import Path
import datetime
import hashlib
import json
import re


ROOT = Path('/workspace/scratch/95988d8d3ab1/ndu-keyring-zbus6-candidate')
OUT = Path(__file__).resolve().parent / 'evidence/PEER_KEYRING_PORT.json'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


rows = json.loads((ROOT / 'UPSTREAM_SOURCE_FILES.json').read_text())
for row in rows:
    for directory, field in [('upstream', 'original_sha256'), ('vendor', 'ported_sha256')]:
        assert sha(ROOT / directory / row['package'] / row['path']) == row[field], row
keyring_rust = [row for row in rows if row['package'] == 'keyring-3.6.3' and row['path'].endswith('.rs')]
assert len(keyring_rust) == 15
assert all(not row['modified'] for row in keyring_rust)

reviewed_runs = []
all_binaries = {}
for name in ['real-dbus-007', 'real-dbus-tokio-001', 'actual-consumer-001']:
    directory = ROOT / 'evidence' / name
    result = json.loads((directory / 'RESULT.json').read_text())
    assert result['passed']
    assert result['activation_service_directories'] == []
    assert result['HOME_modified'] is False
    assert result['isolated_bus_address'] == 'unix:path=' + result['fixture_root'] + '/bus'
    config = (directory / 'fixture-files/session.conf').read_text()
    assert result['isolated_bus_address'] in config
    assert '<servicedir>' not in config and '<standard_session_servicedirs' not in config
    assert (directory / 'fixture-files/ISOLATED_FIXTURE').is_file()
    daemon = ROOT / 'fixture-packages/root/usr/bin/gnome-keyring-daemon'
    assert sha(daemon) == result['daemon_binary_sha256']
    logs = []
    for command in result['commands']:
        log = directory / (command['label'] + '.log')
        assert sha(log) == command['log_sha256']
        assert command['exit_code'] == 0
        argv = command['command']
        native = argv[0] == 'unshare'
        binary = Path(argv[3] if native else argv[0])
        assert binary.parent == ROOT / 'binaries'
        assert re.fullmatch('[0-9a-f]{64}', binary.name)
        assert sha(binary) == binary.name
        all_binaries[str(binary)] = {'bytes': binary.stat().st_size, 'sha256': binary.name}
        if native:
            assert argv[:3] == ['unshare', '--user', '--map-root-user']
            match = re.search(r'ISOLATION parent=(user:\[\d+\]) child=(user:\[\d+\]) new_session=(\d+)', log.read_text())
            assert match and match[1] != match[2] and int(match[3]) > 0
        logs.append({'label': command['label'], 'sha256': sha(log), 'bytes': log.stat().st_size})
    reviewed_runs.append({'name': name, 'receipt_sha256': sha(directory / 'RESULT.json'), 'commands': len(logs), 'verified_logs': logs})

registry = Path('/workspace/scratch/95988d8d3ab1/ndu-dependency-remediation/yaml-migration/cargo-home/registry/src')
runtime = next(registry.glob('*/zbus-6.1.0/src/utils.rs'))
runtime_text = runtime.read_text()
assert 'static TOKIO_RT: OnceLock<tokio::runtime::Runtime>' in runtime_text
assert 'crate::runtime::zruntime::block_on(future)' in runtime_text
source_bindings = {}
for name in ['run_fixture.py', 'run_cargo.py', 'harness/Cargo.toml', 'harness/src/main.rs', 'harness/src/native_fixture.rs', 'harness/src/prompt_fixture.rs']:
    source_bindings[name] = sha(ROOT / name)
for name in ['src/blocking/mod.rs', 'src/blocking/collection.rs', 'src/blocking/item.rs', 'src/session.rs', 'src/util.rs', 'src/error.rs']:
    source_bindings['vendor/secret-service-4.0.0/' + name] = sha(ROOT / 'vendor/secret-service-4.0.0' / name)

OUT.write_text(json.dumps({
    'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'reviewer': '/root/native_continuation',
    'mode': 'Read-only independent source and existing execution evidence review; no new model, test, daemon, keyring or credential operations.',
    'passed_with_scope_limits': True,
    'upstream_inventory_entries_rehashed': len(rows),
    'keyring_original_rust_files_unchanged': len(keyring_rust),
    'reviewed_runs': reviewed_runs,
    'actual_executable_bytes_reopened_and_hashed': all_binaries,
    'source_bindings': source_bindings,
    'official_zbus_6_1_runtime_source': {'path': str(runtime), 'sha256': sha(runtime)},
    'review_findings': [
        'The secret-service blocking facade retains its connection, session, and borrowed proxy lifetimes; each call drives the same async methods through zbus::block_on. It does not create and immediately destroy a Tokio runtime per call.',
        'Official zbus 6.1 default-rt transfers live connection work to a helper between block_on calls; the tokio build holds a process-lifetime OnceLock runtime. Both supported runtime feature configurations have actual lifecycle evidence, including eight parallel Entry users and moving a blocking connection to another thread.',
        'The existing prohibition on invoking the blocking facade inside an async task remains necessary; nested async-runtime calls are not qualified by these fixtures.',
        'Plain and DH secret payloads, binary and Unicode values, attributes, content type, ambiguity, legacy no-target discovery, and sync/async interoperability are exercised against an actual isolated GNOME Secret Service. The lifecycle fixture compares payloads and attributes with the independent libdbus backend.',
        'The prompt fixture uses a controlled D-Bus service, with subscription before invocation and explicit completed/dismissed branches. Error::Zvariant now carries zbus::Error because zbus 6 merged the serialization types; conversion failures remain explicitly mapped to that variant. Source and missing-service evidence retain error causes.',
        'The runner owns a fresh session bus with no activation service directories and XDG data/config/runtime paths under its synthetic fixture. It freezes executable bytes by SHA before execution, terminates only its child daemons, saves fixture state, and removes only that fixture.',
        'Native composite operations verify a different user namespace and a newly created anonymous kernel session keyring before any cache operation; absent-service rollback, prior-value restoration, dual writes, cache refill, and ambiguity preservation are exercised.',
        'actual-consumer-001 executes the real codex-keyring-store library API for Option load, serialized payload persistence, and true/false delete results; this remains an isolated consumer harness rather than the entire first-party workspace CI.',
    ],
    'limits': [
        'The optional kernel persistent register is unavailable on this kernel (EOPNOTSUPP). Passing native tests cover the session cache plus Secret Service persistence, not successful use of that optional register.',
        'The old real-dbus-006 receipt is excluded: it used a mutable target/debug path and was invalidated by the author. Only content-addressed binaries from 007 onward are considered here.',
        'Source inputs for the later tokio/consumer builds are captured before execution; the earlier build-007 receipt has only command/log metadata. This review independently binds the current matching source inventory and saved executables, not a reproducible-build proof for that earlier binary.',
        'Full first-party Cargo/Bazel lock generation, macOS and Windows behavior, and production integration remain independent gates. No advisory ignore or production approval follows from this peer review.',
    ],
}, indent=2, ensure_ascii=False) + '\n')
print(json.dumps({'receipt': str(OUT), 'sha256': sha(OUT), 'verified_commands': sum(x['commands'] for x in reviewed_runs), 'verified_binaries': len(all_binaries)}, indent=2))
