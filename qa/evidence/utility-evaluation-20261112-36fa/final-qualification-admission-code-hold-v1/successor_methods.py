"""Four replacement methods and narrow helpers for the single admission module."""

class SuccessorMethods:
    def __init__(self, cfg, output, runtime):
        check(cfg.get('state') == 'READY_FOR_FINAL_SOURCE_QUALIFICATION'
              and cfg.get('root_execution_approved') is True, 'final source input remains HOLD')
        self._require_complete_bindings(cfg)
        self.cfg = cfg
        self.output = Path(output)
        self.lease = None
        self.runtime = runtime
        self._fixed_raw = {}
        os.environ['GIT_OPTIONAL_LOCKS'] = '0'
        os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
        sys.dont_write_bytecode = True
        self.h = load(cfg['maintenance_guard_path'], V5_PIN, 'original_v5_historical_runtime_environment')
        self.m = load(cfg['maintenance_guard_path'], V5_PIN, 'original_v5_current_source_observation')
        m = self.m
        check(str(m.REPO) == str(self.h.REPO) == HISTORICAL_REPO
              and str(m.TARGET) == str(self.h.TARGET) == cfg['target'], 'original V5 historical source/target constants')
        # Keep the historical module, including its 86dd SEED, completely original.
        m.REPO = Path(cfg['repo']); m.HEAD = cfg['source']; m.TREE = cfg['tree']
        m.OUT = self.output
        m.cfg = cfg['runtime_guard']
        self.h.OUT = self.output / 'historical-runtime'
        self.h.cfg = cfg['runtime_guard']
        check(m.cfg == RUNTIME_GUARD, 'complete original environment/target/runtime proof contract')
        m.real_directory(self.output.parent)
        os.mkdir(self.output, 0o700)
        os.mkdir(self.h.OUT, 0o700)
        self.inventory = load(cfg['inventory_driver_path'], INVENTORY_PIN, 'original_full_inventory_for_qualification')
        self.initial_raw = None
        self.environment = None
        self.initial_git = None
        self.initial_metadata = None
        self.initial_metadata_v5 = None
        m.read_input(cfg['maintenance_guard_path'], V5_PIN)
        m.read_input(cfg['inventory_driver_path'], INVENTORY_PIN)
        self.h.read_input(cfg['maintenance_guard_path'], V5_PIN)

    def acquire_and_validate(self):
        m, cfg = self.m, self.cfg
        self.lease = os.open(cfg['coordination_lock']['path'], os.O_RDONLY | os.O_NOFOLLOW)
        fcntl.flock(self.lease, fcntl.LOCK_SH | fcntl.LOCK_NB)
        m.jwrite('SOURCE_COORDINATION_SH.json', {'path': cfg['coordination_lock']['path'],
                 **self.current_lock(), 'at': m.now(), 'pid': os.getpid(), 'fd': self.lease,
                 'scope': 'Only cooperative source writers; complete actual source checks remain required.'})
        plan = self.read(cfg['plan_path'], PLAN_PIN, 'PLAN.original.json')
        check(plan['schema'] == 'hepta.utility.exact-source-qualification-plan.v2', 'original reviewed qualification plan')
        aligned = self.observed_proof(cfg['canonical_alignment'], 'CANONICAL_ALIGNMENT')
        self.materialized = self.validate_materialization(aligned)
        self._validate_archive()
        maintenance = self._validate_maintenance(self.materialized)
        final_format, final_raw, final_metadata = self._validate_final_format(maintenance)
        self.initial_git = m.git_state()
        check(self.initial_git == aligned['after']['git_state'] == cfg['current_final_git_state'],
              'current raw Git baseline is the actual canonical endpoint, not materialization')
        m.jwrite('GIT_STATE.before.json', self.initial_git)
        self.initial_raw = self.inventory.inventory(Path(cfg['repo']))
        pin(self.initial_raw, cfg['full_physical_inventory'], 'current complete source equals actual clean alignment')
        self.inventory.require_inventory(self.initial_raw, {'source_sha': cfg['source'], 'source_tree': cfg['tree']})
        value = m.parse(self.initial_raw)
        physical_projection(value)
        check(value['source'] == {'head': cfg['source'], 'tree': cfg['tree'], 'status': ''}
              and all(row['matches_index'] is True for row in value['files']), 'complete canonical source is clean')
        self._validate_canonical(aligned, final_format, final_raw, final_metadata, value)
        projected = native_projection(value)
        pin(projected, cfg['full_native_inventory'], 'original native five-field projection of complete clean source')
        check(hashlib.sha256(projected).hexdigest() == cfg['expected_inventory_sha256'], 'original native expected digest')
        m.gzrecord('SOURCE_INITIAL.complete.inventory.json.gz', self.initial_raw)
        m.gzrecord('SOURCE_INITIAL.native-projection.json.gz', projected)
        self._validate_source_controls(plan, value)
        m.read_input(cfg['native_driver_path'], plan['unchanged_original_controls']['native_driver'])
        if self.runtime:
            self.environment = self.h.environment_preflight()
            desired = cfg['runtime_guard']['environment']
            external = {'target': m.external_directory(m.TARGET, 'current source external target')}
            for name in ('UV_PROJECT_ENVIRONMENT', 'UV_CACHE_DIR', 'RUFF_CACHE_DIR'):
                external[name] = m.external_directory(desired[name], 'current source external ' + name)
            m.jwrite('CURRENT_SOURCE_EXTERNAL_DIRECTORIES.json', external)
        else:
            self.h.validate_runtime_restoration()
            self.environment = {'source_gates_only': True}
        self._require_live_metadata('GIT_METADATA.admission')
        check(m.git_state() == self.initial_git, 'canonical Git unchanged through admission')
        m.jwrite('ADMISSION.json', {'status': 'actual_clean_final_source_admitted',
                 'source': cfg['source'], 'tree': cfg['tree'], 'parents': cfg['parents'],
                 'full_initial_inventory': cfg['full_physical_inventory'],
                 'native_snapshot_sha256': cfg['expected_inventory_sha256'], 'qualification': False, 'at': m.now(),
                 'historical_source_repo': HISTORICAL_REPO, 'provenance_donor_repo': DONOR_REPO,
                 'actual_isolated_materialization': cfg['isolated_materialization'],
                 'actual_maintenance': cfg['actual_maintenance'], 'actual_final_format': cfg['final_format'],
                 'actual_canonical_alignment': cfg['canonical_alignment'],
                 'root_workflow_parent_count': 48})
        return self

    def validate_materialization(self, aligned):
        """Bind the actual d256 start, without identifying it with the final endpoint."""
        proof = self.cfg['isolated_materialization']
        value = self._observed_known('materialization', proof, 'ISOLATED_MATERIALIZATION')
        packet = self._fixed_json('MATERIALIZATION_3BB_PACKET')
        self._fixed('MATERIALIZER_3BB')
        self._fixed('MATERIALIZATION_3BB_CONFIG')
        records = {key: self._fixed_json(name) for key, name in MATERIALIZATION_RECORDS.items()}
        self._check_materialization(value, packet, records)
        catalog = artifact_catalog(records['artifact_records'], False)
        metadata_raw = self._artifact(catalog, MATERIALIZATION_CONTROL / 'run', 'final.git-metadata.json.gz',
                                      'MATERIALIZATION_GIT_METADATA', proof['git_metadata'])
        pin(metadata_raw, proof['git_metadata'], 'actual complete new materialization metadata')
        self.materialization_metadata = self.m.parse(metadata_raw)
        check(isinstance(self.materialization_metadata, list)
              and len(self.materialization_metadata) == 6, 'original complete six materialization Git files')
        check(aligned['before']['commit'] == MATERIALIZED_SUBJECT['commit']
              and aligned['before']['tree'] == MATERIALIZED_SUBJECT['tree']
              and aligned['before']['parents'] == MATERIALIZED_SUBJECT['parents'],
              'canonical begins at the materialized commit after separately reviewed maintenance')
        return value

    def finish(self):
        self.current_lock()
        self.m.verify_original_inputs()
        self.h.verify_original_inputs()
        self.h.jwrite('INPUTS.final.json', self.h.input_pins)
        self.h.jwrite('READONLY_COMMANDS.json', self.h.commands)
        current_git = self.m.git_state()
        self.m.jwrite('GIT_STATE.after.json', current_git)
        if current_git != self.initial_git:
            raise SourceChanged('actual raw Git state changed during qualification')
        self._require_live_metadata('GIT_METADATA.after')
        raw = self.inventory.inventory(Path(self.cfg['repo']))
        self.m.gzrecord('SOURCE_FINAL.complete.inventory.json.gz', raw)
        value = json.loads(raw)
        if value['source'] != {'head': self.cfg['source'], 'tree': self.cfg['tree'], 'status': ''}:
            raise SourceChanged('final source identity changed')
        original = {r['path']: r for r in json.loads(self.initial_raw)['files']}
        actual = {r['path']: r for r in value['files']}
        if len(actual) != len(value['files']):
            raise SourceChanged('duplicate physical source inventory path')
        for path, before in original.items():
            if path not in actual or actual[path] != before:
                raise SourceChanged('source-controlled full inventory row changed: ' + path)
        extras = [r for r in value['files'] if r['path'] not in original]
        # The original b92 native snapshot separately enforces tracked/nonignored
        # equality. Preserve actual ignored JUnit/output entries rather than
        # silently calling this full physical inventory unchanged.
        self.m.jwrite('FULL_PHYSICAL_COMPARISON.json', {'original_rows_identical': True,
                     'full_bytes_equal': raw == self.initial_raw,
                     'additional_physical_entries': extras,
                     'scope': 'Original native snapshot equality is a separate required gate; actual generated outputs remain visible.'})
        self.m.jwrite('INPUTS.final.json', self.m.input_pins)
        self.m.jwrite('READONLY_COMMANDS.json', self.m.commands)
        return {'original_source_rows_unchanged': True, 'extra_physical_entries': len(extras),
                'full_physical_bytes_equal': raw == self.initial_raw}

    @staticmethod
    def _require_complete_bindings(cfg):
        check(cfg.get('historical_source_repo') == HISTORICAL_REPO
              and cfg.get('provenance_donor_repo') == DONOR_REPO and cfg.get('repo') == CURRENT_REPO,
              'three distinct original repository roles')
        check(cfg.get('expected_canonical_subject') == FINAL_SUBJECT
              and cfg.get('source') == FINAL_SUBJECT['commit'] and cfg.get('tree') == FINAL_SUBJECT['tree']
              and cfg.get('parents') == FINAL_SUBJECT['parents'] and cfg.get('expected_file_count') == 15243,
              'actual final source must bind the reviewed immutable canonical subject')
        check(cfg.get('materialized_subject') == MATERIALIZED_SUBJECT and cfg.get('runtime_guard') == RUNTIME_GUARD
              and cfg.get('coordination_lock') == COORDINATION_LOCK,
              'original materialized start, complete runtime contract and coordination inode')
        for key in ('full_physical_inventory', 'full_native_inventory'):
            exact_pin(cfg.get(key), 'actual canonical ' + key + ' required')
        check(cfg.get('expected_inventory_sha256') == cfg['full_native_inventory']['sha256'], 'one native expected digest')
        proof = cfg.get('canonical_alignment')
        check(isinstance(proof, dict) and isinstance(proof.get('job_id'), str) and proof['job_id']
              and proof.get('result_path') == str(CANONICAL_CONTROL / 'run' / 'RESULT.json')
              and isinstance(proof.get('supervisor_path'), str) and Path(proof['supervisor_path']).is_absolute(),
              'actual canonical terminal proof remains required')
        for key in ('result', 'supervisor', 'artifacts', 'before_git_metadata_raw', 'final_git_metadata_raw',
                    'final_index_raw', 'final_index_audit', 'complete_entry_delta', 'allowed_metadata_delta',
                    'commands', 'progress', 'inputs', 'approved_config', 'canonical_packet'):
            exact_pin(proof.get(key), 'actual canonical ' + key + ' remains required')
        check(isinstance(cfg.get('current_final_git_state'), dict)
              and cfg.get('canonical_complete_git_metadata') == proof['final_git_metadata_raw']
              and cfg.get('canonical_original_index') == proof['final_index_raw'], 'one complete canonical Git baseline')
        check(cfg.get('actual_final_format_postimages_reviewed') is True
              and cfg.get('actual_final_fences_reviewed') is True
              and cfg.get('reviewed_formatter_changed_paths') == [], 'actual final source reviews required')
        check(cfg.get('source_control_pin_overrides') == [WORKFLOW_OVERRIDE_READY], 'one explicit workflow successor pin')
        for key in ('plan_path', 'native_driver_path', 'maintenance_guard_path', 'inventory_driver_path'):
            check(isinstance(cfg.get(key), str) and Path(cfg[key]).is_absolute(), 'fixed staged original control ' + key)

    def _fixed(self, name):
        if name not in self._fixed_raw:
            spec = FIXED_INPUTS[name]
            raw = self.m.read_input(spec['path'], spec['pin'])
            self._fixed_raw[name] = raw
        return self._fixed_raw[name]

    def _fixed_json(self, name):
        return self.m.parse(self._fixed(name))

    def _observed_known(self, name, proof, prefix):
        expected = ACTUAL_PROOFS[name]
        check(all(proof.get(key) == expected[key] for key in (
            'result_path', 'result', 'supervisor_path', 'supervisor', 'job_id')), 'exact actual ' + name + ' proof')
        return self.observed_proof(proof, prefix)

    def _artifact(self, catalog, root, name, output, raw_pin=None):
        check(name in catalog, 'complete original artifact: ' + name)
        row = catalog[name]
        raw = self.m.read_input(Path(root) / name, pin_fields(row))
        if name.endswith('.gz'):
            expected = {'bytes': row['raw_bytes'], 'sha256': row['raw_sha256'], 'git_blob': row['raw_git_blob']}
            exact_pin(expected, 'original gzip full raw identity')
            check(expected['bytes'] <= 40000000, 'original V5 input bound for decoded proof')
            with gzip.GzipFile(fileobj=io.BytesIO(raw), mode='rb') as stream:
                decoded = stream.read(expected['bytes'] + 1)
            pin(decoded, expected, 'complete decoded original artifact: ' + name)
            raw = decoded
        if raw_pin is not None:
            pin(raw, raw_pin, output + ': explicit original raw artifact binding: ' + name)
        return raw

    @staticmethod
    def _check_materialization(value, packet, records):
        check(packet['source_repo'] == DONOR_REPO and packet['destination_repo'] == CURRENT_REPO
              and {key: packet['current'][key] for key in ('commit', 'tree', 'parents')} == MATERIALIZED_SUBJECT,
              'exact donor and materialized subject')
        check(value['format'] == 'hepta-complete-candidate-materialization-result-v1'
              and value['status'] == 'MATERIALIZED_EXACT_CANDIDATE_FOR_MAINTENANCE_REVIEW_ONLY'
              and value['source_repo'] == DONOR_REPO and value['destination_repo'] == CURRENT_REPO
              and value['source_commit'] == MATERIALIZED_SUBJECT['commit']
              and value['source_tree'] == MATERIALIZED_SUBJECT['tree']
              and value['parents'] == MATERIALIZED_SUBJECT['parents'], 'actual materialization producer roles')
        for key in ('new_repo_created', 'action_completed', 'new_files_and_directories_synced',
                    'donor_physical_and_git_file_state_unchanged', 'input_identities_unchanged'):
            check(value.get(key) is True, 'actual materialization ' + key)
        for key in ('qualification', 'old_source_writes', 'remote_ref_updates', 'cargo_or_formatter_started',
                    'dependency_installation_started', 'automatic_retry', 'rollback'):
            check(value.get(key) is False, 'materialization did not authorize ' + key)
        check(value['test_commands_dispatched'] == 0 and value['physical_leaves_created'] == 15243
              and value['new_objects_fully_verified'] == 16661 and value['donor_objects_fully_verified'] == 16449
              and value['cleanup_errors'] == [] and not any(key in value for key in ('error', 'retention_error')),
              'complete materialization object/leaf/cleanup observations')
        audited(value, ['donor_physical_source_and_git_files', 'new_source_and_git', 'inputs_and_coordination'],
                'all original materialization audits')
        current = value['current_source_after']
        check(value['current_source_before'] == current
              and current['head'] == MATERIALIZED_SUBJECT['commit']
              and current['tree'] == MATERIALIZED_SUBJECT['tree'] and current['parents'] == MATERIALIZED_SUBJECT['parents']
              and current['status'] == '' and pin_fields(current['inventory']) == packet['current']['inventory']
              and current['inventory']['filesystem_entries'] == current['inventory']['tracked_entries'] == 15243
              and current['native_inventory'] == packet['current']['native_inventory'], 'complete actual materialized start')
        state = value['current_git_state_after']
        check(value['current_git_state_before'] == state and set(state) == {
            'head_raw_sha256', 'head', 'tree', 'index_bytes', 'index_sha256',
            'config_bytes', 'config_sha256', 'refs_bytes', 'refs_sha256'}
              and state['head'] == current['head'] and state['tree'] == current['tree']
              and state['refs_bytes'] == 0 and state['refs_sha256'] == hashlib.sha256(b'').hexdigest(),
              'actual detached materialization Git state')
        index = value['current_index']
        check(index['raw']['bytes'] == state['index_bytes'] and index['raw']['sha256'] == state['index_sha256']
              and index['entries'] == 15243 and index['all_entry_logical_identities_verified'] is True
              and index['all_actual_stat_fields_verified'] is True
              and index['assume_unchanged_or_skip_worktree_entries'] == 0
              and [row['name'] for row in index['extensions']] == ['TREE'], 'original normal materialized index')
        expected_scope = dict(packet['object_scope'], complete_ancestry=False,
                              donor_objects_must_be_read_from_git_bodies=16449, format_base_leaf_identities_verified=True)
        check(value['object_scope'] == expected_scope
              and expected_scope['counts'] == {'blob': 14805, 'tree': 1852, 'commit': 4}
              and expected_scope['union_objects'] == 16661, 'exact four-snapshot closure, not complete ancestry')
        check(value['donor_source_before'] == value['donor_source_after']
              and value['donor_source_after']['present'] == 15188 and value['donor_source_after']['missing'] == []
              and value['donor_source_after']['native_inventory'] == packet['donor']['native_inventory']
              and value['donor_git_state_before'] == value['donor_git_state_after'], 'unchanged original clean donor')
        donor_git = value['donor_git_state_after']
        check(set(donor_git) == set(packet['donor_git']) | {'git_state', 'refs'}
              and all(donor_git[key] == item for key, item in packet['donor_git'].items())
              and donor_git['git_state'] == packet['donor_proof']['current_git_state'], 'complete declared donor Git proof')
        lock = value['coordination_lock']
        check(lock['path'] == COORDINATION_LOCK['path'] and lock['mode'] == 'LOCK_EX'
              and all(lock['stat'][a] == COORDINATION_LOCK[b] for a, b in (
                  ('st_dev', 'device'), ('st_ino', 'inode'), ('st_uid', 'uid'), ('st_nlink', 'nlink')))
              and stat.S_IMODE(lock['stat']['st_mode']) == COORDINATION_LOCK['mode'], 'same actual EX inode')
        for key, name in MATERIALIZATION_RECORDS.items():
            check(pin_fields(value[key]) == FIXED_INPUTS[name]['pin'], 'exact original materialization record ' + key)
        check(records['command_records'] and all(row.get('actual_terminal') == 'observed'
              and row.get('returncode') == 0 and row.get('timed_out') is False
              for row in records['command_records']), 'all actual materialization command terminals')
        check([row['kind'] for row in records['mutation_records']] == [
            'create_new_repository', 'write_exact_new_physical_source_and_standard_pack',
            'import_independent_standard_pack', 'new_index_and_detached_head']
              and all(row['actual_terminal'] == 'observed' for row in records['mutation_records']),
              'four original scoped mutation terminals')
        for name in ('MATERIALIZER_3BB', 'MATERIALIZATION_3BB_PACKET', 'MATERIALIZATION_3BB_CONFIG'):
            spec = FIXED_INPUTS[name]
            check(records['input_records'][spec['path']] == spec['pin'], 'exact approved materialization input')

    def _validate_archive(self):
        proof = self.cfg['archive_restoration']
        value = self._observed_known('archive', proof, 'ARCHIVE_V3')
        readback = self._fixed_json('ARCHIVE_V3_READBACK')
        original_catalog = self._fixed_json('ARCHIVE_V3_ARTIFACTS')
        check(set(original_catalog) == {'files', 'terminal_report'}
              and original_catalog['terminal_report'] == 'RESULT.json', 'original archive artifact envelope')
        catalog = artifact_catalog(original_catalog['files'], False)
        check(pin_fields(catalog['ARCHIVE_READBACK.json']) == FIXED_INPUTS['ARCHIVE_V3_READBACK']['pin'],
              'original archive readback is in the actual complete catalog')
        environment = self._fixed_json('HISTORICAL_ENVIRONMENT_READY')
        self._check_archive(value, readback, environment)
        self.m.jwrite('ARCHIVE_HISTORY_AND_CURRENT_CONTRACT.json', {
            'historical_environment': FIXED_INPUTS['HISTORICAL_ENVIRONMENT_READY']['pin'],
            'actual_archive_restore': proof, 'projection_fields': ['path', 'resolved', 'bytes', 'sha256', 'mode'],
            'historical_stat_rewritten': False, 'live_environment_check': 'original unchanged V5 environment_preflight'})

    @staticmethod
    def _check_archive(value, readback, environment):
        check(value['format'] == 'hepta-v8-single-archive-restoration-result-v1'
              and value['status'] == 'ARCHIVE_RESTORED_FOR_REVIEW_ONLY'
              and value['source_repo'] == DONOR_REPO and value['source_commit'] == DONOR_SUBJECT['commit']
              and value['source_tree'] == DONOR_SUBJECT['tree'], 'independent archive restoration provenance')
        for key in ('source_unchanged', 'destination_created', 'downloads_started', 'publication_intent_recorded'):
            check(value[key] is True, 'actual archive restoration ' + key)
        for key in ('source_writes', 'environment_changes', 'dependency_installation', 'native_main_started',
                    'automatic_retry', 'qualification'):
            check(value[key] is False, 'archive restoration did not authorize ' + key)
        check(value['cargo_or_test_commands'] == [], 'archive restoration ran no Cargo/test command')
        audited(value, ['source', 'inputs_environment', 'materials'], 'complete actual archive restoration audits')
        materials = next(row for row in value['final_audits'] if row['check'] == 'materials')
        check(readback == value['archive_actual'] == materials['archive'] == ARCHIVE_ACTUAL,
              'complete original new archive identity and stat')
        observed = {'path': readback['path'], 'resolved': readback['path'],
                    'bytes': readback['identity']['bytes'], 'sha256': readback['identity']['sha256'],
                    'mode': stat.S_IMODE(readback['stat']['st_mode'])}
        old = environment['tool_and_material_files']['v8-sandbox-archive']
        check(observed == RUNTIME_GUARD['v8_files']['RUSTY_V8_ARCHIVE']
              == {key: old[key] for key in observed}, 'original five-field content projection, no historical inode rewrite')

    def _validate_maintenance(self, materialized):
        value = self._observed_known('maintenance', self.cfg['actual_maintenance'], 'MAINTENANCE_41E')
        self._fixed('MAINTENANCE_41E_DRIVER')
        original_cfg = self._fixed_json('MAINTENANCE_41E_CONFIG')
        inputs = self._fixed_json('MAINTENANCE_41E_INPUT_IDENTITIES')
        catalog = artifact_catalog(self._fixed_json('MAINTENANCE_41E_ARTIFACTS'), True)
        self._check_maintenance(value, materialized, original_cfg, inputs)
        initial = catalog['SOURCE.before.inventory.json.gz']
        check({key: initial['raw_' + key] for key in ('bytes', 'sha256', 'git_blob')}
              == pin_fields(materialized['current_source_after']['inventory']),
              'pinned original maintenance catalog and RESULT retain the complete materialized starting inventory')
        before = self._artifact(catalog, MAINTENANCE_CONTROL / 'run', 'SOURCE_GIT_METADATA.before.json.gz',
                                'MAINTENANCE_GIT_METADATA_BEFORE', MAINTENANCE_METADATA_PIN)
        after = self._artifact(catalog, MAINTENANCE_CONTROL / 'run', 'SOURCE_GIT_METADATA.after.json.gz',
                               'MAINTENANCE_GIT_METADATA_AFTER', MAINTENANCE_METADATA_PIN)
        check(before == after, 'complete maintenance Git metadata unchanged')
        v5_files = metadata_file_projection(self.m.parse(before))
        check(set(v5_files) == {row['path'] for row in self.materialization_metadata}, 'six actual Git file paths bridge')
        for row in self.materialization_metadata:
            observed = v5_files[row['path']]
            expected = {'path': row['path'], 'kind': 'file', 'bytes': row['bytes'], 'sha256': row['sha256'],
                        'mode': stat.S_IMODE(row['stat']['st_mode'])}
            expected.update({a: row['stat'][b] for a, b in [('device', 'st_dev'), ('inode', 'st_ino'),
                ('nlink', 'st_nlink'), ('mtime_ns', 'st_mtime_ns'), ('ctime_ns', 'st_ctime_ns')]})
            check(observed == expected, 'every actual materialization file field retained by maintenance')
        git_raw = self._artifact(catalog, MAINTENANCE_CONTROL / 'run', 'SOURCE_GIT_STATE.before.json',
                                'MAINTENANCE_GIT_BEFORE', MATERIALIZED_GIT_PIN)
        check(self.m.parse(git_raw) == materialized['current_git_state_after'], 'actual maintenance starts on materialized Git')
        final_git = self._artifact(catalog, MAINTENANCE_CONTROL / 'run', 'final.git-state.json',
                                  'MAINTENANCE_GIT_AFTER', MATERIALIZED_GIT_PIN)
        check(git_raw == final_git, 'complete maintenance original Git state retained')
        final = catalog['final.inventory.json.gz']
        check({key: final['raw_' + key] for key in ('bytes', 'sha256', 'git_blob')}
              == value['actual_final_source']['inventory'], 'pinned complete actual maintenance final inventory')
        return value

    @staticmethod
    def _check_maintenance(value, materialized, original_cfg, inputs):
        check(value['format'] == 'hepta-original-scoped-maintenance-result-v1'
              and value['status'] == 'MAINTENANCE_COMMANDS_COMPLETED_REVIEW_REQUIRED'
              and value['source_repo'] == CURRENT_REPO and value['source_commit'] == MATERIALIZED_SUBJECT['commit']
              and value['source_tree'] == MATERIALIZED_SUBJECT['tree'] and value['parents'] == MATERIALIZED_SUBJECT['parents'],
              'actual maintenance source identity')
        check(value['source_initial_inventory'] == materialized['current_source_after']['inventory']
              and value['actual_materialization_job'] == ACTUAL_PROOFS['materialization']['job_id']
              and value['actual_materialization_result'] == ACTUAL_PROOFS['materialization']['result'],
              'actual 3bb to 41e link')
        for name, key in [('runtime', 'runtime'), ('archive', 'archive')]:
            check(value['actual_' + key + '_restoration_job'] == ACTUAL_PROOFS[name]['job_id']
                  and value['actual_' + key + '_restoration_result'] == ACTUAL_PROOFS[name]['result'],
                  'separate original ' + key + ' restoration proof')
        check(value['qualification'] is False and value['source_ref_updates'] is False
              and value['automatic_retry'] is False and value['test_commands_dispatched'] == 0
              and value['source_preflight_complete'] is True and value['git_metadata_unchanged'] is True
              and value['attempted_commands'] == ['fix', 'fmt'] and value['not_run_commands'] == [],
              'one actual original fix and fmt, no inferred test qualification')
        check(len(value['stages']) == 2, 'two original maintenance commands')
        require_stage(value['stages'][0], 'fix', FIX_ARGV, 7200)
        require_stage(value['stages'][1], 'fmt', FMT_ARGV, 900)
        audited(value, ['actual_complete_source_and_git', 'original_inputs'], 'two complete maintenance audits')
        audit = next(row for row in value['final_audits'] if row['check'] == 'original_inputs')
        check(audit['input_count'] == 24 and audit['unchanged'] is True and len(inputs) == 24,
              'all actual maintenance inputs unchanged')
        for name in ('MAINTENANCE_41E_DRIVER', 'MAINTENANCE_41E_CONFIG'):
            spec = FIXED_INPUTS[name]
            check(inputs[spec['path']] == spec['pin'], 'exact original maintenance control input')
        check(original_cfg['source_inventory'] == materialized['current_source_after']['inventory']
              and original_cfg['materialization']['result'] == ACTUAL_PROOFS['materialization']['result']
              and original_cfg['runtime_restoration'] == RUNTIME_GUARD['runtime_restoration'],
              'complete original maintenance control provenance')
        complete = value['actual_final_source']
        check(complete['complete'] is True and complete['inventory'] == MAINTENANCE_FINAL_PIN
              and complete['postimages']['all_actual_physical_leaf_count'] == 15243
              and complete['postimages']['all_actual_physical_tree'] == MAINTENANCE_TREE,
              'actual maintained complete dirty source endpoint')

    def _validate_final_format(self, maintenance):
        value = self._observed_known('final_format', self.cfg['final_format'], 'FINAL_FORMAT')
        self._fixed('FINAL_FORMAT_DRIVER')
        control = self._fixed_json('FINAL_FORMAT_CONFIG')
        catalog = artifact_catalog(self._fixed_json('FINAL_FORMAT_ARTIFACTS'), True)
        self._check_final_format(value, maintenance, control)
        root = FINAL_FORMAT_CONTROL / 'run'
        inputs = self.m.parse(self._artifact(catalog, root, 'INPUT_IDENTITIES.json', 'FINAL_FORMAT_INPUTS'))
        check(len(inputs) == 28, 'complete original final-format input map')
        for name in ('FINAL_FORMAT_DRIVER', 'FINAL_FORMAT_CONFIG'):
            spec = FIXED_INPUTS[name]
            check(inputs[spec['path']] == spec['pin'], 'exact original final-format control input')
        before = catalog['SOURCE.before.inventory.json.gz']
        check({key: before['raw_' + key] for key in ('bytes', 'sha256', 'git_blob')}
              == maintenance['actual_final_source']['inventory'],
              'pinned actual 50f before bytes identify the complete actual 41e final bytes')
        meta_before = self._artifact(catalog, root, 'SOURCE_GIT_METADATA.before.json.gz',
                                     'FINAL_FORMAT_METADATA_BEFORE', MAINTENANCE_METADATA_PIN)
        meta_after = self._artifact(catalog, root, 'SOURCE_GIT_METADATA.after.json.gz',
                                    'FINAL_FORMAT_METADATA_AFTER', MAINTENANCE_METADATA_PIN)
        check(meta_before == meta_after, 'complete actual final-format Git metadata unchanged')
        self.final_format_git_raw = self._artifact(catalog, root, 'final.git-state.json',
                                                  'FINAL_FORMAT_GIT', MATERIALIZED_GIT_PIN)
        check(self.m.parse(self.final_format_git_raw) == self.materialized['current_git_state_after'],
              'Git unchanged across actual maintenance and final-format source changes')
        final_raw = self._artifact(catalog, root, 'final.inventory.json.gz', 'FINAL_FORMAT_SOURCE_AFTER', FINAL_FORMAT_PIN)
        empty = self.m.parse(self._artifact(catalog, root, 'fmt.after.postimages.json.gz', 'FINAL_FORMAT_EMPTY_TRANSITION'))
        check(empty['changes'] == [], 'complete actual formatter transition has no new changes')
        return value, final_raw, meta_after

    @staticmethod
    def _check_final_format(value, maintenance, control):
        check(value['format'] == 'hepta-reviewed-nonrust-final-format-result-v1'
              and value['status'] == 'APPLIED_AND_FORMATTED_REVIEW_REQUIRED'
              and value['source_repo'] == CURRENT_REPO and value['source_commit'] == MATERIALIZED_SUBJECT['commit']
              and value['source_tree'] == MATERIALIZED_SUBJECT['tree'] and value['parents'] == MATERIALIZED_SUBJECT['parents'],
              'actual final-format producer identity')
        check(value['actual_maintenance_job'] == ACTUAL_PROOFS['maintenance']['job_id']
              and value['actual_maintenance_result'] == ACTUAL_PROOFS['maintenance']['result']
              and value['baseline_inventory'] == maintenance['actual_final_source']['inventory']
              and value['baseline_physical_tree'] == maintenance['actual_final_source']['postimages']['all_actual_physical_tree'],
              'actual maintained source to final-format before identity')
        check(value['qualification'] is False and value['fix_dispatched'] is False
              and value['test_commands_dispatched'] == 0 and value['source_ref_updates'] is False
              and value['automatic_retry'] is False and value['attempted_commands'] == ['fmt']
              and value['not_run_commands'] == [] and value['nonrust_application_complete'] is True
              and value['git_metadata_unchanged'] is True and value['formatter_changed_paths'] == [],
              'one actual final original fmt, exactly reviewed non-Rust application')
        check(value['applied_paths'] == FINAL_NONRUST_PATHS == control['allowed_paths']
              and value['application']['complete'] is True and value['application']['inventory'] == FINAL_FORMAT_PIN,
              'all four actual non-Rust application paths')
        check(len(value['stages']) == 1, 'one final formatter stage')
        require_stage(value['stages'][0], 'fmt', FMT_ARGV, 900)
        audited(value, ['actual_complete_source_and_git', 'original_inputs', 'same_source_coordination_lock'],
                'all actual final-format audits')
        audit = next(row for row in value['final_audits'] if row['check'] == 'original_inputs')
        check(audit['input_count'] == 28 and audit['unchanged'] is True, '28 actual final-format inputs unchanged')
        complete = value['actual_final_source']
        check(complete['complete'] is True and complete['inventory'] == FINAL_FORMAT_PIN
              and complete['postimages']['all_actual_physical_tree'] == FINAL_SUBJECT['tree']
              and complete['postimages']['all_actual_physical_leaf_count'] == 15243
              and complete['postimages']['paths'] == FINAL_NONRUST_PATHS, 'actual final physical source is complete')

    def _validate_canonical(self, aligned, final_format, final_raw, final_metadata, clean):
        cfg, m = self.cfg, self.m
        proof = cfg['canonical_alignment']
        m.read_input(CANONICAL_CONTROL / 'driver.py', CANONICAL_DRIVER_PIN)
        control = self.read(CANONICAL_CONTROL / 'APPROVED_CONFIG.json', proof['approved_config'], 'CANONICAL_CONFIG.original.json')
        m.read_input(CANONICAL_CONTROL / 'CANONICAL_PACKET.json', proof['canonical_packet'])
        artifacts = self.read(CANONICAL_CONTROL / 'run' / 'ARTIFACTS.json', proof['artifacts'], 'CANONICAL_ARTIFACTS.original.json')
        catalog = artifact_catalog(artifacts, False)
        check(artifacts == aligned['artifacts'] + [dict(proof['result'], name='RESULT.json')],
              'original canonical artifact ordering includes RESULT only after its retained list')
        self._check_canonical(aligned, final_format, cfg, control)
        root = CANONICAL_CONTROL / 'run'
        before_metadata = self._artifact(catalog, root, 'GIT_METADATA.before.json.gz',
                                         'CANONICAL_METADATA_BEFORE', proof['before_git_metadata_raw'])
        check(canonical_to_v5_projection(m.parse(before_metadata)) == final_metadata,
              'complete actual canonical-before metadata projected to actual final-format V5 bytes')
        after_metadata = self._artifact(catalog, root, 'GIT_METADATA.final.json.gz',
                                        'CANONICAL_METADATA_AFTER', proof['final_git_metadata_raw'])
        self.initial_metadata = m.parse(after_metadata)
        self.initial_metadata_v5 = canonical_to_v5_projection(self.initial_metadata)
        changes = m.parse(self._artifact(catalog, root, 'GIT_METADATA.allowed-actual-delta.json',
                                         'CANONICAL_METADATA_DELTA', proof['allowed_metadata_delta']))
        old = {row['path']: row for row in m.parse(before_metadata)['files']}
        new = {row['path']: row for row in self.initial_metadata['files']}
        calculated = [{'path': path, 'before': old.get(path), 'after': new.get(path)}
                      for path in sorted(set(old) | set(new)) if old.get(path) != new.get(path)]
        check(changes == calculated == aligned['git_metadata_actual_changes'], 'complete actual canonical metadata delta')
        recorded_clean = catalog['SOURCE.final.inventory.json.gz']
        check({key: recorded_clean['raw_' + key] for key in ('bytes', 'sha256', 'git_blob')}
              == cfg['full_physical_inventory'], 'complete canonical output catalog is the pinned current inventory')
        check(physical_projection(m.parse(final_raw)) == physical_projection(clean),
              'actual final-format to canonical preserves every complete physical leaf field')
        check(clean['source'] == {'head': cfg['source'], 'tree': cfg['tree'], 'status': ''}
              and all(row['matches_index'] is True for row in clean['files']), 'actual canonical complete clean inventory')
        index_raw = self._artifact(catalog, root, 'INDEX.final.raw.gz', 'CANONICAL_INDEX_RAW', proof['final_index_raw'])
        audit = m.parse(self._artifact(catalog, root, 'INDEX.final.audit.json.gz',
                                       'CANONICAL_INDEX_AUDIT', proof['final_index_audit']))
        self._artifact(catalog, root, 'INDEX.complete-entry-delta.json.gz',
                       'CANONICAL_INDEX_ENTRY_DELTA', proof['complete_entry_delta'])
        state_raw = self._artifact(catalog, root, 'GIT_STATE.final.json', 'CANONICAL_FINAL_GIT_STATE')
        check(m.parse(state_raw) == aligned['after']['git_state'] == cfg['current_final_git_state'],
              'actual final canonical Git state record')
        check(identity(index_raw)['bytes'] == aligned['after']['git_state']['index_bytes']
              and identity(index_raw)['sha256'] == aligned['after']['git_state']['index_sha256'],
              'actual original final index is the current canonical index')
        m.read_input(Path(CURRENT_REPO) / '.git' / 'index', proof['final_index_raw'])
        self._validate_index_audit(audit, clean)
        commands = self.read(root / 'COMMANDS.json', proof['commands'], 'CANONICAL_COMMANDS.original.json')
        progress = self.read(root / 'MUTATION_PROGRESS.json', proof['progress'], 'CANONICAL_PROGRESS.original.json')
        check(commands == aligned['commands'] and progress == aligned['mutation_intents'],
              'all original canonical command and mutation records retained')
        original_inputs = self.read(root / 'INPUTS.final.json', proof['inputs'], 'CANONICAL_INPUTS.original.json')
        for path, expected in [(CANONICAL_CONTROL / 'driver.py', CANONICAL_DRIVER_PIN),
                               (CANONICAL_CONTROL / 'APPROVED_CONFIG.json', proof['approved_config']),
                               (CANONICAL_CONTROL / 'CANONICAL_PACKET.json', proof['canonical_packet'])]:
            check(original_inputs[str(path)] == expected, 'canonical consumed the exact reviewed original control')
        # Some original probes explicitly allow a nonzero status. Preserve their
        # exact records and producer decisions; do not convert them into retries.
        m.jwrite('HISTORICAL_TO_CURRENT_SOURCE_CHAIN.json', {
            'historical_source_repo': HISTORICAL_REPO, 'provenance_donor_repo': DONOR_REPO,
            'current_source_repo': CURRENT_REPO, 'materialized_subject': MATERIALIZED_SUBJECT,
            'actual_materialization': cfg['isolated_materialization'], 'actual_maintenance': cfg['actual_maintenance'],
            'actual_final_format': cfg['final_format'], 'actual_canonical_alignment': proof,
            'final_subject': FINAL_SUBJECT, 'qualification': False,
            'scope': 'Four distinct actual operations; history is retained and the current baseline comes only from canonical alignment.'})

    @staticmethod
    def _check_canonical(aligned, final_format, cfg, control):
        check(aligned['format'] == 'hepta-final-canonical-alignment-result-v1'
              and aligned['status'] == 'CANONICAL_SOURCE_ALIGNED_CLEAN_ONLY'
              and aligned['source_repo'] == CURRENT_REPO and aligned['physical_source_writes_dispatched'] == 0
              and aligned['cargo_or_formatter_started'] is False and aligned['test_commands_dispatched'] == 0
              and aligned['source_branch_refs_updated'] is False and aligned['remote_ref_updates'] is False
              and aligned['automatic_retry'] is False, 'actual clean canonical alignment only')
        audited(aligned, ['source', 'git', 'inputs'], 'complete actual canonical audits')
        before, after = aligned['before'], aligned['after']
        check({key: before[key] for key in ('commit', 'tree', 'parents')} == MATERIALIZED_SUBJECT
              and pin_fields(before['inventory']) == final_format['actual_final_source']['inventory']
              and before['git_state'] == MATERIALIZED_GIT_STATE, 'actual final-format to canonical starting point')
        check({key: after[key] for key in ('commit', 'tree', 'parents')} == FINAL_SUBJECT
              and pin_fields(after['inventory']) == cfg['full_physical_inventory']
              and after['inventory']['tracked_entries'] == after['inventory']['filesystem_entries'] == 15243
              and after['git_state'] == cfg['current_final_git_state'], 'actual canonical endpoint identity')
        check(all(aligned['actual'][key] is True for key in ('physical_bytes_unchanged', 'physical_modes_unchanged',
              'complete_source_clean', 'detached', 'index_equals_tree', 'normal_stat_refresh_verified')),
              'actual physical preservation and normal canonical index')
        check(aligned['final_format'] == {'job_id': ACTUAL_PROOFS['final_format']['job_id'],
              'result': ACTUAL_PROOFS['final_format']['result'], 'supervisor': ACTUAL_PROOFS['final_format']['supervisor'],
              'git_state': MATERIALIZED_GIT_PIN}, 'canonical refers to the exact actual final formatter')
        check(control['format'] == 'hepta-final-canonical-alignment-config-v1'
              and control['root_execution_approved'] is True and control['source_repo'] == CURRENT_REPO
              and control['before_commit'] == before['commit'] and control['before_tree'] == before['tree']
              and control['before_parents'] == before['parents'] and pin_fields(control['before_inventory']) == FINAL_FORMAT_PIN
              and control['after_commit'] == after['commit'] and control['after_tree'] == after['tree']
              and control['after_parents'] == after['parents']
              and pin_fields(control['after_inventory']) == cfg['full_physical_inventory']
              and control['expected_before_git_state'] == before['git_state']
              and control['canonical_packet'] == cfg['canonical_alignment']['canonical_packet']
              and control['complete_leaf_count'] == 15243 and control['action_seconds'] == 600
              and control['record_seconds'] == 180 and control['outer_seconds'] == 900,
              'exact original canonical control and budgets')

    @staticmethod
    def _validate_index_audit(audit, clean):
        check(audit['entry_count'] == 15243 and audit['all_entries_equal_canonical_tree'] is True
              and audit['all_stat_fields_match_actual_files'] is True
              and [row['name'] for row in audit['extensions']] == ['TREE'], 'actual complete canonical index audit')
        entries = audit['entries']
        rows = {row['path']: row for row in clean['files']}
        check(len(entries) == len(rows) == 15243
              and [row['path'] for row in entries] == sorted(rows, key=os.fsencode), 'all original index entries exactly once')
        for entry in entries:
            path = entry['path']; row = rows[path]
            check(entry['mode'] == row['index_mode'] and entry['sha'] == row['index_blob'] == row['working_blob']
                  and entry['flags'] == min(len(os.fsencode(path)), 0xfff), 'normal original canonical index logical entry')
            observed = (Path(CURRENT_REPO) / path).lstat()
            exact = [observed.st_ctime_ns // 1000000000, observed.st_ctime_ns % 1000000000,
                     observed.st_mtime_ns // 1000000000, observed.st_mtime_ns % 1000000000,
                     observed.st_dev & 0xffffffff, observed.st_ino & 0xffffffff, int(entry['mode'], 8),
                     observed.st_uid, observed.st_gid, observed.st_size & 0xffffffff]
            check(entry['stat'] == exact, 'actual canonical index full stat and ownership still current: ' + path)

    def _require_live_metadata(self, name):
        check(self.initial_metadata is not None, 'actual complete canonical metadata required')
        live = stable_canonical_metadata(Path(CURRENT_REPO) / '.git')
        raw = (json.dumps(live, sort_keys=True, separators=(',', ':')) + '\n').encode()
        self.m.gzrecord(name + '.canonical.json.gz', raw)
        if live != self.initial_metadata:
            raise SourceChanged('complete canonical Git metadata including uid/gid changed')
        projected = canonical_to_v5_projection(live)
        original_v5 = self.m.metadata_inventory(Path(CURRENT_REPO) / '.git')
        self.m.gzrecord(name + '.original-v5.json.gz', original_v5)
        if projected != self.initial_metadata_v5 or original_v5 != projected:
            raise SourceChanged('complete stable canonical metadata does not equal the original V5 DFS observation')

    def _validate_source_controls(self, plan, inventory):
        originals = plan['unchanged_original_controls']['reviewed_source_pins']['files']
        check(len(originals) == 12 and len({row['path'] for row in originals}) == 12,
              'all twelve original plan source pins remain present')
        rows = {row['path']: row for row in inventory['files']}
        applied, originals_seen = [], []
        workflow_raw = None
        for item in originals:
            expected = pin_fields(item)
            originals_seen.append(item)
            if item['path'] == WORKFLOW_OVERRIDE_READY['path']:
                check(expected == WORKFLOW_OVERRIDE_READY['original_plan_pin'], 'the single historical workflow pin')
                expected = WORKFLOW_OVERRIDE_READY['reviewed_current_pin']
                applied.append(item['path'])
            raw = self.m.read_input(Path(CURRENT_REPO) / item['path'], expected)
            row = rows[item['path']]
            check(row['bytes'] == expected['bytes'] and row['sha256'] == expected['sha256']
                  and row['working_blob'] == row['index_blob'] == expected['git_blob']
                  and row['stable'] is True and row['matches_index'] is True,
                  'current control exact bytes also occur in the complete canonical inventory')
            if item['path'] == WORKFLOW_OVERRIDE_READY['path']:
                workflow_raw = raw
        check(applied == [WORKFLOW_OVERRIDE_READY['path']], 'one explicit override; eleven original pins unchanged')
        marker = '          cat > "$RUNNER_TEMP/daemon-learning-driver.py" <<\'PY\'\n'
        text = workflow_raw.decode('utf-8')
        check(text.count(marker) == 1 and '          PY\n' in text.split(marker, 1)[1], 'original embedded workflow driver')
        driver = textwrap.dedent(text.split(marker, 1)[1].split('          PY\n', 1)[0])
        constants = {}
        for node in ast.parse(driver).body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                name = getattr(node.targets[0], 'id', None)
                if name in ('parents', 'packages'):
                    check(name not in constants, 'one original workflow constant')
                    constants[name] = ast.literal_eval(node.value)
        check(set(constants) == {'parents', 'packages'} and constants['packages'] == ORIGINAL_ORDINARY_PACKAGES
              and len(constants['parents']) == 48
              and len(set(constants['parents'])) == 48
              and all(isinstance(name, str) and name for name in constants['parents']),
              'exact forty-eight original-AST Root parents and unchanged ordinary packages')
        self.m.jwrite('SOURCE_CONTROL_PIN_BINDINGS.json', {
            'original_plan': PLAN_PIN, 'all_original_rows': originals_seen,
            'explicit_overrides': [WORKFLOW_OVERRIDE_READY], 'unchanged_original_pins': 11,
            'actual_workflow': WORKFLOW_OVERRIDE_READY['reviewed_current_pin'],
            'actual_root_parents': constants['parents'], 'actual_packages': constants['packages'],
            'original_driver_and_filters_unchanged': True, 'test_execution_observed': False})
