def inventory_summary(raw):
    value = parse(raw)
    check(value['tracked_entries']==LEAVES and value['filesystem_entries']==LEAVES,
          'complete physical/index population')
    check(len(value['files'])==LEAVES and all(r.get('stable') is True for r in value['files']),
          'complete stable physical inventory')
    return {'bytes':len(raw),'sha256':sha256(raw),'git_blob':oid('blob',raw),
            'tracked_entries':value['tracked_entries'],'filesystem_entries':value['filesystem_entries']}

def physical_projection(raw):
    value=parse(raw)
    inventory_summary(raw)
    rows={}
    for row in value['files']:
        path=row['path']
        check(path not in rows and not path.startswith('/') and
              all(p not in ('','.','..','.git') for p in path.split('/')), 'safe unique physical path')
        check(row['kind'] in ('file','symlink') and row['stable'] is True, 'supported stable physical leaf')
        mode='120000' if row['kind']=='symlink' else ('100755' if row['permissions']&0o111 else '100644')
        rows[path]={'mode':mode,'sha':row['working_blob'],'bytes':row['bytes'],'sha256':row['sha256'],
                    'physical':{k:v for k,v in row.items() if k not in ('index_blob','index_mode','matches_index')}}
    check(len(rows)==LEAVES,'all physical leaves included')
    return rows

def lock_identity(fd):
    inside=os.fstat(fd);outside=LOCK.lstat()
    fields=lambda s:{'device':s.st_dev,'inode':s.st_ino,'uid':s.st_uid,
                      'mode':stat.S_IMODE(s.st_mode),'nlink':s.st_nlink}
    check(stat.S_ISREG(inside.st_mode) and stat.S_ISREG(outside.st_mode) and
          fields(inside)==fields(outside)==LOCK_ID,'same actual source coordination inode')
    return fields(inside)

def parse_supervisor(raw):
    outer=parse(raw)
    check(("resultType" not in outer or outer["resultType"]=="complete")
          and outer.get("isError") is False and len(outer.get("content",[]))==1
          and outer["content"][0].get("type")=="text","actual terminal SDK envelope")
    terminal=parse(outer["content"][0]["text"].encode())
    check(terminal.get("state")=="succeeded" and terminal.get("exit_code")==0
          and terminal.get("timed_out") is False and terminal.get("cancelled") is False
          and terminal.get("automatic_retry") is False
          and terminal.get("output_complete") is True and terminal.get("output_durable") is True
          and terminal.get("terminal_publication_confirmed") is True
          and not any(terminal.get("log_truncated",{}).values()),"actual complete normal supervisor terminal")
    return terminal

def validate_final_format():
    proof=cfg['final_format']
    raw=read_input(proof['result_path'],proof['result'])
    terminal_raw=read_input(proof['supervisor_path'],proof['supervisor'])
    observed=parse(raw);terminal=parse_supervisor(terminal_raw)
    check(terminal['job_id']==proof['job_id'],'actual final-format supervisor job')
    check(observed['format']=='hepta-reviewed-nonrust-final-format-result-v1' and
          observed['status']=='APPLIED_AND_FORMATTED_REVIEW_REQUIRED' and
          observed['source_repo']==str(REPO) and observed['source_commit']==OLD and
          observed['source_tree']==OLD_TREE and observed['parents']==OLD_PARENTS,
          'actual final-format source identity')
    check(observed['qualification'] is False and observed['test_commands_dispatched']==0 and
          observed['fix_dispatched'] is False and observed['source_ref_updates'] is False and
          observed['attempted_commands']==['fmt'] and observed['not_run_commands']==[],
          'one original final-format command only')
    check(len(observed['stages'])==1 and observed['stages'][0]['name']=='fmt','single original formatter stage')
    stage=observed['stages'][0]
    check(stage['status']=='completed_review_required' and stage['execution']['returncode']==0 and
          stage['execution']['timed_out'] is False and stage['execution']['output_limit_exceeded'] is False,
          'original final formatter normal zero without timeout or output limit')
    check(stage['argv']==['just','fmt','--base','c0f78493f815780f68b9bf5e390a21314d79311f'] and
          stage['timeout_seconds']==900,'original formatter argv and budget')
    check({row['check']:row['status'] for row in observed['final_audits']}=={
        'actual_complete_source_and_git':'verified','original_inputs':'verified',
        'same_source_coordination_lock':'verified'},'all final-format audits verified')
    complete=observed['actual_final_source']
    check(complete['complete'] is True and observed['git_metadata_unchanged'] is True and
          complete['inventory']=={k:cfg['before_inventory'][k] for k in ('bytes','sha256','git_blob')} and
          complete['postimages']['all_actual_physical_tree']==NEW_TREE and
          complete['postimages']['all_actual_physical_leaf_count']==LEAVES,
          'actual final-format complete physical source equals approved canonical tree')
    check(observed['formatter_changed_paths']==cfg['reviewed_formatter_changed_paths'] and
          cfg['actual_final_postimages_reviewed'] is True,'Root-reviewed actual formatter postimages')
    git_raw=read_input(proof['git_state_path'],proof['git_state'])
    check(parse(git_raw)==cfg['expected_before_git_state'],'actual final-format Git state binding')
    write('FINAL_FORMAT_RESULT.original.json',raw)
    write('FINAL_FORMAT_SUPERVISOR.original.json',terminal_raw)
    write('FINAL_FORMAT_GIT_STATE.original.json',git_raw)
    result['final_format']={'job_id':proof['job_id'],'result':proof['result'],
                            'supervisor':proof['supervisor'],'git_state':proof['git_state']}

def preflight():
    global cfg,packet,inventory_module,before_inventory,before_git,before_metadata,before_index
    global NEW,NEW_TREE,NEW_PARENTS
    raw_config=regular_read(CONFIG)
    check(sha256(raw_config)==config_expected_sha256,'launcher-pinned exact approved config')
    cfg=parse(raw_config)
    inputs[str(CONFIG)]={'bytes':len(raw_config),'sha256':sha256(raw_config),'git_blob':oid('blob',raw_config)}
    check(cfg.get('format')=='hepta-final-canonical-alignment-config-v1' and
          cfg.get('status')=='ROOT_APPROVED_FOR_ONE_CANONICAL_ALIGNMENT' and
          cfg.get('root_execution_approved') is True,'HOLD configuration is never executable')
    check(cfg['source_repo']==str(REPO) and cfg['control_dir']==str(CONTROL) and
          cfg['output_dir']==str(OUT),'fixed source/control/output')
    check(cfg['before_commit']==OLD and cfg['before_tree']==OLD_TREE and cfg['before_parents']==OLD_PARENTS and
          cfg['action_seconds']==ACTION_SECONDS and cfg['record_seconds']==RECORD_SECONDS and
          cfg['outer_seconds']==900 and cfg['complete_leaf_count']==LEAVES,
          'fixed old source and unchanged action/record budgets')
    for name in ('physical_source_writes_authorized','dependency_installation_authorized',
                 'cargo_or_formatter_authorized','test_commands_authorized','remote_ref_updates_authorized'):
        check(cfg[name] is False,'excluded operation: '+name)
    NEW=cfg['after_commit'];NEW_TREE=cfg['after_tree'];NEW_PARENTS=cfg['after_parents']
    check(all(isinstance(x,str) and len(x)==40 and all(c in '0123456789abcdef' for c in x)
              for x in [NEW,NEW_TREE,*NEW_PARENTS]) and NEW!=OLD and NEW_PARENTS,
          'complete canonical identity supplied by approval')
    read_input(pathlib.Path(__file__),cfg['driver'])
    check(os.getuid()==1000 and shutil.which('git')==GIT,'fixed operator and actual Git path')
    tool=pathlib.Path(GIT);s=tool.lstat()
    check(stat.S_ISREG(s.st_mode) and not stat.S_ISLNK(s.st_mode) and s.st_uid==0,'fixed Git executable')
    pin(regular_read(tool,expected_uid=0),GIT_PIN,'actual Git executable')
    inputs[str(tool)]=GIT_PIN
    for key in ('GIT_DIR','GIT_WORK_TREE','GIT_INDEX_FILE','GIT_COMMON_DIR','GIT_OBJECT_DIRECTORY',
                'GIT_ALTERNATE_OBJECT_DIRECTORIES','GIT_CONFIG_COUNT','GIT_CONFIG_PARAMETERS'):
        check(not os.environ.get(key),'unexpected inherited Git redirection: '+key)
    packet=parse(read_input(PACKET,cfg['canonical_packet']))
    check(packet['format']=='hepta-final-canonical-source-alignment-packet-v1' and
          packet['source_repo']==str(REPO) and packet['complete_leaf_count']==LEAVES,
          'reviewed canonical packet scope')
    check(packet['before']=={'commit':OLD,'tree':OLD_TREE,'parents':OLD_PARENTS,
          'inventory':cfg['before_inventory'],'git_state':cfg['expected_before_git_state']} and
          packet['after']=={'commit':NEW,'tree':NEW_TREE,'parents':NEW_PARENTS,
          'inventory':cfg['after_inventory']},'exact canonical packet endpoints')
    check(len(packet['objects'])==cfg['canonical_object_count'] and 0<len(packet['objects'])<=2000,
          'exact approved canonical object count')
    for obj in packet['objects']:
        check(obj['type'] in ('blob','tree','commit'),'supported canonical Git object type')
        raw=base64.b64decode(obj['raw_base64'],validate=True)
        check(len(raw)==obj['bytes'] and sha256(raw)==obj['sha256'] and
              oid(obj['type'],raw)==obj['sha'] and obj['sha'] not in object_raw,
              'unique canonical raw original object identity')
        object_raw[obj['sha']]=raw
    check(NEW in object_raw,'authentic canonical commit bytes in packet')
    result['canonical_packet']=cfg['canonical_packet']
    inventory_module=load_inventory()
    validate_final_format()
    concurrency_check('initial')
    before_git=git_state(OLD,OLD_TREE)
    check(before_git==cfg['expected_before_git_state'],'actual final-format raw Git state unchanged')
    before_index=regular_read(REPO/'.git'/'index')
    old_entries,old_extensions=parse_index(before_index)
    check(all(not e['flags']&0xf000 for e in old_entries.values()),'original index stage-zero normal flags')
    check([x['name'] for x in old_extensions]==['TREE'],'only understood original cache-tree extension')
    gzrecord('INDEX.before.raw',before_index)
    write('HEAD.before.raw',regular_read(REPO/'.git'/'HEAD'))
    jwrite('GIT_STATE.before.json',before_git)
    before_metadata=metadata_inventory()
    gzrecord('GIT_METADATA.before.json',encoded(before_metadata))
    before_inventory=inventory_module.inventory(REPO)
    gzrecord('SOURCE.before.inventory.json',before_inventory)
    check(inventory_summary(before_inventory)==cfg['before_inventory'],'actual complete final-format inventory')
    check(parse(before_inventory)['source']['head']==OLD and parse(before_inventory)['source']['tree']==OLD_TREE,
          'dirty physical source and old HEAD tree are distinct identities')
    physical_projection(before_inventory)
    check(git_state(OLD,OLD_TREE)==before_git,'source observation preserves exact raw Git state')
    verify_commit(OLD,OLD_TREE,OLD_PARENTS)
    result['before']={'commit':OLD,'tree':OLD_TREE,'parents':OLD_PARENTS,
                      'inventory':inventory_summary(before_inventory),'git_state':before_git}
    event('canonical_alignment_preconditions_verified',source_commit=OLD,
          head_tree=OLD_TREE,approved_physical_tree=NEW_TREE,tracked_entries=LEAVES)

def import_objects():
    concurrency_check('immediately-before-object-import')
    requested=b''.join((obj['sha']+'\n').encode() for obj in packet['objects'])
    checked=command(['cat-file','--batch-check'],data=requested)[0].splitlines()
    check(len(checked)==len(packet['objects']),'one normal explicit result per canonical object')
    presence={}
    for obj,line in zip(packet['objects'],checked):
        missing=(obj['sha']+' missing').encode()
        present=(obj['sha']+' '+obj['type']+' '+str(obj['bytes'])).encode()
        check(line in (missing,present),'unrecognized original object presence/type/size')
        presence[obj['sha']]=line==present
    for obj in packet['objects']:
        raw=object_raw[obj['sha']]
        if presence[obj['sha']]:
            check(git('cat-file',obj['type'],obj['sha'])==raw,'pre-existing canonical body')
            continue
        action=intent('import_missing_canonical_object',sha=obj['sha'],type=obj['type'],bytes=len(raw))
        observed=command(['hash-object','-t',obj['type'],'-w','--stdin'],data=raw,mutation=True)[0]
        check(observed==(obj['sha']+'\n').encode(),'imported authentic object SHA')
        check(git('cat-file',obj['type'],obj['sha'])==raw,'exact imported body readback')
        object_added.append(obj['sha'])
        action.update(terminal='observed',completed_at=now())
    verify_commit(NEW,NEW_TREE,NEW_PARENTS)
    old_leaves,old_objects=snapshot(OLD_TREE)
    new_leaves,new_objects=snapshot(NEW_TREE)
    physical=physical_projection(before_inventory)
    check(set(old_leaves)==set(new_leaves)==set(physical),'complete path membership unchanged')
    check(new_leaves=={p:{'mode':r['mode'],'sha':r['sha']} for p,r in physical.items()},
          'entire current physical source equals canonical tree before any index/HEAD write')
    expected_blobs={}
    for path,row in physical.items():
        value=(row['bytes'],row['sha256'])
        check(row['sha'] not in expected_blobs or expected_blobs[row['sha']]==value,
              'same physical blob has consistent complete byte evidence')
        expected_blobs[row['sha']]=value
    objects={**old_objects,**new_objects,OLD:'commit',NEW:'commit',**{parent:'commit' for parent in NEW_PARENTS}}
    check(set(object_raw)<=set(objects),'all approved provided objects belong to snapshots or explicit anchors')
    verify_object_union(objects,expected_blobs)
    result['actual']['verified_canonical_objects']=len(packet['objects'])
    result['actual']['physical_equals_canonical_before_index_change']=True
    jwrite('OBJECT_IMPORT.json',{'verified_objects':len(packet['objects']),
             'actually_added_objects':object_added,'existing_objects_retained':True})

def validate_canonical_index(raw):
    entries,extensions=parse_index(raw)
    expected=physical_projection(before_inventory)
    check(set(entries)==set(expected),'complete canonical index path set')
    check([x['name'] for x in extensions]==['TREE'],'only understood canonical cache-tree extension')
    rows=[]
    for path in sorted(entries,key=os.fsencode):
        entry=entries[path];leaf=expected[path]
        check(entry['mode']==leaf['mode'] and entry['sha']==leaf['sha'] and
              not entry['flags']&0xf000 and entry['flags']==min(len(os.fsencode(path)),0xfff),
              'canonical stage-zero blob/mode/normal flags: '+path)
        s=(REPO/path).lstat()
        actual=(s.st_ctime_ns//1000000000,s.st_ctime_ns%1000000000,s.st_mtime_ns//1000000000,
                s.st_mtime_ns%1000000000,s.st_dev&0xffffffff,s.st_ino&0xffffffff,int(leaf['mode'],8),
                s.st_uid,s.st_gid,s.st_size&0xffffffff)
        check(entry['stat']==actual,'actual complete normal index stat: '+path)
        rows.append({'path':path,'mode':entry['mode'],'sha':entry['sha'],'flags':entry['flags'],
                     'stat':list(entry['stat']),'raw_entry_sha256':sha256(entry['raw'])})
    return {'entry_count':len(rows),'all_entries_equal_canonical_tree':True,
            'all_stat_fields_match_actual_files':True,'entries':rows,
            'extensions':[{'name':x['name'],'bytes':x['bytes'],'sha256':sha256(x['raw'])} for x in extensions]}

def align_index_and_head():
    check(git_state(OLD,OLD_TREE)==before_git,'exact old Git state before index/HEAD change')
    check(inventory_module.inventory(REPO)==before_inventory,'full physical source unchanged before transition')
    concurrency_check('immediately-before-index-head-change')
    action=intent('read_canonical_tree_into_index_only',tree=NEW_TREE,worktree_update=False)
    command(['read-tree',NEW_TREE],mutation=True)
    action.update(terminal='observed',completed_at=now())
    action=intent('explicit_normal_stat_refresh_all_index_entries',entries=LEAVES)
    command(['update-index','--refresh'],mutation=True)
    action.update(terminal='observed',completed_at=now())
    action=intent('write_and_verify_canonical_index_tree',expected_tree=NEW_TREE)
    check(command(['write-tree'],mutation=True)[0]==(NEW_TREE+'\n').encode(),'actual canonical index tree')
    raw=regular_read(REPO/'.git'/'index')
    gzrecord('INDEX.pre-head-cas.raw',raw)
    gzrecord('INDEX.pre-head-cas.audit.json',encoded(validate_canonical_index(raw)))
    check(physical_projection(inventory_module.inventory(REPO))==physical_projection(before_inventory),
          'index-only transition leaves all physical source records unchanged')
    action.update(terminal='observed',completed_at=now())
    check(regular_read(REPO/'.git'/'HEAD')==(OLD+'\n').encode(),'detached HEAD remains old before CAS')
    action=intent('align_detached_HEAD_compare_and_swap',expected_old=OLD,new=NEW)
    command(['update-ref','--no-deref','HEAD',NEW,OLD],mutation=True)
    check(regular_read(REPO/'.git'/'HEAD')==(NEW+'\n').encode(),'actual new detached HEAD bytes')
    result['local_head_advanced']=True
    action.update(terminal='observed',completed_at=now())

def final_source():
    global after_inventory,after_git
    check(inventory_module is not None and before_inventory is not None,'original full source baseline available')
    raw=inventory_module.inventory(REPO)
    gzrecord('SOURCE.final.inventory.json',raw)
    after_inventory=raw
    summary=inventory_summary(raw)
    check(summary==cfg['after_inventory'],'actual canonical complete inventory equals reviewed exact projection')
    value=parse(raw)
    check(value['source']=={'head':NEW,'tree':NEW_TREE,'status':''} and
          all(row['matches_index'] is True for row in value['files']),'actual clean canonical HEAD/index/physical source')
    check(physical_projection(raw)==physical_projection(before_inventory),'all physical source bytes/modes unchanged')
    after_git=git_state(NEW,NEW_TREE)
    jwrite('GIT_STATE.final.json',after_git)
    result['after']={'commit':NEW,'tree':NEW_TREE,'parents':NEW_PARENTS,
                     'inventory':summary,'git_state':after_git}
    result['actual'].update(physical_bytes_unchanged=True,physical_modes_unchanged=True,
                           complete_source_clean=True)

def final_git():
    raw=regular_read(REPO/'.git'/'index')
    gzrecord('INDEX.final.raw',raw)
    audit=validate_canonical_index(raw)
    gzrecord('INDEX.final.audit.json',encoded(audit))
    before_entries,before_extensions=parse_index(before_index)
    after_entries,after_extensions=parse_index(raw)
    delta=[{'path':path,'before_mode':before_entries[path]['mode'],'after_mode':after_entries[path]['mode'],
            'before_sha':before_entries[path]['sha'],'after_sha':after_entries[path]['sha'],
            'before_flags':before_entries[path]['flags'],'after_flags':after_entries[path]['flags'],
            'before_stat':list(before_entries[path]['stat']),'after_stat':list(after_entries[path]['stat']),
            'before_raw_sha256':sha256(before_entries[path]['raw']),
            'after_raw_sha256':sha256(after_entries[path]['raw'])}
           for path in sorted(after_entries,key=os.fsencode) if before_entries[path]['raw']!=after_entries[path]['raw']]
    gzrecord('INDEX.complete-entry-delta.json',encoded(delta))
    current=git_state(NEW,NEW_TREE)
    check(after_git is not None and current==after_git,'final exact raw Git state stable')
    check(all(current[k]==before_git[k] for k in ('config_bytes','config_sha256','refs_bytes','refs_sha256')),
          'no config or branch ref changes')
    staged=git('ls-files','--stage','-z')
    expected=b''.join((row['index_mode']+' '+row['index_blob']+' 0\t'+row['path']+'\0').encode()
                     for row in sorted(parse(after_inventory)['files'],key=lambda x:os.fsencode(x['path'])))
    check(staged==expected,'complete actual index entries equal canonical physical leaves')
    actual=metadata_inventory()
    gzrecord('GIT_METADATA.final.json',encoded(actual))
    changes=verify_metadata(before_metadata,actual)
    jwrite('GIT_METADATA.allowed-actual-delta.json',changes)
    result['actual'].update(detached=True,index_equals_tree=True,normal_stat_refresh_verified=True)
    result['git_metadata_actual_changes']=changes

def final_inputs():
    for path,expected in inputs.items():
        raw=regular_read(path,expected_uid=0) if path==GIT else regular_read(path)
        pin(raw,expected,'unchanged original input '+path)
    lock_identity(lock_fd)
    jwrite('INPUTS.final.json',inputs)

def retain_partial():
    observations={}
    for name in ('HEAD','index','config'):
        try:
            raw=regular_read(REPO/'.git'/name)
            observations[name]=gzrecord('PARTIAL.'+name+'.raw',raw)
        except BaseException as error:
            observations[name]={'status':'unknown','error':repr(error)}
    try:
        check(inventory_module is not None,'inventory module unavailable')
        raw=inventory_module.inventory(REPO)
        observations['source_inventory']=gzrecord('PARTIAL.source.inventory.json',raw)
    except BaseException as error:
        observations['source_inventory']={'status':'unknown','error':repr(error)}
    jwrite('PARTIAL_STATE.json',observations)

def main():
    global deadline,lock_fd,config_expected_sha256
    parser=argparse.ArgumentParser()
    parser.add_argument('--config-sha256',required=True)
    config_expected_sha256=parser.parse_args().config_sha256
    result['started_at']=now()
    real_directory(CONTROL);real_directory(REPO)
    check(not os.path.lexists(OUT),'existing attempt: reconcile original identity, never overwrite/retry')
    os.mkdir(OUT,0o700)
    os.environ['GIT_OPTIONAL_LOCKS']='0'
    os.environ['PYTHONDONTWRITEBYTECODE']='1';sys.dont_write_bytecode=True
    deadline=time.monotonic()+ACTION_SECONDS
    signal.signal(signal.SIGALRM,alarm_handler)
    arm_if_remaining()
    result['action_budget_started_at']=now();result['action_budget_seconds']=ACTION_SECONDS
    completed=False
    try:
        lock_fd=os.open(LOCK,os.O_RDONLY|os.O_NOFOLLOW)
        fcntl.flock(lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        jwrite('SOURCE_COORDINATION_EX.json',{'path':str(LOCK),**lock_identity(lock_fd),'at':now(),
                 'pid':os.getpid(),'fd':lock_fd,'lock_acquired':'LOCK_EX|LOCK_NB',
                 'scope':'This task cooperative source writers only; complete physical/Git checks remain required.'})
        preflight()
        import_objects()
        align_index_and_head()
        completed=True
    except BaseException as error:
        result.update(status='FAILED_CANONICAL_ALIGNMENT',error=repr(error),traceback=traceback.format_exc())
        event('canonical_alignment_failed',error=repr(error),local_head_advanced=result['local_head_advanced'])
    finally:
        disarm()
        result['action_finished_at']=now()
        record_end=time.monotonic()+RECORD_SECONDS
        deadline=record_end-15
        arm_if_remaining()
        result['record_budget_started_at']=now();result['record_budget_seconds']=RECORD_SECONDS
        for name,action in (('source',final_source),('git',final_git),('inputs',final_inputs)):
            row={'check':name,'status':'unknown','started_at':now()}
            try:
                remaining();action();row['status']='verified'
            except BaseException as error:
                row.update(error=repr(error),traceback=traceback.format_exc())
            row['finished_at']=now();result['final_audits'].append(row)
        if completed and all(row['status']=='verified' for row in result['final_audits']):
            result['status']='CANONICAL_SOURCE_ALIGNED_CLEAN_ONLY'
        elif any(row['status']!='verified' for row in result['final_audits']):
            result['status']='UNKNOWN_PARTIAL_CANONICAL_ALIGNMENT'
        if result['status']!='CANONICAL_SOURCE_ALIGNED_CLEAN_ONLY':
            try:
                remaining();retain_partial()
            except BaseException as error:
                result['partial_retention_error']=repr(error)
        disarm();deadline=record_end;remaining();arm_if_remaining()
        result['finished_at']=now();result['commands']=commands
        jwrite('MUTATION_PROGRESS.json',intents);jwrite('COMMANDS.json',commands)
        result['artifacts']=list(artifacts)
        jwrite('RESULT.json',result);jwrite('ARTIFACTS.json',artifacts)
        if lock_fd is not None:
            os.close(lock_fd);lock_fd=None
        event('canonical_alignment_terminal',status=result['status'],local_head_advanced=result['local_head_advanced'])
        disarm()
    return 0 if result['status']=='CANONICAL_SOURCE_ALIGNED_CLEAN_ONLY' else 1
