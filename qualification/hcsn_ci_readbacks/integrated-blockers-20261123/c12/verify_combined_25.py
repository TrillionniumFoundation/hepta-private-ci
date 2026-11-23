"""Replay the original strict, source-guard, bootstrap and paired Artifact Head evidence.

From this directory with Python 3.10 or later:
    python3 verify_combined_25.py > /tmp/combined-25-independent.json
    cmp /tmp/combined-25-independent.json combined-25-independent.json

The input ZIP contains the unmodified archive bytes from seven GitHub artifacts.
combined-25-strict.zip is the unmodified eighth artifact. No network is required.
"""
from collections import Counter
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
import json
import re

HERE = Path(__file__).resolve().parent
C12 = 'c12ee03f3185d5a13949faca54f066dfd634e509'
BOOTSTRAP_SOURCE = '11e1660799a97fe3a52def730d36f98cb070f8ad'
INTEGRATED = '3b1387335f57a67ae9f5878064feb26a1601d715'
PUBLISHER = {
    "11e-native": {
        "artifact": 14807639771,
        "bytes": 12324,
        "run": 45154413605,
        "sha256": "7dccad9d6dd713b1671d0a0c91663e981cfd7083c055ab0754e2ca9e53ec52ca"
    },
    "11e-source": {
        "artifact": 14809821869,
        "bytes": 64581,
        "run": 45154413605,
        "sha256": "c625518c538b848d4f0d72233797c3d0e81c9dd520eb416178d9f87c8fbd9ff8"
    },
    "11e-strict": {
        "artifact": 14808930207,
        "bytes": 29494,
        "run": 45154413605,
        "sha256": "68b42c9aef406361ef6f71c3d5592b1668be50a31508634382e4d79c991670c3"
    },
    "c12-strict": {
        "artifact": 14808498546,
        "bytes": 47790,
        "run": 45155293939,
        "sha256": "b3edd0eee2d9f3a407d58c526baad2f6a7a995fc8d5f9c458ead991a62279f41"
    },
    "first-wire": {
        "artifact": 14809961397,
        "bytes": 13974,
        "run": 45156905998,
        "sha256": "c8834da07c83d00243f8a2d115d6cdfb26eca8ce8d18c79d48190f18c5770482"
    },
    "integrated-source": {
        "artifact": 14810985622,
        "bytes": 67903,
        "run": 45157522735,
        "sha256": "677aced60a304e561b92b50eda4a29573a8637b941de00a38ad1e381afef9b1b"
    },
    "integrated-strict": {
        "artifact": 14809048803,
        "bytes": 29170,
        "run": 45157522735,
        "sha256": "da9a032221b447d1bf8907ee6858ff22a05832912bc7f5c998b403ffc9886521"
    },
    "paired-wire": {
        "artifact": 14809569222,
        "bytes": 20558,
        "run": 45158841882,
        "sha256": "6296d5511fff32848b96fdc5c458f38584426b0fce0d9a1fed02c69f1872fe84"
    }
}

OLD_OBSERVER = {
    'authority_host_generation_publication_root_fixture_tests.rs': '51c4efe5cd395b58cb8bf7d3992f5ef30cc286bfb684520cf7d67d1a5b962822',
    'authority_host_publication_deployment_tests.rs': '59b5d27020357cdcc470a90c416873b938190695b032c36245672f3edc6f540c',
    'authority_host_successor_deployment_files_tests.rs': '25059b256e4caa4cc0fe810cf6f324127b260319ef968459a390780119871284',
}
ORDINARY = {'versioned_record_rejects_hybrid_unknown_fields_and_invalid_live_binding',
            'successor_deployment_requires_every_original_pin_and_bounded_context'}
ROOT_CASE = 'root_broker_late_enrolls_publishes_and_recovers_original_current'
WIRE = 'QUALIFIED_WIRE_OBJECT v1-positive=1 v2-positive=1 encoder-negative=2 decoder-negative=16 reencode-bytes=2'

SEALS = {
    'base': ('11e1660799a97fe3a52def730d36f98cb070f8ad', '1e6cad7a4dbc6f559169471b56d0634a64acb77e'),
    'candidate': ('0652ab8f32a36da9c13cdf18ee3d22eb44863d92', '932c51b759f06809df648bab0ae730feb3bb21a0'),
}
FIXTURE = 'c5427b44c054e6276a9d053bedd8f9870b209e79'
SUPPORT = 'a322d61efc03b105fc14ccbc5f55b545ad3b879d'
DRIVER = '578044e1ccfb12569765207b6e8c955d20d6c330'



def unpack(raw):
    with ZipFile(BytesIO(raw)) as archive:
        assert len(archive.namelist()) == len(set(archive.namelist()))
        assert archive.testzip() is None
        return {key: archive.read(key) for key in archive.namelist()}


def archives():
    raw = {k.removesuffix('.zip'): v for k,v in unpack((HERE / 'combined-25-inputs.zip').read_bytes()).items()}
    raw['integrated-strict'] = (HERE / 'combined-25-strict.zip').read_bytes()
    assert raw.keys() == PUBLISHER.keys()
    for name, data in raw.items():
        assert sha256(data).hexdigest() == PUBLISHER[name]['sha256'] and len(data) == PUBLISHER[name]['bytes']
    return {k: unpack(v) for k,v in raw.items()}

def diagnose(raw):
    raw = raw.decode()
    rows = Counter()
    sections = re.split(r'^error(?:\[(E\d+)\])?: ', raw, flags=re.M)
    for code, block in zip(sections[1::2], sections[2::2], strict=True):
        message = block.splitlines()[0]
        if message.startswith('could not compile'):
            continue
        location = re.search(r'^\s*--> ([^:\n]+):(\d+):(\d+)\s*$', block, re.M)
        assert location, (code, message)
        path, line, col = location.groups()
        rows[(path.removeprefix('codex-rs/'), int(line), int(col), code or '', message)] += 1
    summary = re.findall(r'^error: could not compile .+$', raw, re.M)
    return rows, summary


def compare(now, earlier):
    return dict(earlier_count=earlier.total(), added=sorted((now-earlier).elements()),
                removed=sorted((earlier-now).elements()))

def check_source(files, subject, suite_count):
    assert files['commit.txt'].decode().strip() == subject
    callers = json.loads(files['callers.json'])
    assert callers['status'] == 'PASS_HEPTA_CALLER_CLOSED_SET' and callers['authorityGranted'] is False
    guards = {}
    for name, data in files.items():
        if name.endswith('.log'):
            count, = re.findall(rb'^Ran (\d+) tests? in ', data, re.M)
            assert data.rstrip().endswith(b'OK') and int(count) > 0
            guards[name] = int(count)
    assert len(guards) == suite_count
    return dict(guard_tests=guards, guard_total=sum(guards.values()), rust_files=callers['rustFilesScanned'],
                boundaries=len(callers['boundaries']), protected=len(callers['protectedFiles']),
                callers_sha256=sha256(files['callers.json']).hexdigest())


def check_native(files):
    assert files['source.txt'].decode().strip() == BOOTSTRAP_SOURCE and b'Build completed successfully' in files['build.log']
    assert '054075188a68c0b6673c5779108be6556358d6c6' in files['originals.txt'].decode()
    assert dict(line.split()[::-1] for line in files['observer-hashes.txt'].decode().splitlines()) == OLD_OBSERVER
    native = json.loads(files['native-candidate.json'])
    for kind, names in [('ordinary', ORDINARY), ('uid0', {ROOT_CASE})]:
        raw = files['candidate-' + kind + '.log']
        summary = native[kind]
        assert summary['exit'] == 0 and summary['pass'] and summary['log_sha256'] == sha256(raw).hexdigest()
        result = re.findall(r'^test (\S+) \.\.\. (ok|FAILED|ignored)$', raw.decode(), re.M)
        assert len(result) == len(names) and {n.split('::')[-1] for n, s in result if s == 'ok'} == names
    rootlog = files['candidate-uid0.log'].decode()
    assert re.search('^actual UID0$', rootlog, re.M) and rootlog.count(WIRE) == 10
    pattern = r'^.*ROOT_PUBLICATION_ORIGINAL lifecycle=passed terminal=(StalePrepare|Revoked) actual_consumer_uid=(\d+) actual_consumer_pid=(\d+) original_root_pid=(\d+) '
    children = re.findall(pattern, rootlog, re.M)
    assert len(children) == 2 and {r[0] for r in children} == {'StalePrepare', 'Revoked'}
    assert all(int(uid) > 0 and subpid != rootpid for _, uid, subpid, rootpid in children)
    phases = re.findall(r'^ROOT_PUBLICATION_COMPONENT phase=(\S+) service=(.*)$', rootlog, re.M)
    assert len(phases) == 10
    return dict(elf=native['ELF_SHA256'], root_children=children, phases=phases,
                observer_sha256=OLD_OBSERVER, observations=rootlog.count(WIRE), native=native)



def check_paired_wire(files):
    assert files['driver.txt'].decode().strip() == DRIVER
    recorded = json.loads(files['results.json'])
    table = {}
    for arm, (source, production) in SEALS.items():
        assert files[arm + '-source.txt'].decode().strip() == source == recorded[arm]['source']
        originals = files[arm + '-original-blobs.txt'].decode().splitlines()
        blobs = {ln.split()[-1].split('/')[-1]: ln.split()[2] for ln in originals}
        assert blobs == {'artifact_original_head_wire.rs': production,
                         'artifact_original_head_tests.rs': FIXTURE,
                         'artifact_original_head_support_tests.rs': SUPPORT}
        guard = files[arm + '-source-guard.log']
        assert b'Ran 9 tests' in guard and guard.rstrip().endswith(b'OK')
        assert b'Build completed successfully' in files[arm + '-build.log']
        elf = files[arm + '-elf.txt'].decode().split()[0]
        assert recorded[arm]['elf'] == elf and re.fullmatch('[0-9a-f]{64}', elf)
        stages = {}
        for label, key, count in [('original','original',3), ('wire','wire',2),
                                  ('cross','cross_read_from_' + ('base' if arm == 'candidate' else 'candidate'),1)]:
            data = files[f'{arm}-{label}.log']
            assert recorded[arm][key]['log_sha256'] == sha256(data).hexdigest()
            matched = re.findall(rb'^test (\S+) \.\.\. (ok|FAILED|ignored)$', data, re.M)
            assert len(matched) == count and all(row[1] == b'ok' for row in matched)
            assert [(n.decode(), s.decode()) for n,s in matched] == [tuple(r) for r in recorded[arm][key]['cases']]
            stages[label] = [n.decode() for n,_ in matched]
        frames = {}
        for i in range(1,6):
            payload = b'original head wire comparison\x00\xff' if i == 1 else b''
            frame = b'HARPC001' + bytes([2,1]) + (7).to_bytes(8,'big') + bytes([0x37])*32
            frame += bytes([i]) + len(payload).to_bytes(4, 'big') + payload
            got = files[f'{arm}-frames/{i}.bin']
            assert got == frame
            frames[str(i)] = sha256(got).hexdigest()
            assert recorded[arm]['frames'][str(i)+'.bin'] == frames[str(i)]
        table[arm] = dict(source=source, product_blob=production, elf=elf, cases=stages,
                          original_guard_tests=9, frames=frames)
    assert table['base']['elf'] != table['candidate']['elf']
    assert table['base']['frames'] == table['candidate']['frames']
    assert files['base-observer.txt'] == files['candidate-observer.txt']
    return dict(driver=DRIVER, original_archive_sha256=PUBLISHER['paired-wire']['sha256'], arms=table,
                tag_length_partition_per_elf=512, maximum_wire_bytes=16384, fixture_test_only=True)

def check_first_attempt(files, paired):
    assert files['driver.txt'].decode().strip() == 'b0122305c6c4213d59ecd04bf8a74977b5ecd200'
    assert files['base-source.txt'].decode().strip() == BOOTSTRAP_SOURCE
    assert files['candidate-source.txt'].decode().strip() == SEALS['candidate'][0]
    assert b'Build completed successfully' in files['base-build.log']
    assert files['base-elf.txt'].decode().split()[0] == paired['arms']['base']['elf']
    assert 'candidate-elf.txt' not in files
    assert b'workspace_directory=' in files['candidate-build.log']
    assert b'is not a declared prerequisite of this rule' in files['candidate-build.log']
    assert b'Build did NOT complete successfully' in files['candidate-build.log']
    assert files['base-observer.txt'] == files['candidate-observer.txt']
    assert all(b'Ran 9 tests' in files[arm+'-source-guard.log'] and
               files[arm+'-source-guard.log'].rstrip().endswith(b'OK') for arm in SEALS)
    assert all(not any(k.endswith(suffix) for suffix in ('-cross.log','-original.log','-wire.log'))
               for k in files)
    return dict(driver=files['driver.txt'].decode().strip(), base_elf=paired['arms']['base']['elf'],
                candidate_elf=False, execution_comparison_cases=0, source_guards_each=9,
                failure='Candidate build stopped at Bazel dependency analysis after workspace_directory changed.')


def evaluate():
    files = archives()
    old, direct, product = [files[k] for k in ('c12-strict', '11e-strict', 'integrated-strict')]
    assert old['identity-base.txt'].decode().strip() == C12
    assert direct['commit.txt'].decode().strip() == BOOTSTRAP_SOURCE
    assert product['commit.txt'].decode().strip() == INTEGRATED
    c12, _ = diagnose(old['strict-base.log'])
    parent, _ = diagnose(direct['strict.log'])
    active, summary = diagnose(product['strict.log'])
    paired = check_paired_wire(files['paired-wire'])
    result = dict(
        publisher_artifacts=PUBLISHER,
        integrated_source=INTEGRATED, compiler=product['rustc.txt'].decode().strip(),
        clippy=product['clippy.txt'].decode().strip(),
        strict_exit_codes=dict(c12=int(old['strict-base.exit']), bootstrap=int(direct['strict.exit']),
                               integrated=int(product['strict.exit'])),
        strict_total=active.total(), compiler_summary=summary,
        by_message=dict(sorted(Counter(d[-1] for d in active.elements()).items())),
        vs_c12=compare(active,c12), vs_bootstrap=compare(active,parent), diagnostics=sorted(active.elements()),
        bootstrap_source=BOOTSTRAP_SOURCE, bootstrap_wire=check_native(files['11e-native']),
        bootstrap_guards=check_source(files['11e-source'], BOOTSTRAP_SOURCE, 6),
        integrated_guards=check_source(files['integrated-source'], INTEGRATED, 11),
        paired_wire=paired, first_wire_attempt=check_first_attempt(files['first-wire'],paired))
    assert result['bootstrap_guards']['callers_sha256'] == result['integrated_guards']['callers_sha256']
    assert result['bootstrap_guards']['guard_total'] == 44 and result['integrated_guards']['guard_total'] == 96
    assert c12.total() == 115 and parent.total() == 114 and active.total() == 111
    assert set(result['strict_exit_codes'].values()) == {101}
    return result


if __name__ == '__main__':
    print(json.dumps(evaluate(), sort_keys=True, indent=2))
