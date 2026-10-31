"""Exact local CLI invocation and full child-process cost receipt; no upload."""

import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import time
import traceback


WORKSPACE = Path('/workspace/scratch/2b3c256bef7d')
REPOSITORY = WORKSPACE / 'hepta-ndu-recovery'
SOURCE = REPOSITORY / 'experiments/multimodal_output_portfolio/abc_recovery/evidence_inventory.py'
EXPECTED_SOURCE_SHA256 = '0d39bffcc7398a3ba039974b408163c244103ad161b97e3107b00eb41062182c'
OUTPUT = WORKSPACE / 'evidence-inventory-001.json'
RECEIPT = WORKSPACE / 'evidence-inventory-001-receipt.json'
COMMAND = [str(WORKSPACE / 'ndu-env/bin/python'), '-B', '-m',
           'experiments.multimodal_output_portfolio.abc_recovery.evidence_inventory', '--output', str(OUTPUT)]


def main():
    result = {'schema': 'hepta.abc.local-evidence-inventory-process.v1', 'argv': COMMAND,
              'cwd': str(REPOSITORY), 'started_unix_ns': time.time_ns(), 'status': 'failed',
              'raw_evidence_copied_archived_or_uploaded': False}
    with RECEIPT.open('x', encoding='utf-8') as receipt:
        try:
            result['source_sha256'] = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
            result['invocation_source_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            if result['source_sha256'] != EXPECTED_SOURCE_SHA256:
                raise ValueError('Reviewed inventory implementation changed; scan was not started')
            before, usage_before = time.monotonic_ns(), resource.getrusage(resource.RUSAGE_CHILDREN)
            process = subprocess.run(COMMAND, cwd=REPOSITORY, capture_output=True, text=True, check=False)
            elapsed = time.monotonic_ns() - before
            usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
            result.update(returncode=process.returncode, stdout=process.stdout, stderr=process.stderr,
                          complete_child_process_wall_ns=elapsed,
                          complete_child_process_cpu_seconds=usage_after.ru_utime + usage_after.ru_stime
                          - usage_before.ru_utime - usage_before.ru_stime,
                          child_peak_rss_bytes=usage_after.ru_maxrss * 1024)
            if process.returncode:
                raise RuntimeError('Inventory refused or failed; no condition was ignored')
            cli = json.loads(process.stdout)
            manifest_bytes = OUTPUT.read_bytes()
            result['manifest_sha256'] = hashlib.sha256(manifest_bytes).hexdigest()
            if result['manifest_sha256'] != cli['sha256']:
                raise ValueError('Published manifest differs from the CLI receipt')
            manifest = json.loads(manifest_bytes)
            if manifest['status'] != 'complete' or cli['status'] != 'complete':
                raise ValueError('Complete inventory was not published')
            result.update(status='complete', cli_receipt=cli, scan_cost=manifest['scan_cost'],
                          file_count=manifest['file_count'], total_bytes=manifest['total_bytes'],
                          by_root=manifest['by_root'], by_run=manifest['by_run'])
        except Exception as error:
            result.update(error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
        json.dump(result, receipt, indent=2, sort_keys=True)
        receipt.write('\n')
        receipt.flush()
        os.fsync(receipt.fileno())
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0 if result['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
