def _historical_transport_stat(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read_historical_transport_file(path, expected, maximum):
    """Read only the fixed manifest or one of this instance's four history files."""
    path = pathlib.Path(path)
    allowed = {HISTORY_MANIFEST_PATH} | {row['transport_path'] for row in HISTORY_RUNTIME_ROLES.values()}
    check(str(path) in allowed, 'closed historical-runtime transport file')
    check(type(maximum) is int and 0 <= maximum <= 40000000, 'original historical input limit')
    real_directory(HISTORY_TRANSPORT_CONTROL)
    real_directory(path.parent)
    for directory in {pathlib.Path(HISTORY_TRANSPORT_CONTROL), path.parent}:
        current = directory.lstat()
        check(stat.S_ISDIR(current.st_mode) and current.st_uid == 1000
              and stat.S_IMODE(current.st_mode) == 0o700, 'owned private historical transport directory')
    before = path.lstat()
    check(stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1
          and stat.S_IMODE(before.st_mode) == 0o600, 'owned immutable historical transport file')
    raw = read_input(path, expected, maximum)
    check(_historical_transport_stat(before) == _historical_transport_stat(path.lstat()),
          'historical transport full ownership/stat identity stable during original read')
    return raw


def read_transported_historical_input(role, original_path, expected, maximum=40000000):
    """Separate the four original provenance identities from their transport locations."""
    check(role in HISTORY_RUNTIME_ROLES, 'one of four fixed runtime history roles')
    spec = HISTORY_RUNTIME_ROLES[role]
    check(str(original_path) == spec['original_path']
          and {key: expected[key] for key in ('bytes', 'sha256', 'git_blob')} == spec['pin'],
          'original runtime history path and exact bytes remain unchanged')
    manifest_raw = _read_historical_transport_file(HISTORY_MANIFEST_PATH, HISTORY_MANIFEST_PIN, 100000)
    manifest = parse(manifest_raw)
    check(manifest['format'] == 'hepta-closed-transported-originals-manifest-v1'
          and manifest['control'] == HISTORY_TRANSPORT_CONTROL
          and manifest['historical_original_count'] == 55 and len(manifest['rows']) == 55,
          'complete fixed transported history manifest')
    rows = {row['role']: row for row in manifest['rows']}
    check(len(rows) == 55 and rows[role] == spec,
          'the exact four runtime inputs belong to the complete reviewed closed map')
    return _read_historical_transport_file(spec['transport_path'], expected, maximum)
