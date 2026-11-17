"""Decode frozen ProposedPlan byte data without recognizing input text.

Affine rows are integer data encodings for repeated records and state words.
No input classifier, parser state machine or reference implementation is used.
"""
import hashlib
import struct


INVALID, SHORT = 0xFFFFFFFF, 0xFFFFFFFE
ERRORS = (INVALID, SHORT)
WORD_MAX = (1 << 64) - 1
MAX_COMMANDS = 12288


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def decimal(value):
    require(type(value) is str and value.isascii() and value.isdecimal(),
            'word data is not unsigned ASCII decimal')
    number = int(value)
    require(0 <= number <= WORD_MAX and str(number) == value,
            'word data is not canonical u64')
    return number


def vector(start, step, index, count):
    require(type(start) is list and len(start) == count
            and type(step) is list and len(step) == count,
            'affine word vector has the wrong size')
    require(type(index) is int and 0 <= index < 12288, 'word index outside literal range')
    values = tuple(decimal(a) + index * decimal(b) for a, b in zip(start, step))
    require(all(value <= WORD_MAX for value in values), 'affine literal word overflows')
    return values


def pack(values):
    return struct.pack('<' + 'Q' * len(values), *values)


def unpack(data):
    require(len(data) % 8 == 0, 'unaligned word bytes')
    return struct.unpack('<' + 'Q' * (len(data) // 8), data)


def literal_bytes(value):
    require(type(value) is dict, 'byte literal is not an object')
    if set(value) == {'hex'}:
        return bytes.fromhex(value['hex'])
    require(set(value) == {'unit_hex', 'repeat'} and type(value['repeat']) is int
            and 0 <= value['repeat'] <= 1052672, 'unknown repeated byte literal')
    unit = bytes.fromhex(value['unit_hex'])
    require(len(unit) <= 16 and len(unit) * value['repeat'] <= 1052672,
            'literal byte data is too large')
    return unit * value['repeat']


def command_words(expressions):
    require(type(expressions) is list, 'command data is not a list')
    result = []
    for expression in expressions:
        if type(expression) is list:
            result.append(vector(expression, ['0'] * 4, 0, 4))
        else:
            require(type(expression) is dict
                    and set(expression) == {'start', 'step', 'repeat'},
                    'unknown command data expression')
            count = expression['repeat']
            require(type(count) is int and 1 <= count <= MAX_COMMANDS,
                    'command repeat is outside frozen range')
            result.extend(vector(expression['start'], expression['step'], index, 4)
                          for index in range(count))
        require(len(result) <= MAX_COMMANDS, 'too many literal commands')
    return result


def source_bytes(call, iteration):
    source = call['source']
    if set(source) == {'bytes'}:
        raw = literal_bytes(source['bytes'])
    else:
        require(set(source) == {'words', 'word_step', 'payload'},
                'unknown source data expression')
        raw = pack(vector(source['words'], source['word_step'], iteration, 11))
        raw += literal_bytes(source['payload'])
    require(len(raw) <= 4185, 'literal source is outside admitted test extent')
    return raw


def expected_prefix(call, iteration):
    expected = call['expected']
    returned = expected['return']
    require(type(returned) is int
            and (returned in ERRORS or 80 <= returned <= 393296),
            'unknown literal Core return')
    if returned in ERRORS:
        require(set(expected) == {'return'}, 'error expectation promises output')
        return b''
    require(set(expected) == {'return', 'header', 'header_step', 'commands'},
            'unknown successful output data expression')
    header = vector(expected['header'], expected['header_step'], iteration, 10)
    commands = command_words(expected['commands'])
    require(header[8] == len(commands) and header[9] == 0,
            'literal command count or reserved word differs')
    result = pack(header) + b''.join(pack(record) for record in commands)
    require(len(result) == returned, 'literal result has a different exact EOF')
    return result


def case_data(call, iteration):
    repeat = call['repeat']
    require(type(repeat) is int and 1 <= repeat <= 257
            and type(iteration) is int and 0 <= iteration < repeat,
            'call iteration is outside its frozen extent')
    raw, prefix = source_bytes(call, iteration), expected_prefix(call, iteration)
    for key, data in (('source_sha256s', raw), ('output_prefix_sha256s', prefix)):
        values = call[key]
        require(type(values) is list and len(values) == repeat
                and digest(data) == values[iteration], 'literal complete-byte hash differs')
    return raw, prefix
