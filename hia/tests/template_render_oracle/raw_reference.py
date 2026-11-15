"""Independent executable reading of the frozen render buffer contract."""
import struct

INVALID = 4294967295
SHORT = 4294967294
MAXIMUM = (1 << 64) - 1


def key_frame(names):
    body = b''.join(struct.pack('<Q', len(name)) + name for name in names)
    return struct.pack('<8Q', 1, 0, 64 + len(body), len(names), 0, 0, 0, 0) + body


def final_frame(variables, placeholders, segments):
    body = b''.join(struct.pack('<QQ', len(name), len(value)) + name + value for name, value in variables)
    body += b''.join(struct.pack('<Q', len(name)) + name for name in placeholders)
    body += b''.join(struct.pack('<QQ', kind, len(value)) + value for kind, value in segments)
    return struct.pack('<8Q', 1, 1, 64 + len(body), len(variables), len(placeholders), len(segments), 0, 0) + body


def reference(source, workspace, capacity):
    try:
        if len(workspace) != 32 or len(source) < 64:
            raise ValueError('frame extent')
        version, operation, r0, r1 = struct.unpack('<4Q', workspace)
        if version != 1 or operation not in (0, 1, 2) or r0 or r1:
            raise ValueError('request')
        version, kind, total, n, p, s, r0, r1 = struct.unpack_from('<8Q', source)
        if version != 1 or kind != int(operation != 0) or total != len(source) or r0 or r1:
            raise ValueError('header')
        if operation == 0 and (not n or p or s):
            raise ValueError('key shape')
        cursor = 64

        def number():
            nonlocal cursor
            if len(source) - cursor < 8:
                raise ValueError('number')
            value = struct.unpack_from('<Q', source, cursor)[0]
            cursor += 8
            return value

        def string(size):
            nonlocal cursor
            if size > len(source) - cursor:
                raise ValueError('string')
            offset = cursor
            value = source[cursor:cursor + size]
            value.decode('utf-8')
            cursor += size
            return value, offset

        variables = []
        for _ in range(n):
            name_size = number()
            value_size = number() if operation else 0
            name, offset = string(name_size)
            value, _ = string(value_size)
            variables.append((name, value, offset))
        placeholders = []
        for _ in range(p):
            name, offset = string(number())
            if placeholders and placeholders[-1][0] >= name:
                raise ValueError('strict placeholder order')
            placeholders.append((name, offset))
        segments = []
        for _ in range(s):
            kind, size = number(), number()
            if kind not in (1, 3):
                raise ValueError('segment kind')
            value, offset = string(size)
            segments.append((kind, value, offset))
        if cursor != len(source):
            raise ValueError('trailing bytes')
        error = origin = error_index = offset = size = 0
        payload = b''
        if operation == 0:
            name, _, candidate_offset = variables[-1]
            if any(prior[0] == name for prior in variables[:-1]):
                error, origin, error_index, offset, size = 1, 1, n - 1, candidate_offset, len(name)
        else:
            seen = {}
            for index, (name, value, name_offset) in enumerate(variables):
                if name in seen:
                    error, origin, error_index, offset, size = 1, 1, index, name_offset, len(name)
                    break
                seen[name] = value
            if not error:
                for index, (name, name_offset) in enumerate(placeholders):
                    if name not in seen:
                        error, origin, error_index, offset, size = 2, 2, index, name_offset, len(name)
                        break
            if not error:
                declared = {item[0] for item in placeholders}
                extras = [(name, index, name_offset) for index, (name, _, name_offset) in enumerate(variables) if name not in declared]
                if extras:
                    name, index, name_offset = min(extras)
                    error, origin, error_index, offset, size = 3, 1, index, name_offset, len(name)
            if not error:
                pieces = []
                total = 80
                for index, (kind, value, name_offset) in enumerate(segments):
                    if kind == 3 and value not in seen:
                        error, origin, error_index, offset, size = 2, 3, index, name_offset, len(value)
                        break
                    piece = value if kind == 1 else seen[value]
                    if len(piece) > MAXIMUM - total:
                        raise ValueError('output overflow')
                    total += len(piece)
                    pieces.append(piece)
                if not error:
                    payload = b''.join(pieces)
        required = 80 if error else 80 + len(payload)
        written = required if operation == 2 and not error else 80
        if capacity < written:
            return SHORT, b''
        header = struct.pack('<10Q', 1, operation, len(source), required, written, error, origin, error_index, offset, size)
        return 0, header + (payload if operation == 2 and not error else b'')
    except (ValueError, UnicodeError, struct.error):
        return INVALID, b''
