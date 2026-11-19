"""Independent, restricted source interpreter for the example-validation HIA assembly.

Not the HIA compiler, target VM, verifier, or native product. Rejects every
unrecognized syntax/instruction; uses source instructions rather than translating
its algorithm to Python.
"""
import json
import re
import struct
from pathlib import Path

BLOCK_RE = re.compile(r'^block ([A-Za-z_]\w*)\(([^()]*)\)$')
OP_RE = re.compile(r'^([A-Za-z_]\w*|_)\s*(?::(u32|u64|usize|bool))?\s*=\s*([\w.]+)\(([^()]*)\)(?:\s+(\{.*\}))?$')
BRANCH_RE = re.compile(r'^branch (\w+) (\w+)\(([^()]*)\) (\w+)\(([^()]*)\)$')
JUMP_RE = re.compile(r'^jump (\w+)\(([^()]*)\)$')
RET_RE = re.compile(r'^ret\((\w+)\)$')
MAX_U64 = (1 << 64) - 1


def _no_duplicate_json_fields(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError('duplicate constant field')
        obj[key] = value
    return obj


def _args(s):
    return [x.strip() for x in s.split(',')] if s.strip() else []


class Program:
    def __init__(self, source):
        lines = source.splitlines()
        if len(lines) < 5 or lines[0] != ('hia-asm.v1 hepta.hia.program.v9 '
                                             'codex_example_validation_continuation_candidate'):
            raise ValueError('unexpected HIA format/version')
        if lines[1] != ('fn f0(source:readbuf,output:mutbuf,workspace:mutbuf) -> (u32) '
                        'effects(read,write,trap) entry(entry)'):
            raise ValueError('unexpected function signature')
        if lines[-1].strip() != 'end':
            raise ValueError('missing program end')
        self.blocks = {}
        current = None
        for line in lines[2:-1]:
            m = BLOCK_RE.fullmatch(line)
            if m:
                name, params = m.groups()
                if name in self.blocks:
                    raise ValueError('duplicate block')
                parsed = []
                for item in _args(params):
                    n, t = item.split(':')
                    if t not in ('u64', 'u32', 'usize', 'bool', 'readbuf', 'mutbuf'):
                        raise ValueError('bad parameter type')
                    if not n.isidentifier() or n in {x for x, _ in parsed}:
                        raise ValueError('duplicate or invalid parameter')
                    parsed.append((n, t))
                self.blocks[name] = (parsed, [])
                current = name
                continue
            if current is None or not line.startswith('  '):
                raise ValueError('bad indentation or instruction')
            op = line.strip()
            if not any(p.fullmatch(op) for p in (OP_RE, BRANCH_RE, JUMP_RE, RET_RE)):
                raise ValueError('unsupported instruction: ' + op)
            self.blocks[current][1].append(op)
        if 'entry' not in self.blocks:
            raise ValueError('no entry block')
        if self.blocks['entry'][0] != [
            ('source', 'readbuf'), ('output', 'mutbuf'), ('workspace', 'mutbuf')
        ]:
            raise ValueError('entry block ABI mismatch')
        for name, (params, operations) in self.blocks.items():
            if not operations or not any(x.startswith(('branch ', 'jump ', 'ret(')) for x in operations[-1:]):
                raise ValueError('missing terminator: ' + name)
            for op in operations:
                m = BRANCH_RE.fullmatch(op)
                targets = [(m.group(2), _args(m.group(3))), (m.group(4), _args(m.group(5)))] if m else []
                j = JUMP_RE.fullmatch(op)
                if j:
                    targets.append((j.group(1), _args(j.group(2))))
                for target, actual in targets:
                    if target not in self.blocks or len(actual) != len(self.blocks[target][0]):
                        raise ValueError('unbound target or wrong block arity')
        self._check_static_types()

    def _check_static_types(self):
        """Reject unreachable malformed ops and ill-typed CFG edges before execution.

        This checks only the restricted source-VM dialect, not compiler semantics.
        """
        arities = {'const': 0, 'buffer.len': 1, 'buffer.load.u64.le': 2,
                   'buffer.store.u64.le': 3, 'int.add.checked': 2,
                   'compare.eq': 2, 'compare.lt': 2, 'compare.le': 2,
                   'compare.ge': 2, 'bool.and': 2}
        for block_name, (params, operations) in self.blocks.items():
            types = dict(params)
            for index, instruction in enumerate(operations):
                opmatch = OP_RE.fullmatch(instruction)
                if opmatch:
                    dest, result_type, operator, raw, literal = opmatch.groups()
                    names = _args(raw)
                    if operator not in arities or len(names) != arities[operator]:
                        raise ValueError('unsupported operation or arity')
                    if any(name not in types for name in names):
                        raise ValueError('undefined SSA input')
                    argument_types = [types[name] for name in names]
                    if operator == 'const':
                        if literal is None or result_type not in ('u32', 'u64', 'usize'):
                            raise ValueError('invalid constant type')
                        value = json.loads(literal, object_pairs_hook=_no_duplicate_json_fields)
                        if not isinstance(value, dict) or set(value) != {'value'} or type(value['value']) is not int:
                            raise ValueError('non-integer constant')
                        limit = (1 << (32 if result_type == 'u32' else 64)) - 1
                        if not 0 <= value['value'] <= limit:
                            raise ValueError('constant outside declared type')
                    else:
                        if literal is not None:
                            raise ValueError('unexpected literal')
                        expected = {
                            'buffer.len': (('readbuf', 'mutbuf'),),
                            'buffer.load.u64.le': (('readbuf',), ('usize',)),
                            'buffer.store.u64.le': (('mutbuf',), ('usize',), ('u64',)),
                            'int.add.checked': (('u64',), ('u64',)),
                            'bool.and': (('bool',), ('bool',)),
                        }.get(operator)
                        if expected is not None and any(t not in allowed for t, allowed in zip(argument_types, expected)):
                            raise ValueError('invalid operand type')
                        if operator.startswith('compare.') and (
                            len(set(argument_types)) != 1 or
                            argument_types[0] not in ('u64', 'u32', 'usize')
                        ):
                            raise ValueError('invalid compare operands')
                        produced = ('usize' if operator == 'buffer.len' else
                                    'u64' if operator in ('int.add.checked', 'buffer.load.u64.le') else
                                    'bool' if operator.startswith('compare.') or operator == 'bool.and' else None)
                        if result_type != produced:
                            raise ValueError('wrong SSA result type')
                    if operator == 'buffer.store.u64.le':
                        if dest != '_' or result_type is not None:
                            raise ValueError('store must discard result without type annotation')
                    elif dest == '_' or dest in types:
                        raise ValueError('discarded or redefined SSA result')
                    else:
                        types[dest] = result_type
                    continue
                if index != len(operations) - 1:
                    raise ValueError('terminator must be final')
                branch = BRANCH_RE.fullmatch(instruction)
                jump = JUMP_RE.fullmatch(instruction)
                ret = RET_RE.fullmatch(instruction)
                if branch:
                    if types.get(branch.group(1)) != 'bool':
                        raise ValueError('invalid branch condition')
                    edges = [(branch.group(2), _args(branch.group(3))),
                             (branch.group(4), _args(branch.group(5)))]
                elif jump:
                    edges = [(jump.group(1), _args(jump.group(2)))]
                elif ret:
                    if types.get(ret.group(1)) != 'u32':
                        raise ValueError('invalid return type')
                    edges = []
                else:
                    raise ValueError('not a known terminator')
                for target, names in edges:
                    if target not in self.blocks:
                        raise ValueError('undefined block')
                    if [types.get(name) for name in names] != [
                            declared for _, declared in self.blocks[target][0]]:
                        raise ValueError('wrong block argument types')

    def execute(self, source, output_capacity=40, workspace_capacity=0):
        output = bytearray([0xA5] * output_capacity)
        workspace = bytearray(workspace_capacity)
        current, values = 'entry', [bytes(source), output, workspace]
        visits = 0
        while visits < 100:
            visits += 1
            params, operations = self.blocks[current]
            env = dict(zip([name for name, _ in params], values))
            if len(env) != len(values):
                raise ValueError('arity mismatch')
            next_target = None
            for instruction in operations:
                m = OP_RE.fullmatch(instruction)
                if m:
                    dest, ty, op, args_raw, literal = m.groups()
                    args = [env[a] for a in _args(args_raw)]
                    if op == 'const':
                        if args or literal is None:
                            raise ValueError('bad constant')
                        value = json.loads(literal)['value']
                    elif op == 'buffer.len':
                        value = len(args[0])
                    elif op == 'compare.eq':
                        value = args[0] == args[1]
                    elif op == 'compare.ge':
                        value = args[0] >= args[1]
                    elif op == 'compare.le':
                        value = args[0] <= args[1]
                    elif op == 'compare.lt':
                        value = args[0] < args[1]
                    elif op == 'bool.and':
                        value = args[0] and args[1]
                    elif op == 'int.add.checked':
                        value = args[0] + args[1]
                        if value > MAX_U64:
                            raise OverflowError('checked add overflow')
                    elif op == 'buffer.load.u64.le':
                        buf, offset = args
                        if offset < 0 or offset + 8 > len(buf):
                            raise ValueError('out of bounds load')
                        value = struct.unpack_from('<Q', buf, offset)[0]
                    elif op == 'buffer.store.u64.le':
                        buf, offset, value = args
                        if offset < 0 or offset + 8 > len(buf):
                            raise ValueError('out of bounds store')
                        struct.pack_into('<Q', buf, offset, value)
                        value = None
                    else:
                        raise ValueError('unknown operation ' + op)
                    if dest != '_':
                        if dest in env:
                            raise ValueError('SSA redefinition')
                        if ty == 'bool' and not isinstance(value, bool):
                            raise ValueError('wrong boolean result type')
                        if ty in ('u32','u64','usize') and (not isinstance(value,int) or value < 0 or value > ((1 << (32 if ty == 'u32' else 64)) - 1)):
                            raise ValueError('wrong integer result type')
                        env[dest] = value
                    continue
                branch = BRANCH_RE.fullmatch(instruction)
                if branch:
                    selector = env[branch.group(1)]
                    if not isinstance(selector,bool):
                        raise ValueError('non-bool branch')
                    next_target = (branch.group(2),branch.group(3)) if selector else (branch.group(4),branch.group(5))
                    break
                jump = JUMP_RE.fullmatch(instruction)
                if jump:
                    next_target = jump.group(1),jump.group(2)
                    break
                ret = RET_RE.fullmatch(instruction)
                if ret:
                    status = env[ret.group(1)]
                    return status, bytes(output), visits
                raise ValueError('unknown statement')
            if next_target is None:
                raise ValueError('unterminated block')
            current, arg_str = next_target
            values = [env[x] for x in _args(arg_str)]
        raise ValueError('too many block visits')


def encode(mode, total, index, misses, hit, version=1):
    return struct.pack('<6Q', version, mode, total, index, misses, hit)


def interpret_event(vm, mode, total, index, misses, hit):
    status, output, _ = vm.execute(encode(mode, total, index, misses, hit))
    if status != 0:
        return None
    return struct.unpack_from('<4Q', output)

if __name__ == '__main__':
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('program')
    a=p.parse_args()
    vm=Program(Path(a.program).read_text())
    print({'blocks':len(vm.blocks), 'sample':interpret_event(vm,1,2,1,1,0)})
