"""Reproduce the frozen v1 controller branch on metadata; never launch a process."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    started, cpu = time.monotonic(), time.process_time()
    raw = args.source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == '195c8100a4147111cbc6b220cd1548aa8ca76d13ba4ebe0f4063005ef1912791'
    tree = ast.parse(raw)
    worker = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'run_one')
    branch = next(n for n in ast.walk(worker) if isinstance(n, ast.If)
                  and isinstance(n.test, ast.Call) and ast.unparse(n.test) == 'result_path.is_file()')
    assignment = next(n for n in ast.walk(worker) if isinstance(n, ast.Assign)
                      and ast.unparse(n.targets[0]) == "row['status']")
    assert 'hard_timeout_sent' in ast.unparse(assignment)
    totals = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'cost_totals')
    extracted = ast.unparse(ast.Module(body=[branch, assignment, totals], type_ignores=[])) + '\n'
    args.output.mkdir(exist_ok=False)
    (args.output / 'EXACT-EXTRACTED-LOGIC.py').write_text(extracted)
    with tempfile.TemporaryDirectory(prefix='c2-pure-metadata-counterexample-') as directory:
        row = {'name': 'explicit-software-counterexample', 'returncode': 0, 'hard_timeout_sent': False,
               'process_started': True, 'whole_process_wall_seconds': 2.0,
               'attempt_wrapper_wall_seconds': 2.1, 'child_cpu_seconds': .5}
        namespace = {'row': row, 'result_path': Path(directory) / 'absent-result.json', 'json': json}
        exec(compile(extracted, str(args.source) + ':exact-extracted-branch', 'exec'), namespace)
        result = {'schema': 'c2-v1-missing-terminal-result-reproduction-v1', 'source': str(args.source),
            'source_bytes': len(raw), 'source_sha256': digest, 'extracted_logic_sha256':
            hashlib.sha256(extracted.encode()).hexdigest(),
            'program_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'old_terminal_row': row, 'old_cost_totals': namespace['cost_totals']([row], [row['name']]),
            'counterexample_reproduced': row['status'] == 'completed', 'expected_status': 'failed',
            'source_unchanged': args.source.read_bytes() == raw,
            'model_processes_started': 0, 'model_reads_or_forward_backward_or_optimizer_steps': 0,
            'scope': 'synthetic metadata values only; not a native process outcome',
            'wall_seconds': time.monotonic() - started, 'cpu_seconds': time.process_time() - cpu}
    (args.output / 'RESULT.json').write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
