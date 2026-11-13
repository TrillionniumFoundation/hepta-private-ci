"""Source fragments for the isolated admission successor; not a CLI."""

def exact_pin(value, reason):
    check(isinstance(value, dict) and set(value) == {'bytes', 'sha256', 'git_blob'}
          and type(value['bytes']) is int and value['bytes'] >= 0
          and isinstance(value['sha256'], str) and re.fullmatch('[0-9a-f]{64}', value['sha256'])
          and isinstance(value['git_blob'], str) and re.fullmatch('[0-9a-f]{40}', value['git_blob']), reason)
    return value


def pin_fields(value):
    return {key: value[key] for key in ('bytes', 'sha256', 'git_blob')}


def audited(value, names, reason):
    rows = value.get('final_audits')
    check(isinstance(rows, list) and len(rows) == len(names)
          and len({row['check'] for row in rows}) == len(rows)
          and {row['check']: row['status'] for row in rows} == {name: 'verified' for name in names}, reason)


def artifact_catalog(value, wrapped):
    if wrapped:
        check(isinstance(value, dict) and set(value) == {
            'files', 'terminal_report', 'terminal_report_self_hash_not_included'}
              and value['terminal_report'] == 'RESULT.json'
              and value['terminal_report_self_hash_not_included'] is True, 'original maintenance artifact envelope')
        rows = value['files']
    else:
        rows = value
    check(isinstance(rows, list), 'complete artifact list')
    indexed = {}
    for row in rows:
        name = row.get('name')
        check(isinstance(name, str) and name not in ('', '.', '..') and '/' not in name
              and '\\' not in name and '\0' not in name and name not in indexed,
              'one-level unique original artifact name')
        exact_pin(pin_fields(row), 'complete original artifact pin')
        indexed[name] = row
    return indexed


def canonical_to_v5_projection(canonical):
    """Reconstruct V5 bytes only after retaining the full ownership-bearing input."""
    check(isinstance(canonical, dict) and set(canonical) == {'root', 'files'}
          and canonical['root'] == str(Path(CURRENT_REPO) / '.git'), 'complete canonical Git metadata envelope')
    common = {'path', 'kind', 'mode', 'uid', 'gid', 'device', 'inode', 'nlink', 'mtime_ns', 'ctime_ns'}
    rows = canonical['files']
    check(isinstance(rows, list), 'complete canonical metadata rows')
    indexed, children = {}, {}
    for row in rows:
        path = row.get('path')
        check(isinstance(path, str) and '\0' not in path and '\\' not in path,
              'canonical metadata path text')
        path.encode('utf-8', 'strict')
        parts = path.split('/')
        check(all(part not in ('', '.', '..') for part in parts) and path not in indexed,
              'safe unique canonical metadata path')
        check(row.get('kind') in ('file', 'directory')
              and set(row) == common | ({'bytes', 'sha256'} if row['kind'] == 'file' else set()),
              'exact canonical metadata row fields')
        check(all(type(row[key]) is int and row[key] >= 0 for key in (
            'mode', 'uid', 'gid', 'device', 'inode', 'nlink', 'mtime_ns', 'ctime_ns')),
              'complete exact integer canonical ownership and stat fields')
        check(row['mode'] <= 0o7777 and row['nlink'] >= 1, 'canonical metadata mode and links')
        if row['kind'] == 'file':
            check(type(row['bytes']) is int and row['bytes'] >= 0
                  and isinstance(row['sha256'], str) and re.fullmatch('[0-9a-f]{64}', row['sha256']),
                  'complete canonical metadata file identity')
        indexed[path] = row
        children.setdefault('/'.join(parts[:-1]), []).append(path)
    check(rows == sorted(rows, key=lambda row: os.fsencode(row['path'])), 'canonical complete path order')
    for path in indexed:
        parent = path.rpartition('/')[0]
        check(not parent or parent in indexed and indexed[parent]['kind'] == 'directory',
              'canonical metadata parent directory closure')
    result = []
    def visit(parent):
        for path in sorted(children.get(parent, []), key=lambda item: os.fsencode(item.rsplit('/', 1)[-1])):
            row = indexed[path]
            result.append({key: value for key, value in row.items() if key not in ('uid', 'gid')})
            if row['kind'] == 'directory':
                visit(path)
    visit('')
    check(len(result) == len(rows), 'complete V5 DFS projection')
    value = {'format': 'hepta-source-git-metadata-inventory-v1', 'root': canonical['root'], 'files': result}
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode()


def stable_canonical_metadata(root):
    """Observe every real Git entry, including uid/gid; no metadata writes."""
    root = Path(root)
    check(str(root) == str(Path(CURRENT_REPO) / '.git'), 'fixed current Git metadata root')
    rows = []
    def full_stat(info):
        return (info.st_mode, info.st_uid, info.st_gid, info.st_dev, info.st_ino,
                info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    def visit(directory):
        before_dir = directory.lstat()
        check(stat.S_ISDIR(before_dir.st_mode), 'real Git metadata directory')
        with os.scandir(directory) as scan:
            entries = sorted(list(scan), key=lambda entry: os.fsencode(entry.name))
        for entry in entries:
            path = Path(entry.path)
            observed = path.lstat()
            row = {'path': path.relative_to(root).as_posix(), 'mode': stat.S_IMODE(observed.st_mode),
                   'uid': observed.st_uid, 'gid': observed.st_gid, 'device': observed.st_dev,
                   'inode': observed.st_ino, 'nlink': observed.st_nlink,
                   'mtime_ns': observed.st_mtime_ns, 'ctime_ns': observed.st_ctime_ns}
            if stat.S_ISDIR(observed.st_mode):
                row['kind'] = 'directory'
                rows.append(row)
                visit(path)
                check(full_stat(path.lstat()) == full_stat(observed), 'Git directory remained stable')
            else:
                check(stat.S_ISREG(observed.st_mode), 'canonical Git metadata only real regular files')
                digest, size = hashlib.sha256(), 0
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd, 'rb') as stream:
                    opened = os.fstat(stream.fileno())
                    check(full_stat(opened) == full_stat(observed), 'Git file lstat/open identity')
                    for chunk in iter(lambda: stream.read(1048576), b''):
                        digest.update(chunk)
                        size += len(chunk)
                    finished = os.fstat(stream.fileno())
                check(full_stat(observed) == full_stat(opened) == full_stat(finished)
                      == full_stat(path.lstat()) and size == observed.st_size,
                      'complete Git file ownership, mode, identity and bytes stable during read')
                row.update(kind='file', bytes=size, sha256=digest.hexdigest())
                rows.append(row)
        with os.scandir(directory) as scan:
            after_names = sorted((entry.name for entry in scan), key=os.fsencode)
        check(after_names == [entry.name for entry in entries]
              and full_stat(directory.lstat()) == full_stat(before_dir), 'complete Git directory membership stable')
    visit(root)
    value = {'root': str(root), 'files': sorted(rows, key=lambda row: os.fsencode(row['path']))}
    canonical_to_v5_projection(value)
    return value


def physical_projection(value):
    rows = {}
    check(isinstance(value, dict) and value.get('tracked_entries') == 15243
          and value.get('filesystem_entries') == 15243 and isinstance(value.get('files'), list),
          'complete final physical source membership')
    for row in value['files']:
        path = row['path']
        check(isinstance(path, str) and '\0' not in path and not path.startswith('/')
              and all(part not in ('', '.', '..', '.git') for part in path.split('/'))
              and path not in rows, 'safe unique full physical source path')
        check(row['kind'] in ('file', 'symlink') and row['stable'] is True, 'supported stable physical leaf')
        rows[path] = {key: item for key, item in row.items()
                      if key not in ('index_blob', 'index_mode', 'matches_index')}
    check(len(rows) == 15243, 'all actual physical leaves')
    return rows


def native_projection(value):
    # Exact original b92/972ec projection: default ensure_ascii, compact, no LF.
    rows = [{'path': row['path'], 'mode': row['index_mode'], 'bytes': row['bytes'],
             'sha256': row['sha256'], 'blob': row['working_blob']} for row in value['files']]
    rows.sort(key=lambda row: os.fsencode(row['path']))
    return json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()


def metadata_file_projection(value):
    """Compare 3bb's six actual file rows with V5's complete DFS envelope."""
    check(set(value) == {'format', 'root', 'files'}
          and value['format'] == 'hepta-source-git-metadata-inventory-v1'
          and value['root'] == str(Path(CURRENT_REPO) / '.git'), 'original V5 metadata envelope')
    result = {}
    for row in value['files']:
        check(row['path'] not in result, 'unique original V5 metadata rows')
        result[row['path']] = row
    return {path: row for path, row in result.items() if row['kind'] == 'file'}


def require_stage(stage, name, argv, seconds):
    check(stage['name'] == name and stage['argv'] == argv and stage['timeout_seconds'] == seconds
          and stage['working_directory'] == CURRENT_REPO and stage['maximum_log_bytes'] == 67108864
          and stage['command_returned'] is True and stage['execution_outcome'] == 'completed'
          and stage['status'] == 'completed_review_required' and stage['raw_log_retained'] is True
          and stage['retention']['complete'] is True and stage['test_command'] is False,
          'original maintenance command, complete output and retention')
    execution = stage['execution']
    check(execution['returncode'] == 0 and execution['timed_out'] is False
          and execution['output_limit_exceeded'] is False
          and execution['observed_passed_tests'] == execution['observed_failed_tests'] == 0,
          'actual normal maintenance command; no test result inferred')
