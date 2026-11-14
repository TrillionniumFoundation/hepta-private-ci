"""Bounded read-only Bazel9 ExecLogEntry wire decoder; no commands are executed."""
import collections
import hashlib
import io
import json
from pathlib import Path
import time
import zipfile
import zstandard

ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / '1421-windows-release-execution.zip'
LIMIT = 256 * 1024**2
MAX_MESSAGE = 16 * 1024**2
START = time.monotonic()


def varint(data, offset):
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise ValueError('truncated protobuf varint')
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, offset
    raise ValueError('oversized protobuf varint')


def fields(data):
    output = collections.defaultdict(list)
    offset = 0
    while offset < len(data):
        tag, offset = varint(data, offset)
        number, wire = tag >> 3, tag & 7
        if wire == 0:
            value, offset = varint(data, offset)
        elif wire == 2:
            size, offset = varint(data, offset)
            if size > MAX_MESSAGE or offset + size > len(data):
                raise ValueError('invalid protobuf field bound')
            value = data[offset:offset + size]
            offset += size
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
            value = data[offset:offset + size]
            offset += size
        else:
            raise ValueError(f'unsupported wire type {wire}')
        output[number].append(value)
    return output


def first(message, key, default=None):
    return message.get(key, [default])[0]


def file_value(data):
    message = fields(data)
    digest = fields(first(message, 2, b''))
    size = first(digest, 2, 0)
    if size >= 2**63:
        raise ValueError('negative/oversized file length')
    return first(message, 1, b'').decode(), first(digest, 1, b'').decode(), size


raw_entries = []
entries = {}
unique = {}
counts = collections.Counter()
invocation = {}
bytes_read = 0
missing = []
with zipfile.ZipFile(ARCHIVE) as archive:
    infos = archive.infolist()
    assert len(infos) == 1 and infos[0].file_size < 16 * 1024**2
    with archive.open(infos[0]) as compressed:
        with zstandard.ZstdDecompressor().stream_reader(compressed) as decompressed:
            stream = io.BufferedReader(decompressed)
            while True:
                if time.monotonic() - START > 60 or counts['entries'] >= 1_000_000:
                    raise ValueError('analysis time/entry bound exceeded')
                first_byte = stream.read(1)
                if not first_byte:
                    break
                header = bytearray(first_byte)
                while header[-1] >= 128:
                    if len(header) >= 10:
                        raise ValueError('invalid message delimiter')
                    byte = stream.read(1)
                    if not byte:
                        raise ValueError('truncated delimiter')
                    header.extend(byte)
                size, _ = varint(header, 0)
                bytes_read += len(header) + size
                if size > MAX_MESSAGE or bytes_read > LIMIT:
                    raise ValueError('decompression/message bound exceeded')
                data = stream.read(size)
                if len(data) != size:
                    raise ValueError('truncated message')
                message = fields(data)
                raw_entries.append(message)
                counts['entries'] += 1
                identity = first(message, 1, 0)
                if 2 in message:
                    item = fields(message[2][0])
                    invocation = {'hash_function': first(item, 1, b'').decode(),
                                  'workspace': first(item, 2, b'').decode(),
                                  'id': first(item, 4, b'').decode()}
                elif 3 in message:
                    entries[identity] = [file_value(message[3][0])]
                    counts['file_entries'] += 1
                elif 4 in message:
                    item = fields(message[4][0])
                    directory = first(item, 1, b'').decode()
                    entries[identity] = [(directory + '/' + path, digest, size)
                                         for path, digest, size in map(file_value, item.get(2, []))]
                    counts['directory_entries'] += 1
                elif 5 in message:
                    entries[identity] = []
                elif 7 in message:
                    spawn = fields(message[7][0])
                    counts['spawns'] += 1
                    mnemonic = first(spawn, 8, b'').decode()
                    cacheable = bool(first(spawn, 14, 0))
                    success = first(spawn, 9, 0) == 0 and not first(spawn, 10, b'')
                    counts['cacheable_spawns'] += cacheable
                    if not cacheable or not success or mnemonic == 'TestRunner':
                        continue
                    counts['eligible_successful_non_test_spawns'] += 1
                    for encoded in spawn.get(6, []):
                        output = fields(encoded)
                        reference = first(output, 5, 0)
                        if not reference:
                            counts['invalid_output_paths'] += 1
                            continue
                        if reference not in entries:
                            missing.append(reference)
                            continue
                        for path, digest, size in entries[reference]:
                            if not digest and size:
                                raise ValueError('nonempty output has no digest')
                            if digest:
                                key = (digest, size)
                                unique.setdefault(key, {'digest': digest, 'bytes': size,
                                                        'path': path, 'mnemonic': mnemonic})

# Resolve observed spawn input dependencies by exec-root paths. This is an
# observed Windows execution subgraph, not a new Bazel analysis or Linux bound.
sets = {}; links = {}; spawns = []; producers = {}
def ints(values):
    out=[]
    for value in values:
        if isinstance(value,int): out.append(value); continue
        offset=0
        while offset<len(value):
            v,offset=varint(value,offset); out.append(v)
    return out
for m in raw_entries:
    ident=first(m,1,0)
    if 6 in m: sets[ident]=fields(m[6][0])
    elif 8 in m:
        v=fields(m[8][0]); links[first(v,2,b'').decode()]=first(v,1,b'').decode()
    elif 7 in m:
        sp=fields(m[7][0]); i=len(spawns); spawns.append(sp)
        for o in sp.get(6,[]):
            for path,_,_ in entries.get(first(fields(o),5,0),[]): producers[path]=i

def input_paths(sp):
    todo=[first(sp,4,0),first(sp,5,0)]; seen=set(); paths=set(); unsupported=set()
    while todo:
        sid=todo.pop()
        if not sid or sid in seen: continue
        seen.add(sid)
        if sid not in sets: unsupported.add(sid); continue
        v=sets[sid]; todo.extend(ints(v.get(4,[])))
        for ref in ints(v.get(5,[])):
            if ref not in entries: unsupported.add(ref)
            paths.update(x[0] for x in entries.get(ref,[]))
    return paths,unsupported
labels=sorted(set(first(s,7,b'').decode() for s in spawns))
selected=[l for l in labels if any(x in l for x in ['hepta-supervisor-robrix_control_projection','windows-sandbox-rs-helper_manifest','windows-sandbox-rs-unit-tests','core-unit-tests','queue-queue_service'])]
results=[]
selected_outputs={}
for label in selected:
    todo=[i for i,s in enumerate(spawns) if first(s,7,b'').decode()==label]; seen=set(); outputs={}; missing=set()
    while todo:
        i=todo.pop()
        if i in seen: continue
        seen.add(i); sp=spawns[i]
        paths,unknown=input_paths(sp); missing.update(unknown)
        for path in paths:
            linked=set()
            while path in links and path not in linked: linked.add(path); path=links[path]
            if path in producers: todo.append(producers[path])
        if first(sp,14,0) and not first(sp,9,0) and not first(sp,10,b'') and first(sp,8,b'')!=b'TestRunner':
            for o in sp.get(6,[]):
                for path,digest,size in entries.get(first(fields(o),5,0),[]):
                    if digest: outputs[(digest,size)]=path
    selected_outputs[label]=set(outputs)
    results.append({'label':label,'observed_spawns':len(seen),'unique_output_bytes':sum(k[1] for k in outputs),'unique_output_digests':len(outputs),'unresolved_entry_ids':sorted(missing)})
overlap=[]
for a, keys in selected_outputs.items():
    for b, other in selected_outputs.items():
        if a<b: overlap.append({'a':a,'b':b,'shared_output_bytes':sum(k[1] for k in keys & other),'union_output_bytes':sum(k[1] for k in keys | other)})
result={'pairwise_output_overlap':overlap,'archive_sha256':hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(),'targets':results,'limits':'Observed Windows release-action predecessor graph only. Excludes non-spawn output bytes, action/tree metadata; unresolved runfiles references reported. Not Linux occupancy or a full configured target closure.'}
(ROOT/'target-subgraph-sizes.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
