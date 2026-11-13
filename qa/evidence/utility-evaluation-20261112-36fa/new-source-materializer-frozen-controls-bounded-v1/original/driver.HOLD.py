#!/usr/bin/env python3
"""Create one independent complete reviewed candidate from the exact cc57 donor.

HOLD until Root's exact config/request approval. No Cargo, tests, source repair,
remote refs, network, history walk, fsck, retry, or rollback.
"""
from __future__ import annotations
import base64, datetime, fcntl, gzip, hashlib, io, json, os, pathlib, select
import shutil, signal, stat, struct, subprocess, sys, time, traceback, types, zlib

SOURCE = pathlib.Path('/home/qian-qi/hepta-utility-36fa-native-cc57-isolated-v1')
TARGET = pathlib.Path('/home/qian-qi/hepta-utility-36fa-provider-0c59-isolated-v1')
CONTROL = pathlib.Path('/home/qian-qi/hepta-utility-36fa-evidence/provider-0c59-isolated-materialization-v1')
STAGING_PREFIX = '/home/qian-qi/hepta-utility-36fa-evidence/provider-0c59-materialization-v1'
OUT = CONTROL / 'run'
CONFIG = CONTROL / 'APPROVED_CONFIG.json'
PACKET = CONTROL / 'MATERIALIZATION_PACKET.json'
INVENTORY_MODULE = pathlib.Path('/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/inventory-driver-v2.py')
COORDINATION = pathlib.Path('/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/SOURCE_COORDINATION.lock')
GIT = '/usr/bin/git'
HEAD = '0c59aaca0b4932507f068c723f73da2f96729b3d'
TREE = '4b1ef6a81f8fc49d4c267d9e47bc4b8127fc8d09'
PARENT = 'cc57c7198db6293ccca562253c42fffbe2a04633'
LEAVES = 15237
DONOR_HEAD = 'cc57c7198db6293ccca562253c42fffbe2a04633'
DONOR_TREE = 'b7b357c07b5539769a068c6b9b009629f5612d1e'
DONOR_LEAVES = 15188
ACTION_SECONDS = 600
RECORD_SECONDS = 180
PACKET_PIN = {'bytes': 14331, 'sha256': 'b733baa29e1b70c6fa57582d61dfe47e360e9d3de4d0ef482193be30057914c6', 'git_blob': '728a9251a3ee0e5fca4dd4cc43e8629bbfa9185c'}
INVENTORY_MODULE_PIN = {'bytes':22946,'sha256':'20c11034146f6739dd24e9d7e33b94ee909754b07ce6295c242c842c5f3c40b2','git_blob':'51181866cbbb6e0176aab04117efffa8b6792b31'}
GIT_PIN = {'bytes':4066232,'sha256':'eb54b535467e0975c1284d4c4d08eea779aeb248a5d34b02e2ee171382e22201'}
artifacts = []
commands = []
inputs = {}
intents = []
deadline = None
cfg = packet = complete = donor_complete = inventory_module = None
base_input = candidate_input = None
source_before = old_git_before = None
new_source_before = new_git_before = new_metadata_before = None
source_reader = target_reader = journal_stream = None
lock_fd = None
target_created = False
object_index = raw_trees = raw_commits = parent_rows = donor_object_keys = provided_raw = None
pack_path = None
result = {'format':'hepta-complete-candidate-materialization-result-v1','status':'HOLD','source_repo':str(SOURCE),'destination_repo':str(TARGET),'source_commit':HEAD,'source_tree':TREE,'parents':[PARENT],'qualification':False,'new_repo_created':False,'old_source_writes':False,'remote_ref_updates':False,'cargo_or_formatter_started':False,'test_commands_dispatched':0,'dependency_installation_started':False,'automatic_retry':False,'rollback':False,'action_completed':False,'final_audits':[]}

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
    cleanup_attempted = False
    disarm()
    try:
        budget = remaining()
        if stdin_path is not None:
            handle = open(stdin_path, 'rb')
        process = subprocess.Popen(argv, cwd=repo, stdin=handle if handle is not None else (subprocess.PIPE if data is not None else subprocess.DEVNULL), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            stdout, stderr = process.communicate(data, timeout=budget)
            row.update(actual_terminal='observed', returncode=process.returncode, timed_out=False)
        except subprocess.TimeoutExpired as original_timeout:
            process.kill()
            cleanup_attempted = True
            try:
                stdout, stderr = process.communicate(timeout=5)
                row.update(actual_terminal='observed', returncode=process.returncode, timed_out=True)
            except subprocess.TimeoutExpired as cleanup_timeout:
                stdout = cleanup_timeout.stdout or original_timeout.stdout or b''
                stderr = cleanup_timeout.stderr or original_timeout.stderr or b''
                row.update(actual_terminal='unknown_after_bounded_owned_cleanup', timed_out=True, cleanup_terminal='unknown_not_observed', captured_streams_are_partial=True)
            row['stdout'] = write(prefix + '.stdout', stdout)
            row['stderr'] = write(prefix + '.stderr', stderr)
            raise
        row['stdout'] = write(prefix + '.stdout', stdout)
        row['stderr'] = write(prefix + '.stderr', stderr)
        check(process.returncode == 0, 'normal exact Git command: ' + repr(arguments))
        return stdout
    finally:
        if process is not None:
            if process.poll() is None and not cleanup_attempted:
                process.kill()
                try:
                    row['cleanup_returncode'] = process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    row['cleanup_terminal'] = 'unknown_not_observed'
                    row['actual_terminal'] = 'unknown_after_bounded_owned_cleanup'
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()
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
        self.row['current_stream_read'] = {'requested_bytes': count, 'received_bytes': 0}
        while count:
            check(select.select([self.process.stdout], [], [], remaining())[0], 'bounded original object stream')
            raw = os.read(self.process.stdout.fileno(), min(count, 1048576))
            check(bool(raw), 'complete original object body')
            blocks.append(raw)
            count -= len(raw)
            self.row['current_stream_read']['received_bytes'] += len(raw)
        return b''.join(blocks)

    def get(self, key, expected):
        remaining()
        self.row['requested_objects'] += 1
        self.row['current_request'] = {'sha': key, 'expected': expected}
        self.process.stdin.write((key + '\n').encode())
        self.process.stdin.flush()
        header = b''
        while not header.endswith(b'\n'):
            check(len(header) < 160, 'bounded original object header')
            header += self.exact(1)
        self.row['current_request']['actual_header_base64'] = base64.b64encode(header).decode()
        check(header == (key + ' ' + expected['type'] + ' ' + str(expected['bytes']) + '\n').encode(), 'exact existing object type/size, no missing substitute')
        raw = self.exact(expected['bytes'])
        self.row['current_request']['actual_body'] = {**identity(raw), 'object_sha': oid(expected['type'], raw)}
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

def load_provided_input(label):
    fixed = packet['provided_inputs'][label]
    check(fixed['maximum_decoded_part'] == 524288 and len(fixed['parts']) == (2 if label == 'base' else 3), 'fixed bounded compressed input partition')
    pieces = []
    offset = 0
    for number, item in enumerate(fixed['parts'], 1):
        expected_path = STAGING_PREFIX + '-' + label + '.json.gz.part-%03d' % number
        check(item['path'] == expected_path and item['offset'] == offset and 0 < item['bytes'] <= 524288 and item['mode'] == 0o600, 'exact create-only staging input')
        raw = read_input(pathlib.Path(item['path']), item)
        check(stat.S_IMODE(pathlib.Path(item['path']).lstat().st_mode) == item['mode'], 'fixed staged input mode')
        pieces.append(raw)
        offset += len(raw)
    packed = pin(b''.join(pieces), fixed['gzip'], 'complete compressed ' + label + ' input')
    with gzip.GzipFile(fileobj=io.BytesIO(packed), mode='rb') as stream:
        raw = stream.read(fixed['raw']['bytes'] + 1)
        check(stream.read(1) == b'', 'bounded exact decompressed ' + label + ' input')
    pin(raw, fixed['raw'], 'complete provided ' + label + ' input')
    gzrecord('PROVIDED_' + label.upper() + '_OBJECT_INPUT.json', raw)
    return parse(raw)

def derive_candidate_inventory():
    global complete
    check(candidate_input['format'] == 'hepta-reviewed-candidate-source-object-input-v1' and candidate_input['qualification'] is False and candidate_input['native_execution'] is False, 'prepared candidate input schema')
    check(candidate_input['donor_commit'] == DONOR_HEAD and candidate_input['candidate_commit'] == HEAD and candidate_input['candidate_tree'] == TREE and candidate_input['candidate_parents'] == [PARENT], 'exact candidate input identities')
    check(candidate_input['canonical_source_deletions'] == [] and packet['overlay']['canonical_source_deletions'] == [], 'no canonical source deletion')
    check(candidate_input['reviewed_overlay'] == packet['overlay']['identity'], 'exact reviewed full overlay')
    rows = {row['path']: dict(row) for row in donor_complete['files']}
    original_paths = set(rows)
    covered = set()
    added = changed = unchanged = 0
    for item in candidate_input['covered_paths']:
        path = item['path']
        check(path not in covered and path == item['after']['path'], 'unique complete covered path')
        covered.add(path)
        before = rows.get(path)
        check(before == item['before'], 'complete donor preimage for every covered path')
        after = item['after']
        check(set(after) == {'bytes', 'index_blob', 'index_mode', 'kind', 'matches_index', 'path', 'permissions', 'sha256', 'stable', 'working_blob'}, 'original 5118 row schema')
        check(after['index_mode'] in ('100644', '100755', '120000') and after['permissions'] == {'100644': 0o644, '100755': 0o755, '120000': 0o777}[after['index_mode']], 'canonical original permission semantics')
        check(after['kind'] == ('symlink' if after['index_mode'] == '120000' else 'file') and after['index_blob'] == after['working_blob'] and after['matches_index'] is True and after['stable'] is True, 'exact intended clean source row')
        added += before is None
        changed += before is not None and before != after
        unchanged += before == after
        rows[path] = after
    check(len(covered) == packet['overlay']['covered_paths'] == 110 and added == packet['overlay']['new_paths'] == 49 and changed == packet['overlay']['modified_paths'] == 60 and unchanged == packet['overlay']['unchanged_covered_paths'] == 1, 'exact complete reviewed 110-path overlay')
    check(original_paths <= set(rows) and len(rows) == LEAVES, 'complete donor membership plus approved new paths')
    complete = {'files': sorted(rows.values(), key=lambda row: os.fsencode(row['path'])), 'filesystem_entries': LEAVES, 'schema': donor_complete['schema'], 'source': {'head': HEAD, 'status': '', 'tree': TREE}, 'tracked_entries': LEAVES}
    raw = pin(encoded(complete), packet['current']['inventory'], 'expected complete candidate inventory from the exact donor and overlay')
    native_projection(raw)
    gzrecord('EXPECTED_CANDIDATE.complete.inventory.json', raw)
    result['expected_source_is_not_actual_observation'] = True

def expected_graphs():
    global object_index, raw_trees, raw_commits, parent_rows, donor_object_keys, provided_raw
    parent_rows = {x['path']: dict(x) for x in donor_complete['files']}
    for change in packet['parent_snapshot']['changes_from_current']:
        row = parent_rows[change['path']]
        check(row['index_mode'] == change['mode'] and identity_projection(row) == change['current'], 'actual parent delta donor preimage')
        row.update(index_blob=change['parent']['git_blob'], working_blob=change['parent']['git_blob'], bytes=change['parent']['bytes'], sha256=change['parent']['sha256'])
    object_index, raw_trees, raw_commits, provided_raw = {}, {}, {}, {}
    def add(key, meta):
        check(key not in object_index or object_index[key] == meta, 'union object identity equality')
        object_index[key] = meta
    def add_snapshot(rows, expected, count):
        tree, bodies = tree_objects(rows)
        check(tree == expected['tree'] and len(rows) == count, 'complete independent snapshot root and leaf count')
        keys = set(bodies)
        for key, body in bodies.items():
            check(key not in raw_trees or raw_trees[key] == body, 'union tree body equality')
            raw_trees[key] = body
            add(key, {'type': 'tree', 'bytes': len(body), 'sha256': sha256(body)})
        for row in rows:
            key = row['working_blob']
            keys.add(key)
            add(key, {'type': 'blob', 'bytes': row['bytes'], 'sha256': row['sha256']})
        return keys
    add_snapshot(donor_complete['files'], packet['donor'], DONOR_LEAVES)
    add_snapshot(list(parent_rows.values()), packet['parent_snapshot'], DONOR_LEAVES)
    for item in packet['seed_raw_commits']:
        raw = base64.b64decode(item['raw_base64'], validate=True)
        check(item['type'] == 'commit' and len(raw) == item['bytes'] and sha256(raw) == item['sha256'] and oid('commit', raw) == item['sha'], 'authentic original donor commit, no reserialization')
        expected = packet['donor'] if item['sha'] == DONOR_HEAD else packet['parent_snapshot']
        check(item['sha'] == expected['commit'] and raw_commit_fields(raw) == (expected['tree'], expected['parents']), 'original donor commit tree and ordered parents')
        check(item['sha'] not in raw_commits, 'one original donor commit')
        raw_commits[item['sha']] = raw
        add(item['sha'], {'type': 'commit', 'bytes': len(raw), 'sha256': sha256(raw)})
    donor_counts = {kind: sum(x['type'] == kind for x in object_index.values()) for kind in ('blob', 'tree', 'commit')}
    check(len(object_index) == 16449 and donor_counts == {'blob': 14615, 'tree': 1832, 'commit': 2} and set(raw_commits) == {DONOR_HEAD, packet['parent_snapshot']['commit']}, 'exact original donor two-snapshot union')
    donor_object_keys = set(object_index)
    def add_provided(value, count):
        check(len(value['objects']) == count, 'fixed provided object count')
        keys = set()
        for item in value['objects']:
            remaining()
            key = item['sha']
            check(key not in keys and item['type'] in ('blob', 'tree', 'commit'), 'unique recognized provided Git object')
            raw = base64.b64decode(item['raw_base64'], validate=True)
            check(base64.b64encode(raw).decode() == item['raw_base64'] and len(raw) == item['bytes'] and sha256(raw) == item['sha256'] and oid(item['type'], raw) == key, 'complete canonical provided object bytes')
            check(key not in donor_object_keys, 'provided object is not a substituted donor object')
            check(key not in provided_raw or provided_raw[key] == raw, 'provided raw overlap equality')
            keys.add(key)
            provided_raw[key] = raw
            add(key, {k: item[k] for k in ('type', 'bytes', 'sha256')})
            if item['type'] == 'tree':
                check(key not in raw_trees or raw_trees[key] == raw, 'provided tree raw equality')
                raw_trees[key] = raw
            elif item['type'] == 'commit':
                check(key not in raw_commits or raw_commits[key] == raw, 'provided commit raw equality')
                raw_commits[key] = raw
        return keys
    check(base_input['format'] == 'hepta-c0f-format-base-provided-objects-v1' and base_input['base'] == {k: packet['format_base'][k] for k in ('commit', 'tree', 'parents', 'inventory', 'leaves')}, 'exact immutable original format-base input')
    check(base_input['provided_count'] == 83 and base_input['required_existing_count'] == 16011, 'original format-base counts')
    base_provided = add_provided(base_input, 83)
    candidate_provided = add_provided(candidate_input, 120)
    check(sorted(base_provided & candidate_provided) == packet['object_scope']['provided_base_candidate_overlap'] == [], 'actual base and candidate provided sets disjoint')
    target_keys = add_snapshot(complete['files'], packet['current'], LEAVES)
    target_keys.add(HEAD)
    check(candidate_provided == target_keys - donor_object_keys, 'all and only the exact new candidate objects supplied')
    base_seen, base_rows = set(), []
    def walk_base(tree, prefix, ancestors):
        remaining()
        check(tree not in ancestors and tree in raw_trees and object_index[tree]['type'] == 'tree', 'complete bounded format-base tree graph')
        base_seen.add(tree)
        raw = raw_trees[tree]
        offset = 0
        entries = []
        while offset < len(raw):
            stop = raw.index(b'\0', offset)
            head = raw[offset:stop]
            mode, name = head.split(b' ', 1)
            check(mode in (b'40000', b'100644', b'100755', b'120000') and name and b'/' not in name and name not in (b'.', b'..') and name.lower() != b'.git', 'safe canonical format-base tree entry')
            check(stop + 21 <= len(raw), 'complete format-base tree object id')
            key = raw[stop + 1:stop + 21].hex()
            path = prefix + name.decode('utf-8')
            entries.append((name + (b'/' if mode == b'40000' else b''), raw[offset:stop + 21]))
            offset = stop + 21
            if mode == b'40000':
                walk_base(key, path + '/', ancestors | {tree})
            else:
                check(key in object_index and object_index[key]['type'] == 'blob', 'complete format-base blob belongs to the declared union')
                meta = object_index[key]
                base_seen.add(key)
                base_rows.append({'path': path, 'mode': mode.decode(), 'bytes': meta['bytes'], 'sha256': meta['sha256'], 'blob': key})
                check(len(base_rows) <= packet['format_base']['leaves'], 'format-base leaf count bounded')
        check(offset == len(raw) and len({entry[0] for entry in entries}) == len(entries) and entries == sorted(entries) and b''.join(item[1] for item in entries) == raw, 'canonical raw format-base tree ordering')
    walk_base(packet['format_base']['tree'], '', set())
    base_seen.add(packet['format_base']['commit'])
    base_counts = {kind: sum(object_index[key]['type'] == kind for key in base_seen) for kind in ('blob', 'tree', 'commit')}
    check(len(base_rows) == packet['format_base']['leaves'] == 14851 and len(base_seen) == packet['format_base']['objects'] == 16094 and base_counts == packet['format_base']['counts'], 'exact complete original c0f closure')
    check(base_provided == base_seen - donor_object_keys and len(base_seen & donor_object_keys) == packet['format_base']['required_donor_objects'] == 16011, 'complete c0f 83 supplied plus 16011 donor objects')
    projection = json.dumps(sorted(base_rows, key=lambda row: os.fsencode(row['path'])), sort_keys=True, separators=(',', ':')).encode()
    pin(projection, packet['format_base']['leaf_projection'], 'complete original c0f leaf identities')
    for expected in (packet['donor'], packet['parent_snapshot'], packet['format_base'], packet['current']):
        check(expected['commit'] in raw_commits and raw_commit_fields(raw_commits[expected['commit']]) == (expected['tree'], expected['parents']), 'four authentic raw commits with exact original parent references')
    check(set(raw_commits) == set(packet['object_scope']['complete_snapshot_commits']), 'only four declared raw commits')
    counts = {kind: sum(x['type'] == kind for x in object_index.values()) for kind in ('blob', 'tree', 'commit')}
    check(len(object_index) == packet['object_scope']['union_objects'] == 16652 and counts == packet['object_scope']['counts'] == {'blob': 14796, 'tree': 1852, 'commit': 4}, 'complete exact four-snapshot union, not ancestry')
    check(set(object_index) == donor_object_keys | base_seen | target_keys, 'no undeclared object outside the four complete snapshots')
    result['object_scope'] = {**packet['object_scope'], 'complete_ancestry': False, 'format_base_leaf_identities_verified': True, 'donor_objects_must_be_read_from_git_bodies': len(donor_object_keys)}
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
    expected = {x['path'] for x in donor_complete['files']}
    check(packet['donor']['allowed_missing_paths'] == [] and len(expected) == DONOR_LEAVES and physical_paths(SOURCE) == expected, 'all 15188 donor physical leaves; no missing-path recovery branch')
    audit, native_rows = [], []
    for row in donor_complete['files']:
        remaining()
        raw, observed = source_leaf(row)
        audit.append({'path': row['path'], 'identity': identity(raw), 'stable_stat': observed})
        native_rows.append({'path': row['path'], 'mode': row['index_mode'], 'bytes': len(raw), 'sha256': sha256(raw), 'blob': row['working_blob']})
    native = json.dumps(sorted(native_rows, key=lambda row: os.fsencode(row['path'])), sort_keys=True, separators=(',', ':')).encode()
    pin(native, packet['donor']['native_inventory'], 'complete actual unchanged donor source')
    data = encoded(audit)
    gzrecord(label + '.donor-physical.json', data)
    return {'records': audit, 'raw_identity': identity(data), 'native_inventory': identity(native), 'present': len(expected), 'missing': []}

def old_git_state(label):
    gd = SOURCE / '.git'
    real_directory(gd)
    check(command(SOURCE, ['rev-parse', '--absolute-git-dir']).decode().strip() == str(gd) and command(SOURCE, ['rev-parse', '--path-format=absolute', '--git-common-dir']).decode().strip() == str(gd), 'independent actual donor Git metadata directory')
    raw_metadata = git_metadata(label + '.donor', repo=SOURCE)
    pin(raw_metadata, packet['donor_proof']['current_git_metadata'], 'historical actual complete donor Git file identities and stat')
    check(parse(raw_metadata) == packet['donor_git']['files'], 'all six donor Git files unchanged, including independent pack/idx/rev')
    for relative in packet['donor_git']['absent_lookup_paths']:
        check(not os.path.lexists(SOURCE / relative), 'donor Git indirection and lock paths remain absent')
    refs = command(SOURCE, ['for-each-ref', '--format=%(refname) %(objectname)'])
    check(base64.b64encode(refs).decode() == packet['donor_git']['refs_base64'] == '', 'actual donor has no refs')
    head = regular_read(gd / 'HEAD', 1000)
    check(head == (DONOR_HEAD + '\n').encode(), 'actual donor detached HEAD')
    actual_head = command(SOURCE, ['rev-parse', 'HEAD']).decode().strip()
    actual_tree = command(SOURCE, ['rev-parse', 'HEAD^{tree}']).decode().strip()
    files = {row['path']: row for row in parse(raw_metadata)}
    actual = {'head_raw_sha256': sha256(head), 'head': actual_head, 'tree': actual_tree,
        'index_bytes': files['index']['bytes'], 'index_sha256': files['index']['sha256'],
        'config_bytes': files['config']['bytes'], 'config_sha256': files['config']['sha256'],
        'refs_bytes': len(refs), 'refs_sha256': sha256(refs)}
    check(actual == packet['donor_proof']['current_git_state'] and actual_head == DONOR_HEAD and actual_tree == DONOR_TREE, 'actual donor raw Git baseline equals its authentic materialization proof')
    value = {'files': parse(raw_metadata), 'refs': identity(refs), 'refs_base64': '', 'absent_lookup_paths': packet['donor_git']['absent_lookup_paths'], 'git_state': actual}
    jwrite(label + '.donor-git.json', value)
    return value

def parse_supervisor(raw, job_id):
    outer = parse(raw)
    value = parse(outer['content'][0]['text'].encode())
    check(not outer.get('isError') and value['job_id'] == job_id and value['state'] == 'succeeded' and value['exit_code'] == 0 and not value['timed_out'] and not value['cancelled'] and not value['automatic_retry'] and value['output_complete'] and value['output_durable'] and value['terminal_publication_confirmed'], 'actual original availability normal supervisor')
    return value

def preflight():
    global cfg, packet, complete, donor_complete, inventory_module, source_before, old_git_before, lock_fd, base_input, candidate_input
    check(os.getuid() == 1000, 'original non-root operator')
    cfg_raw = regular_read(CONFIG)
    cfg = parse(cfg_raw)
    check(cfg['status'] == 'APPROVED_CANDIDATE_ISOLATED_MATERIALIZATION' and cfg['root_execution_approved'] is True, 'candidate materialization remains HOLD')
    check(cfg['source_repo'] == str(SOURCE) and cfg['destination_repo'] == str(TARGET) and cfg['control'] == str(CONTROL) and cfg['action_seconds'] == 600 and cfg['record_seconds'] == 180, 'fixed scope and original preparation budgets')
    check(not os.path.lexists(TARGET), 'new isolated source must be absent; no retry, replacement, or reuse')
    read_input(CONFIG, identity(cfg_raw))
    read_input(pathlib.Path(__file__), cfg['driver'])
    packet = parse(retained_pin(PACKET, PACKET_PIN))
    check(packet['format'] == 'hepta-complete-candidate-isolated-materialization-packet-v1' and packet['source_repo'] == str(SOURCE) and packet['destination_repo'] == str(TARGET), 'fixed distinct donor and candidate packet')
    check(packet['donor']['commit'] == DONOR_HEAD and packet['donor']['tree'] == DONOR_TREE and packet['donor']['leaves'] == DONOR_LEAVES and packet['donor']['parents'] == [packet['parent_snapshot']['commit']], 'actual complete cc57 donor identity')
    check(packet['current']['commit'] == HEAD and packet['current']['tree'] == TREE and packet['current']['parents'] == [PARENT] and PARENT == DONOR_HEAD and packet['current']['leaves'] == LEAVES, 'exact new candidate source identity')
    check(packet['object_scope']['format'] == 'four-complete-snapshots-not-full-ancestry' and packet['qualification'] is False, 'bounded declared object scope')
    observed = parse(retained_pin(CONTROL / 'DONOR_RESULT.original.json', packet['donor_proof']['result']))
    parse_supervisor(retained_pin(CONTROL / 'DONOR_SUPERVISOR.original.json', packet['donor_proof']['supervisor']), packet['donor_proof']['job_id'])
    check(observed['format'] == 'hepta-isolated-cc57-materialization-result-v1' and observed['status'] == 'MATERIALIZED_EXACT_CC57_FOR_NATIVE_REVIEW_ONLY' and observed['destination_repo'] == str(SOURCE) and observed['source_commit'] == DONOR_HEAD and observed['source_tree'] == DONOR_TREE and observed['parents'] == packet['donor']['parents'], 'actual independent donor materialization proof, not a new qualification')
    check(observed['action_completed'] is True and observed['new_repo_created'] is True and observed['new_objects_fully_verified'] == 16449 and observed['input_identities_unchanged'] is True and observed['qualification'] is False and observed['cargo_or_formatter_started'] is False and observed['test_commands_dispatched'] == 0, 'completed preparation-only donor proof')
    check(len(observed['final_audits']) == 3 and all(item['status'] == 'verified' for item in observed['final_audits']) and observed['current_source_before'] == observed['current_source_after'] and observed['current_git_state_before'] == observed['current_git_state_after'] == packet['donor_proof']['current_git_state'] and observed['current_git_metadata'] == packet['donor_proof']['current_git_metadata'], 'all original donor source/Git/input audit facts')
    actual_inventory = observed['current_source_after']['inventory']
    check({key: actual_inventory[key] for key in ('bytes', 'sha256', 'git_blob')} == packet['donor']['inventory'] and actual_inventory['tracked_entries'] == actual_inventory['filesystem_entries'] == DONOR_LEAVES and observed['current_source_after']['native_inventory'] == packet['donor']['native_inventory'], 'actual full donor source and distinct native inventory')
    result['donor_materialization_proof'] = packet['donor_proof']
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
        raw = stream.read(packet['donor']['inventory']['bytes'] + 1)
        check(stream.read(1) == b'', 'bounded complete original canonical donor inventory')
    pin(raw, packet['donor']['inventory'], 'actual original complete donor inventory')
    donor_complete = parse(raw)
    check(donor_complete['source'] == {'head': DONOR_HEAD, 'tree': DONOR_TREE, 'status': ''} and donor_complete['tracked_entries'] == donor_complete['filesystem_entries'] == len(donor_complete['files']) == DONOR_LEAVES and all(row['stable'] and row['matches_index'] for row in donor_complete['files']), 'canonical original full donor source membership')
    base_input = load_provided_input('base')
    candidate_input = load_provided_input('candidate')
    derive_candidate_inventory()
    expected_graphs()
    old_git_before = old_git_state('before')
    source_before = source_physical('before')
    result['donor_source_before'] = {key: value for key, value in source_before.items() if key != 'records'}
    listing = b''.join((key + '\n').encode() for key in sorted(donor_object_keys))
    actual = command(SOURCE, ['cat-file', '--batch-check'], data=listing)
    expected = b''.join((key + ' ' + object_index[key]['type'] + ' ' + str(object_index[key]['bytes']) + '\n').encode() for key in sorted(donor_object_keys))
    check(actual == expected, 'all original donor objects available; complete body reads remain mandatory during import')
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
    before_by_path = {row['path']: row for row in source_before['records']}
    donor_rows = {row['path']: row for row in donor_complete['files']}
    pack_path = OUT / 'INDEPENDENT_OBJECTS.input.pack'
    action = mutation_intent('write_exact_new_physical_source_and_standard_pack', source_leaves=LEAVES, object_count=len(object_index))
    journal_stream = (OUT / 'PHYSICAL_CREATION_JOURNAL.jsonl').open('xb')
    for number, row in enumerate(complete['files'], 1):
        remaining()
        key = row['working_blob']
        original = donor_rows.get(row['path'])
        if original == row:
            raw, current_stat = source_leaf(original)
            check(before_by_path[row['path']]['stable_stat'] == current_stat, 'same complete donor leaf while copying')
        else:
            check(key in provided_raw and object_index[key]['type'] == 'blob', 'changed/new candidate leaf has exact reviewed raw bytes')
            raw = pin(provided_raw[key], identity_projection(row), 'actual provided candidate leaf before creation')
        destination_leaf(row, raw)
        if number % 1024 == 0:
            event('fresh_physical_leaves', completed=number, total=LEAVES)
    source_reader = ObjectReader(SOURCE, 'original-donor-bodies')
    pack_hash, pack_sha256 = hashlib.sha1(), hashlib.sha256()
    included, donor_verified = set(), []
    with pack_path.open('xb') as stream:
        def put(raw):
            stream.write(raw)
            pack_hash.update(raw)
            pack_sha256.update(raw)
        put(b'PACK' + struct.pack('>II', 2, len(object_index)))
        for key in sorted(object_index):
            remaining()
            expected = object_index[key]
            if key in donor_object_keys:
                raw = source_reader.get(key, expected)
                donor_verified.append({'sha': key, **expected})
            else:
                check(key in provided_raw, 'all non-donor objects are supplied by exact immutable inputs')
                raw = provided_raw[key]
            check(len(raw) == expected['bytes'] and sha256(raw) == expected['sha256'] and oid(expected['type'], raw) == key, 'complete original raw object before independent import')
            if key in raw_trees:
                check(raw == raw_trees[key], 'actual full donor/provided tree equals complete derived raw tree')
            if key in raw_commits:
                check(raw == raw_commits[key], 'actual full authentic commit bytes')
            check(key not in included, 'one copy of every independent Git object')
            put(pack_entry_header(expected['type'], len(raw)))
            put(zlib.compress(raw))
            included.add(key)
        check(set(included) == set(object_index) and len(donor_verified) == 16449, 'complete fixed independent union and every reused donor full body')
        footer = pack_hash.digest()
        stream.write(footer)
        pack_sha256.update(footer)
        stream.flush()
        os.fsync(stream.fileno())
        size = stream.tell()
    journal_stream.close()
    journal_stream = None
    source_reader.close()
    gzrecord('DONOR_OBJECT_READBACK.json', encoded(donor_verified))
    result['donor_objects_fully_verified'] = len(donor_verified)
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
    check(command(TARGET, ['write-tree'], mutation=True).decode().strip() == TREE, 'new normal index exact Merkle tree')
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
    check(set(entries) == {row['path'] for row in complete['files']}, 'all exact new candidate index entries')
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

def git_metadata(label, repo=TARGET):
    check(repo in (SOURCE, TARGET), 'only fixed donor/new Git metadata directories')
    rows = []
    for directory, children, files in os.walk(repo / '.git', followlinks=False):
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
            rows.append({'path': path.relative_to(repo / '.git').as_posix(), 'bytes': before.st_size, 'sha256': digest.hexdigest(), 'git_blob': blob.hexdigest(), 'stat': stat_identity(before)})
    rows.sort(key=lambda row: row['path'].encode())
    raw = encoded(rows)
    gzrecord(label + '.git-metadata.json', raw)
    return raw

def final_old():
    current = source_physical('final')
    check(current == source_before, 'all original donor physical leaves and stable metadata unchanged')
    current_git = old_git_state('final')
    check(current_git == old_git_before, 'complete donor Git file bytes/stat and no-ref state unchanged')
    result['donor_source_after'] = {key: value for key, value in current.items() if key != 'records'}
    result['donor_git_state_before'] = old_git_before
    result['donor_git_state_after'] = current_git
    result['donor_physical_and_git_file_state_unchanged'] = True
    result['donor_git_observation_scope'] = {'complete_git_file_listing_and_bytes_and_stat': True, 'complete_ref_listing_unchanged': True, 'absent_lookup_paths': current_git['absent_lookup_paths'], 'directory_metadata_or_unrelated_old_repository_observed': False}

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
            for name, method, available in [('donor_physical_source_and_git_files', final_old, source_before is not None and old_git_before is not None), ('new_source_and_git', final_new, new_source_before is not None and new_git_before is not None), ('inputs_and_coordination', final_inputs, lock_fd is not None and cfg is not None)]:
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
                result['status'] = 'MATERIALIZED_EXACT_CANDIDATE_FOR_MAINTENANCE_REVIEW_ONLY' if success else 'FAILED_CANDIDATE_MATERIALIZATION'
                result['old_source_writes'] = False
                result['finished_at'] = now()
                result['command_records'] = jwrite('COMMANDS.json', commands)
                result['mutation_records'] = jwrite('MUTATION_INTENTS.json', intents)
                result['input_records'] = jwrite('INPUT_IDENTITIES.before.json', inputs)
                result['artifact_records'] = jwrite('ARTIFACTS.json', artifacts)
                jwrite('RESULT.json', result)
                event('isolated_materialization_complete', status=result['status'], qualification=False)
            finally:
                disarm()
                if lock_fd is not None:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    os.close(lock_fd)
    raise SystemExit(0 if result.get('status') == 'MATERIALIZED_EXACT_CANDIDATE_FOR_MAINTENANCE_REVIEW_ONLY' else 1)

if __name__ == '__main__':
    main()
