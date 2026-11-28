"""Qualify the five actual state retention calculations against original Chrono."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import time
import traceback

sys.dont_write_bytecode = True
from datetime_calendar_oracle.custody import binding, compile_original, require
from state_retention_cases import retention_cases
from state_retention_sources import REFERENCE, generate, inventory_sha256, source_custody
from test_datetime_calendar import identity
from test_duration_units import preserve

ROOT = Path(__file__).resolve().parents[2]


def qualify(args, report):
    require(sys.flags.optimize == 0, "retention qualification cannot disable assertions")
    producer = identity()
    contract = json.loads((ROOT / 'hia/state_retention_contract.json').read_bytes())
    require(contract['reference_commit'] == REFERENCE, "original source reference differs")
    build = json.loads((args.build / 'build.json').read_bytes())
    lock = json.loads((ROOT / 'hia/toolchain.json').read_bytes())
    require(build['status'] == 'built' and build['build_mode'] == 'native-selfhost'
            and build['compiler_fixed_point']
            and build['compiler_sha256'] == contract['compiler_sha256'], "native fixed point differs")
    for name, key in [('toolchain.json', 'toolchain_lock_sha256'),
                      ('build.py', 'build_driver_sha256'), ('cargo_build.rs', 'cargo_helper_sha256')]:
        require(binding(ROOT / 'hia' / name)['sha256'] == build[key], "native build input differs")
    require(build['toolchain'] == lock and set(build['modules']) == set(lock['modules'])
            and len(lock['modules']) == contract['production_native_modules'],
            "complete production module catalog differs")
    for name, row in build['modules'].items():
        require(binding(ROOT / f'hia/{name}.hepta')['sha256'] == row['source_sha256'],
                "production native source differs: " + name)
    archives = []
    for name, frozen in contract['qualified_components_reused'].items():
        row = build['modules'][name]
        component = json.loads((ROOT / f'hia/{name}_buffer_contract.json').read_bytes())
        require(row['source_sha256'] == component['source_sha256'] == frozen['source_sha256']
                and row['core_sha256'] == component['core_sha256'] == frozen['core_sha256']
                and binding(args.build / f'{name}.o')['sha256'] == frozen['object_sha256'],
                "production machine object differs from its qualified component")
        archive = binding(args.build / f'libcodex_hia_{name}.a')
        require(archive['sha256'] == row['codex_link_abi']['archive_sha256'], "native archive differs")
        archives.append(archive)
    require(set(contract['qualified_components_reused']) ==
            {'duration_units', 'datetime_arithmetic', 'datetime_units'}, "retention component set differs")
    inventory, originals, currents = source_custody(args.original_repo)
    require(len(inventory) == contract['complete_original_rust_files']
            and inventory_sha256(inventory) == contract['source_inventory_sha256'],
            "complete original/current state source differs")
    (args.output / 'state-source-inventory.json').write_text(json.dumps(inventory, indent=2) + '\n')
    generated, fragments = generate(originals, currents)
    require(fragments == contract['calculation_fragments'], "actual calculation source differs")
    generated_path = args.output / 'production_calculations.rs'
    generated_path.write_text(generated)
    require(binding(generated_path)['sha256'] == contract['generated_source_sha256'],
            "generated calculation observer differs")
    transport = binding(ROOT / 'hia/datetime_retention.rs')
    require(all(transport[key] == contract['transport'][key] for key in ('bytes', 'sha256')),
            "actual production ABI transport differs")
    report.update(producer=producer, native_build=binding(args.build / 'build.json'),
                  linked_native=archives, contract=binding(ROOT / 'hia/state_retention_contract.json'),
                  source_inventory=binding(args.output / 'state-source-inventory.json'),
                  complete_original_rust_files=len(inventory), methods=fragments,
                  generated_source=binding(generated_path), transport=transport)
    component = json.loads((ROOT / 'hia/datetime_arithmetic_buffer_contract.json').read_bytes())
    _, custody = compile_original(ROOT, args.original_lock, args.cargo, args.rustc, args.output,
                                  component, 'hia/tests/datetime_arithmetic_oracle')
    report['original'] = {'receipt': binding(args.output / 'original-custody.json'),
                          'toolchain': custody['toolchain'], 'executable': custody['executable']}
    messages = [json.loads(line) for line in (args.output / 'build.stdout').read_bytes().splitlines()]
    chrono = [name for row in messages if row.get('reason') == 'compiler-artifact'
              and row['target']['name'] == 'chrono' for name in row['filenames'] if name.endswith('.rlib')]
    require(len(chrono) == 1, "original compile has no unique Chrono library")
    chrono = Path(chrono[0]).resolve(strict=True)
    require(chrono.is_relative_to(args.output / 'target'), "original library escaped its fresh target")
    corpus = args.output / 'inputs.bin'
    count = 0
    with corpus.open('xb') as stream:
        for row in retention_cases():
            stream.write(struct.pack('<5Q', *row))
            count += 1
    require(count == contract['input_cases'] and binding(corpus)['sha256'] == contract['input_sha256'],
            "complete frozen retention corpus differs")
    report['inputs'] = preserve(args.output / 'inputs.bin.gz', corpus.read_bytes())
    executable = args.output / 'state-retention-callers'
    command = [str(args.rustc), '--edition=2024', '--test', '--cfg', 'feature="hia-native"',
               str(Path(__file__).with_name('state_retention_callers.rs')), '--extern', 'chrono=' + str(chrono),
               '-L', 'dependency=' + str(chrono.parent), '-L', 'native=' + str(args.build),
               '-l', 'static=codex_hia_duration_units', '-l', 'static=codex_hia_datetime_arithmetic',
               '-l', 'static=codex_hia_datetime_units', '-o', str(executable)]
    env = dict(os.environ, CODEX_STATE_RETENTION_METHODS=str(generated_path),
               CODEX_STATE_RETENTION_CASES=str(corpus), CODEX_STATE_RETENTION_TRACE=str(args.output / 'observations.bin'))
    report.update(linked_chrono=binding(chrono), compile_argv=command,
                  replay_source=binding(Path(__file__).with_name('state_retention_callers.rs')))
    archived_chrono = args.output / 'linked-original-chrono.rlib'
    archived_chrono.write_bytes(chrono.read_bytes())
    report['linked_chrono_archive'] = binding(archived_chrono)
    require(report['linked_chrono_archive']['sha256'] == report['linked_chrono']['sha256'],
            "archived original implementation differs from its linked bytes")
    compiled = subprocess.run(command, env=env, capture_output=True, timeout=60)
    for stream in ('stdout', 'stderr'):
        (args.output / ('compile.' + stream)).write_bytes(getattr(compiled, stream))
    report['compile_returncode'] = compiled.returncode
    require(compiled.returncode == 0, "actual retention calculation replay failed to compile")
    report['executable'] = binding(executable)
    executed = subprocess.run([str(executable), '--nocapture', '--test-threads=1'], env=env,
                              capture_output=True, timeout=120)
    for stream in ('stdout', 'stderr'):
        (args.output / ('tests.' + stream)).write_bytes(getattr(executed, stream))
    report['test_returncode'] = executed.returncode
    require(executed.returncode == 0 and b'1 passed; 0 failed; 0 ignored' in executed.stdout,
            "actual original/current retention calculation differs")
    records = re.findall(rb'STATE_RETENTION_REPORT=(\{[^\n]+\})', executed.stdout)
    require(len(records) == 1, "actual caller observation counts are missing or duplicated")
    counts = json.loads(records[0])
    require(counts == contract['observations'] and counts['input_cases'] == count
            and sum(counts['typed_cases']) + counts['outside_typed_domain'] == count,
            "complete original/native observation accounting differs")
    report['observations'] = counts
    trace = args.output / 'observations.bin'
    require(trace.stat().st_size == count * 88, "original/native complete trace is truncated")
    report['trace'] = preserve(args.output / 'observations.bin.gz', trace.read_bytes())
    require(report['trace']['raw_bytes'] == contract['trace_raw_bytes']
            and report['trace']['raw_sha256'] == contract['trace_raw_sha256'],
            "complete original/native observations differ from the frozen trace")
    require(identity() == producer and source_custody(args.original_repo)[0] == inventory
            and binding(chrono) == report['linked_chrono']
            and all(binding(Path(row['path'])) == row for row in archives),
            "production source or linked implementation changed")
    report['passed'] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('build', 'original-repo', 'original-lock', 'cargo', 'rustc', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    for name in ('build', 'original_repo', 'original_lock', 'cargo', 'rustc'):
        setattr(args, name, getattr(args, name).resolve(strict=True))
    args.output = args.output.resolve()
    require(not args.output.is_relative_to(ROOT) and not args.output.is_relative_to(args.build),
            "retention output must be outside source and production native output")
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'schema': 'codex.hia.state-retention-callers.v1', 'passed': False, 'started_unix': time.time(),
              'controller': binding(Path(__file__).resolve()),
              'scope': 'Five original state date calculations, exact cutoff values, panic payloads and clock order',
              'clock_seam': 'Utc::now() -> identical two-value counting clock in both production calculation fragments',
              'log_observation_seam': 'delete_logs_before argument observed; checked underflow observes skipped cleanup',
              'whole_production_crate_qualified': False, 'chrono_removed': False, 'legacy_retirement': False}
    try:
        qualify(args, report)
    except BaseException:
        report['exception'] = traceback.format_exc()
        raise
    finally:
        report['finished_unix'] = time.time()
        path = args.output / 'report.json'
        path.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'passed': report['passed'], 'report': binding(path)}), flush=True)


if __name__ == '__main__':
    main()
