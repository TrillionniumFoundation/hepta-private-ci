"""Read-only independent curation review. No numerical oracle or training runs."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import re
import stat
import time
from urllib.parse import unquote, urlsplit
from zipfile import ZipFile


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_bytes())


def identity(path):
    raw = Path(path).read_bytes()
    return {'bytes': len(raw), 'sha256': digest(raw)}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def audit_zip(raw, name, records, depth=0):
    require(depth < 8, 'unexpected nested archive depth')
    with ZipFile(BytesIO(raw)) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), 'duplicate ZIP member: '+name)
        for info in archive.infolist():
            path = PurePosixPath(info.filename)
            require(not path.is_absolute() and '..' not in path.parts and '\\' not in info.filename,
                    'unsafe ZIP member: '+name+'/'+info.filename)
            require(not stat.S_ISLNK(info.external_attr >> 16), 'ZIP symlink: '+name)
        require(archive.testzip() is None, 'ZIP CRC failure: '+name)
        records.append({'archive': name, 'bytes': len(raw), 'sha256': digest(raw),
                        'members': len(names), 'crc_duplicate_path_checks_passed': True})
        for name_inside in names:
            if name_inside.endswith('.zip'):
                audit_zip(archive.read(name_inside), name+'!'+name_inside, records, depth+1)


def local_links(path, repository):
    text = re.sub(r'```.*?```', '', path.read_text(), flags=re.S)
    rows = []
    for match in re.finditer(r'\[[^\]]+\]\(([^\s)]+)(?:\s+"[^"]*")?\)', text):
        destination = match.group(1)
        url = urlsplit(destination)
        if url.scheme or url.netloc or not url.path:
            continue
        resolved = (path.parent/unquote(url.path)).resolve()
        require(resolved.is_relative_to(repository), 'relative link escapes repository')
        rows.append({'document': str(path.relative_to(repository)), 'destination': destination,
                     'resolved': str(resolved.relative_to(repository)), 'exists': resolved.exists(),
                     'fragment_not_validated': url.fragment or None})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--expected-manifest-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    began = time.monotonic()
    repo = args.repository.resolve()
    base = repo/'qualification/hcsn_differentiable/evidence/p0p5-20261110'
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    documents = [repo/'qualification/hcsn_differentiable/CURRENT.md',
                 repo/'proposals/localization-v3/README.md', base/'README.md',
                 base/'p1/width16-v6/INDEX.md']
    key_paths = documents + [base/name for name in ['STATUS.json','COSTS.json','assets.json','MANIFEST.json']]
    before = {str(path.relative_to(repo)): identity(path) for path in key_paths}
    require(identity(base/'MANIFEST.json')['sha256'] == args.expected_manifest_sha256,
            'curation manifest changed from requested review snapshot')
    manifest = read_json(base/'MANIFEST.json')
    checked = {}; problems = []
    for name, expected in manifest['files'].items():
        path = (base/name).resolve()
        require(path.is_relative_to(base), 'unsafe manifest path')
        if not path.is_file():
            problems.append({'file': name, 'error': 'missing'}); continue
        actual = identity(path); checked[name] = actual
        if actual != expected:
            problems.append({'file': name, 'expected': expected, 'actual': actual})
    actual_names = {str(p.relative_to(base)) for p in base.rglob('*') if p.is_file()}
    extra = sorted(actual_names - set(manifest['files']) - {'MANIFEST.json'})
    missing = sorted(set(manifest['files']) - actual_names)
    archives = []
    for name in manifest['files']:
        if name.endswith('.zip'):
            audit_zip((base/name).read_bytes(), name, archives)
    links = [row for path in documents for row in local_links(path, repo)]
    costs = read_json(base/'COSTS.json'); status = read_json(base/'STATUS.json')
    assets = read_json(base/'assets.json')
    rowmap = {row['id']: row for row in costs['rows']}
    require(len(rowmap) == len(costs['rows']), 'duplicate cost row identity')
    refs = [{'row': row['id'], 'artifact': row['artifact'],
             'exists': (base/row['artifact']).is_file()} for row in costs['rows']]
    numeric_checks = []

    def exact(row_id, row_key, source, source_key):
        raw = read_json(base/source)
        value = raw
        for component in source_key.split('.'):
            value = value[component]
        actual = rowmap[row_id][row_key]
        require(actual == value, 'cost mismatch: '+row_id+'/'+row_key)
        numeric_checks.append({'row': row_id, 'field': row_key, 'source': source,
                               'source_field': source_key, 'value': value})

    for row_id, source in [('raw36-campaign','p2/raw36-campaign-result.json'),
                           ('adapter-pilot-six','p2/adapter-pilot-result.json')]:
        for left,right in [('children_cpu_seconds','children_cpu_seconds'),
                           ('controller_elapsed_seconds','whole_wall_seconds'),
                           ('sum_attempt_elapsed_seconds','sum_attempt_wall_seconds')]:
            exact(row_id,left,source,right)
    for left,right in [('algorithm_elapsed_seconds','wall_seconds'),
                       ('process_cpu_seconds','cpu_seconds'),('peak_rss_bytes','peak_rss_bytes')]:
        exact('hcsn-width16-micro1',left,'p2/hcsn-micro1-cost.json',right)
    exact('hcsn-width16-micro1','whole_process_elapsed_seconds','p2/hcsn-micro1-process.json','whole_process_wall_seconds')
    for field in ['review_cpu_seconds','review_wall_seconds']:
        exact('independent-plif-analog-replay',field,'review/plif-analog-review-v1.json',field)
    rv = read_json(base/'review/fresh42-reviewer-v2-validation.json')
    require(rv['tests'] == 23 and rv['passed'] and not rv['training_performed']
            and not rv['original_fresh42_roster_audited'] and not rv['production_continuation_audited'],
            'prepared reviewer scope differs from claims')
    require(rowmap['fresh42-reviewer-v2-preparation']['sum_test_child_cpu_seconds'] == sum(r['children_cpu_seconds'] for r in rv['executions']), 'review CPU total mismatch')
    require(rowmap['fresh42-reviewer-v2-preparation']['sum_test_subprocess_wall_seconds'] == sum(r['whole_process_wall_seconds'] for r in rv['executions']), 'review wall total mismatch')
    numeric_checks.append({'row':'fresh42-reviewer-v2-preparation','derived_sums_checked':True})

    raw36 = read_json(base/'p2/raw36-campaign-result.json')
    require(len(raw36['attempts']) == 36 and raw36['training_adequacy_passed_fits'] == 2,
            'raw36 roster/adequacy mismatch')
    require(status['fresh42']['dispatched'] and not status['fresh42']['complete_final_result_observed']
            and not status['fresh42']['independent_final_review_completed']
            and status['fresh42']['current_status'] == 'unknown_due_to_native_control_disconnect',
            'unknown native status lost')
    require(not status['continuation']['production_dispatched'], 'C1 deployment was claimed')
    require(status['gates']['scientific_benefit'] == 'HOLD'
            and status['gates']['full_training_numerical_domain'] == 'HOLD'
            and status['gates']['training_comparison'] == 'HOLD', 'scientific gate promoted')
    require(not costs['accounting_complete'] and all(costs[k] is None for k in
            ['total_elapsed_seconds','total_energy_joules','total_currency_cost','peak_vram_bytes']),
            'unknown cost promoted to zero or a complete sum')
    require(assets['draft'] and not assets['published'] and len(assets['verified_assets']) == 13
            and len(assets['server_metadata_matched_only']) == 2, 'asset scope differs')
    for row in assets['verified_assets']:
        require(row['authenticated_readback_matches'] is True, 'unverified verified-asset row')
        if 'receipt' in row:
            require((base/row['receipt']).is_file(), 'asset receipt missing')
    for row in assets['server_metadata_matched_only']:
        require(row['authenticated_final_byte_readback_receipt'].startswith('unavailable'),
                'metadata-only asset promoted to byte readback')

    hosted_path = base/'publication/hosted-science-42827955616-1.zip'
    hosted_summary = read_json(base/'publication/hosted-science-summary.json')
    with ZipFile(hosted_path) as hosted:
        require(len(hosted.namelist()) == 14, 'hosted artifact roster differs')
        require(digest(hosted_path.read_bytes()) == hosted_summary['archive_sha256'], 'hosted ZIP SHA mismatch')
        ci_identity = json.loads(hosted.read('identity.json'))
        outcome = json.loads(hosted.read('outcome.json'))
        qualification = json.loads(hosted.read('qualification.json'))
        require(ci_identity == read_json(base/'publication/hosted-science-identity.json'), 'hosted identity copy differs')
        require(ci_identity['source_tree'] == ci_identity['tested_tree'] == '0fd8f2f35e190442025005ca17a4662af522a491', 'hosted tested tree differs')
        require(qualification['tests_run'] == 92 and qualification['failures'] == qualification['errors'] == 0
                and qualification['source_before'] == qualification['source_after'], 'hosted qualification claim differs')
        require(outcome['science_status'] == 'PASSED_DECLARED_FIXTURES'
                and all(v == 'success' for v in outcome['steps'].values()), 'hosted steps failed')
        metadata = read_json(base/'publication/hosted-science-42827955616-metadata.json')
        require(metadata['run']['head_sha'] == ci_identity['source_head']
                and metadata['run']['head_commit']['tree_id'] == ci_identity['source_tree'], 'hosted metadata identity mismatch')
    with ZipFile(base/'p2/training-source-v8.zip') as old, ZipFile(base/'p2/continuation-source-c1.zip') as new:
        same = [n for n in old.namelist() if n in new.namelist() and old.read(n) == new.read(n)]
        changed = [n for n in old.namelist() if n in new.namelist() and old.read(n) != new.read(n)]
        added = sorted(set(new.namelist())-set(old.namelist()))
        require(len(same) == 35, 'C1 inherited byte-identical source count differs')
        capsule_comparison = {'identical_inherited_members':same, 'changed_metadata_members':changed, 'new_members':added}
    findings = []
    current = documents[0].read_text()
    if '48.839' in current and not any('48.839' in json.dumps(r) for r in costs['rows']):
        findings.append({'id':'COST-01','severity':'medium','status':'open_at_review_snapshot',
                         'finding':'CURRENT says a prior failed batch32 probe cost48.839 seconds remains charged, but no COSTS row binds that attempt or timer.',
                         'source':'qualification/hcsn_differentiable/CURRENT.md',
                         'recommendation':'Add its exact failure/process receipt and scoped ledger row, or explicitly mark source-bound cost unavailable and avoid claiming it is already charged.'})
    after = {str(path.relative_to(repo)): identity(path) for path in key_paths}
    stable = before == after and all(identity(base/name) == value for name,value in checked.items())
    integrity = not problems and not extra and not missing and all(r['exists'] for r in links+refs) and stable
    report = {'schema':'independent-final-curation-review-v1','created_utc':datetime.now(timezone.utc).isoformat(),
              'reviewed_manifest_sha256':args.expected_manifest_sha256,
              'integrity_passed':integrity,'claims_review_status':'changes_requested' if findings else 'reviewed_with_limits',
              'findings':findings,'top_level_files_checked':len(checked),'coverage_extra':extra,'coverage_missing':missing,
              'file_identity_mismatches':problems,'manifest_file_identities':checked,
              'zip_checks':archives,'relative_markdown_links':links,'cost_artifact_links':refs,
              'quantitative_cost_checks':numeric_checks,'hosted_identity':ci_identity,
              'hosted_fixture_status':outcome['science_status'],'hosted_ci_is_not_overall_ci':True,
              'c1_capsule_source_comparison':capsule_comparison,
              'opaque_historical_records':['review/curation-assembly-v1-failed.json','review/curation-working-manifest-v1.json'],
              'source_before':before,'source_after':after,'reviewed_inputs_unchanged':stable,
              'source_sha256':identity(__file__)['sha256'], 'review_wall_seconds':time.monotonic()-began,
              'numerical_oracle_rerun':False,'training_performed':False,'native_progress_reobserved':False,
              'scientific_admission':'HOLD',
              'scope':'Final document claims, current local manifests, ZIP content safety, relative file links and selected raw cost/CI/source crosschecks. External URLs/fragments and native post-outage outcomes are not newly verified.'}
    (out/'RESULT.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    summary = {k:report[k] for k in ['schema','created_utc','reviewed_manifest_sha256','integrity_passed','claims_review_status','findings','top_level_files_checked','reviewed_inputs_unchanged','review_wall_seconds','scientific_admission']}
    summary.update(zip_archives_checked=len(archives),relative_links_checked=len(links),cost_artifact_links_checked=len(refs),quantitative_cost_checks=len(numeric_checks),result_sha256=identity(out/'RESULT.json')['sha256'])
    (out/'SUMMARY.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
    (out/'review_final_curation_v1.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps(summary,indent=2,sort_keys=True))


if __name__ == '__main__':
    main()
