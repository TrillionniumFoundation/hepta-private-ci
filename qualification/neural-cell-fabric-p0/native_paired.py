"""P0.4 matched-in-process typed-vs-compiled pure Q24 CPU work pilot.

Not MCP, UI, GPU, a live OS effect, or proof that executing binary is faster.
Unlike the original guarded NativeMotorShadow path, timed native work excludes
an additional Python numerical oracle. Both arms pay identical typed-policy,
input-digest and output lineage work; numerical oracle runs AFTER each timed call.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import statistics
import tempfile
import time

from fabric import Denied, LIMIT, Q24, percentile_ns, q24_dot, sha
from native import CellProgram, NativeMotorShadow, compile_reviewed_source


def _envelope(program: CellProgram, f: tuple[int, ...], w: tuple[int, ...]) -> tuple[str, str]:
    program.validate()
    if not 1 <= len(f) <= 16 or len(f) != len(w):
        raise Denied('invalid Q24 ABI width')
    if any(type(x) is not int or abs(x) > LIMIT for x in f + w):
        raise Denied('invalid Q24 scalar')
    raw = b''.join(x.to_bytes(4, 'big', signed=True) for x in f + w)
    lineage = (program.source_digest + program.model_digest +
               str(program.generation) + program.opcode).encode()
    return sha(raw), sha(lineage)


def run_paired(*, repetitions: int = 512, repeats: int = 3) -> dict:
    if type(repetitions) is not int or not 64 <= repetitions <= 4096:
        raise Denied('invalid measured repetitions')
    if type(repeats) is not int or not 2 <= repeats <= 8:
        raise Denied('paired repeats required')
    input_a = tuple(((ix * 7) % 31 - 15) * Q24 // 16 for ix in range(16))
    input_b = tuple(((ix * 11) % 29 - 14) * Q24 // 16 for ix in range(16))
    program = CellProgram(sha(b'pinned synthetic input'), sha(b'pinned native model'),
                          1, 'PURE_Q24_DOT16')
    with tempfile.TemporaryDirectory(prefix='hepta-matched-native-') as temp:
        root = Path(temp)
        aot = root / 'reviewed.so'
        manifest = compile_reviewed_source(Path(__file__).with_name('q24_native.c'), aot)
        driver = NativeMotorShadow(aot, manifest['binary_sha256'])
        def compiled():
            input_digest, program_digest = _envelope(program, input_a, input_b)
            f = (ctypes.c_int32 * 16)(*input_a)
            w = (ctypes.c_int32 * 16)(*input_b)
            result = ctypes.c_int64()
            if driver._func(f, w, 16, ctypes.byref(result)) != 0:
                raise Denied('native status not success')
            return result.value, input_digest, program_digest
        def typed():
            input_digest, program_digest = _envelope(program, input_a, input_b)
            value = q24_dot(input_a, input_b)
            return value, input_digest, program_digest
        oracle = q24_dot(input_a, input_b)
        if compiled() != typed() or compiled()[0] != oracle:
            raise Denied('initial typed vs native mismatch')
        for _ in range(32):
            if typed()[0] != oracle or compiled()[0] != oracle:
                raise Denied('warmup mismatch')
        samples = {'typed': [], 'native': []}
        per_repeat = []
        for rep in range(repeats):
            batch = {'typed': [], 'native': []}
            arms = (('typed', typed), ('native', compiled)) if rep % 2 == 0 else (
                ('native', compiled), ('typed', typed))
            for _ in range(repetitions):
                for arm, fn in arms:
                    start = time.perf_counter_ns()
                    result = fn()
                    end = time.perf_counter_ns()
                    if result[0] != oracle or result[1:] != typed()[1:]:
                        raise Denied('observed numerical/source difference')
                    batch[arm].append(end - start)
            for arm in samples:
                samples[arm].extend(batch[arm])
            per_repeat.append({arm: {'p50_ns': percentile_ns(batch[arm], .50),
                                     'p95_ns': percentile_ns(batch[arm], .95),
                                     'p99_ns': percentile_ns(batch[arm], .99)}
                               for arm in samples})
        return {
            'kind': 'actual-local-CPU-fixed-16-lane-matched-typed-vs-aot-with-validation',
            'source_sha256': manifest['source_sha256'],
            'binary_sha256': manifest['binary_sha256'],
            'compile_ns': manifest['compile_ns'],
            'width': len(input_a), 'repetitions': repetitions,
            'repeats': repeats,
            'calls_per_arm': repeats * repetitions,
            'work': 'one exact Q24 dot plus identical policy/source lineage SHA per arm',
            'typed_vs_native_same_numeric_outputs': True,
            'benchmark_in_process_only': True,
            'native_excludes_double_python_reference_but_postcall_uses_separate_oracle': True,
            'scope_missing': ['model inference', 'network', 'real OS UI', 'GPU',
                              'MCP schema overhead', 'sandbox transfer',
                              'full effect authorization', 'energy'],
            'paired_runs': per_repeat,
            'combined': {name: {'p50_ns': percentile_ns(sample, .50),
                                'p95_ns': percentile_ns(sample, .95),
                                'p99_ns': percentile_ns(sample, .99)}
                         for name, sample in samples.items()},
            'speedup_claim_authorized': False,
            'external_effects': False,
            'disposition': 'HOLD_NO_GO', 'authority': 'DENY_ALL',
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repetitions', type=int, default=512)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise Denied('create-only cost receipt required')
    result = run_paired(repetitions=args.repetitions)
    raw = (json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'wb') as writer:
        writer.write(raw)
        writer.flush()
        os.fsync(writer.fileno())
    print(json.dumps({'sha256': sha(raw), 'calls_per_arm': result['calls_per_arm'],
                      'authority': result['authority'], 'disposition': result['disposition']}))


if __name__ == '__main__':
    main()
