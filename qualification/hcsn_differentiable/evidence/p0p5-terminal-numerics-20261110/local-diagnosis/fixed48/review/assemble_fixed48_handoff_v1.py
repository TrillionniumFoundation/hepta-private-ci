"""Read saved scalar outputs and seal evidence; never import or rerun the toys."""
from collections import Counter
from pathlib import Path, PurePosixPath
import hashlib
import json
import shutil
import zipfile

BASE = Path('/workspace/scratch/c385a7439f8e')
DEST = BASE / 'p1-short-time-toy-handoff-v1'
PROGRAM_SHA = '8b7015a93d3da6f158b11e330b3dc7e5af5d01a4521585e5f7578a7e1842e966'


def require(value, message):
    if not value:
        raise ValueError(message)


def identity(path):
    raw = path.read_bytes()
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def read(path):
    return json.loads(path.read_bytes())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def check_zip(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), 'duplicate ZIP member')
        require(all(not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts
                    and '\\' not in n for n in names), 'unsafe ZIP member')
        require(archive.testzip() is None, 'ZIP CRC failed')
        if 'MEMBER-MANIFEST.json' in names:
            members = json.loads(archive.read('MEMBER-MANIFEST.json'))
            require(set(members) == set(names) - {'MEMBER-MANIFEST.json'}, 'archive coverage')
            for name, spec in members.items():
                raw = archive.read(name)
                require(spec == {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}, name)
        return {'members': len(names), 'crc_verified': True, **identity(path)}


def main():
    require(not DEST.exists(), 'exclusive handoff directory already exists')
    program = BASE / 'p1-short-time-toy-program-v1'
    executed = BASE / 'p1-short-time-toy-execution-v2'
    infrastructure = BASE / 'p1-short-time-toy-infrastructure-attempt2'
    failure_dir = BASE / 'p1-short-time-toy-launch-failure-v1'
    source_manifest = read(program / 'PROGRAM-MANIFEST.json')
    require(identity(program / 'PROGRAM-MANIFEST.json')['sha256'] == PROGRAM_SHA, 'program identity')
    for name, spec in source_manifest['files'].items():
        require(identity(program / name) == spec, 'program file changed: ' + name)
    for name, spec in read(infrastructure / 'SOURCE-MANIFEST.json')['files'].items():
        require(identity(infrastructure / name) == spec, 'infrastructure file changed: ' + name)
    result = read(executed / 'worker/RESULT.json')
    execution = read(executed / 'EXECUTION.json')
    outer = read(infrastructure / 'RESULT.json')
    failure = read(failure_dir / 'RESULT.json')
    receipt = read(executed / 'ARCHIVE-RECEIPT.json')
    roster = read(program / 'ROSTER.json')['cases']
    journal = [json.loads(row) for row in (executed / 'worker/cases.jsonl').read_text().splitlines()]
    require(journal == result['cases'], 'journal does not equal saved result cases')
    ids = [row['id'] for row in roster]
    require(len(ids) == len(set(ids)) == 48, 'roster is not unique fixed48')
    require(ids == [row['id'] for row in journal], 'case sequence changed')
    require(ids == [row['id'] for row in execution['fixed_case_admission_roster']], 'admission roster changed')
    require(result['computed_cases'] == 48 and result['case_failures'] == result['unrun_cases'] == 0, 'execution count')
    require(result['source_unchanged'] and execution['source_unchanged'], 'producer source guard')
    require(all(row['execution_status'] == 'computed_scalar_case' for row in journal), 'incomplete case')
    require(outer['launcher_exit_code'] == 0 and outer['numeric_retry'] is False, 'launcher outcome')
    require(failure['exit_code'] == 127 and not failure['launcher_started'] and not failure['worker_started'], 'first failure scope')
    require(failure['scalar_cases_started'] == 0 and not (BASE / 'p1-short-time-toy-execution-v1').exists(), 'first-run absence proof')
    require(identity(executed / 'worker/RESULT.json') == execution['worker_result_identity'], 'worker identity')
    require(identity(executed / 'EXECUTION.json') == outer['execution_receipt'], 'execution identity')
    require(identity(executed / 'ARCHIVE-RECEIPT.json') == outer['archive_receipt'], 'archive receipt identity')
    archive_path = Path(receipt['archive']['path'])
    require(identity(archive_path) == {k: receipt['archive'][k] for k in ('bytes', 'sha256')}, 'execution ZIP identity')
    require(outer['archive'] == receipt['archive'] and receipt['archive_finalized'], 'archive receipt linkage')
    input_paths = [p for root in (program, executed, infrastructure, failure_dir)
                   for p in sorted(root.rglob('*')) if p.is_file()]
    before = {str(p): identity(p) for p in input_paths}
    active = [row for row in journal if row['kind'] == 'active']
    pressure = [row for row in active if row['h_star_factor'] is None]
    phase = [row for row in journal if row['kind'] == 'phase']
    tail = [row for row in journal if row['kind'] == 'tail']
    require((len(active), len(pressure), len(phase), len(tail)) == (42, 12, 4, 2), 'fixed kind counts')
    counts = dict(Counter(row['resolution_status'] for row in active))
    require(counts == {'Gauss_positive_mass_underflowed': 6,
                       'difference_above_roundoff_scale': 29,
                       'difference_sign_inconclusive_at_roundoff_scale': 7}, 'saved resolution counts')
    DEST.mkdir()
    copied = {}
    for label, root in [('program', program), ('execution', executed),
                        ('infrastructure-attempt2', infrastructure), ('infrastructure-attempt1', failure_dir)]:
        for p in sorted(root.rglob('*')):
            if p.is_file():
                target = DEST / 'originals' / label / p.relative_to(root)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, target)
                require(identity(target) == identity(p), 'copy mismatch')
                copied[target.relative_to(DEST).as_posix()] = {'source': str(p), **identity(p)}
    original_archives = {}
    for name in ['p1-short-time-toy-program-v1.zip', 'p1-short-time-toy-execution-v2.zip',
                 'p1-short-time-toy-launch-failure-v1.zip', 'p1-fixed-grid-short-time-diagnosis-v1.zip']:
        p = BASE / name
        original_archives[name] = check_zip(p)
        with zipfile.ZipFile(p) as archive:
            for member in archive.namelist():
                local = None
                if name == 'p1-short-time-toy-program-v1.zip':
                    local = program / member
                elif name == 'p1-short-time-toy-launch-failure-v1.zip':
                    local = failure_dir / member
                elif name == 'p1-short-time-toy-execution-v2.zip' and member != 'MEMBER-MANIFEST.json':
                    head, relative = member.split('/', 1)
                    local = {'program': program, 'execution': executed}[head] / relative
                if local is not None:
                    require(archive.read(member) == local.read_bytes(), 'ZIP/local byte mismatch: ' + member)
        target = DEST / 'original-archives' / name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(p, target)
        require(identity(target) == identity(p), 'archive copy mismatch')
        copied[target.relative_to(DEST).as_posix()] = {'source': str(p), **identity(p)}
    for p in [Path(__file__), BASE / 'package_fixed48_with_wait4_v1.py']:
        target = DEST / 'review' / p.name
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(p, target)
    write(DEST / 'review/EXTERNAL-TOOL-TERMINAL-TRANSCRIPTION.json', {
        'schema': 'tool-result-transcription-not-new-process-measurement',
        'source': 'original functions.exec exec_command return observed in this conversation',
        'chunk_id': '789833', 'exit_code': 0, 'tool_wall_time_seconds': 0.120979967,
        'scope': 'Tool-return metadata only; not a complete independent OS process wall measurement.',
        'command_summary': '/usr/bin/timeout --signal=KILL 120s python -B wait4_wrapper.py',
        'actual_scalar_executions': 1, 'infrastructure_launch_attempts': 2,
        'GNU_time_available': False,
        'replacement': 'Complete launcher os.wait4 and monotonic interval; wrapper prefix and timeout exit separately retained.'})
    costs = {
        'schema': 'fixed48-cost-scopes-v1', 'accounting_complete': False,
        'rows': [
            {'id': 'infrastructure-attempt1', 'status': 'exit127_before_python',
             'wall_seconds': None, 'CPU_seconds': None, 'scalar_cases_started': 0,
             'receipt': 'originals/infrastructure-attempt1/RESULT.json',
             'scope': 'Exact complete OS cost unknown. Missing /usr/bin/time; preserved tool timing is not full OS cost.'},
            {'id': 'infrastructure-attempt2-complete-launcher', 'status': 'exit0',
             'wall_seconds': outer['complete_launcher_wall_seconds'],
             'CPU_seconds': outer['launcher_wait4_CPU_seconds'],
             'wait4_peak_RSS_bytes': outer['launcher_wait4_peak_RSS_bytes'],
             'receipt': 'originals/infrastructure-attempt2/RESULT.json',
             'scope': 'Complete Python launcher plus waited worker CPU; includes source checks, worker, archive and launcher exit.'},
            {'id': 'nested-complete-worker', 'status': 'exit0',
             'wall_seconds': execution['child_full_wall_seconds'],
             'CPU_seconds': execution['child_wait4_CPU_seconds'],
             'wait4_peak_RSS_bytes': execution['child_peak_RSS_bytes'],
             'receipt': 'originals/execution/EXECUTION.json',
             'overlaps': 'infrastructure-attempt2-complete-launcher',
             'scope': 'Includes worker import, scalar cases, serialization and exit. Do not add to launcher.'},
            {'id': 'external-wrapper-prefix',
             'wall_seconds': outer['whole_wall_prefix_seconds'],
             'own_CPU_seconds': outer['own_CPU_prefix_seconds'],
             'sampled_combined_RSS_bytes': outer['sampled_combined_RSS_bytes'],
             'conservative_sum_process_peak_RSS_bytes': outer['conservative_all_three_process_peak_RSS_upper_bound_bytes'],
             'receipt': 'originals/infrastructure-attempt2/RESULT.json',
             'scope': 'Wall overlaps the launcher; own CPU excludes launcher CPU but ends before wrapper final receipt and exit.'}],
        'nested_case_timers': 'Original cases.jsonl retains all 48 local timers; they overlap worker timing and zero timer values are below clock resolution.',
        'external_whole_timeout_seconds': 120,
        'complete_external_command_wall_seconds': None,
        'complete_external_command_CPU_seconds': None,
        'complete_all_attempt_cost': None,
        'unmeasured': ['First infrastructure attempt full OS cost', 'External wrapper final serialization/exit tail',
                       'Interactive preparation and read-only packaging are outside the scalar execution; packaging has its own external receipt.'],
        'old_GNU_wording': 'Original launcher receipts remain unchanged. Their anticipated external GNU record was unavailable; the root-authorized second infrastructure wrapper uses wait4 instead.'}
    write(DEST / 'COSTS.json', costs)
    summary = {
        'schema': 'saved-fixed48-result-summary-v1',
        'execution': {'status': result['status'], 'planned': 48, 'computed': 48,
                      'case_failures': 0, 'unrun': 0, 'numerical_execution_count': 1,
                      'infrastructure_attempts': 2, 'first_infrastructure_exit': 127},
        'active_resolution_counts': counts, 'active_pressure_dt_rows': pressure,
        'isolated_phase_rows': phase, 'hypothetical_tail_rows': tail,
        'original_archives': original_archives,
        'program_manifest_sha256': PROGRAM_SHA,
        'all_original_input_bytes_unchanged': before == {str(p): identity(p) for p in input_paths},
        'journal_matches_saved_result_and_fixed_roster': True,
        'model_posterior_E_or_oracle_access_by_packaging': False,
        'new_scalar_evaluation_by_packaging': False,
        'training_domain_qualification': 'HOLD', 'scientific_admission': 'HOLD',
        'attribution_to_real_pressure_value_error': False,
        'roundoff_scale_is_a_certified_error_bound': False,
        'bounded_local_inference': 'At n256/q32, the two declared pressure dt values are above h_star for this free mu0 adjacent-cell calculation. This does not partition real recurrent value errors.',
        'COPY_SOURCE_MAP': copied}
    require(summary['all_original_input_bytes_unchanged'], 'original input mutation')
    write(DEST / 'SUMMARY.json', summary)
    lines = [
        '# Fixed48 short-time scalar diagnostic: saved results and limits', '',
        '**All 48 predeclared scalar cases executed once.** There were two infrastructure launch attempts: the first exited 127 before Python because `/usr/bin/time` was absent; the second used the authorized standard-library `wait4` wrapper. The mathematical program, roster and 120 s / 256 MiB envelope did not change. No scalar case was retried.', '',
        'This is a local FP64 mechanism diagnostic. Training-domain and scientific admission remain **HOLD**. It does not evaluate an HCSN model, posterior, E data, or a numerical oracle, and it does not assign shares of the 12 observed perpetual-value pressure failures.', '',
        '## Scope and source', '',
        f'The frozen mathematical manifest is `{PROGRAM_SHA}`. The original source, roster, authorization transcriptions, each case, journal, stdout/stderr, both infrastructure attempts, original execution ZIP and external final receipts are included unchanged. [SUMMARY.json](SUMMARY.json) binds the copied files and archive identities; [COSTS.json](COSTS.json) separates nested measurements. The original analytic note and source capsule are retained under `original-archives/`.', '',
        'The active toy uses a free Gaussian kernel, drift 0 and sigma 0.35, uniform source `[0, Delta]`, and target `[Delta, 2 Delta]`. The widths are 4.8/128 and 4.8/256. Orders 16/32/64 use the original operator Gauss-node function, extracted as standalone source without importing Torch or the operator. The closed-form uniform-source probability and finite Gauss sum are both evaluated in FP64; “exact” in the raw field names refers to the analytic integral, not exact machine arithmetic.', '',
        '## All twelve fixed pressure-dt rows', '',
        'Relative difference is `(Gauss - closed form) / closed form`. These are local one-step adjacent-cell probabilities, not the original value/resolvent test or a numerical qualification gate.', '',
        '| Active cells | Gauss order | h | h / h_star | Signed relative difference (%) | Resolution |',
        '|---:|---:|---:|---:|---:|---|']
    for row in pressure:
        n = row['id'].split('-')[1][1:]
        label = 'inconclusive at engineering scale' if 'inconclusive' in row['resolution_status'] else 'above engineering scale'
        lines.append(f"| {n} | {row['order']} | {row['h']:.0e} | {row['h_over_h_star']:.9g} | {100 * row['signed_relative_difference_FP64']:+.10g} | {label} |")
    lines.extend([
        '', 'For the nominal 256-cell/order-32 geometry, the differences are **+0.1354797523%** at 1e-7 and **-0.0001402580933%** at 8e-7. Their h/h_star values are about 18.6173 and 148.939, so these two local cases are not in the declared h much smaller than h_star regime. They neither explain nor bound the coupled, nonzero-drift, phase/tail, infinite-repeat value errors. Increasing quadrature order reduced these two local differences; no network fix, training benefit or hardware benefit was tested.', '',
        'The 42 active cases include all five h_star factors for each width/order. Six smallest-step Gauss sums underflowed while the analytic probability was positive; the saved log Mills bounds distinguish this from a mathematical zero. Twenty-nine differences exceed the declared engineering roundoff scale and seven are inconclusive at that scale. These are resolution categories, not 42 pass/fail qualifications. The ULP scale is not a certified function-error bound. The symmetry-based nearest-node distance used for h_star and the right-edge subtraction in the probability can differ in final FP64 bits; the frozen implementation is retained.', '',
        '## Isolated phase transport', '',
        'The four cases start from the same physical uniform remaining-time law `[0.1875, 0.2]`, use phase width 0.0125 and 16 phases, and ask for release by time 0.1. That physical law has zero release probability at this time. The projected phase-only binomial-chain results are:', '',
        '| h / phase width | Projected release probability | Same initial uniform physical CDF | Projected waiting-time variance |',
        '|---:|---:|---:|---:|'])
    for row in phase:
        lines.append(f"| {row['h_over_width']:.4g} | {row['projected_isolated_release_probability']:.12g} | {row['same_initial_uniform_physical_release_probability']:.1f} | {row['geometric_chain_wait_variance']:.12g} |")
    lines.extend([
        '', 'All four projected means are 0.2, compared with 0.19375 for that initial physical uniform law. At fixed phase width, the h-to-zero isolated-chain limit has Erlang variance 0.0025. This illustrates re-projection broadening in the isolated phase transport; no coupled reset/active process or actual event count was evaluated.', '',
        '## Returning-tail information loss', '',
        'The two hypothetical laws are `4.8 + shift + Exp(rate=1)` with shift 0 or 1. Both project to tail coefficient 1. For drift -0.12, sigma 0.35 and discount 0.15, their analytic first-hit Laplace moments are respectively **0.008362287694218247** and **0.003515177193925358**, a ratio **0.42036071018649357**. Reconstruction from the same coefficient gives the former moment in both cases. No actual posterior tail was read; this demonstrates the information a single tail coefficient cannot retain.', '',
        '## Execution and costs', '',
        f"The successful complete launcher took {outer['complete_launcher_wall_seconds']:.12g} s wall and {outer['launcher_wait4_CPU_seconds']:.12g} s wait4 CPU. Its nested complete worker took {execution['child_full_wall_seconds']:.12g} s wall and {execution['child_wait4_CPU_seconds']:.12g} s CPU. **Do not add these nested totals.** The conservative sum of the three process peak RSS values was {outer['conservative_all_three_process_peak_RSS_upper_bound_bytes']:,} B, below 256 MiB.", '',
        f"The external wrapper recorded a {outer['whole_wall_prefix_seconds']:.12g} s wall prefix and {outer['own_CPU_prefix_seconds']:.12g} s own CPU prefix; its final receipt/exit tail is not measured. The external timeout command exited 0. Complete first-attempt OS wall/CPU and exact complete all-attempt costs remain unknown. The original launcher text anticipated a GNU-time record; the preserved second infrastructure receipt explicitly replaces it with wait4. A separate external packaging receipt reports only this read-only evidence assembly, not a second scalar execution.", '',
        '## Evidence finality', '',
        'The original execution ZIP is retained byte for byte, together with its external `ARCHIVE-RECEIPT.json` and complete-launcher `RESULT.json`. The new handoff ZIP adds the original pre-launch failure, authorized replacement source, source capsule, this summary and provenance checks. Its own external packaging receipt binds the completed archive SHA. All cases, including underflows and inconclusive results, remain in the raw journal. Research admission stays HOLD.', ''])
    with (DEST / 'REPORT.md').open('x', encoding='utf-8') as stream:
        stream.write('\n'.join(lines))
    manifest = {'schema': 'fixed48-complete-handoff-manifest-v1',
                'files': {p.relative_to(DEST).as_posix(): identity(p)
                          for p in sorted(DEST.rglob('*')) if p.is_file()}}
    require(all(spec['bytes'] <= 500000 for spec in manifest['files'].values()), 'member exceeds requested transfer size')
    write(DEST / 'MANIFEST.json', manifest)
    output_zip = DEST.with_suffix('.zip')
    with zipfile.ZipFile(output_zip, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for p in sorted(DEST.rglob('*')):
            if p.is_file():
                archive.write(p, p.relative_to(DEST).as_posix())
    require(output_zip.stat().st_size <= 500000, 'handoff ZIP exceeds requested transfer size')
    checked = check_zip(output_zip)
    print(json.dumps({'status': 'sealed_saved_results_only', 'zip': str(output_zip), **checked,
                      'manifest': identity(DEST / 'MANIFEST.json'), 'numerical_cases_executed_by_this_script': 0}))


if __name__ == '__main__':
    main()
