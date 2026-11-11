"""New v2 terminal/auditor metadata admission; never reads a live process or model."""
from metadata_io import AUDIT_RSS as AUDITOR_RSS, AUDITOR_SHA, AUDIT_WHOLE, VerifiedArchive
from resource_arithmetic import nonnegative, require, roster
from native_envelope import verify_native


def bounded(value, maximum, label):
    require(nonnegative(value, label) <= maximum, label+' exceeds fixed limit')


def terminal_roster(controller, commands, terminal):
    names = set(roster('hcsn'))
    require(terminal.get('state') in ('succeeded','failed','cancelled')
            and all(terminal.get(k) is True for k in
                    ('output_complete','output_durable','terminal_publication_confirmed')),
            'durable native terminal absent')
    require(controller.get('status') == 'completed_attempt_roster'
            and controller.get('execution_requested') is True
            and controller.get('confirmation_access') is False
            and controller.get('source_inputs_unchanged') is True, 'C2 terminal/source gate failed')
    rows = controller['attempts']
    require(len(rows)==6 and {r['name'] for r in rows}==names, 'missing/duplicate C2 opportunity')
    require({r['name'] for r in commands}==names, 'raw command opportunity roster differs')
    pids = []
    for row in rows:
        require(type(row.get('process_started')) is bool and not row.get('child_terminal_unknown')
                and row.get('status') not in ('running','preparing','started'), 'unknown/live C2 attempt')
        selected = [r for r in commands if r['name']==row['name']]
        require(selected and selected[-1]==row, 'terminal command differs from raw attempt')
        starts = [r for r in selected if r.get('status')=='running']
        require(len(starts)==int(row['process_started']), 'duplicate/missing actual launch')
        if row['process_started']:
            require(type(row.get('pid')) is int and row['pid']>0 and type(row.get('returncode')) is int,
                    'missing actual process terminal')
            require(starts[0].get('pid')==row['pid'], 'launch/terminal PID differs')
            pids.append(row['pid'])
    require(len(pids)==len(set(pids)), 'reused C2 child identity')
    return {r['name']:r for r in rows}


class Auditor:
    """Trust only a source-bound external receipt and every actual archived stage."""
    def __init__(self, spec, inputs):
        self.external = inputs.json(spec['external_receipt'])
        outer = self.external
        require(outer.get('schema')=='independent-c2-audit-launch-v1'
                and outer.get('status')=='completed' and outer.get('process_started') is True
                and outer.get('returncode')==0 and outer.get('whole_hard_wall_seconds')==AUDIT_WHOLE,
                'independent audit external process did not complete under fixed cap')
        require(outer.get('archive_finalized') is True and outer.get('CRC_members_manifest_verified') is True
                and outer.get('CPU_is_lower_bound') is False
                and not outer.get('unaccounted_orphan_stage_CPU_possible'), 'audit terminal/CPU unknown')
        bounded(outer['whole_wall_seconds'], AUDIT_WHOLE, 'audit launch prefix wall')
        nonnegative(outer['waited_controller_and_descendant_CPU_seconds'], 'audit waited CPU')
        for key in ('sampled_controller_peak_rss_bytes','exact_waited_peak_rss_bytes','waited_peak_rss_bytes'):
            require(type(outer.get(key)) is int, 'missing audit outer RSS')
            bounded(outer[key], AUDITOR_RSS, key)
        require(outer['archive']==spec['archive']['identity'], 'external/archive identity differs')
        self.native=verify_native(spec['native_complete_envelope'],inputs,outer)
        self.archive = VerifiedArchive(spec['archive']['path'], inputs, spec['archive']['identity'])
        require(outer['members']==len(self.archive.members)
                and outer['summary']==self.archive.members['SUMMARY.json'], 'external archive coverage differs')
        self.summary = self.archive.json('SUMMARY.json')
        summary = self.summary
        require(summary.get('schema')=='independent-c2-terminal-audit-v1'
                and summary.get('execution_status')=='completed_fixed_audit_roster'
                and summary.get('program_manifest_before')==summary.get('program_manifest_after')==AUDITOR_SHA
                and not summary.get('final_program_error'), 'independent audit source/summary gate failed')
        require(summary.get('confirmation_E_access') is False and summary.get('training_steps')==0
                and summary.get('optimizer_construct_restore_step_calls')==0, 'auditor scope differs')
        bounded(summary['complete_process_wall_seconds'], AUDIT_WHOLE, 'audit controller prefix wall')
        bounded(summary['own_peak_rss_bytes'], AUDITOR_RSS, 'audit controller peak RSS')
        entries = summary['entries']
        require(len(entries)==6 and {r['name'] for r in entries}==set(roster('hcsn')), 'audit entry roster differs')
        for r in entries:
            require(r['name']==f"hcsn-s{r['seed']}-lr{r['learning_rate']:g}", 'audit candidate label differs')
        self.entries = {r['name']:r for r in entries}
        stages = summary['stages']
        expected = {'context'} | {s+'-'+n for s in ('chain','replay') for n in roster('hcsn')}
        require(len(stages)==13 and {r['label'] for r in stages}==expected, 'audit stage roster differs')
        self.stages = {r['label']:r for r in stages}
        self.context, _ = self.stage('context')
        require(self.context.get('schema')=='independent-c2-context-v1'
                and self.context.get('status')=='passed_terminal_context' and self.context.get('no_E') is True,
                'unadmitted terminal context')
        require(set(self.context['attempts'])==set(roster('hcsn'))
                and set(self.context['parents'])==set(roster('hcsn')), 'context opportunity lost')
        require(set(self.native['original_C2_pids'])=={r['pid'] for r in self.context['attempts'].values()}
                | {self.native['original_C2_controller_pid']}, 'native seven-PID/context binding differs')
        self.external_clock_scope = 'Original 1800s launch prefix, not complete native supervisor exit; separately authorized native envelope remains required.'

    def stage(self, label):
        row = self.stages[label]
        stage, name = ('context',None) if label=='context' else label.split('-',1)
        require(row.get('stage')==stage and row.get('name')==name and row.get('admitted') is True,
                'audit stage is unrun or unadmitted: '+label)
        grant, outer = row['planned_grant_seconds'], row['outer']
        require(nonnegative(grant, 'stage grant')>0 and grant <= (360 if stage in ('context','chain') else 210),
                'audit stage grant outside fixed limit')
        require(outer.get('status')=='completed' and outer.get('process_started') is True
                and outer.get('returncode')==0 and outer.get('CPU_cost_complete') is True
                and not outer.get('child_terminal_unknown'), 'stage process/CPU incomplete')
        require(outer.get('wall_limit_seconds')==grant and outer.get('RSS_limit_bytes')==AUDITOR_RSS,
                'stage declared limits differ')
        bounded(outer['whole_child_wall_seconds'], grant, 'stage actual whole wall')
        nonnegative(outer['waited_child_CPU_seconds'], 'stage exact waited CPU')
        for key in ('sampled_peak_rss_bytes','wait4_peak_rss_bytes'):
            require(type(outer.get(key)) is int, 'stage outer RSS missing')
            bounded(outer[key], AUDITOR_RSS, key)
        prefix = 'stages/'+label
        require(self.archive.json(prefix+'-process/OUTER.json')==outer, 'stage outer raw bytes/object differs')
        require(self.archive.json(prefix+'-admission.json')==row, 'stage admission summary differs')
        require(self.archive.members[prefix+'/STAGE.json']==row['artifact'], 'stage artifact identity differs')
        artifact = self.archive.json(prefix+'/STAGE.json')
        require(artifact==row['result'] and artifact.get('schema')=='independent-c2-audit-stage-v1'
                and artifact.get('stage')==stage and artifact.get('name')==name
                and artifact.get('inputs_unchanged') is True, 'stage result scope/identity differs')
        require(artifact.get('program_before')==artifact.get('program_after')==AUDITOR_SHA,
                'stage source changed')
        require(artifact.get('declared_wall_seconds')==grant and artifact.get('declared_RSS_bytes')==AUDITOR_RSS,
                'stage artifact limits differ')
        bounded(artifact['process_wall_seconds'], grant, 'stage recorded process wall')
        bounded(artifact['self_peak_rss_bytes'], AUDITOR_RSS, 'stage recorded peak RSS')
        allowed = ('passed','failed_recording_chain') if stage=='chain' else ('passed',)
        require(artifact.get('status') in allowed, 'stage evidence failed')
        member = prefix+'/'+{'context':'CONTEXT','chain':'CHAIN','replay':'REPLAY'}[stage]+'.json'
        require(artifact['artifact']==self.archive.members[member], 'stage output identity differs')
        return self.archive.json(member), artifact

    def candidate(self, name):
        entry = self.entries[name]
        chain, stage = self.stage('chain-'+name)
        replay, _ = self.stage('replay-'+name)
        prefix = 'stages/chain-'+name+'/'
        require(stage['BEST_BINDING']==self.archive.members[prefix+'BEST-BINDING.json'], 'best binding SHA differs')
        best = self.archive.json(prefix+'BEST-BINDING.json')
        require(entry.get('quality_reproducibility')=='passed'
                and entry['chain_result']==self.archive.members[prefix+'CHAIN.json']
                and entry['replay_result']==self.archive.members['stages/replay-'+name+'/REPLAY.json'],
                'entry/replay/chain differs')
        require(chain.get('schema')=='independent-c2-chain-v1' and chain.get('name')==name
                and chain.get('inputs_unchanged') is True and chain.get('quality_checkpoint_bound') is True
                and chain.get('status') in ('PASSED_BOUND_EVIDENCE_ONLY','FAILED_OR_INCOMPLETE_CHAIN'),
                'checkpoint chain not bound')
        require(replay.get('schema')=='independent-c2-best-D-v1' and replay.get('name')==name
                and replay.get('status')==replay.get('quality_reproducibility')=='passed'
                and replay.get('inputs_unchanged') is True and replay.get('confirmation_E_access') is False
                and replay.get('optimizer_construct_restore_step_calls')==replay.get('backward_calls')==0,
                'fresh replay scope failed')
        require(best['best']==chain['best'] and best['report_identity']==chain['report_identity']
                and replay['best_checkpoint']==chain['best']['identity']
                and replay['best_epoch']==chain['best']['epoch']==entry['best_epoch'],
                'fresh replay is not the independently bound best')
        require(entry['fresh_development']==replay['fresh_development']
                and entry['independent_adequacy_supported']==chain['independent_adequacy_supported'],
                'summary quality/adequacy differs')
        require(replay['tensor_digest_before']==replay['tensor_digest_after'], 'replay tensors changed')
        return chain, replay

