"""Stream all registered training receipts through the separate CPU auditor.

This harness reads training records only. It runs no fits, tests, or confirmation.
The controller owns an external wait4 receipt for all worker CPU, including imports.
"""
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

sys.dont_write_bytecode = True
STUDY = Path(__file__).resolve().parents[1]
REPO = STUDY.parents[2]
EVIDENCE = STUDY / 'evidence'
REPORT = EVIDENCE / 'TRAINING_RECORDS_AUDIT.json'
EXPECTED_AUDITOR_SHA = 'd30a2ebfe8743ccfefbd839d68e46e82a6682aa3b8bc3f61541c934eb559915e'
EXPECTED_PROTOCOL_SHA = '1ef05b04457d12106ceed68000212e4c0d44720658fffed03a1fc0dd461a533c'
EXPECTED_MANIFEST_SHA = '97eda99bb3c097f4fa49c06d8b2b6a60d3b999e5bca2456d47964fb1aa75e175'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_new(path, value):
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    with path.open('xb') as stream:
        stream.write(raw)
    return dict(sha256=sha(raw), bytes=len(raw))


def worker():
    started_cpu, started_wall = time.process_time(), time.perf_counter()
    inputs = {
        'manifest': STUDY / 'MODEL_MANIFEST.json',
        'protocol': STUDY / 'protocol.json',
        'auditor': STUDY / 'audit' / 'independent.py',
        'harness': Path(__file__).resolve(),
    }
    input_bytes = {name: path.read_bytes() for name, path in inputs.items()}
    input_hashes = {name: sha(raw) for name, raw in input_bytes.items()}
    snapshots = EVIDENCE / 'TRAINING_RECORDS_AUDIT_INPUTS'
    snapshots.mkdir(exist_ok=False)
    for name, raw in input_bytes.items():
        suffix = '.py' if name in ('auditor', 'harness') else '.json'
        with (snapshots / (name + suffix)).open('xb') as stream:
            stream.write(raw)
    protocol = json.loads(input_bytes['protocol'])
    manifest = json.loads(input_bytes['manifest'])
    log = (EVIDENCE / 'TRAINING_RECORDS_AUDIT.stdout.jsonl').open('x')

    def emit(value):
        line = json.dumps(value, sort_keys=True, allow_nan=False)
        log.write(line + '\n')
        log.flush()
        print(line, flush=True)

    receipt_hashes = {}
    result, error, review = None, None, None
    try:
        if input_hashes['auditor'] != EXPECTED_AUDITOR_SHA:
            raise RuntimeError('Independent auditor bytes changed before the registered audit')
        if input_hashes['protocol'] != EXPECTED_PROTOCOL_SHA or input_hashes['manifest'] != EXPECTED_MANIFEST_SHA:
            raise RuntimeError('Frozen protocol or pre-seal manifest bytes changed before the registered audit')
        from tools.hcsn.digital_feedback_20261101.audit.independent import ARMS, Review, cpu_checks
        review = Review()
        review.equal('input_manifest/protocol', manifest['protocol'], protocol)
        review.equal('input_manifest/fits', manifest['fits'], protocol['fits'])
        review.equal('input_manifest/registered_candidates', manifest['cpu_matching']['registered_candidates'], list(ARMS[:-1]))
        review.equal('registered_receipt_count', len(protocol['fits']) * len(ARMS[:-1]), 480)
        emit(dict(event='STARTED', input_sha256=input_hashes,
                  expected_receipts=len(protocol['fits']) * len(ARMS[:-1])))

        def rows():
            for fit in protocol['fits']:
                for candidate in ARMS[:-1]:
                    relative = f'training/{candidate}.json.gz'
                    path = STUDY / 'training_002' / f'fit_{fit}' / relative
                    raw = path.read_bytes()
                    identity = str(path.relative_to(STUDY))
                    digest = sha(raw)
                    receipt_hashes[identity] = dict(sha256=digest, bytes=len(raw))
                    review.equal('custody/' + identity, digest,
                                 manifest['training_files_sha256'][str(fit)][relative])
                    receipt = json.loads(gzip.decompress(raw))
                    review.equal('receipt_identity/' + identity, (receipt.get('fit'), receipt.get('spec', {}).get('id')),
                                 (fit, candidate))
                    previous_violations = review.violations_count
                    yield receipt
                    if review.violations_count > previous_violations:
                        emit(dict(event='VIOLATION', fit=fit, candidate=candidate, review=review.report()))
                emit(dict(event='FIT_READ', fit=fit, receipt_count=len(receipt_hashes), violations=review.violations_count))

        result = cpu_checks(review, rows(), protocol, manifest)
        for name, path in inputs.items():
            review.equal('input_unchanged_after_audit/' + name, sha(path.read_bytes()), input_hashes[name])
    except BaseException as caught:
        error = dict(kind=type(caught).__name__, message=str(caught), traceback=traceback.format_exc())
        if review is not None:
            review.fail('audit_execution', 'audit harness did not complete', repr(caught))
        emit(dict(event='ERROR', error=error))
    report = review.report() if review is not None else dict(passed=False, violations=[error])
    passed = bool(error is None and report['passed'] and result is not None
                  and result['all_actual_cpu_matching'] and result['all_training_valid'])
    artifact = dict(schema='digital-feedback-training-records-independent-audit-v1',
        created_utc=datetime.now(timezone.utc).isoformat(), passed=passed, review=report,
        cpu_checks=result, error=error, input_sha256=input_hashes,
        input_paths={name:str(path.relative_to(REPO)) for name,path in inputs.items()},
        input_snapshots=str(snapshots.relative_to(REPO)), training_receipts_sha256=receipt_hashes,
        streamed_receipts=len(receipt_hashes), confirmation_read_or_generated=False,
        worker_interval_cpu_seconds=time.process_time()-started_cpu,
        worker_interval_wall_seconds=time.perf_counter()-started_wall,
        scope='Separate computation using audit.independent.cpu_checks and Review over all actual registered training receipts and the pre-seal manifest; no third-party authorship or independent data claim; no confirmation, tests, or fitting.')
    output_identity = write_new(REPORT, artifact)
    emit(dict(event='FINISHED', passed=passed, review=report, streamed_receipts=len(receipt_hashes), report=output_identity))
    log.close()
    return 0 if passed else 1


def controller():
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    stderr_path = EVIDENCE / 'TRAINING_RECORDS_AUDIT.stderr'
    with stderr_path.open('xb') as error:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--worker'],
            cwd=REPO, stderr=error, env=dict(os.environ, OMP_NUM_THREADS='1',
                OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', PYTHONDONTWRITEBYTECODE='1'))
        _, status, usage = os.wait4(child.pid, 0)
        child.returncode = os.waitstatus_to_exitcode(status)
    result = dict(schema='digital-feedback-training-records-audit-process-v1',
        returncode=child.returncode, worker_cpu_seconds=usage.ru_utime+usage.ru_stime,
        worker_user_cpu_seconds=usage.ru_utime, worker_system_cpu_seconds=usage.ru_stime,
        worker_peak_rss_kib=usage.ru_maxrss, controller_cpu_seconds=time.process_time()-start_cpu,
        elapsed_wall_seconds=time.perf_counter()-start_wall,
        report_sha256=sha(REPORT.read_bytes()) if REPORT.exists() else None,
        scope='External wait4 worker user+system CPU includes imports and report persistence. Controller CPU is disjoint; report in-process interval is nested and must not be added again.')
    write_new(EVIDENCE / 'TRAINING_RECORDS_AUDIT_PROCESS.json', result)
    print(json.dumps(dict(event='PROCESS_RECEIPT', **result), sort_keys=True), flush=True)
    return child.returncode


if __name__ == '__main__':
    raise SystemExit(worker() if len(sys.argv) > 1 and sys.argv[1] == '--worker' else controller())
