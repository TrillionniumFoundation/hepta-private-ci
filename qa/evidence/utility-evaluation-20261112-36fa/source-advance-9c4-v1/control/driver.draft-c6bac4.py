#!/usr/bin/env python3
"""One reviewed, forward-only local source advance. Preparation, never qualification.

Only six authentic objects, one physical file, its index entry/cache tree, and
the detached HEAD may change. A partial failure is retained; no rollback or retry.
"""
from __future__ import annotations
import base64, datetime, fcntl, gzip, hashlib, json, os, pathlib, select
import shutil, signal, stat, struct, subprocess, sys, time, traceback, types, zlib

REPO = pathlib.Path('/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1')
CONTROL = pathlib.Path('/home/qian-qi/hepta-utility-36fa-evidence/source-advance-9c4-v1')
OUT = CONTROL / 'run'
CONFIG = CONTROL / 'APPROVED_CONFIG.json'
PACKET = CONTROL / 'CANONICAL_PACKET.json'
CONTRACT = CONTROL / 'SOURCE_ADVANCE_CONTRACT.json'
INVENTORY = pathlib.Path('/home/qian-qi/hepta-utility-36fa-evidence/fresh-maintenance-86dd-v1/inventory-driver-v2.py')
GIT = '/usr/bin/git'
OLD = '86dd56a930277e0d1aef3e475e35c2b5d60b43b7'
OLD_TREE = '383ab85c39ef9d848252ef5c25922d13d9fae6c6'
OLD_PARENTS = ['c0f78493f815780f68b9bf5e390a21314d79311f', 'a96d1b821d10ed3d9e99dd06c5141f9f242ae318']
NEW = '9c4a11f61d30e9cc352bf44d56c98909d202a55d'
NEW_TREE = 'ee42ec7e6289e0ccdbe03a5af0b39216a5a6dab7'
CHANGED = 'codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_original_ports_tests.rs'
LEAVES = 15188
ACTION_SECONDS = 600
RECORD_SECONDS = 180
BEFORE_INDEX = {'bytes':2072488, 'sha256':'b19fab7a860a4281331096bd6a9c2ab5b6b9ef95ff8411e9f757cd1373380f15'}
PACKET_PIN = {'bytes':98087, 'sha256':'e72cd85a68ff67412865f14a76c398cd1f26b8c948a16da4bfe5155c300000e0', 'git_blob':'a62a7e701f42ea18dfa93fc0d5eb521f836750cb'}
CONTRACT_PIN = {'bytes':6589, 'sha256':'ff781d283f274cb20115734cf007e3f7c2565468381205ebd4df8aa2652ae977', 'git_blob':'a1ef48291d34646c4c5c763ba51a63d32a76c3f7'}
INVENTORY_PIN = {'bytes':22946, 'sha256':'20c11034146f6739dd24e9d7e33b94ee909754b07ce6295c242c842c5f3c40b2', 'git_blob':'51181866cbbb6e0176aab04117efffa8b6792b31'}
GIT_PIN = {'bytes':4066232, 'sha256':'eb54b535467e0975c1284d4c4d08eea779aeb248a5d34b02e2ee171382e22201'}

artifacts = []
commands = []
inputs = {}
intents = []
deadline = None
cfg = packet = inventory_module = None
before_inventory = before_git = before_metadata = before_index = None
after_inventory = after_git = None
object_raw = {}
object_added = []
result = {
    'format':'hepta-exact-source-advance-result-v1', 'status':'HOLD',
    'source_repo':str(REPO), 'local_head_advanced':False,
    'source_branch_refs_updated':False, 'remote_ref_updates':False,
    'dependency_installation_started':False, 'cargo_or_formatter_started':False,
    'test_commands_dispatched':0, 'qualification':False, 'automatic_retry':False,
    'final_audits':[], 'actual':{}, 'mutation_intents':intents,
    'scope':'Two exact snapshots and six canonical objects; no recursive historical ancestry/fsck.'
}

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

def regular_read(path, maximum=40000000):
    path = pathlib.Path(path)
    real_directory(path.parent)
    fd = os.open(path, os.O_RDONLY|os.O_NOFOLLOW)
    try:
        a = os.fstat(fd)
        check(stat.S_ISREG(a.st_mode) and a.st_nlink==1 and a.st_uid==os.getuid(), 'regular owned single-link input: '+str(path))
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

def intent(kind, **details):
    row = {'ordinal':len(intents)+1,'at':now(),'action':kind,'terminal':'unknown_not_observed',**details}
    jwrite('intent-%02d.json'%row['ordinal'],row)
    intents.append(row)
    return row

def command(args, data=None, mutation=False, allow_nonzero=False):
    argv = [GIT,'--no-optional-locks','-c','core.fsmonitor=false','-c','core.untrackedCache=false',
            '-c','diff.autoRefreshIndex=false','-c','core.logAllRefUpdates=false','-C',str(REPO),*args]
    row = {'argv':argv,'started_at':now(),'purpose':'authorized mutation' if mutation else 'read-only',
           'actual_terminal':'unknown_not_observed'}
    commands.append(row)
    prefix = 'command-%03d'%len(commands)
    jwrite(prefix+'.intent.json',row)
    if data is not None:
        row['stdin'] = write(prefix+'.stdin',data)
    process = None
    try:
        process = subprocess.Popen(argv,stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                                   stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=REPO)
        try:
            stdout,stderr = process.communicate(data,timeout=remaining())
        except subprocess.TimeoutExpired:
            process.kill()
            stdout,stderr = process.communicate()
            row.update(timed_out=True,returncode=process.returncode,actual_terminal='observed')
            write(prefix+'.stdout',stdout);write(prefix+'.stderr',stderr)
            raise
        row.update(returncode=process.returncode,timed_out=False,actual_terminal='observed')
        row['stdout'] = write(prefix+'.stdout',stdout)
        row['stderr'] = write(prefix+'.stderr',stderr)
        if not allow_nonzero:
            check(process.returncode==0,'Git command failed: '+repr(args))
        return stdout,process.returncode
    finally:
        if process is not None and process.poll() is None:
            process.kill(); process.wait()
        row['finished_at'] = now()
        jwrite(prefix+'.terminal.json',row)

def git(*args):
    return command(list(args))[0]

def git_state(commit, tree):
    gd = REPO/'.git'
    real_directory(gd)
    check(git('rev-parse','--absolute-git-dir').decode().strip()==str(gd) and
          git('rev-parse','--path-format=absolute','--git-common-dir').decode().strip()==str(gd), 'independent Git directory')
    for relative in ('objects/info/alternates','shallow','info/grafts','index.lock','HEAD.lock'):
        check(not os.path.lexists(gd/relative),'unexpected Git indirection/lock: '+relative)
    raw_head = regular_read(gd/'HEAD',1000)
    index = regular_read(gd/'index')
    config = regular_read(gd/'config',1000000)
    refs = git('for-each-ref','--format=%(refname) %(objectname)')
    check(raw_head==(commit+'\n').encode() and not refs,'exact detached HEAD and no branch refs')
    check(git('rev-parse','HEAD').decode().strip()==commit and
          git('rev-parse','HEAD^{tree}').decode().strip()==tree,'exact observed HEAD/tree')
    return {'head_raw_sha256':sha256(raw_head),'head':commit,'tree':tree,
            'index_bytes':len(index),'index_sha256':sha256(index),'config_bytes':len(config),
            'config_sha256':sha256(config),'refs_bytes':len(refs),'refs_sha256':sha256(refs)}

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

def index_preservation(old, new):
    a,ae = parse_index(old); b,be = parse_index(new)
    check(set(a)==set(b),'index path membership unchanged')
    check(all(a[p]['raw']==b[p]['raw'] for p in a if p!=CHANGED),'unaltered 15187 entries retain exact stat/flags/padding')
    change = packet['changed_source'][0]
    check(a[CHANGED]['sha']==change['before_git_blob'] and b[CHANGED]['sha']==change['after_git_blob'] and
          a[CHANGED]['mode']==b[CHANGED]['mode']=='100644' and a[CHANGED]['flags']==b[CHANGED]['flags'],
          'only reviewed blob changes in the one index entry')
    check([x for x in ae if x['name']!='TREE']==[x for x in be if x['name']!='TREE'],
          'all non-cache-tree index extensions remain exact')
    s = (REPO/CHANGED).lstat()
    fs = b[CHANGED]['stat']
    actual = (s.st_ctime_ns//1000000000,s.st_ctime_ns%1000000000,s.st_mtime_ns//1000000000,
              s.st_mtime_ns%1000000000,s.st_dev&0xffffffff,s.st_ino&0xffffffff,0o100644,
              s.st_uid,s.st_gid,s.st_size&0xffffffff)
    check(fs==actual,'modified index entry contains actual current stat, not zero-stat reconstruction')
    return {'unchanged_entries':LEAVES-1,'raw_entry_bytes_equal':True,
            'changed_path':CHANGED,'changed_entry_stat_matches_actual_file':True,
            'other_extensions_unchanged':True,
            'before_cache_tree':[{'name':x['name'],'bytes':x['bytes'],'sha256':sha256(x['raw'])} for x in ae],
            'after_cache_tree':[{'name':x['name'],'bytes':x['bytes'],'sha256':sha256(x['raw'])} for x in be]}

def metadata_inventory():
    root = REPO/'.git'
    rows = []
    for directory, dirs, files in os.walk(root,followlinks=False):
        parent = pathlib.Path(directory)
        for name in sorted(dirs+files,key=os.fsencode):
            path = parent/name
            s = path.lstat()
            row = {'path':path.relative_to(root).as_posix(),'mode':stat.S_IMODE(s.st_mode),
                   'uid':s.st_uid,'gid':s.st_gid,'device':s.st_dev,'inode':s.st_ino,
                   'nlink':s.st_nlink,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns}
            if stat.S_ISDIR(s.st_mode):
                row['kind']='directory'
            else:
                check(stat.S_ISREG(s.st_mode),'Git metadata must be real directories/files')
                raw = regular_read(path,512*1024*1024)
                row.update(kind='file',bytes=len(raw),sha256=sha256(raw))
            rows.append(row)
    return {'root':str(root),'files':sorted(rows,key=lambda x:os.fsencode(x['path']))}

def verify_metadata(before, after):
    a = {r['path']:r for r in before['files']}; b = {r['path']:r for r in after['files']}
    allowed_new = {'objects/'+x[:2]+'/'+x[2:] for x in object_added}
    allowed_dirs = {'objects/'+x[:2] for x in object_added}
    check(not set(a)-set(b),'no pre-existing Git metadata may disappear')
    check(set(b)-set(a)<=allowed_new|allowed_dirs,'no unreviewed new Git metadata')
    changes = []
    for path in sorted(set(a)|set(b)):
        old = a.get(path); new = b.get(path)
        if old==new:
            continue
        if path in ('HEAD','index'):
            check(new['kind']=='file' and new['uid']==os.getuid() and new['nlink']==1,'safe new HEAD/index')
        elif path in allowed_new:
            check(old is None and new['kind']=='file','only missing canonical loose object may be added')
            obj = path.split('/')[-2]+path.split('/')[-1]
            raw = regular_read(REPO/'.git'/path)
            expanded = zlib.decompress(raw)
            expected_type = next(o['type'] for o in packet['objects'] if o['sha']==obj)
            check(expanded==expected_type.encode()+b' '+str(len(object_raw[obj])).encode()+b'\0'+object_raw[obj],
                  'actual added loose object body')
        elif path=='objects' or path in allowed_dirs:
            check(new['kind']=='directory','object directories only')
            if old is not None:
                check(all(old[k]==new[k] for k in old if k not in ('mtime_ns','ctime_ns','nlink')),'existing object directory identity/mode unchanged')
        else:
            check(False,'unexpected pre-existing Git metadata change: '+path)
        changes.append({'path':path,'before':old,'after':new})
    return changes

def inventory_summary(raw):
    value = parse(raw)
    check(value['tracked_entries']==LEAVES and value['filesystem_entries']==LEAVES,'full physical/index population')
    check(all(r.get('matches_index') is True and r.get('stable') is True for r in value['files']), 'full source/index bytes must agree')
    return {'bytes':len(raw),'sha256':sha256(raw),'git_blob':oid('blob',raw),
            'tracked_entries':value['tracked_entries'],'filesystem_entries':value['filesystem_entries']}

def verify_commit(commit, tree, parents):
    raw = git('cat-file','commit',commit)
    lines = raw.split(b'\n\n',1)[0].split(b'\n')
    check(oid('commit',raw)==commit and lines[0]==('tree '+tree).encode() and
          [line[7:].decode() for line in lines if line.startswith(b'parent ')]==parents,'authentic original commit/tree/ordered parents')
    return raw

def snapshot(tree):
    raw = git('ls-tree','-r','-t','-z','--full-tree',tree)
    leaves = {}; objects = {tree:'tree'}
    for record in raw.split(b'\0'):
        if not record:
            continue
        meta,path = record.split(b'\t',1)
        mode,kind,value = meta.decode().split()
        path = path.decode('utf-8')
        check(mode in ('040000','100644','100755','120000') and kind in ('tree','blob'),'snapshot type/mode')
        check(not path.startswith('/') and all(p not in ('','.','..','.git') for p in path.split('/')),'safe snapshot path')
        check(value not in objects or objects[value]==kind,'consistent object types')
        objects[value]=kind
        if kind=='blob':
            check(path not in leaves,'unique snapshot leaf')
            leaves[path]={'mode':mode,'sha':value}
    check(len(leaves)==LEAVES,'complete snapshot leaf count')
    return leaves,objects

def verify_object_union(objects, expected_blobs):
    """Read each required snapshot object once; no commit ancestry traversal."""
    order = sorted(objects)
    listing = b''.join((obj+'\n').encode() for obj in order)
    write('OBJECT_REQUESTS.txt',listing)
    argv = [GIT,'--no-optional-locks','-C',str(REPO),'cat-file','--batch']
    row = {'argv':argv,'started_at':now(),'purpose':'full two-snapshot original object validation',
           'actual_terminal':'unknown_not_observed','stdin_sha256':sha256(listing),'objects':len(order),
           'raw_payload_scope':'Per-object exact full bytes are hashed; six canonical bodies remain in the original packet. No new history reads.'}
    commands.append(row)
    jwrite('OBJECT_BATCH.intent.json',row)
    observed = []
    proc = None
    def read_exact(stream, size):
        chunks = []; count = 0
        while count<size:
            check(select.select([stream],[],[],remaining())[0], 'object batch read deadline')
            part = os.read(stream.fileno(),min(size-count,1048576))
            check(part,'short original Git object stream')
            chunks.append(part); count+=len(part)
        return b''.join(chunks)
    try:
        with open(OUT/'OBJECT_REQUESTS.txt','rb') as requests, open(OUT/'OBJECT_BATCH.stderr','xb') as errors:
            proc = subprocess.Popen(argv,stdin=requests,stdout=subprocess.PIPE,stderr=errors,cwd=REPO,bufsize=0)
            for expected in order:
                header = b''
                while not header.endswith(b'\n'):
                    check(len(header)<160,'object header bound')
                    header+=read_exact(proc.stdout,1)
                fields = header.rstrip(b'\n').split(b' ')
                check(len(fields)==3 and fields[0].decode()==expected and fields[1].decode()==objects[expected],'exact original object header/type')
                size = int(fields[2]); check(0<=size<=40000000,'single-object size bound')
                body = read_exact(proc.stdout,size)
                check(read_exact(proc.stdout,1)==b'\n','original object delimiter')
                check(oid(objects[expected],body)==expected,'original object body/hash')
                if expected in object_raw:
                    check(body==object_raw[expected],'canonical object exact raw readback')
                if expected in expected_blobs:
                    check((len(body),sha256(body))==expected_blobs[expected],'original snapshot blob bytes')
                observed.append({'sha':expected,'type':objects[expected],'bytes':size,'sha256':sha256(body)})
            check(proc.stdout.read(1)==b'','unexpected trailing object payload')
            row['returncode']=proc.wait(timeout=remaining())
            row['actual_terminal']='observed'
            errors.flush();os.fsync(errors.fileno())
            check(row['returncode']==0,'object batch terminal')
        gzrecord('VERIFIED_OBJECTS.json',encoded(observed))
        result['actual']['verified_snapshot_objects']=len(observed)
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill();proc.wait()
        row['finished_at']=now();row['objects_observed']=len(observed)
        jwrite('OBJECT_BATCH.terminal.json',row)

def load_inventory():
    raw = read_input(INVENTORY,INVENTORY_PIN)
    module = types.ModuleType('source_advance_exact_inventory')
    module.__file__=str(INVENTORY)
    exec(compile(raw,str(INVENTORY),'exec'),module.__dict__)
    return module

def preflight():
    global cfg, packet, inventory_module, before_inventory, before_git, before_metadata, before_index
    raw_config = regular_read(CONFIG)
    cfg = parse(raw_config)
    inputs[str(CONFIG)]={'bytes':len(raw_config),'sha256':sha256(raw_config),'git_blob':oid('blob',raw_config)}
    check(cfg.get('status')=='APPROVED_FOR_ONE_SOURCE_ADVANCE' and cfg.get('root_execution_approved') is True,
          'HOLD configuration is never executable')
    check(cfg['source_repo']==str(REPO) and cfg['control_dir']==str(CONTROL) and cfg['output_dir']==str(OUT), 'fixed source/control/output')
    check(cfg['before_commit']==OLD and cfg['after_commit']==NEW and cfg['action_seconds']==ACTION_SECONDS and
          cfg['record_seconds']==RECORD_SECONDS and cfg['test_commands_authorized'] is False and
          cfg['dependency_installation_authorized'] is False and cfg['remote_ref_updates_authorized'] is False, 'fixed operation scope')
    read_input(pathlib.Path(__file__),cfg['driver'])
    check(os.getuid()==1000 and shutil.which('git')==GIT,'fixed operator and actual Git path')
    # Git is system-owned; unlike source/control inputs its expected owner is root.
    tool=pathlib.Path(GIT);s=tool.lstat()
    check(stat.S_ISREG(s.st_mode) and not stat.S_ISLNK(s.st_mode) and s.st_uid==0,'fixed Git executable')
    with tool.open('rb') as stream: git_bytes=stream.read()
    pin(git_bytes,GIT_PIN,'actual Git executable')
    inputs[str(tool)] = GIT_PIN
    for key in ('GIT_DIR','GIT_WORK_TREE','GIT_INDEX_FILE','GIT_COMMON_DIR','GIT_OBJECT_DIRECTORY',
                'GIT_ALTERNATE_OBJECT_DIRECTORIES','GIT_CONFIG_COUNT','GIT_CONFIG_PARAMETERS'):
        check(not os.environ.get(key),'unexpected inherited Git redirection: '+key)
    packet = parse(read_input(PACKET,PACKET_PIN))
    contract = parse(read_input(CONTRACT,CONTRACT_PIN))['successful_result_required_fields']
    check(packet['source_repo']==str(REPO) and packet['before']['commit']==OLD and packet['before']['tree']==OLD_TREE and
          packet['after']['commit']==NEW and packet['after']['tree']==NEW_TREE and packet['after']['parents']==[OLD], 'canonical packet endpoints')
    check(packet['complete_leaf_count']==LEAVES and packet['changed_source']==contract['changes'] and
          len(packet['changed_source'])==1 and packet['changed_source'][0]['path']==CHANGED, 'one reviewed test-port change')
    check(len(packet['objects'])==6 and sorted(o['type'] for o in packet['objects'])==['blob','commit','tree','tree','tree','tree'], 'six canonical objects')
    for obj in packet['objects']:
        raw = base64.b64decode(obj['raw_base64'],validate=True)
        check(len(raw)==obj['bytes'] and sha256(raw)==obj['sha256'] and oid(obj['type'],raw)==obj['sha'], 'canonical raw original object identity')
        check(obj['sha'] not in object_raw,'duplicate canonical object')
        object_raw[obj['sha']] = raw
    change = packet['changed_source'][0]
    check(change['after_git_blob'] in object_raw and NEW in object_raw and NEW_TREE in object_raw,'canonical object membership')
    expected_proofs = contract['seed_proofs']
    check(set(cfg['seed_proofs'])==set(expected_proofs),'three exact historical proof bindings')
    for name, expected in expected_proofs.items():
        descriptor = cfg['seed_proofs'][name]
        check(descriptor['pin']==expected,'original historical proof pin')
        read_input(descriptor['path'],expected)
    result.update(seed_proofs=expected_proofs,canonical_packet=PACKET_PIN,changes=packet['changed_source'])
    inventory_module = load_inventory()
    before_git = git_state(OLD,OLD_TREE)
    check(before_git['index_bytes']==BEFORE_INDEX['bytes'] and before_git['index_sha256']==BEFORE_INDEX['sha256'], 'actual original stat-populated index, not reconstructed zero-stat seed')
    before_index = regular_read(REPO/'.git'/'index')
    parse_index(before_index)
    gzrecord('INDEX.before.raw',before_index)
    jwrite('GIT_STATE.before.json',before_git)
    before_metadata = metadata_inventory()
    gzrecord('GIT_METADATA.before.json',encoded(before_metadata))
    before_inventory = inventory_module.inventory(REPO)
    gzrecord('SOURCE.before.inventory.json',before_inventory)
    check(inventory_summary(before_inventory)==contract['before']['inventory'],'complete actual original source identity')
    check(git_state(OLD,OLD_TREE)==before_git,'initial source inspection leaves Git raw state unchanged')
    verify_commit(OLD,OLD_TREE,OLD_PARENTS)
    oldblob = git('cat-file','blob',change['before_git_blob'])
    pin(oldblob,{'bytes':change['before_bytes'],'sha256':change['before_sha256'],'git_blob':change['before_git_blob']},'original test-port blob')
    check(regular_read(REPO/CHANGED)==oldblob,'actual original physical test-port')
    write('CHANGED.before.rs',oldblob)
    newblob = object_raw[change['after_git_blob']]
    write('CHANGED.after.reviewed.rs',newblob)
    check(newblob.count(b'pub(crate) use super::super::connection::recovered_peer;\n')==1 and
          newblob.replace(b'pub(crate) use super::super::connection::recovered_peer;\n',b'',1)==oldblob,
          'exact one-line reviewed source addition')
    result['before']={'commit':OLD,'tree':OLD_TREE,'parents':OLD_PARENTS,
                      'inventory':inventory_summary(before_inventory),'git_state':before_git}
    event('preconditions_verified',source_commit=OLD,tree=OLD_TREE,tracked_entries=LEAVES)

def import_objects():
    for obj in packet['objects']:
        raw = object_raw[obj['sha']]
        _, code = command(['cat-file','-e',obj['sha']],allow_nonzero=True)
        if code==0:
            check(git('cat-file',obj['type'],obj['sha'])==raw,'pre-existing canonical body')
            continue
        check(code==1,'absence must be an explicit cat-file missing status')
        action = intent('import_missing_canonical_object',sha=obj['sha'],type=obj['type'],bytes=len(raw))
        observed = command(['hash-object','-t',obj['type'],'-w','--stdin'],data=raw,mutation=True)[0]
        check(observed==(obj['sha']+'\n').encode(),'imported authentic object SHA')
        check(git('cat-file',obj['type'],obj['sha'])==raw,'exact imported raw readback')
        object_added.append(obj['sha'])
        action.update(terminal='observed',completed_at=now())
    verify_commit(NEW,NEW_TREE,[OLD])
    old_leaves, old_objects = snapshot(OLD_TREE)
    new_leaves, new_objects = snapshot(NEW_TREE)
    check(set(old_leaves)==set(new_leaves),'full snapshot path set unchanged')
    check([p for p in old_leaves if old_leaves[p]!=new_leaves[p]]==[CHANGED],'full snapshot delta exactly one path')
    rows = parse(before_inventory)['files']
    expected_blobs = {}
    for row in rows:
        check(old_leaves[row['path']]=={'mode':row['index_mode'],'sha':row['index_blob']}, 'original full tree/index/physical relation')
        val = (row['bytes'],row['sha256'])
        check(row['index_blob'] not in expected_blobs or expected_blobs[row['index_blob']]==val,'same original blob has consistent byte evidence')
        expected_blobs[row['index_blob']] = val
    change=packet['changed_source'][0]
    check(new_leaves[CHANGED]=={'mode':change['mode'],'sha':change['after_git_blob']},'new original tree entry')
    expected_blobs[change['after_git_blob']] = (change['after_bytes'],change['after_sha256'])
    objects = {**old_objects,**new_objects,OLD:'commit',NEW:'commit'}
    verify_object_union(objects,expected_blobs)
    result['actual']['verified_canonical_objects']=6
    jwrite('OBJECT_IMPORT.json',{'verified_objects':6,'actually_added_objects':object_added,'existing_objects_retained':True})

def advance_source():
    change = packet['changed_source'][0]
    check(git_state(OLD,OLD_TREE)==before_git,'CAS source precondition before any physical/index/HEAD write')
    current = inventory_module.inventory(REPO)
    check(current==before_inventory,'complete original source still exact immediately before mutation')
    path = REPO/CHANGED
    old_stat = path.lstat()
    check(stat.S_ISREG(old_stat.st_mode) and old_stat.st_nlink==1 and old_stat.st_uid==os.getuid() and
          stat.S_IMODE(old_stat.st_mode)==0o644,'single owned original source file')
    old_bytes = regular_read(path)
    pin(old_bytes,{'bytes':change['before_bytes'],'sha256':change['before_sha256'],'git_blob':change['before_git_blob']},'physical mutation preimage')
    temporary = path.with_name(path.name+'.hepta-source-advance-9c4-v1.tmp')
    check(not os.path.lexists(temporary),'create-only source temporary path')
    action = intent('replace_reviewed_single_source_file',path=CHANGED,temporary=str(temporary),
                    before_git_blob=change['before_git_blob'],after_git_blob=change['after_git_blob'])
    fd = os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,stat.S_IMODE(old_stat.st_mode))
    with os.fdopen(fd,'wb') as stream:
        stream.write(object_raw[change['after_git_blob']]);stream.flush();os.fsync(stream.fileno())
        os.fchmod(stream.fileno(),stat.S_IMODE(old_stat.st_mode))
    check(regular_read(temporary)==object_raw[change['after_git_blob']],'source temporary full readback')
    current_stat=path.lstat()
    check(all(getattr(old_stat,k)==getattr(current_stat,k) for k in
              ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns','st_mode','st_uid','st_nlink')) and
          regular_read(path)==old_bytes,'source preimage stable at publication')
    os.replace(temporary,path)
    directory = os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(directory)
    finally:os.close(directory)
    check(regular_read(path)==object_raw[change['after_git_blob']],'actual physical source after publication')
    action.update(terminal='observed',completed_at=now())
    action = intent('update_index_single_cacheinfo',path=CHANGED,mode='100644',sha=change['after_git_blob'])
    command(['update-index','--cacheinfo','100644',change['after_git_blob'],CHANGED],mutation=True)
    action.update(terminal='observed',completed_at=now())
    action = intent('refresh_actual_index_stat',path=CHANGED)
    command(['update-index','--refresh','--',CHANGED],mutation=True)
    action.update(terminal='observed',completed_at=now())
    action = intent('write_and_verify_actual_index_tree',expected_tree=NEW_TREE)
    check(command(['write-tree'],mutation=True)[0]==(NEW_TREE+'\n').encode(),'actual index write-tree exact successor')
    index_raw = regular_read(REPO/'.git'/'index')
    jwrite('INDEX_PRESERVATION.json',index_preservation(before_index,index_raw))
    gzrecord('INDEX.pre-head-cas.raw',index_raw)
    action.update(terminal='observed',completed_at=now())
    check(regular_read(REPO/'.git'/'HEAD')==(OLD+'\n').encode(),'actual detached HEAD remains original before CAS')
    action = intent('advance_detached_HEAD_compare_and_swap',expected_old=OLD,new=NEW)
    command(['update-ref','--no-deref','HEAD',NEW,OLD],mutation=True)
    check(regular_read(REPO/'.git'/'HEAD')==(NEW+'\n').encode(),'detached HEAD CAS actual new bytes')
    result['local_head_advanced']=True
    action.update(terminal='observed',completed_at=now())

def final_source():
    global after_inventory, after_git
    raw = inventory_module.inventory(REPO)
    gzrecord('SOURCE.final.inventory.json',raw)
    summary = inventory_summary(raw)
    after_inventory = raw
    after_git = git_state(NEW,NEW_TREE)
    jwrite('GIT_STATE.final.json',after_git)
    expected = parse(read_input(CONTRACT,CONTRACT_PIN))['successful_result_required_fields']['after']['inventory']
    check(summary==expected,'actual complete successor inventory must equal reviewed prediction')
    a = {r['path']:r for r in parse(before_inventory)['files']}
    b = {r['path']:r for r in parse(raw)['files']}
    check(set(a)==set(b) and all(a[p]==b[p] for p in a if p!=CHANGED),'other 15187 full physical records unchanged')
    result['after']={'commit':NEW,'tree':NEW_TREE,'parents':[OLD],'inventory':summary,'git_state':after_git}
    result['actual'].update(physical_bytes_equal=True,other_tracked_paths_unchanged=True)

def final_git():
    raw = regular_read(REPO/'.git'/'index')
    gzrecord('INDEX.final.raw',raw)
    preservation = index_preservation(before_index,raw)
    jwrite('INDEX.final-preservation.json',preservation)
    current = git_state(NEW,NEW_TREE)
    check(after_git is not None and current==after_git,'final exact raw Git state stable')
    check(all(current[k]==before_git[k] for k in ('config_bytes','config_sha256','refs_bytes','refs_sha256')), 'no config or branch ref changes')
    actual = metadata_inventory()
    gzrecord('GIT_METADATA.final.json',encoded(actual))
    changes = verify_metadata(before_metadata,actual)
    jwrite('GIT_METADATA.allowed-actual-delta.json',changes)
    staged = git('ls-files','--stage','-z')
    expected = b''
    for p,row in sorted(((r['path'],r) for r in parse(after_inventory)['files']),key=lambda x:os.fsencode(x[0])):
        expected+=(row['index_mode']+' '+row['index_blob']+' 0\t'+p+'\0').encode()
    check(staged==expected,'complete index actual entries equal full physical successor tree')
    result['actual'].update(detached=True,index_equals_tree=True)
    result['git_metadata_actual_changes']=changes

def final_inputs():
    for path, expected in inputs.items():
        if path==GIT:
            with open(path,'rb') as stream: raw=stream.read()
        else:
            raw=regular_read(path)
        pin(raw,expected,'unchanged original input '+path)
    jwrite('INPUTS.final.json',inputs)

def retain_partial():
    observations = {}
    for name in ('HEAD','index','config'):
        try:
            raw=regular_read(REPO/'.git'/name)
            observations[name]=gzrecord('PARTIAL.'+name+'.raw',raw)
        except BaseException as error:
            observations[name]={'status':'unknown','error':repr(error)}
    try:
        raw=regular_read(REPO/CHANGED)
        observations['source']=write('PARTIAL.changed-source.rs',raw)
    except BaseException as error:
        observations['source']={'status':'unknown','error':repr(error)}
    jwrite('PARTIAL_STATE.json',observations)

def main():
    global deadline
    result['started_at']=now()
    real_directory(CONTROL);real_directory(REPO)
    check(not os.path.lexists(OUT),'one original run only; never overwrite/retry')
    os.mkdir(OUT,0o700)
    lock_fd=os.open(CONTROL/'source-advance.lock',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    fcntl.flock(lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    os.environ['GIT_OPTIONAL_LOCKS']='0'
    os.environ['PYTHONDONTWRITEBYTECODE']='1';sys.dont_write_bytecode=True
    deadline=time.monotonic()+ACTION_SECONDS
    completed=False
    try:
        preflight()
        import_objects()
        advance_source()
        completed=True
    except BaseException as error:
        result.update(status='FAILED_SOURCE_ADVANCE',error=repr(error),traceback=traceback.format_exc())
        event('source_advance_failed',error=repr(error),local_head_advanced=result['local_head_advanced'])
    finally:
        deadline=time.monotonic()+RECORD_SECONDS
        for name,action in (('source',final_source),('git',final_git),('inputs',final_inputs)):
            row={'check':name,'status':'unknown','started_at':now()}
            try:
                remaining()
                action()
                row['status']='verified'
            except BaseException as error:
                row.update(error=repr(error),traceback=traceback.format_exc())
            row['finished_at']=now()
            result['final_audits'].append(row)
        if completed and all(r['status']=='verified' for r in result['final_audits']):
            result['status']='SOURCE_ADVANCED_FOR_MAINTENANCE_ONLY'
        elif any(r['status']!='verified' for r in result['final_audits']):
            result['status']='UNKNOWN_PARTIAL_SOURCE_ADVANCE'
        if result['status']!='SOURCE_ADVANCED_FOR_MAINTENANCE_ONLY':
            retain_partial()
        result['finished_at']=now()
        result['commands']=commands
        jwrite('MUTATION_PROGRESS.json',intents)
        jwrite('COMMANDS.json',commands)
        result['artifacts']=list(artifacts)
        jwrite('RESULT.json',result)
        jwrite('ARTIFACTS.json',artifacts)
        os.fsync(lock_fd);os.close(lock_fd)
        event('source_advance_terminal',status=result['status'],local_head_advanced=result['local_head_advanced'])
    return 0 if result['status']=='SOURCE_ADVANCED_FOR_MAINTENANCE_ONLY' else 1

if __name__=='__main__':
    raise SystemExit(main())
