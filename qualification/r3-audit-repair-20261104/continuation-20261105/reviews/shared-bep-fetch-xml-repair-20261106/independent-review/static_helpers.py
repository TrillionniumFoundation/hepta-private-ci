import hashlib

def identity(data):
    return {'bytes': len(data), 'git_blob': hashlib.sha1(
        b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest(),
        'sha256': hashlib.sha256(data).hexdigest()}

def merkle(leaves):
    nodes = {'': {}}
    for path, leaf in leaves.items():
        parts = path.split('/')
        assert all(p and p not in ('.', '..') for p in parts)
        for i in range(len(parts)-1):
            parent, child = '/'.join(parts[:i]), '/'.join(parts[:i+1])
            nodes.setdefault(parent, {})[parts[i]] = ('40000', child, True)
            nodes.setdefault(child, {})
        parent = '/'.join(parts[:-1])
        assert parts[-1] not in nodes[parent]
        nodes[parent][parts[-1]] = (leaf['mode'], leaf['sha'], False)
    hashes = {}
    for path in sorted(nodes, key=lambda p: (p.count('/'), bool(p)), reverse=True):
        body = b''
        for name, (mode, ref, is_tree) in sorted(nodes[path].items(),
                key=lambda kv: (kv[0] + ('/' if kv[1][2] else '')).encode()):
            sha = hashes[ref] if is_tree else ref
            body += mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(sha)
        hashes[path] = hashlib.sha1(b'tree ' + str(len(body)).encode() + b'\0' + body).hexdigest()
    return hashes[''], hashes
