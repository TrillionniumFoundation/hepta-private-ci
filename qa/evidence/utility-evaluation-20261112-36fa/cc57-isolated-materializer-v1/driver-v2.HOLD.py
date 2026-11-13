#!/usr/bin/env python3
"""Create one independent exact cc57 source; preserve the damaged original.

HOLD until Root's exact config/request approval. No Cargo, tests, source repair,
remote refs, network, history walk, fsck, retry, or rollback.
"""
from __future__ import annotations
import base64, datetime, fcntl, gzip, hashlib, io, json, os, pathlib, select
import shutil, signal, stat, struct, subprocess, sys, time, traceback, types, zlib

SOURCE = pathlib.Path('/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1')
TARGET = pathlib.Path('/home/qian-qi/hepta-utility-36fa-native-cc57-isolated-v1')
CONTROL = pathlib.Path('/home/qian-qi/hepta-utility-36fa-evidence/cc57-isolated-materialization-v1')
OUT = CONTROL / 'run'
CONFIG = CONTROL / 'APPROVED_CONFIG.json'
PACKET = CONTROL / 'MATERIALIZATION_PACKET.json'
INVENTORY_MODULE = pathlib.Path('/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/inventory-driver-v2.py')
COORDINATION = pathlib.Path('/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/SOURCE_COORDINATION.lock')
GIT = '/usr/bin/git'
HEAD = 'cc57c7198db6293ccca562253c42fffbe2a04633'
TREE = 'b7b357c07b5539769a068c6b9b009629f5612d1e'
PARENT = '246d8cb614770252ee42029a5c014f2a4904176a'
LEAVES = 15188
ACTION_SECONDS = 600
RECORD_SECONDS = 180
PACKET_PIN = {'bytes':13764,'sha256':'b2a62c45873fe6c37257df5561accd9d30dcf2d7ca969de6968fec7ac1e3acc3','git_blob':'06503652a2895120daf8b66e42b3a01cefeaf4fb'}
INVENTORY_MODULE_PIN = {'bytes':22946,'sha256':'20c11034146f6739dd24e9d7e33b94ee909754b07ce6295c242c842c5f3c40b2','git_blob':'51181866cbbb6e0176aab04117efffa8b6792b31'}
GIT_PIN = {'bytes':4066232,'sha256':'eb54b535467e0975c1284d4c4d08eea779aeb248a5d34b02e2ee171382e22201'}
artifacts = []
commands = []
inputs = {}
intents = []
deadline = None
cfg = packet = complete = inventory_module = None
source_before = old_git_before = None
new_source_before = new_git_before = new_metadata_before = None
source_reader = target_reader = journal_stream = None
lock_fd = None
target_created = False
missing_paths = set()
object_index = raw_trees = raw_commits = parent_rows = None
pack_path = None
result = {'format':'hepta-isolated-cc57-materialization-result-v1','status':'HOLD','source_repo':str(SOURCE),'destination_repo':str(TARGET),'source_commit':HEAD,'source_tree':TREE,'parents':[PARENT],'qualification':False,'new_repo_created':False,'old_source_writes':False,'remote_ref_updates':False,'cargo_or_formatter_started':False,'test_commands_dispatched':0,'dependency_installation_started':False,'automatic_retry':False,'rollback':False,'action_completed':False,'final_audits':[]}

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def check(condition, message):
    if not condition:
        raise ValueError(message)

def sha256(raw):
    return hashlib.sha256(raw).hexdigest()

def oid(kind, raw):
    return hashlib.sha1(kind.encode()+b' '+str(len(raw)).encode()+b'\0'+raw).hexdigest()

def nodup(pairs):
    value = {}
    for key, item in pairs:
        check(key not in value, 'duplicate JSON key: '+key)
        value[key] = item
    return value

def parse(raw):
    return json.loads(raw.decode('utf-8'), object_pairs_hook=nodup)

def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',',':'))+'\n').encode()

def pin(raw, expected, label):
    check(len(raw)==expected['bytes'] and sha256(raw)==expected['sha256'], 'byte identity: '+label)
    if 'git_blob' in expected:
        check(oid('blob',raw)==expected['git_blob'], 'Git blob identity: '+label)
    return raw

def real_directory(path):
    path = pathlib.Path(path)
    check(path.is_absolute(), 'absolute directory required')
    current = pathlib.Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        s = current.lstat()
        check(stat.S_ISDIR(s.st_mode) and not stat.S_ISLNK(s.st_mode), 'non-real directory: '+str(current))

def regular_read(path, maximum=40000000, expected_uid=None):
    path = pathlib.Path(path)
    if expected_uid is None:
        expected_uid=os.getuid()
    real_directory(path.parent)
    fd = os.open(path, os.O_RDONLY|os.O_NOFOLLOW)
    try:
        a = os.fstat(fd)
        check(stat.S_ISREG(a.st_mode) and a.st_nlink==1 and a.st_uid==expected_uid, 'regular owned single-link input: '+str(path))
        check(a.st_size<=maximum, 'read ceiling')
        chunks = []
        total = 0
        while True:
            chunk = os.read(fd, min(1048576, maximum+1-total))
            if not chunk:
                break
            total += len(chunk)
            check(total<=maximum, 'read ceiling exceeded')
            chunks.append(chunk)
        b = b''.join(chunks)
        z = os.fstat(fd)
        fields = ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns','st_mode','st_uid','st_nlink')
        check(all(getattr(a,k)==getattr(z,k) for k in fields) and len(b)==a.st_size, 'unstable input: '+str(path))
        return b
    finally:
        os.close(fd)

def read_input(path, expected):
    raw = pin(regular_read(path), expected, str(path))
    inputs[str(path)] = {k:expected[k] for k in ('bytes','sha256','git_blob') if k in expected}
    return raw

def write(name, raw):
    path = OUT/name
    check(path.parent==OUT and path.name==name, 'one-level output required')
    fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd,'wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    check(regular_read(path,max(40000000,len(raw)))==raw, 'output readback mismatch')
    row = {'name':name,'bytes':len(raw),'sha256':sha256(raw),'git_blob':oid('blob',raw)}
    artifacts.append(row)
    return row

def jwrite(name, value):
    return write(name, encoded(value))

def gzrecord(name, raw):
    gz = gzip.compress(raw,mtime=0)
    check(gzip.decompress(gz)==raw,'gzip roundtrip')
    row = write(name+'.gz',gz)
    row.update(raw_bytes=len(raw),raw_sha256=sha256(raw),raw_git_blob=oid('blob',raw),parts=[])
    for n, off in enumerate(range(0,len(gz),262144),1):
        block = gz[off:off+262144]
        part = write(name+'.gz.part-%03d.b64'%n,base64.b64encode(block)+b'\n')
        part.update(decoded_offset=off,decoded_bytes=len(block),decoded_sha256=sha256(block))
        row['parts'].append(part)
    return row

def event(kind, **details):
    row = {'at':now(),'event':kind,**details}
    print(json.dumps(row,sort_keys=True),flush=True)
    return row

def remaining(maximum=120):
    value = deadline-time.monotonic()
    check(value>0,'operation budget exhausted')
    return min(maximum,value)

def alarm_handler(signum, frame):
    raise TimeoutError('exact source-advance phase deadline exhausted')

def disarm():
    signal.setitimer(signal.ITIMER_REAL,0)

def arm_if_remaining():
    value=deadline-time.monotonic()
    if value<=0:
        raise TimeoutError('exact source-advance phase deadline exhausted after owned command cleanup')
    signal.setitimer(signal.ITIMER_REAL,value)

def active_build_processes():
    active=[];unreadable=[]
    for item in pathlib.Path("/proc").iterdir():
        if not item.name.isdecimal():continue
        try:
            name=(item/"comm").read_text().strip()
            if name not in ("cargo","cargo-clippy","clippy-driver","rustc","rustfmt","just","uv","ruff"):
                continue
            status=(item/"status").read_text()
            uid_line=next(x for x in status.splitlines() if x.startswith("Uid:"))
            uid=int(uid_line.split()[1])
            if uid!=os.getuid():continue
            active.append({"pid":int(item.name),"comm":name,"uid":uid})
        except FileNotFoundError:
            continue
        except (OSError,StopIteration,ValueError) as error:
            unreadable.append({"pid":int(item.name),"error":type(error).__name__})
    return {"active_matching_processes":active,"unreadable_matching_processes":unreadable,
            "scope":"Same-UID process names only; no environment/argument values or credentials inspected; no processes killed."}

def parse_index(raw):
    check(raw[:4]==b'DIRC' and struct.unpack('>I',raw[4:8])[0]==2,'original version-2 index')
    check(hashlib.sha1(raw[:-20]).digest()==raw[-20:],'complete index trailing checksum')
    count = struct.unpack('>I',raw[8:12])[0]
    position = 12
    entries = {}
    for _ in range(count):
        start = position
        check(position+62<=len(raw)-20,'index entry bound')
        fields = struct.unpack('>10I20sH',raw[position:position+62])
        flags = fields[-1]
        check(not flags&0x4000,'unexpected extended v2 flags')
        end = raw.index(b'\0',position+62,len(raw)-20)
        path = raw[position+62:end].decode('utf-8')
        position = start+((end+1-start+7)//8)*8
        check(path not in entries and not flags&0x3000,'duplicate/unmerged index path')
        check(raw[end:position]==b'\0'*(position-end),'index entry padding')
        entries[path] = {'raw':raw[start:position],'stat':fields[:10],
                         'mode':format(fields[6],'o'),'sha':fields[10].hex(),'flags':flags}
    extensions = []
    while position<len(raw)-20:
        check(position+8<=len(raw)-20,'index extension bound')
        label = raw[position:position+4]
        size = struct.unpack('>I',raw[position+4:position+8])[0]
        end = position+8+size
        check(end<=len(raw)-20,'index extension payload bound')
        extensions.append({'name':label.decode('ascii'),'bytes':size,'raw':raw[position:end]})
        position = end
    check(count==LEAVES and len(entries)==LEAVES and position==len(raw)-20,'complete original index population')
    return entries,extensions

def pack_entry_header(kind,size):
    type_id={"commit":1,"tree":2,"blob":3}[kind]
    first=(type_id<<4)|(size & 15);size >>= 4
    out=bytearray()
    if size:first |= 128
    out.append(first)
    while size:
        byte=size & 127;size >>= 7
        if size:byte |= 128
        out.append(byte)
    return bytes(out)

def stat_identity(value):
    return {key: getattr(value, key) for key in ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns')}

def identity(raw):
    return {'bytes': len(raw), 'sha256': sha256(raw), 'git_blob': oid('blob', raw)}

def retained_pin(path, expected):
    raw = read_input(path, expected)
    check(pathlib.Path(path).lstat().st_size == len(raw), 'retained input exact size')
    return raw

def check_processes(label):
    observed = active_build_processes()
    jwrite(label + '.processes.json', observed)
    check(not observed['active_matching_processes'] and not observed['unreadable_matching_processes'], 'original global same-UID build/formatter guard')

def mutation_intent(kind, **detail):
    remaining()
    row = {'ordinal': len(intents) + 1, 'at': now(), 'kind': kind, 'actual_terminal': 'unknown_not_observed', **detail}
    jwrite('mutation-%03d.intent.json' % row['ordinal'], row)
    intents.append(row)
    return row

def command(repo, arguments, data=None, mutation=False, stdin_path=None):
    check(repo in (SOURCE, TARGET), 'only the fixed source and new destination Git directories')
    check(not mutation or (repo == TARGET and target_created), 'all Git mutations are confined to the new destination')
    check(not (data is not None and stdin_path is not None), 'one stdin source')
    argv = [GIT, '--no-optional-locks', '-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false', '-c', 'diff.autoRefreshIndex=false', '-c', 'core.logAllRefUpdates=false', '-C', str(repo), *arguments]
    row = {'argv': argv, 'started_at': now(), 'actual_terminal': 'unknown_not_observed', 'writes_new_repo_only': mutation}
    commands.append(row)
    prefix = 'command-%03d' % len(commands)
    jwrite(prefix + '.intent.json', row)
    if data is not None:
        row['stdin'] = write(prefix + '.stdin', data)
    handle = process = None
    disarm()
    try:
        budget = remaining()
        if stdin_path is not None:
            handle = open(stdin_path, 'rb')
        process = subprocess.Popen(argv, cwd=repo, stdin=handle if handle is not None else (subprocess.PIPE if data is not None else subprocess.DEVNULL), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            stdout, stderr = process.communicate(data, timeout=budget)
            row.update(actual_terminal='observed', returncode=process.returncode, timed_out=False)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            row.update(actual_terminal='observed', returncode=process.returncode, timed_out=True)
            row['stdout'] = write(prefix + '.stdout', stdout)
            row['stderr'] = write(prefix + '.stderr', stderr)
            raise
        row['stdout'] = write(prefix + '.stdout', stdout)
        row['stderr'] = write(prefix + '.stderr', stderr)
        check(process.returncode == 0, 'normal exact Git command: ' + repr(arguments))
        return stdout
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        if handle is not None:
            handle.close()
        row['finished_at'] = now()
        jwrite(prefix + '.terminal.json', row)
        arm_if_remaining()

class ObjectReader:
    def __init__(self, repo, label):
        remaining()
        self.repo = repo
        self.label = label
        self.process = None
        self.closed = False
        self.error_fd = os.memfd_create('hepta-object-reader-stderr', os.MFD_CLOEXEC)
        self.row = {'argv': [GIT, '--no-optional-locks', '-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false', '-C', str(repo), 'cat-file', '--batch'], 'started_at': now(), 'actual_terminal': 'unknown_not_observed', 'requested_objects': 0, 'fully_verified_objects': 0}
        commands.append(self.row)
        self.prefix = 'command-%03d' % len(commands)
        jwrite(self.prefix + '.intent.json', self.row)
        disarm()
        try:
            remaining()
            self.process = subprocess.Popen(self.row['argv'], cwd=repo, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.error_fd, bufsize=0)
            arm_if_remaining()
        except BaseException:
            disarm()
            if self.process is not None:
                if self.process.poll() is None:
                    self.process.kill()
                self.row['cleanup_returncode'] = self.process.wait(timeout=5)
                self.process.stdin.close()
                self.process.stdout.close()
            os.close(self.error_fd)
            self.closed = True
            self.row['finished_at'] = now()
            jwrite(self.prefix + '.terminal.json', self.row)
            raise

    def exact(self, count):
        blocks = []
        while count:
            check(select.select([self.process.stdout], [], [], remaining())[0], 'bounded original object stream')
            raw = os.read(self.process.stdout.fileno(), min(count, 1048576))
            check(bool(raw), 'complete original object body')
            blocks.append(raw)
            count -= len(raw)
        return b''.join(blocks)

    def get(self, key, expected):
        remaining()
        self.row['requested_objects'] += 1
        self.process.stdin.write((key + '\n').encode())
        self.process.stdin.flush()
        header = b''
        while not header.endswith(b'\n'):
            check(len(header) < 160, 'bounded original object header')
            header += self.exact(1)
        check(header == (key + ' ' + expected['type'] + ' ' + str(expected['bytes']) + '\n').encode(), 'exact existing object type/size, no missing substitute')
        raw = self.exact(expected['bytes'])
        check(self.exact(1) == b'\n', 'object delimiter')
        check(oid(expected['type'], raw) == key and sha256(raw) == expected['sha256'], 'complete original object hash')
        self.row['fully_verified_objects'] += 1
        return raw

    def close(self):
        if self.closed:
            return
        disarm()
        try:
            self.process.stdin.close()
            check(select.select([self.process.stdout], [], [], remaining())[0], 'bounded object final EOF')
            check(os.read(self.process.stdout.fileno(), 1) == b'', 'no extra original object output')
            self.row.update(returncode=self.process.wait(timeout=remaining()), actual_terminal='observed', timed_out=False)
            check(self.row['returncode'] == 0, 'object reader normal terminal')
        finally:
            if self.process.poll() is None:
                self.process.kill()
                self.row['cleanup_returncode'] = self.process.wait(timeout=5)
            self.process.stdout.close()
            size = os.fstat(self.error_fd).st_size
            os.lseek(self.error_fd, 0, os.SEEK_SET)
            errors = os.read(self.error_fd, min(size + 1, 65537))
            os.close(self.error_fd)
            self.row['stderr'] = write(self.prefix + '.stderr', errors)
            self.row['stderr_complete'] = len(errors) == size
            self.row['finished_at'] = now()
            self.closed = True
            jwrite(self.prefix + '.terminal.json', self.row)
            arm_if_remaining()

    def abort(self):
        if self.closed:
            return
        disarm()
        try:
            if self.process.poll() is None:
                self.process.kill()
            self.row['cleanup_returncode'] = self.process.wait(timeout=5)
            self.row['cleanup_scope'] = 'only this materializer own read-only Git child'
        finally:
            self.process.stdin.close()
            self.process.stdout.close()
            size = os.fstat(self.error_fd).st_size
            os.lseek(self.error_fd, 0, os.SEEK_SET)
            errors = os.read(self.error_fd, min(size + 1, 65537))
            os.close(self.error_fd)
            self.row['stderr'] = write(self.prefix + '.stderr', errors)
            self.row['stderr_complete'] = len(errors) == size
            self.row['finished_at'] = now()
            self.closed = True
            jwrite(self.prefix + '.terminal.json', self.row)
            arm_if_remaining()

def tree_objects(rows):
    root = {}
    trees = {}
    for row in rows:
        path = pathlib.PurePosixPath(row['path'])
        check(not path.is_absolute() and all(x not in ('', '.', '..') and x.lower() != '.git' for x in path.parts), 'safe canonical path')
        node = root
        for part in path.parts[:-1]:
            node = node.setdefault(part, {})
            check(isinstance(node, dict), 'canonical directory/file disjoint')
        check(path.name not in node, 'unique canonical path')
        node[path.name] = (row['index_mode'], row['working_blob'])
    def build(node):
        entries = []
        for name, value in node.items():
            mode, value = ('40000', build(value)) if isinstance(value, dict) else value
            raw_name = name.encode()
            entries.append((raw_name + (b'/' if mode == '40000' else b''), mode.encode() + b' ' + raw_name + b'\0' + bytes.fromhex(value)))
        raw = b''.join(x[1] for x in sorted(entries))
        key = oid('tree', raw)
        check(key not in trees or trees[key] == raw, 'same original tree bytes')
        trees[key] = raw
        return key
    return build(root), trees

def raw_commit_fields(raw):
    fields = raw.split(b'\n\n', 1)[0].splitlines()
    trees = [x[5:].decode() for x in fields if x.startswith(b'tree ')]
    parents = [x[7:].decode() for x in fields if x.startswith(b'parent ')]
    check(len(trees) == 1, 'one authentic commit tree')
    return trees[0], parents

def expected_graphs():
    global object_index, raw_trees, raw_commits, parent_rows
    current_rows = complete['files']
    parent_rows = {x['path']: dict(x) for x in current_rows}
    for change in packet['parent_snapshot']['changes_from_current']:
        row = parent_rows[change['path']]
        check(row['index_mode'] == change['mode'] and identity_projection(row) == change['current'], 'actual parent delta current preimage')
        row.update(index_blob=change['parent']['git_blob'], working_blob=change['parent']['git_blob'], bytes=change['parent']['bytes'], sha256=change['parent']['sha256'])
    object_index = {}
    raw_trees = {}
    for label, rows in [('current', current_rows), ('parent_snapshot', list(parent_rows.values()))]:
        expected = packet[label]
        tree, bodies = tree_objects(rows)
        check(tree == expected['tree'] and len(rows) == LEAVES, 'two exact complete snapshot roots')
        for key, body in bodies.items():
            check(key not in raw_trees or raw_trees[key] == body, 'union tree body equality')
            raw_trees[key] = body
        for row in rows:
            meta = {'type': 'blob', 'bytes': row['bytes'], 'sha256': row['sha256']}
            key = row['working_blob']
            check(key not in object_index or object_index[key] == meta, 'union blob identity equality')
            object_index[key] = meta
    for key, raw in raw_trees.items():
        object_index[key] = {'type': 'tree', 'bytes': len(raw), 'sha256': sha256(raw)}
    raw_commits = {}
    for item in packet['raw_commits']:
        raw = base64.b64decode(item['raw_base64'], validate=True)
        check(item['type'] == 'commit' and len(raw) == item['bytes'] and sha256(raw) == item['sha256'] and oid('commit', raw) == item['sha'], 'authentic original commit, no reserialization')
        expected = packet['current'] if item['sha'] == HEAD else packet['parent_snapshot']
        check(item['sha'] == expected['commit'] and raw_commit_fields(raw) == (expected['tree'], expected['parents']), 'original commit tree/ordered parents')
        raw_commits[item['sha']] = raw
        object_index[item['sha']] = {'type': 'commit', 'bytes': len(raw), 'sha256': sha256(raw)}
    counts = {kind: sum(x['type'] == kind for x in object_index.values()) for kind in ('blob', 'tree', 'commit')}
    check(len(object_index) == 16449 and counts == {'blob': 14615, 'tree': 1832, 'commit': 2}, 'exact two-snapshot union, not complete ancestry')
    result['object_scope'] = {'complete_snapshots': [HEAD, PARENT], 'objects': len(object_index), 'counts': counts, 'complete_ancestry': False, 'unmaterialized_parent_boundary': '9c4a11f61d30e9cc352bf44d56c98909d202a55d', 'recursive_history_walk': False, 'network': False}
    gzrecord('EXPECTED_OBJECTS.json', encoded([{'sha': key, **object_index[key]} for key in sorted(object_index)]))

def identity_projection(row):
    return {'bytes': row['bytes'], 'sha256': row['sha256'], 'git_blob': row['working_blob']}

def physical_paths(root):
    paths = set()
    for directory, children, files in os.walk(root, followlinks=False):
        remaining()
        parent = pathlib.Path(directory)
        if parent == root:
            children[:] = [name for name in children if name != '.git']
        for name in children[:]:
            path = parent / name
            if path.is_symlink():
                paths.add(path.relative_to(root).as_posix())
                children.remove(name)
        paths.update((parent / name).relative_to(root).as_posix() for name in files)
    return paths

def source_leaf(row):
    path = SOURCE / row['path']
    real_directory(path.parent)
    before = path.lstat()
    check(before.st_uid == os.getuid() and before.st_nlink == 1, 'owned independent original physical leaf')
    check(stat.S_IMODE(before.st_mode) == row['permissions'], 'original physical permissions retained')
    if row['kind'] == 'symlink':
        check(stat.S_ISLNK(before.st_mode), 'original symbolic link type')
        raw = os.fsencode(os.readlink(path))
    else:
        check(row['kind'] == 'file' and stat.S_ISREG(before.st_mode), 'original regular file type')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            check(stat_identity(os.fstat(stream.fileno())) == stat_identity(before), 'opened original leaf identity')
            raw = stream.read(row['bytes'] + 1)
            check(stat_identity(os.fstat(stream.fileno())) == stat_identity(before), 'stable full original leaf read')
    check(stat_identity(path.lstat()) == stat_identity(before), 'stable original leaf directory entry')
    pin(raw, identity_projection(row), 'original complete source leaf ' + row['path'])
    return raw, stat_identity(before)

def source_physical(label):
    expected = {x['path'] for x in complete['files']} - missing_paths
    check(physical_paths(SOURCE) == expected, 'exact 15181 existing leaves and only the seven known missing paths')
    audit = []
    native_rows = []
    for row in complete['files']:
        remaining()
        if row['path'] in missing_paths:
            check(not os.path.lexists(SOURCE / row['path']), 'known missing path remains absent, never restored in old source')
            native_rows.append({'path': row['path'], 'missing': True})
            audit.append({'path': row['path'], 'missing': True})
            continue
        raw, observed = source_leaf(row)
        audit.append({'path': row['path'], 'identity': identity(raw), 'stable_stat': observed})
        native_rows.append({'path': row['path'], 'mode': row['index_mode'], 'bytes': len(raw), 'sha256': sha256(raw), 'blob': row['working_blob']})
    native = json.dumps(sorted(native_rows, key=lambda row: os.fsencode(row['path'])), sort_keys=True, separators=(',', ':')).encode()
    pin(native, packet['expected_old_native_inventory'], 'preserved actually missing old source snapshot')
    data = encoded(audit)
    gzrecord(label + '.old-physical.json', data)
    return {'records': audit, 'raw_identity': identity(data), 'native_inventory': identity(native), 'present': len(expected), 'missing': sorted(missing_paths)}

def old_git_state(label):
    rows = []
    for fixed in packet['old_git']['files']:
        raw = pin(regular_read(fixed['path']), fixed['identity'], 'old raw Git state retained')
        current = pathlib.Path(fixed['path']).lstat()
        observed = {'device': current.st_dev, 'inode': current.st_ino, 'mode': current.st_mode, 'uid': current.st_uid, 'gid': current.st_gid, 'nlink': current.st_nlink, 'size': current.st_size, 'mtime_ns': current.st_mtime_ns, 'ctime_ns': current.st_ctime_ns}
        check(observed == fixed['stable_stat'], 'old fixed Git metadata unchanged since actual observer')
        rows.append({'path': fixed['path'], 'identity': identity(raw), 'stable_stat': observed})
    for relative in packet['old_git']['absent_lookup_paths']:
        check(not os.path.lexists(SOURCE / relative), 'old Git indirection remains absent')
    refs = command(SOURCE, ['for-each-ref', '--format=%(refname) %(objectname)'])
    check(base64.b64encode(refs).decode() == packet['old_git']['refs_base64'], 'old actual ref preserved, not copied or cleared')
    value = {'files': rows, 'refs': identity(refs), 'refs_base64': base64.b64encode(refs).decode(), 'absent_lookup_paths': packet['old_git']['absent_lookup_paths']}
    jwrite(label + '.old-git.json', value)
    return value

def parse_supervisor(raw, job_id):
    outer = parse(raw)
    value = parse(outer['content'][0]['text'].encode())
    check(not outer.get('isError') and value['job_id'] == job_id and value['state'] == 'succeeded' and value['exit_code'] == 0 and not value['timed_out'] and not value['cancelled'] and not value['automatic_retry'] and value['output_complete'] and value['output_durable'] and value['terminal_publication_confirmed'], 'actual original availability normal supervisor')
    return value

def preflight():
    global cfg, packet, complete, inventory_module, missing_paths, source_before, old_git_before, lock_fd
    check(os.getuid() == 1000, 'original non-root operator')
    cfg_raw = regular_read(CONFIG)
    cfg = parse(cfg_raw)
    check(cfg['status'] == 'APPROVED_ISOLATED_MATERIALIZATION' and cfg['root_execution_approved'] is True, 'materialization remains HOLD')
    check(cfg['source_repo'] == str(SOURCE) and cfg['destination_repo'] == str(TARGET) and cfg['control'] == str(CONTROL) and cfg['action_seconds'] == 600 and cfg['record_seconds'] == 180, 'fixed scope and original preparation budgets')
    check(not os.path.lexists(TARGET), 'new isolated source must be absent; no retry, replacement, or reuse')
    read_input(CONFIG, identity(cfg_raw))
    read_input(pathlib.Path(__file__), cfg['driver'])
    packet = parse(retained_pin(PACKET, PACKET_PIN))
    check(packet['format'] == 'hepta-cc57-isolated-materialization-packet-v1' and packet['source_repo'] == str(SOURCE) and packet['destination_repo'] == str(TARGET), 'fixed source packet schema')
    check(packet['current']['commit'] == HEAD and packet['current']['tree'] == TREE and packet['current']['parents'] == [PARENT], 'exact cc57 canonical source')
    check(packet['object_scope']['format'] == 'two-complete-snapshots-not-full-ancestry' and packet['qualification'] is False, 'bounded declared object scope')
    observed = parse(retained_pin(CONTROL / 'AVAILABILITY_RESULT.original.json', packet['observer']['result']))
    normal = parse_supervisor(retained_pin(CONTROL / 'AVAILABILITY_SUPERVISOR.original.json', packet['observer']['supervisor']), packet['observer']['job_id'])
    check(observed['status'] == 'completed_readonly_availability_check' and observed['all_snapshot_objects_available'] and observed['local_seven_blob_recovery_material_available'] and observed['old_fixed_git_state_unchanged'] and observed['old_git_after'] == packet['old_git'], 'actual successful bounded availability observation')
    check(observed['availability']['expected_objects'] == 16439 and observed['availability']['missing_objects'] == [] and observed['availability']['mismatched_objects'] == [] and observed['body_verification']['actual_verified_objects'] == 1836, 'actual complete scoped availability')
    result['availability_observation'] = packet['observer']
    for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR', 'GIT_INDEX_FILE', 'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_SHALLOW_FILE', 'GIT_REPLACE_REF_BASE', 'GIT_CONFIG_COUNT', 'GIT_CONFIG_PARAMETERS', 'GIT_CONFIG_GLOBAL', 'GIT_CONFIG_SYSTEM'):
        check(not os.environ.get(key), 'no inherited Git override: ' + key)
    os.environ.update(PATH='/usr/bin:/bin', GIT_OPTIONAL_LOCKS='0', GIT_NO_REPLACE_OBJECTS='1', GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_SYSTEM='/dev/null', PYTHONDONTWRITEBYTECODE='1')
    sys.dont_write_bytecode = True
    git_raw = pin(regular_read(GIT, expected_uid=0), GIT_PIN, 'actual original Git executable')
    inputs[GIT] = identity(git_raw)
    check(stat.S_IMODE(pathlib.Path(GIT).lstat().st_mode) == 0o755, 'actual system Git mode')
    raw_inventory = read_input(INVENTORY_MODULE, INVENTORY_MODULE_PIN)
    inventory_module = types.ModuleType('original_complete_physical_inventory')
    inventory_module.__file__ = str(INVENTORY_MODULE)
    exec(compile(raw_inventory, str(INVENTORY_MODULE), 'exec'), inventory_module.__dict__)
    real_directory(COORDINATION.parent)
    lock_fd = os.open(COORDINATION, os.O_RDONLY | os.O_NOFOLLOW)
    info = os.fstat(lock_fd)
    check(stat.S_ISREG(info.st_mode) and info.st_uid == 1000 and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600 and info.st_dev == 2050 and info.st_ino == 50139448, 'same original source coordination lock')
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    result['coordination_lock'] = {'path': str(COORDINATION), 'mode': 'LOCK_EX', 'stat': stat_identity(info), 'scope': 'cooperating task writers only; full source checks remain mandatory'}
    jwrite('SOURCE_COORDINATION_EX.json', result['coordination_lock'])
    check_processes('before-preparation')
    source_inventory = packet['original_inventory']
    packed = retained_pin(pathlib.Path(source_inventory['path']), source_inventory['identity'])
    with gzip.GzipFile(fileobj=io.BytesIO(packed), mode='rb') as stream:
        raw = stream.read(packet['current']['inventory']['bytes'] + 1)
        check(stream.read(1) == b'', 'bounded complete original canonical inventory')
    pin(raw, packet['current']['inventory'], 'actual original canonical full inventory')
    complete = parse(raw)
    check(complete['source'] == {'head': HEAD, 'tree': TREE, 'status': ''} and complete['tracked_entries'] == complete['filesystem_entries'] == len(complete['files']) == LEAVES and all(row['stable'] and row['matches_index'] for row in complete['files']), 'canonical original full source membership')
    missing_paths = {row['path'] for row in packet['seven_missing']}
    check(len(missing_paths) == 7 and sum(x['bytes'] for x in packet['seven_missing']) == 18176884, 'only seven originally missing archives')
    for fixed in packet['seven_missing']:
        row = next(x for x in complete['files'] if x['path'] == fixed['path'])
        check(row['kind'] == 'file' and row['index_mode'] == '100644' and row['bytes'] == fixed['bytes'] and row['sha256'] == fixed['sha256'] and row['working_blob'] == fixed['sha'], 'seven exact original archive identities')
    expected_graphs()
    old_git_before = old_git_state('before')
    source_before = source_physical('before')
    result['old_source_before'] = {k: value for k, value in source_before.items() if k != 'records'}
    listing = b''.join((key + '\n').encode() for key in sorted(object_index))
    actual = command(SOURCE, ['cat-file', '--batch-check'], data=listing)
    expected = b''.join((key + ' ' + object_index[key]['type'] + ' ' + str(object_index[key]['bytes']) + '\n').encode() for key in sorted(object_index))
    check(actual == expected, 'all fixed two-snapshot local objects available, including five parent preimages')
    real_directory(TARGET.parent)
    check(os.access(TARGET.parent, os.W_OK | os.X_OK), 'new destination parent writable and traversable')
    physical = sum(row['bytes'] for row in complete['files'])
    pack_upper = sum(row['bytes'] + row['bytes'] // 1000 + 64 for row in object_index.values()) + 32
    required = 2 * pack_upper + physical + 384 * 1024 * 1024
    free = shutil.disk_usage(TARGET.parent).free
    jwrite('DISK_PREFLIGHT.json', {'actual_free': free, 'required_free': required, 'physical_bytes': physical, 'conservative_pack_bytes': pack_upper, 'same_original_two_pack_copies_plus_384MiB_record_headroom_formula': True})
    check(free >= required, 'sufficient actual disk for independent Git store and exact source')
    check_processes('before-new-destination')

def journal(row):
    raw = encoded(row)
    journal_stream.write(raw)
    journal_stream.flush()
    os.fsync(journal_stream.fileno())

def destination_leaf(row, raw):
    path = TARGET / row['path']
    parent = TARGET
    for part in pathlib.PurePosixPath(row['path']).parts[:-1]:
        parent /= part
        if not os.path.lexists(parent):
            journal({'at': now(), 'action': 'create_new_directory', 'path': str(parent), 'phase': 'intent'})
            os.mkdir(parent, 0o755)
        real_directory(parent)
    check(not os.path.lexists(path), 'destination original leaf must not already exist')
    journal({'at': now(), 'action': 'create_new_leaf', 'path': row['path'], 'identity': identity(raw), 'permissions': row['permissions'], 'phase': 'intent'})
    if row['kind'] == 'symlink':
        check(b'\0' not in raw, 'original symlink target bytes')
        os.symlink(os.fsdecode(raw), path)
        check(os.fsencode(os.readlink(path)) == raw, 'new symlink target exact readback')
    else:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fchmod(stream.fileno(), row['permissions'])
            os.fsync(stream.fileno())
    info = path.lstat()
    check(stat.S_IMODE(info.st_mode) == row['permissions'] and info.st_uid == 1000 and info.st_nlink == 1, 'new original permissions and independent ownership')
    journal({'at': now(), 'action': 'create_new_leaf', 'path': row['path'], 'phase': 'observed', 'actual_stat': stat_identity(info)})

def create_destination():
    global target_created, journal_stream, source_reader, pack_path
    check(not os.path.lexists(TARGET), 'atomic create-only new destination')
    action = mutation_intent('create_new_repository', path=str(TARGET))
    os.mkdir(TARGET, 0o700)
    target_created = True
    result['new_repo_created'] = True
    action['actual_terminal'] = 'observed'
    command(TARGET, ['init', '--quiet', '--template='], mutation=True)
    for key, value in (('core.autocrlf', 'false'), ('core.filemode', 'true'), ('core.symlinks', 'true'), ('index.version', '2')):
        command(TARGET, ['config', '--local', key, value], mutation=True)
    check(command(TARGET, ['rev-parse', '--absolute-git-dir']).decode().strip() == str(TARGET / '.git'), 'independent new Git object directory')
    check(command(TARGET, ['for-each-ref']) == b'', 'new repository has no refs')
    for name in ('objects/info/alternates', 'shallow', 'info/grafts', 'packed-refs'):
        check(not os.path.lexists(TARGET / '.git' / name), 'no new repository indirection or copied refs')
    source_reader = ObjectReader(SOURCE, 'original-source-bodies')
    archive_blobs = {}
    for item in packet['seven_missing']:
        archive_blobs[item['sha']] = source_reader.get(item['sha'], object_index[item['sha']])
    for key, raw in raw_commits.items():
        check(source_reader.get(key, object_index[key]) == raw, 'same authentic local raw commit')
    before_by_path = {row['path']: row for row in source_before['records']}
    pack_path = OUT / 'INDEPENDENT_OBJECTS.input.pack'
    action = mutation_intent('write_exact_new_physical_source_and_standard_pack', source_leaves=15188, object_count=len(object_index))
    journal_stream = (OUT / 'PHYSICAL_CREATION_JOURNAL.jsonl').open('xb')
    pack_hash = hashlib.sha1()
    pack_sha256 = hashlib.sha256()
    included = set()
    with pack_path.open('xb') as stream:
        def put(raw):
            stream.write(raw)
            pack_hash.update(raw)
            pack_sha256.update(raw)
        def put_object(key, raw):
            check(key not in included, 'one copy of every independent Git object')
            expected = object_index[key]
            check(len(raw) == expected['bytes'] and sha256(raw) == expected['sha256'] and oid(expected['type'], raw) == key, 'original raw object before independent import')
            put(pack_entry_header(expected['type'], len(raw)))
            put(zlib.compress(raw))
            included.add(key)
        put(b'PACK' + struct.pack('>II', 2, len(object_index)))
        for number, row in enumerate(complete['files'], 1):
            remaining()
            if row['path'] in missing_paths:
                check(not os.path.lexists(SOURCE / row['path']), 'known missing source remains untouched')
                raw = archive_blobs[row['working_blob']]
            else:
                raw, current_stat = source_leaf(row)
                check(before_by_path[row['path']]['stable_stat'] == current_stat, 'same original source leaf while copying')
            destination_leaf(row, raw)
            if row['working_blob'] not in included:
                put_object(row['working_blob'], raw)
            if number % 1024 == 0:
                event('fresh_physical_leaves', completed=number, total=LEAVES)
        for key in sorted(object_index):
            if key in included:
                continue
            raw = raw_trees[key] if key in raw_trees else raw_commits[key] if key in raw_commits else source_reader.get(key, object_index[key])
            put_object(key, raw)
        check(len(included) == len(object_index), 'complete fixed union pack')
        footer = pack_hash.digest()
        stream.write(footer)
        pack_sha256.update(footer)
        stream.flush()
        os.fsync(stream.fileno())
        size = stream.tell()
    journal_stream.close()
    journal_stream = None
    source_reader.close()
    action['actual_terminal'] = 'observed'
    result['physical_leaves_created'] = LEAVES
    result['input_pack'] = {'path': str(pack_path), 'bytes': size, 'sha256': pack_sha256.hexdigest(), 'pack_sha1': footer.hex(), 'objects': len(included), 'version': 2, 'delta_objects': 0}
    jwrite('PACK_INPUT.json', result['input_pack'])
    action = mutation_intent('import_independent_standard_pack', objects=len(included))
    output = command(TARGET, ['index-pack', '--threads=1', '--stdin'], stdin_path=pack_path, mutation=True)
    check(output.strip() == ('pack\t' + footer.hex()).encode(), 'actual new index-pack checksum')
    stored = TARGET / '.git' / 'objects' / 'pack' / ('pack-' + footer.hex() + '.pack')
    with stored.open('rb') as stream:
        actual_hash = hashlib.sha256()
        actual_size = 0
        for chunk in iter(lambda: stream.read(1048576), b''):
            remaining()
            actual_hash.update(chunk)
            actual_size += len(chunk)
    check(actual_size == size and actual_hash.hexdigest() == pack_sha256.hexdigest(), 'independent standard pack stored exact bytes')
    action['actual_terminal'] = 'observed'

def verify_import():
    global target_reader
    target_reader = ObjectReader(TARGET, 'new-independent-objects')
    verified = []
    for key in sorted(object_index):
        raw = target_reader.get(key, object_index[key])
        if key in raw_trees:
            check(raw == raw_trees[key], 'new complete tree raw bytes')
        if key in raw_commits:
            check(raw == raw_commits[key], 'new authentic raw commit bytes')
        verified.append({'sha': key, **object_index[key]})
    target_reader.close()
    gzrecord('IMPORTED_OBJECT_READBACK.json', encoded(verified))
    result['new_objects_fully_verified'] = len(verified)

def initialize_index():
    action = mutation_intent('new_index_and_detached_head', tree=TREE, commit=HEAD)
    command(TARGET, ['read-tree', TREE], mutation=True)
    command(TARGET, ['update-ref', '--no-deref', 'HEAD', HEAD], mutation=True)
    command(TARGET, ['update-index', '--refresh'], mutation=True)
    check(command(TARGET, ['write-tree']).decode().strip() == TREE, 'new normal index exact Merkle tree')
    action['actual_terminal'] = 'observed'
    verify_index('initial')
    for directory, children, files in os.walk(TARGET, topdown=False, followlinks=False):
        remaining()
        if pathlib.Path(directory).is_relative_to(TARGET / '.git'):
            for name in files:
                fd = os.open(pathlib.Path(directory) / name, os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    result['new_files_and_directories_synced'] = True

def verify_index(label):
    raw = regular_read(TARGET / '.git' / 'index')
    entries, extensions = parse_index(raw)
    check(set(entries) == {row['path'] for row in complete['files']}, 'all 15188 new index entries')
    for row in complete['files']:
        item = entries[row['path']]
        check(item['mode'] == row['index_mode'] and item['sha'] == row['working_blob'], 'new index logical original identity')
        check(not item['flags'] & (0x8000 | 0x4000 | 0x3000) and item['flags'] & 0x0fff == min(len(row['path'].encode()), 0x0fff), 'normal index flags, no assume-unchanged/skip-worktree/extended/unmerged state')
        value = (TARGET / row['path']).lstat()
        expected = (int(value.st_ctime_ns // 1000000000) & 0xffffffff, value.st_ctime_ns % 1000000000, int(value.st_mtime_ns // 1000000000) & 0xffffffff, value.st_mtime_ns % 1000000000, value.st_dev & 0xffffffff, value.st_ino & 0xffffffff, int(row['index_mode'], 8), value.st_uid & 0xffffffff, value.st_gid & 0xffffffff, value.st_size & 0xffffffff)
        check(item['stat'] == expected, 'actual normal stat fields for every new index entry')
    check(all(x['name'] == 'TREE' for x in extensions), 'only ordinary cache-tree index extension')
    value = {'raw': identity(raw), 'entries': len(entries), 'all_entry_logical_identities_verified': True, 'all_actual_stat_fields_verified': True, 'assume_unchanged_or_skip_worktree_entries': 0, 'extensions': [{'name': x['name'], 'bytes': x['bytes']} for x in extensions]}
    gzrecord(label + '.new-index.raw', raw)
    jwrite(label + '.new-index-check.json', value)
    return value

def current_git_state():
    gd = TARGET / '.git'
    real_directory(gd)
    check(command(TARGET, ['rev-parse', '--absolute-git-dir']).decode().strip() == str(gd) and command(TARGET, ['rev-parse', '--path-format=absolute', '--git-common-dir']).decode().strip() == str(gd), 'independent current Git metadata directory')
    for name in ('objects/info/alternates', 'shallow', 'info/grafts', 'packed-refs', 'index.lock', 'HEAD.lock'):
        check(not os.path.lexists(gd / name), 'no copied refs, indirection or pending index lock')
    head = regular_read(gd / 'HEAD', 1000)
    index = regular_read(gd / 'index')
    config = regular_read(gd / 'config', 1000000)
    refs = command(TARGET, ['for-each-ref', '--format=%(refname) %(objectname)'])
    check(head == (HEAD + '\n').encode() and not refs, 'exact current detached HEAD and no refs')
    check(command(TARGET, ['rev-parse', 'HEAD']).decode().strip() == HEAD and command(TARGET, ['rev-parse', 'HEAD^{tree}']).decode().strip() == TREE, 'exact current commit/tree')
    return {'head_raw_sha256': sha256(head), 'head': HEAD, 'tree': TREE, 'index_bytes': len(index), 'index_sha256': sha256(index), 'config_bytes': len(config), 'config_sha256': sha256(config), 'refs_bytes': len(refs), 'refs_sha256': sha256(refs)}

def native_projection(raw_inventory):
    rows = []
    for row in parse(raw_inventory)['files']:
        rows.append({'path': row['path'], 'mode': row['index_mode'], 'bytes': row['bytes'], 'sha256': row['sha256'], 'blob': row['working_blob']})
    raw = json.dumps(sorted(rows, key=lambda row: os.fsencode(row['path'])), sort_keys=True, separators=(',', ':')).encode()
    pin(raw, packet['current']['native_inventory'], 'original native five-field projection of actual new complete bytes')
    return raw

def destination_physical(label):
    raw = inventory_module.inventory(TARGET)
    pin(raw, packet['current']['inventory'], 'actual full original 5118 inventory in the new destination')
    inventory_module.require_inventory(raw, {'source_sha': HEAD, 'source_tree': TREE})
    value = parse(raw)
    check(value['tracked_entries'] == value['filesystem_entries'] == len(value['files']) == LEAVES, 'complete new physical source without extra files')
    gzrecord(label + '.complete.inventory.json', raw)
    native = native_projection(raw)
    gzrecord(label + '.native-five-field.inventory.json', native)
    return {'inventory': {**identity(raw), 'tracked_entries': LEAVES, 'filesystem_entries': LEAVES}, 'native_inventory': identity(native), 'head': HEAD, 'tree': TREE, 'parents': [PARENT], 'status': ''}

def git_metadata(label):
    rows = []
    for directory, children, files in os.walk(TARGET / '.git', followlinks=False):
        for name in children:
            check(not (pathlib.Path(directory) / name).is_symlink(), 'no symlink in independent Git metadata')
        for name in files:
            remaining()
            path = pathlib.Path(directory) / name
            before = path.lstat()
            check(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1, 'independent ordinary Git metadata file')
            digest = hashlib.sha256()
            blob = hashlib.sha1(b'blob ' + str(before.st_size).encode() + b'\0')
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1048576), b''):
                    remaining()
                    digest.update(block)
                    blob.update(block)
            check(stat_identity(before) == stat_identity(path.lstat()), 'stable complete Git metadata read')
            rows.append({'path': path.relative_to(TARGET / '.git').as_posix(), 'bytes': before.st_size, 'sha256': digest.hexdigest(), 'git_blob': blob.hexdigest(), 'stat': stat_identity(before)})
    rows.sort(key=lambda row: row['path'].encode())
    raw = encoded(rows)
    gzrecord(label + '.git-metadata.json', raw)
    return raw

def final_old():
    current = source_physical('final')
    check(current == source_before, 'old original physical leaves and seven missing paths unchanged')
    current_git = old_git_state('final')
    check(current_git == old_git_before, 'old actual HEAD/index/config/ref state unchanged')
    result['old_source_after'] = {k: value for k, value in current.items() if k != 'records'}
    result['old_git_state_before'] = old_git_before
    result['old_git_state_after'] = current_git
    result['old_source_and_git_unchanged'] = True

def final_new():
    check_processes('final-new-source')
    actual = destination_physical('final')
    check(actual == new_source_before, 'actual new full source stable before/after final audit')
    checked = verify_index('final')
    actual_git = current_git_state()
    check(actual_git == new_git_before, 'new raw Git state remains the new actual baseline')
    metadata = git_metadata('final')
    check(metadata == new_metadata_before, 'all independent Git metadata stable after initial normal refresh')
    result['current_source_after'] = actual
    result['current_git_state_after'] = actual_git
    result['current_index'] = checked
    result['current_git_metadata'] = identity(metadata)

def final_inputs():
    rows = []
    for path, expected in inputs.items():
        raw = regular_read(path, expected_uid=0 if path == GIT else None)
        pin(raw, expected, 'original preparation input unchanged')
        rows.append({'path': path, **identity(raw)})
    jwrite('INPUT_IDENTITIES.final.json', rows)
    check(stat_identity(os.fstat(lock_fd)) == result['coordination_lock']['stat'] == stat_identity(COORDINATION.lstat()), 'same source coordination lock inode remains held')
    result['input_identities_unchanged'] = True

def retain_existing_output(name):
    path = OUT / name
    if not os.path.lexists(path):
        return
    before = path.lstat()
    check(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1, 'ordinary own retained output')
    digest = hashlib.sha256()
    blob = hashlib.sha1(b'blob ' + str(before.st_size).encode() + b'\0')
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            remaining()
            digest.update(chunk)
            blob.update(chunk)
    check(stat_identity(before) == stat_identity(path.lstat()), 'stable own output retained')
    artifacts.append({'name': name, 'bytes': before.st_size, 'sha256': digest.hexdigest(), 'git_blob': blob.hexdigest(), 'retained_original': True})

def main():
    global deadline, source_reader, target_reader, journal_stream, new_source_before, new_git_before, new_metadata_before
    real_directory(CONTROL)
    check(not os.path.lexists(OUT), 'fresh immutable output directory, no reuse')
    os.mkdir(OUT, 0o700)
    result['started_at'] = now()
    signal.signal(signal.SIGALRM, alarm_handler)
    deadline = time.monotonic() + ACTION_SECONDS
    arm_if_remaining()
    operation_error = None
    try:
        preflight()
        event('independent_materialization_preflight_complete')
        create_destination()
        verify_import()
        initialize_index()
        new_git_before = current_git_state()
        new_source_before = destination_physical('initial')
        check(current_git_state() == new_git_before, 'initial full inventory did not change normal index metadata')
        new_metadata_before = git_metadata('initial')
        result['current_source_before'] = new_source_before
        result['current_git_state_before'] = new_git_before
        result['action_completed'] = True
    except BaseException as exc:
        operation_error = type(exc).__name__ + ': ' + str(exc)
        result['error'] = operation_error
        result['traceback'] = traceback.format_exc()
    finally:
        disarm()
        record_deadline = time.monotonic() + RECORD_SECONDS
        deadline = record_deadline - 10
        arm_if_remaining()
        audits = []
        cleanup_errors = []
        try:
            for reader in (source_reader, target_reader):
                if reader is not None and not reader.closed:
                    try:
                        reader.abort()
                    except BaseException as exc:
                        cleanup_errors.append(type(exc).__name__ + ': ' + str(exc))
            if journal_stream is not None and not journal_stream.closed:
                try:
                    journal_stream.flush()
                    os.fsync(journal_stream.fileno())
                    journal_stream.close()
                except BaseException as exc:
                    cleanup_errors.append(type(exc).__name__ + ': ' + str(exc))
            for name, method, available in [('old_source_and_git', final_old, source_before is not None and old_git_before is not None), ('new_source_and_git', final_new, new_source_before is not None and new_git_before is not None), ('inputs_and_coordination', final_inputs, lock_fd is not None and cfg is not None)]:
                row = {'check': name, 'status': 'unknown_not_available'}
                if available:
                    try:
                        method()
                        row['status'] = 'verified'
                    except BaseException as exc:
                        row.update(status='failed', error=type(exc).__name__ + ': ' + str(exc), traceback=traceback.format_exc())
                audits.append(row)
            for name in ('PHYSICAL_CREATION_JOURNAL.jsonl', 'INDEPENDENT_OBJECTS.input.pack'):
                retain_existing_output(name)
        except BaseException as exc:
            result['retention_error'] = type(exc).__name__ + ': ' + str(exc)
            result['retention_traceback'] = traceback.format_exc()
        finally:
            disarm()
            deadline = record_deadline
            arm_if_remaining()
            try:
                result['final_audits'] = audits
                result['cleanup_errors'] = cleanup_errors
                success = operation_error is None and result.get('action_completed') is True and not cleanup_errors and 'retention_error' not in result and len(audits) == 3 and all(row['status'] == 'verified' for row in audits)
                result['status'] = 'MATERIALIZED_EXACT_CC57_FOR_NATIVE_REVIEW_ONLY' if success else 'FAILED_ISOLATED_MATERIALIZATION'
                result['old_source_writes'] = False
                result['finished_at'] = now()
                jwrite('COMMANDS.json', commands)
                jwrite('MUTATION_INTENTS.json', intents)
                jwrite('INPUT_IDENTITIES.before.json', inputs)
                jwrite('ARTIFACTS.json', artifacts)
                jwrite('RESULT.json', result)
                event('isolated_materialization_complete', status=result['status'], qualification=False)
            finally:
                disarm()
                if lock_fd is not None:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    os.close(lock_fd)
    raise SystemExit(0 if result.get('status') == 'MATERIALIZED_EXACT_CC57_FOR_NATIVE_REVIEW_ONLY' else 1)

if __name__ == '__main__':
    main()
