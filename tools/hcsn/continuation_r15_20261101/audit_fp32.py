"""Reproduce frozen full-financial FP32 failures without changing scientific sources.

Run from a repository checkout, or pass --repo explicitly. --output must name a
new JSON file outside the repository or inside its additive R15 directory.
Exit zero means the diagnosis completed; it never grants FP32 qualification.
The optional debt rearrangements are diagnostic formulas, not production code.
"""

import argparse
import gzip
import hashlib
import importlib.util
import json
import platform
import sys
from pathlib import Path

sys.dont_write_bytecode = True
import numpy as np

R11 = Path('tools/hcsn/calibrated_operator_r11_20261031/numerics')
R15 = Path('tools/hcsn/continuation_r15_20261101')
SOURCE_NAMES = ('kernel.py', 'reference.py', 'audit.py', 'PROTOCOL_V3.json')
KERNEL_BLOB = '95cace749982a6b48b738dfa5d369b6491589a87'
ARCHIVE_SHA = 'aa35be2e7e8760518ca6d0865abb363256d04f937ab831f35c408e719e92bec0'
WITNESSES = [
    ('maturity_0.01', 'log_distance', 0.0004600004758685827),
    ('maturity_0.01', 'log_distance', 0.00034500000765547156),
    ('maturity_0.1', 'asset', 87.50782775878906),
    ('delta_0.2', 'log_distance', 0.0),
    ('recovery_0', 'asset', 128.73773193359375),
]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def locations(repo_arg, output_arg):
    candidates = [repo_arg.expanduser().resolve()] if repo_arg else list(Path(__file__).resolve().parents) + [Path.cwd(), *Path.cwd().parents]
    repo = next((p for p in candidates if (p / R11 / 'kernel.py').is_file()), None)
    require(repo is not None, 'Cannot locate R11 sources; pass --repo /path/to/checkout')
    require(not output_arg.is_symlink(), 'Output must not be a symlink')
    output = output_arg.expanduser().resolve()
    require(not output.is_relative_to(repo) or output.is_relative_to(repo / R15),
            'Repository output is restricted to the additive R15 directory; frozen paths are read-only')
    require(not output.exists(), 'Output already exists; choose a new path')
    require(output.parent.is_dir(), 'Output parent directory must already exist')
    return repo, output


def debt_diagnostic(kernel, rows, gates):
    """Two algebraic candidates; all 432 old rows, only debt and its Jacobian.

    With sf=1-F and recovery=alpha*b/m, regrouping gives
    recovery*G + (c/R)*(1-G) + discount*q*sf.
    Positive components give
    (c/R)*((1-discount)*sf+(F-G)) + p*discount*sf + recovery*G.
    Computing sf and F-G from rounded fields remains inaccurate. Neither
    candidate repairs the boundary or equity, or establishes qualification.
    """
    models, statistics = {}, {n: [] for n in ('original', 'debt_regroup', 'debt_positive_components')}
    basis = np.eye(10, dtype=np.float32)
    for row in rows:
        key = tuple(row['quantized_theta'])
        if key not in models:
            models[key] = kernel.FullHX([kernel.Dual(v, basis[i]) for i, v in enumerate(key)])
        model = models[key]
        arg = kernel.Dual(row['state'], basis[-1])
        x = kernel.log(arg / model.b) if row['coordinate'] == 'asset' else arg
        if x.v <= 0 and row['coordinate'] == 'asset':
            variants = dict.fromkeys(statistics, model.alpha * model.b / model.m)
        else:
            f, g = model.first_hit(x, model.m)
            sf, recovery = 1 - f, model.alpha * model.b / model.m
            variants = {
                'original': model.c / model.R + model.discount * model.q * sf + (recovery - model.c / model.R) * g,
                'debt_regroup': recovery * g + model.c / model.R * (1 - g) + model.discount * model.q * sf,
                'debt_positive_components': model.c / model.R * (-kernel.expm1(-model.R * model.m) * sf + (f - g))
                    + model.p * model.discount * sf + recovery * g,
            }
        for name, d in variants.items():
            require(d.g.dtype == np.float32 and isinstance(d.v, np.float32), 'Unexpected financial dtype')
            ve = float(abs(float(d.v) - row['reference'][4]) / max(1., abs(row['reference'][4])))
            je = float(np.max(abs(d.g - row['reference_jacobian'][4]) / np.maximum(1., np.abs(row['reference_jacobian'][4]))))
            statistics[name].append(dict(case=row['case'], value_error=ve, jacobian_error=je,
                passed=ve <= gates['value_scaled'] and je <= gates['jacobian_scaled']))
    baseline, summary = statistics['original'], {}
    for name, part in statistics.items():
        summary[name] = dict(rows=len(part), debt_rows_passed=sum(r['passed'] for r in part),
            debt_cases_passed=sum(all(r['passed'] for r in part if r['case'] == c) for c in {r['case'] for r in part}),
            max_value_scaled=max(r['value_error'] for r in part), max_jacobian_scaled=max(r['jacobian_error'] for r in part),
            fixed_debt_pass_failures=sum(r['passed'] and not o['passed'] for r, o in zip(part, baseline)),
            regressed_debt_passes=sum(o['passed'] and not r['passed'] for r, o in zip(part, baseline)))
    return summary


def run(repo, output, include_debt):
    root = repo / R11
    before = {name: sha((root / name).read_bytes()) for name in SOURCE_NAMES}
    source = (root / 'kernel.py').read_bytes()
    blob = hashlib.sha1(b'blob ' + str(len(source)).encode() + b'\0' + source).hexdigest()
    require(blob == KERNEL_BLOB, 'Kernel differs from the pinned published source')
    spec = importlib.util.spec_from_file_location('_hcsn_fp32_diagnostic_kernel', root / 'kernel.py')
    kernel = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kernel)
    index = json.loads((root / 'EVIDENCE_ARCHIVE.json').read_text())
    member = next(m for m in index['members'] if m['member'] == 'FINAL_RESULTS.json')
    chunks, offset = [], 0
    for chunk in member['chunks']:
        packed = (root / chunk['path']).read_bytes()
        require(len(packed) == chunk['compressed_bytes'] and sha(packed) == chunk['compressed_sha256'], 'Invalid compressed archive chunk')
        raw = gzip.decompress(packed)
        require(len(raw) == chunk['raw_bytes'] and sha(raw) == chunk['raw_sha256'], 'Invalid decompressed archive chunk')
        require(offset == chunk['offset'], 'Invalid chunk offset')
        offset += len(raw)
        chunks.append(raw)
    raw = b''.join(chunks)
    require(len(raw) == member['bytes'] and sha(raw) == member['sha256'] == ARCHIVE_SHA, 'Invalid complete reference archive')
    archive = json.loads(raw)
    require(source.endswith(b'\n\n') and sha(source[:-1]) == archive['source_sha256']['kernel.py'], 'Unexpected historical kernel difference')
    rows = [row for row in archive['rows'] if row['mode'] == 'float32']
    protocol = json.loads((root / 'PROTOCOL_V3.json').read_text())
    require(before['PROTOCOL_V3.json'] == archive['protocol_sha256'], 'Protocol differs from frozen reference')
    require(all(before[n] == archive['source_sha256'][n] for n in ('reference.py', 'audit.py')), 'Historical numerical source mismatch')
    gates = protocol['gates']['float32']
    witnesses = []
    for case, coordinate, state in WITNESSES:
        row = next(r for r in rows if (r['case'], r['coordinate'], r['state']) == (case, coordinate, state))
        values, jacobian = kernel.evaluate(row['quantized_theta'], state, coordinate=coordinate, mode='float32')
        ve = abs(values - row['reference']) / np.maximum(1., np.abs(row['reference']))
        je = abs(jacobian - row['reference_jacobian']) / np.maximum(1., np.abs(row['reference_jacobian']))
        j, k = np.unravel_index(je.argmax(), je.shape)
        witnesses.append(dict(case=case, coordinate=coordinate, state=state,
            theta=row['quantized_theta'], values=values.tolist(), reference=row['reference'],
            value_errors=ve.tolist(), max_jacobian_error=float(je.max()),
            fails_original_gate=bool(ve.max() > gates['value_scaled'] or je.max() > gates['jacobian_scaled']),
            worst_jacobian=dict(output=archive['output_order'][j], column=archive['jacobian_columns'][k],
                actual=float(jacobian[j, k]), reference=row['reference_jacobian'][j][k]),
            current_values_exactly_equal_archived=bool(np.array_equal(values, row['actual'])),
            current_jacobian_exactly_equal_archived=bool(np.array_equal(jacobian, row['jacobian']))))
    rearrangements = debt_diagnostic(kernel, rows, gates) if include_debt else None
    after = {name: sha((root / name).read_bytes()) for name in SOURCE_NAMES}
    require(before == after, 'Numerical source seal changed during diagnosis')
    receipt = dict(schema='hcsn.r15.readonly-full-financial-fp32-diagnosis.v2',
        published_commit_checked='0ee3bb576e3db6156dad9b914ef5bae83a5387db', source_location=R11.as_posix(),
        reproducer_sha256=sha(Path(__file__).read_bytes()), environment=dict(python=platform.python_version(), numpy=np.__version__),
        current_kernel_git_blob_sha1=blob, source_sha256=before, source_seal_after=after, source_unchanged=True,
        archive_member=member['member'], archive_member_sha256=member['sha256'], all_chunk_hashes_offsets_sizes_verified=True,
        historical_kernel_sha256=archive['source_sha256']['kernel.py'],
        historical_source_difference='Current kernel has exactly one additional final newline; removing it reproduces the archived source SHA256.',
        gate_scope=dict(original_archive='All five financial outputs and all ten Jacobian columns; 432 rows, 18 cases.',
            current_rerun='Five selected previous failures only; no new qualification.',
            debt_rearrangements='Debt output and its ten Jacobian columns ONLY. A debt case passes only if all its state rows pass. This is not a full financial-operator case pass.'),
        error_definition='max(abs(actual-reference)/max(1,abs(reference)))', original_gates=gates,
        original_full_operator_native_fp32_summary=archive['summary']['float32'], reproduced_current_source_witnesses=witnesses,
        narrow_rearrangement_diagnostic=dict(executed=include_debt, scope='Post hoc, debt-only, all 432 old FP32 rows; not a new qualification or benchmark.',
            definitions=dict(sf='1-F', recovery='alpha*b/m',
                debt_regroup='recovery*G + (c/R)*(1-G) + discount*q*sf',
                debt_positive_components='(c/R)*((1-discount)*sf+(F-G))+p*discount*sf+recovery*G'),
            results=rearrangements, source_mutated=False, precision_promoted=False, full_operator_qualification_inferred=False),
        conclusion=dict(full_native_fp32_qualified=False, single_debt_rearrangement_closes_blocker=False,
            independent_failure_sites=['B/b boundary value and parameter derivatives', 'wrong asset/default branch caused by inaccurate b',
                'raw A7 equity cancellation and C2 blend derivative amplification', 'debt complements and derivative cancellation'],
            next_stage='New additive stable FP32 financial kernel with unchanged inherited gates and independent high-precision values/Jacobians. Preserve R11 source and failures.',
            exclusions=['No R15 benchmark rerun', 'No acceptance change', 'No mixed32 relabeling', 'No full parameter-box or production qualification']))
    with output.open('x', encoding='utf-8') as target:
        json.dump(receipt, target, indent=2, allow_nan=False)
        target.write('\n')
    return dict(path=str(output), bytes=output.stat().st_size, sha256=sha(output.read_bytes()),
        diagnostic_completed=True, witnesses_reproduced=len(witnesses), source_unchanged=True,
        full_native_fp32_qualified=False, debt_rearrangements_executed=include_debt)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, help='Repository root; otherwise discover from script or working directory')
    parser.add_argument('--output', type=Path, required=True, help='Create-only JSON destination; never a frozen repository path')
    parser.add_argument('--debt-rearrangements', action='store_true', help='Also compare two debt-only algebraic candidates against all 432 archived rows')
    args = parser.parse_args()
    repo_path, output_path = locations(args.repo, args.output)
    print(json.dumps(run(repo_path, output_path, args.debt_rearrangements), indent=2))
