"""Build the standalone bridge; --fetch resolves pinned deps once, then vendors.

This compiles this research crate only, never the real Hepta workspace.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parent
CRATE = ROOT / 'rust_bridge'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch', action='store_true')
    args = parser.parse_args()
    environment = dict(os.environ)
    environment['PATH'] = str(ROOT / 'toolchain/bin') + os.pathsep + environment['PATH']
    environment['CARGO_HOME'] = str(ROOT / 'cargo_cache')
    environment['CARGO_TARGET_DIR'] = str(CRATE / 'target')
    environment['CARGO_BUILD_JOBS'] = '1'
    if hasattr(os, 'sched_setaffinity') and 6 in os.sched_getaffinity(0):
        os.sched_setaffinity(0, {6})
    steps = []

    def run(command):
        begun = time.perf_counter()
        result = subprocess.run(command, cwd=CRATE, env=environment, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        steps.append({'command': command, 'returncode': result.returncode,
                      'wall_seconds': time.perf_counter() - begun, 'output': result.stdout})
        print(json.dumps({'command': command, 'returncode': result.returncode,
                          'output_tail': result.stdout[-4500:]}), flush=True)
        if result.returncode:
            raise RuntimeError('Build step failed; see saved log')
        return result.stdout

    try:
        if args.fetch:
            run(['cargo', 'generate-lockfile'])
            run(['cargo', 'fetch', '--locked'])
            run(['cargo', 'vendor', '--locked', '--offline', '--versioned-dirs', 'vendor'])
            configuration = CRATE / '.cargo/config.toml'
            configuration.parent.mkdir(exist_ok=True)
            configuration.write_text('[source.crates-io]\nreplace-with = "vendored-sources"\n'
                                     '[source.vendored-sources]\ndirectory = "vendor"\n[net]\noffline = true\n')
        run(['cargo', 'fmt', '--all'])
        run(['cargo', 'test', '--locked', '--offline', '--all-targets'])
        run(['cargo', 'build', '--locked', '--offline', '--release'])
        binary = CRATE / 'target/release/rrsnn-offline-replay-bridge'
        report = {'schema': 'rrsnn.standalone-rust-build.v1', 'all_passed': True,
                  'scope': 'Independent offline research crate; not a Hepta workspace build.',
                  'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
                  'binary_bytes': binary.stat().st_size, 'steps': steps}
    except Exception as error:
        report = {'schema': 'rrsnn.standalone-rust-build.v1', 'all_passed': False,
                  'error': str(error), 'steps': steps}
        raise
    finally:
        (ROOT / 'rust_build_report.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
