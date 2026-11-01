"""Static x86 instruction inventory; supporting evidence, not a dtype theorem."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from recovery_eval import dump, seal

ROOT = Path(__file__).resolve().parent


def run(protocol_path, expected, output):
    if output.exists():
        raise ValueError('Receipt is create-only')
    protocol = json.loads(protocol_path.read_text())
    seal(protocol, protocol_path, expected)
    command = ['objdump', '--disassemble', '--demangle', '--no-show-raw-insn', str(ROOT/'recovered.so')]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    functions = {}
    current = None
    for line in result.stdout.splitlines():
        header = re.match(r'^[0-9a-f]+ <(.*)>:$', line)
        if header:
            current = header.group(1)
            functions[current] = []
        else:
            instruction = re.match(r'^\s*([0-9a-f]+):\s+(\S+)\s*(.*)$', line)
            if instruction and current is not None:
                functions[current].append({'address': instruction[1], 'mnemonic': instruction[2], 'operands': instruction[3]})
    selected = {name: lines for name, lines in functions.items() if 'hx::Pair' in name or name.startswith('hcsn_primitive')}
    arithmetic = re.compile(r'^v?(?:add|sub|mul|div|sqrt|max|min|round|fmadd\d*|fmsub\d*|fnmadd\d*|fnmsub\d*)(?:sd|pd)$')
    conversions = re.compile(r'^v?(?:cvtss2sd|cvtps2pd|cvtsd2ss|cvtpd2ps)$')
    violations, conversion_records, external_calls = [], [], []
    for name, lines in selected.items():
        for instruction in lines:
            if arithmetic.match(instruction['mnemonic']):
                violations.append({'function': name, **instruction})
            if conversions.match(instruction['mnemonic']):
                conversion_records.append({'function': name, **instruction})
            if instruction['mnemonic'].startswith(('call', 'jmp')) and '@plt' in instruction['operands']:
                external_calls.append({'function': name, **instruction})
    seal(protocol, protocol_path, expected)
    receipt = {
        'schema': 'hcsn.recovered-static-instruction-inventory.v1',
        'scope': 'Named Pair template functions and public primitive dispatch in this sealed x86 binary. This inventory is not a formal proof about all compiler optimizations, rounding behavior or external library internals.',
        'binary_sha256': protocol['binary_sha256'], 'protocol_sha256': expected,
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'command': command, 'objdump_version': subprocess.run(['objdump', '--version'], check=True, capture_output=True, text=True).stdout,
        'selected_function_count': len(selected), 'functions': {name: len(lines) for name, lines in selected.items()},
        'fp64_arithmetic_in_named_pair_functions': violations, 'float_double_conversions': conversion_records,
        'external_calls': external_calls,
        'inventory_gate_passed': bool(selected) and not violations,
        'transport_convention': 'Rounded FP32 outputs are promoted exactly to double for the C API; this transport does not increase financial arithmetic precision.',
    }
    dump(output, receipt)
    print(json.dumps({k: v for k, v in receipt.items() if k not in ('functions', 'external_calls')}, indent=2))
    return receipt['inventory_gate_passed']


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--protocol', type=Path, required=True)
    p.add_argument('--protocol-sha256', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    raise SystemExit(0 if run(a.protocol, a.protocol_sha256, a.output) else 1)
