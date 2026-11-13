    @staticmethod
    def _require_transport_bindings(cfg):
        check(cfg.get('historical_runtime_guard_path') == HISTORY_RUNTIME_GUARD_PATH
              and cfg.get('historical_runtime_guard_pin') == HISTORY_RUNTIME_GUARD_PIN,
              'one explicitly reviewed historical-only V5 successor')
        spec = cfg.get('history_transport')
        check(isinstance(spec, dict) and set(spec) == {
            'control', 'manifest_path', 'manifest', 'staging_result_path', 'staging_result',
            'staging_supervisor_path', 'staging_supervisor', 'staging_job_id', 'staging_payload'},
              'complete closed history transport binding schema')
        check(spec['control'] == HISTORY_TRANSPORT_CONTROL
              and spec['manifest_path'] == HISTORY_MANIFEST_PATH
              and spec['manifest'] == HISTORY_MANIFEST_PIN
              and spec['staging_result_path'] == HISTORY_TRANSPORT_CONTROL + '/STAGING_READBACK.json'
              and spec['staging_supervisor_path'] == SOURCE_TRANSPORT_CONTROL + '/TRANSPORT_SUPERVISOR.original.json',
              'only the fixed new transport and source-control paths')
        for name in ('staging_result', 'staging_supervisor', 'staging_payload'):
            exact_pin(spec[name], 'actual complete transport ' + name + ' remains required')
        check(isinstance(spec['staging_job_id'], str) and bool(spec['staging_job_id']),
              'actual successful transport job remains required')

    @staticmethod
    def _transport_stat(info):
        return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
                info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def _read_transport_file(self, path, expected, maximum=40000000):
        path = Path(path)
        allowed = {HISTORY_MANIFEST_PATH} | {
            HISTORY_TRANSPORT_CONTROL + '/originals/' + role + '.original' for role in HISTORY_ROLES}
        check(str(path) in allowed, 'closed historical transport file; no live-path resolver')
        check(type(maximum) is int and 0 <= maximum <= 40000000, 'original bounded input limit')
        self.m.real_directory(HISTORY_TRANSPORT_CONTROL)
        self.m.real_directory(path.parent)
        for directory in {Path(HISTORY_TRANSPORT_CONTROL), path.parent}:
            info = directory.lstat()
            check(stat.S_ISDIR(info.st_mode) and info.st_uid == 1000
                  and stat.S_IMODE(info.st_mode) == 0o700, 'owned private history transport directory')
        before = path.lstat()
        check(stat.S_ISREG(before.st_mode) and before.st_uid == 1000 and before.st_nlink == 1
              and stat.S_IMODE(before.st_mode) == 0o600, 'owned single-link history transport file')
        raw = self.m.read_input(path, expected, maximum)
        stamp = self._transport_stat(before)
        check(stamp == self._transport_stat(path.lstat()),
              'full history transport ownership/stat stable during original full read')
        key = str(path)
        if key in self._transport_stats:
            check(self._transport_stats[key] == stamp, 'immutable transport metadata remains unchanged')
        else:
            self._transport_stats[key] = stamp
        return raw

    def _load_transport_manifest(self):
        raw = self._read_transport_file(HISTORY_MANIFEST_PATH, HISTORY_MANIFEST_PIN, 100000)
        manifest = self.m.parse(raw)
        check(manifest['format'] == 'hepta-closed-transported-originals-manifest-v1'
              and manifest['control'] == HISTORY_TRANSPORT_CONTROL
              and manifest['source_control'] == SOURCE_TRANSPORT_CONTROL
              and manifest['qualification'] is False and manifest['root_execution_approved'] is False
              and manifest['historical_original_count'] == 55 and manifest['raw_original_bytes'] == 7976106,
              'fixed history-only manifest; not an execution grant')
        rows = manifest['rows']
        check(isinstance(rows, list) and [row['role'] for row in rows] == HISTORY_ROLES,
              'exact complete ordered historical role closure')
        result = {}
        for row in rows:
            role, original = row['role'], row['original_path']
            exact_pin(row['pin'], 'exact historical original content')
            check(original.startswith(HISTORY_EVIDENCE_PARENT + '/')
                  and '/.git/' not in original and not original.endswith('.lock')
                  and row['transport_path'] == HISTORY_TRANSPORT_CONTROL + '/originals/' + role + '.original',
                  'fixed historical origin and isolated exact transport destination')
            result[role] = row
        check(len(result) == len({row['original_path'] for row in rows}) == 55,
              'unique historical role and origin; no wildcard or fallback')
        return result

    def _read_historical(self, role, original_path, expected, maximum=40000000):
        check(role in self._history_rows, 'explicit closed historical role')
        row = self._history_rows[role]
        check(str(original_path) == row['original_path'] and pin_fields(expected) == row['pin'],
              'historical provenance path and full original pin remain unchanged')
        return self._read_transport_file(row['transport_path'], expected, maximum)

    def read_historical(self, role, original_path, expected, name):
        raw = self._read_historical(role, original_path, expected)
        self.m.write(name, raw)
        return self.m.parse(raw)

    def _require_transport_staging(self):
        """A future actual normal stage and complete readback are mandatory, never inferred."""
        spec = self.cfg['history_transport']
        stage = self.read(spec['staging_result_path'], spec['staging_result'],
                          'TRANSPORT_STAGING.original.json')
        normal_raw = self.m.read_input(spec['staging_supervisor_path'], spec['staging_supervisor'])
        normal = self.m.parse_supervisor(normal_raw)
        check(normal['job_id'] == spec['staging_job_id'], 'actual successful transport job identity')
        self.m.write('TRANSPORT_SUPERVISOR.original.json', normal_raw)
        check(set(stage) == {'format', 'control', 'historical_original_count', 'manifest',
              'packet', 'compressed_packet', 'part_inputs', 'files', 'source_writes',
              'old_path_writes', 'main_dispatched', 'qualification', 'automatic_retry'}
              and stage['format'] == 'hepta-closed-history-transport-readback-v1'
              and stage['control'] == HISTORY_TRANSPORT_CONTROL
              and stage['historical_original_count'] == 55
              and stage['manifest'] == HISTORY_MANIFEST_PIN
              and stage['packet'] == HISTORY_PACKET_PIN
              and stage['compressed_packet'] == HISTORY_GZIP_PIN
              and stage['part_inputs'] == HISTORY_PART_INPUTS
              and all(stage[key] is False for key in ('source_writes', 'old_path_writes',
                                                     'main_dispatched', 'qualification', 'automatic_retry')),
              'complete original history transport receipt, no gate or source action')
        expected = {row['transport_path']: row['pin'] for row in self._history_rows.values()}
        expected.update({HISTORY_MANIFEST_PATH: HISTORY_MANIFEST_PIN,
                         HISTORY_RUNTIME_GUARD_PATH: HISTORY_RUNTIME_GUARD_PIN,
                         HISTORY_TRANSPORT_CONTROL + '/ACTUAL_TRANSPORT_BOOTSTRAP.py': HISTORY_STAGER_PIN,
                         HISTORY_TRANSPORT_CONTROL + '/ACTUAL_TRANSPORT_ARGV.json': HISTORY_STAGER_ARGV_PIN,
                         HISTORY_TRANSPORT_CONTROL + '/ACTUAL_TRANSPORT_PAYLOAD.json': spec['staging_payload']})
        rows = stage['files']
        check(isinstance(rows, list) and len(rows) == 60
              and all(set(row) == {'path', 'bytes', 'sha256', 'git_blob'} for row in rows)
              and len({row['path'] for row in rows}) == 60
              and {row['path']: pin_fields(row) for row in rows} == expected,
              'all 55 originals, manifest, historical guard and three exact staging controls fully read back')
        for row in self._history_rows.values():
            self._read_historical(row['role'], row['original_path'], row['pin'])
        self.m.read_input(HISTORY_RUNTIME_GUARD_PATH, HISTORY_RUNTIME_GUARD_PIN)
        for path, expected_pin in expected.items():
            if path not in {row['transport_path'] for row in self._history_rows.values()} | {HISTORY_MANIFEST_PATH, HISTORY_RUNTIME_GUARD_PATH}:
                self.m.read_input(path, expected_pin)
        self.m.jwrite('TRANSPORTED_ORIGINAL_PROVENANCE.json', {
            'format': 'hepta-closed-transported-original-provenance-v1',
            'manifest': HISTORY_MANIFEST_PIN, 'rows': list(self._history_rows.values()),
            'transport_stage_job': spec['staging_job_id'], 'transport_stage_result': spec['staging_result'],
            'all_55_complete_actual_transport_reads': True, 'origin_path_availability': 'Unknown',
            'old_paths_recreated': False, 'historical_stat_records_rewritten': False,
            'current_live_checks_replaced': False, 'qualification': False})

    def _verify_transport_stability(self):
        self._read_transport_file(HISTORY_MANIFEST_PATH, HISTORY_MANIFEST_PIN, 100000)
        for row in self._history_rows.values():
            self._read_historical(row['role'], row['original_path'], row['pin'])
        return {'historical_original_count': 55, 'complete_current_transport_bytes_and_metadata_stable': True,
                'original_location_availability': 'Unknown'}
