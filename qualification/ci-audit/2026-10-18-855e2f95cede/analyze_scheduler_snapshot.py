#!/usr/bin/env python3
"""Reproduce queue classifications; this script never cancels or dispatches runs."""
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
SOURCE = Path('/workspace/scratch/28fd839d6e0d/hepta-private-ci')
MAIN = 'f8c9419df6ddeb36ff8b522a50219981fb8d9345'


def git(*args):
    return subprocess.check_output(['git', '-C', str(SOURCE), *args], text=True).strip()


def main():
    runs = json.loads((ROOT / 'active_runs_snapshot.json').read_text())
    jobs = json.loads(gzip.decompress((ROOT / 'active_jobs_snapshot.json.gz').read_bytes()))
    branches = json.loads((ROOT / 'github_inventory/branch_inventory_enriched.json').read_text())
    heads = {r['name']: r['head_sha'] for r in branches['branches']}
    job_records = {r['run_id']: r for r in jobs['records']}
    result = {
        'schema_version': 1,
        'runs_observed_utc': runs['observed_utc'],
        'jobs_interval': [jobs['started_utc'], jobs['completed_utc']],
        'main': MAIN,
        'scope': 'Non-atomic recorded run and branch snapshots, not current runner capacity.',
        'run_status_counts': dict(Counter(r['status'] for r in runs['runs'])),
        'workflow_concurrency_source': [],
        'zero_job_runs': [],
        'duplicate_workflow_branch_groups': [],
        'mutations': [],
    }
    for path in sorted((SOURCE / '.github/workflows').glob('*.yml')):
        text = path.read_text()
        lines = text.splitlines()
        block = []
        for i, line in enumerate(lines):
            if line != 'concurrency:':
                continue
            block.append(line)
            for following in lines[i + 1:]:
                if following and not following[0].isspace() and not following.startswith('#'):
                    break
                block.append(following)
            break
        if not block:
            continue
        rel = path.relative_to(SOURCE).as_posix()
        expected = git('rev-parse', MAIN + ':' + rel)
        raw = path.read_bytes()
        observed = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        assert expected == observed, rel
        result['workflow_concurrency_source'].append({
            'path': rel, 'blob_sha': observed, 'source_sha': MAIN,
            'concurrency_literal': '\n'.join(block).strip(),
        })
    groups = defaultdict(list)
    for run in runs['runs']:
        record = job_records[run['id']]
        assert record['status'] == 'COMPLETE_PAGES'
        assert len(record['jobs']) == record['expected_total']
        head = heads.get(run['head_branch'])
        row = {key: run.get(key) for key in ('id', 'name', 'path', 'status', 'head_sha', 'head_branch', 'created_at', 'html_url')}
        row.update({
            'job_count': len(record['jobs']),
            'branch_snapshot_sha': head,
            'source_relation': 'UNKNOWN_BRANCH' if head is None else ('CURRENT_AT_BRANCH_SNAPSHOT' if head == run['head_sha'] else 'DIFFERENT_FROM_BRANCH_SNAPSHOT'),
        })
        if not record['jobs']:
            result['zero_job_runs'].append(row)
        groups[(run['path'], run['head_branch'])].append(row)
    result['zero_job_run_count'] = len(result['zero_job_runs'])
    result['zero_job_source_relation_counts'] = dict(Counter(r['source_relation'] for r in result['zero_job_runs']))
    result['duplicate_workflow_branch_groups'] = [
        {'workflow_path': key[0], 'head_branch': key[1], 'runs': values}
        for key, values in sorted(groups.items()) if len(values) > 1
    ]
    result['interpretation'] = [
        'A zero-job queued run has no observed runner assignment; it is not counted as a queued or executing job.',
        'A different branch SHA is a review candidate, not proof that cancellation is safe; dependent branch owners and current head must be checked first.',
        'Workflow concurrency literals do not disclose organization concurrency ceilings or runner utilization.',
        'No cancellation, label change, coverage change, or gate change was performed.',
    ]
    out = ROOT / 'SCHEDULER_SOURCE_AUDIT.json'
    out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({
        'output': str(out), 'sha256': hashlib.sha256(out.read_bytes()).hexdigest(),
        'source_workflows': len(result['workflow_concurrency_source']),
        'run_status_counts': result['run_status_counts'],
        'zero_job_runs': result['zero_job_run_count'],
        'zero_job_source_relation_counts': result['zero_job_source_relation_counts'],
        'duplicate_workflow_branch_groups': len(result['duplicate_workflow_branch_groups']),
    }))


if __name__ == '__main__':
    main()
