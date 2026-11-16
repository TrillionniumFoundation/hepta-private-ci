from pathlib import Path
import copy
import json
import re
import tomllib

ROOT = Path('/workspace/scratch/ce434f960ee9/learn-evaluator-budget-v2')
AGENT = 'codex-rs/hepta-agentd/src/'
OWNER = AGENT + 'neuron_cell_evaluation_receipt_owner.rs'
OP = AGENT + 'neuron_cell_evaluation_training_operation.rs'
RECEIPT = AGENT + 'neuron_cell_evaluation_receipt_operation.rs'
HOST = AGENT + 'neuron_cell_evaluation_host.rs'
PANEL = AGENT + 'neuron_cell_evaluation_panel.rs'
MEMBER = AGENT + 'neuron_cell_evaluation_panel_member.rs'
SOURCE = AGENT + 'neuron_cell_evaluation_qualification_sources.rs'
QUAL = AGENT + 'neuron_cell_evaluation_qualification_owner.rs'
READ = AGENT + 'neuron_cell_evaluation_qualification_readback.rs'
EXPORT = AGENT + 'neuron_cell_evaluation_model_material_export.rs'
FACTORY = AGENT + 'neuron_cell_evaluation_host_training_readback.rs'
CONNECTION = AGENT + 'neuron_cell_evaluation_model_material_connection.rs'
MODEL_READ = AGENT + 'neuron_cell_evaluation_model_read_operation.rs'

def order(function, sequence, top=()):
    if len(sequence) < 2:
        sequence = [function, *sequence]
    return {'function': function, 'sequence': sequence, 'top_level': list(top)}

def replace_value(value, changes):
    if isinstance(value, str):
        for before, after in changes.items():
            value = value.replace(before, after)
        return value
    if isinstance(value, list):
        return [replace_value(x, changes) for x in value]
    if isinstance(value, dict):
        return {k: replace_value(v, changes) for k, v in value.items()}
    return value

changes = {
    'source.prepare(&self.config, started_at).await?': '.prepare(&self.config, started_at, TrainingRead::Independent)',
    'self.finish_readback(source, &prepared, bytes, started_at, false)\n                .await': 'self.finish_readback(',
    'self.read_trainer(config).await?': 'self.read_training(config, training).await?',
    'source.read_trainer(&self.config).await?': 'source.read_training(&self.config, training).await?',
    'self.read_current_with_clock(original::now).await': 'self.read_current_with_clock(original::now, TrainingRead::Independent)',
    'self.read_original_panel(&mut clock).await': 'self.read_original_panel(&mut clock, training).await',
    'self.read_members(clock).await?': 'self.read_members(clock, training).await?',
    'OriginalCellEvaluationPanelMemberOwnersV1::read_original(owner, task, clock)\n                    .await?': 'OriginalCellEvaluationPanelMemberOwnersV1::read_original(owner, task, clock, training)',
    '.prepare(&self.qualification.config, started_at)': '.prepare(&self.qualification.config, started_at, training)',
}

path = ROOT/'CALLERS.toml'
text = path.read_text()
blocks = re.split(r'(?=^\[\[(?:boundary|protected_file)\]\]\s*$)', text, flags=re.M)
new_rows = []
boundary_updates = {
    'learning_original_evaluation_receipt_attest': [],
    'learning_original_evaluation_receipt_readback': [],
    'learning_original_evaluation_panel_current': [],
    'learning_original_evaluation_host_profile': [HOST, FACTORY],
    'learning_original_evaluation_host_constructor': [OWNER, FACTORY],
}

def toml(value):
    if isinstance(value,str): return json.dumps(value, ensure_ascii=False)
    if isinstance(value,bool): return str(value).lower()
    if isinstance(value,list): return '['+', '.join(toml(v) for v in value)+']'
    if isinstance(value,dict): return '{ '+', '.join(k+' = '+toml(v) for k,v in value.items())+' }'
    return str(value)

def render(kind,row):
    return '[['+kind+']]\n'+'\n'.join(k+' = '+toml(v) for k,v in row.items())+'\n\n'

for i, block in enumerate(blocks):
    if not block.startswith('[['): continue
    kind=block.split(']]',1)[0][2:]
    # All boundary/protected records are isolated by the next array header.
    parsed=tomllib.loads(block)
    row=parsed[kind][0]
    old=copy.deepcopy(row)
    if kind=='boundary':
        if row['definition_path'] in (PANEL,MEMBER,SOURCE,QUAL,READ):
            row=replace_value(row,changes)
        if row['id'] in boundary_updates: row['product_callers']=boundary_updates[row['id']]
        if row['id']=='learning_evidence_original_owner_readback':
            row['product_callers']=[OP if p==OWNER else p for p in row['product_callers']]
    elif row['path'] in (PANEL,MEMBER,SOURCE,QUAL,READ):
        row=replace_value(row,changes)
        if row['path']==SOURCE:
            row['required_function_order'].append(order('fn read_training(',[
                'match training', 'TrainingRead::Independent => self.read_trainer(config).await',
                'TrainingRead::Operation(original)',
                'TrainingOperation::require_qualification(original, self.trainer, config)',
            ]))
        if row['path']==MEMBER:
            f=next(f for f in row['required_function_order'] if f['function']=='fn read_original(')
            f['sequence'][1:1]=['if let TrainingRead::Operation(original) = training',
                'TrainingOperation::require_member(original, &self.trainer, &self.qualification.config)?']
    elif row['path']==OWNER and 'required_function_order' in row:
        if 'pub struct OriginalCellEvaluationReceiptOwnerV1' in row.get('required',[]):
            row['required']=[s.replace('!= bytes','!= expected') for s in row['required']]
            old_orders=row.pop('required_order')
            moved=[old_orders[0],old_orders[1],old_orders[4]]
            moved=replace_value(moved,{
                'fn attest_original_completion<':'fn attest_with_training<',
                'pub async fn readback<':'pub(crate) async fn readback_with_training<',
                'fn readback<':'fn readback_with_training<',
                'readback(source.snapshot, self.training()?)':'.receipt_evidence(source.trainer, source.snapshot, &self.config)',
                '&prepared.1, &training':'&prepared.1, &observed_training',
                'self.authenticate_completed(&mut source, prepared, &bytes)':'self.authenticate_completed(&mut source, prepared, &bytes, training)',
            })
            moved[1][-1]='async fn authenticate_completed<'
            moved[2].pop()
            new_rows.append({'path':RECEIPT,'required':['self.host_origin = HostOrigin::ReadbackOnly',
                'if self.journal.read(&self.saved)? != bytes'], 'forbidden':old['forbidden']+[
                'pub async fn', 'TrainingRead::Independent', 'TrainingOperation {'],
                'required_order':moved})
            row['required_order']=[old_orders[2],old_orders[3],old_orders[5]]
            row['required_order'][1][-1]='fn validate_config('
            row['required_order'].append(['fn attest_original_completion<',
                'self.attest_with_training(source, TrainingRead::Independent).await',
                'pub async fn readback<',
                'self.readback_with_training(source, TrainingRead::Independent).await',
                'fn original_host_profile('])
            row['forbidden'].append('if false')
        elif 'enum HostOrigin' in row.get('required',[]):
            row.pop('required_order')
    elif row['path']==HOST:
        functions={f['function']:f for f in row['required_function_order']}
        constructor=functions['fn from_original_receipt_owner(']
        constructor['sequence'].insert(-2,'shared_training: None')
        old_completion=functions['fn completion(']
        functions['fn completion(']=order('fn completion(',[
            'if self.fenced','return Err(Error::CommitUncertain)',
            'let result = self.complete_original_operation(context, action).await',
            'self.fence_result(result)',
        ],['if self.fenced','let result =','self.fence_result(result)'])
        row['required_order']=[['fn fence_result<T>',
            'if result.is_err()', 'LearningOriginalOwnerErrorV1::Pending',
            'ProductEvaluationExecutionStoreErrorV1::Missing','self.fenced = true','result',
            'fn begin_training_operation(']]
        functions['fn begin_training_operation(']=order('fn begin_training_operation(',[
            'match &self.shared_training','Some(trainer)',
            'TrainingOperation::begin(Arc::clone(trainer), context).await?',
            'None => Ok(None)',
        ])
        functions['fn complete_original_operation(']=order('fn complete_original_operation(',[
            'let started_at = self.current_time()?','context.authenticate(started_at)?',
            'let operation = self.begin_training_operation(context).await?',
            'Some(original) => TrainingRead::Operation(original)', 'None => TrainingRead::Independent',
            '.read_original_completion(context, action, training)',
            'if let Some(original) = operation','TrainingOperation::finish(original).await?',
            'self.finish_original_completion(context, action, completed, &after, started_at)',
        ],['let started_at =','context.authenticate(started_at)?','let operation =',
            'let (completed, after) =','if let Some(original) = operation','self.finish_original_completion('])
        original=functions['fn read_original_completion(']
        seq=original['sequence']
        split=seq.index('OriginalCellEvaluationReceiptOwnerV1::require_original_host_completed(')
        original['sequence']=replace_value(seq[:split],{
            'self.read_panel().await?':'self.read_panel(training).await?',
            '::attest_original_completion(':'::attest_with_training(',
            '::readback(':'::readback_with_training(',
        })+['let current = self.current_time()?','require_clock(started_at, current)?',
            'contract::authenticate_receipt(context, completed.0, completed.1, current)?','Ok((completed, after))']
        original['top_level']=['let started_at =','context.authenticate(started_at)?','let before =',
            'let completed = {','let after =','if before != after','Ok((completed, after))']
        tail=replace_value(seq[split:],{
            '&completed.0,\n            &completed.1':'completed.receipt(),\n            completed.attestation()',
            'self.authenticate_panel(&after, current)?':'self.authenticate_panel(after, current)?',
            'contract::authenticate_receipt(context, completed.0, completed.1, current)?':'contract::authenticate_receipt(',
        })
        functions['fn finish_original_completion(']=order('fn finish_original_completion(',tail,[
            'OriginalCellEvaluationReceiptOwnerV1::require_original_host_completed(',
            'let current =','require_clock(started_at, current)?','self.authenticate_panel(after, current)?',
            'let original = contract::authenticate_receipt(', 'self.retained = Some(original.clone())','Ok(original)',
        ])
        functions['fn read_panel(']=order('fn read_panel(',['training: TrainingRead',
            'OriginalCellEvaluationPanelOwnerV1::read_current_with_clock(', '&mut self.panel',
            'super::original::now', 'training,','.map_err(Error::from)',
        ])
        row['required_function_order']=list(functions.values())
        row['required'].append('shared_training: Option<Arc<crate::LearningIterationEvidenceClientV1>>')
    if row!=old:
        blocks[i]=render(kind,row)

new_boundaries=[
 ('learning_original_evaluation_operation_begin','TrainingOperation::begin',OP,[HOST]),
 ('learning_original_evaluation_operation_finish','TrainingOperation::finish',OP,[HOST,EXPORT]),
 ('learning_original_evaluation_operation_member','TrainingOperation::require_member',OP,[MEMBER]),
 ('learning_original_evaluation_operation_qualification','TrainingOperation::require_qualification',OP,[SOURCE]),
 ('learning_original_evaluation_operation_receipt','TrainingRead::receipt_evidence',OP,[RECEIPT]),
 ('learning_original_evaluation_receipt_operation_attest','OriginalCellEvaluationReceiptOwnerV1::attest_with_training',RECEIPT,[OWNER,HOST]),
 ('learning_original_evaluation_receipt_operation_read','OriginalCellEvaluationReceiptOwnerV1::readback_with_training',RECEIPT,[OWNER,HOST]),
 ('learning_original_evaluation_panel_operation_current','OriginalCellEvaluationPanelOwnerV1::read_current_with_clock',PANEL,[HOST]),
 ('learning_original_evaluation_shared_training_host','OriginalCellEvaluationReceiptOwnerV1::into_host_from_original_training_readback',FACTORY,[]),
 ('learning_original_evaluation_model_read_begin','OriginalCellEvaluationModelMaterialClientV1::begin_model_read',MODEL_READ,[]),
 ('learning_original_evaluation_model_read_finish','OriginalCellEvaluationModelReadV1::finish',MODEL_READ,[]),
 ('learning_original_evaluation_model_read_borrow','OriginalCellEvaluationModelReadV1::material',MODEL_READ,[]),
]

op_functions=[
 order('fn begin(',['trainer: Arc<LearningIterationEvidenceClientV1>', 'context: &Context',
    'let original = Self', 'context: context.clone()', 'original.read_original().await?', 'Ok(original)'],
    ['let original = Self','original.read_original().await?','Ok(original)']),
 order('fn finish(',['self','self.read_original().await'],['self.read_original().await']),
 order('fn read_original(',['.training','.receipts','.last()',
    'LearningIterationEvidenceClientV1::readback(', 'self.trainer.as_ref()', '&self.context.training',
    'if actual != self.context.training_evidence','return Err(Error::Binding(','Ok(())'],
    ['let receipt =','let actual =','if actual != self.context.training_evidence','Ok(())']),
 order('fn require_member(',['if !Arc::ptr_eq(&self.trainer, trainer)',
    'return Err(OriginalCellEvaluationQualificationErrorV1::Binding(',
    'TrainingOperation::require_qualification(self, trainer.as_ref(), config)'],
    ['if !Arc::ptr_eq(','TrainingOperation::require_qualification(']),
 order('fn require_qualification(',['if !std::ptr::eq(self.trainer.as_ref(), trainer)',
    'config.training != self.context.training','config.training_evidence != self.context.training_evidence',
    'config.scope != self.context.scope',
    'config.verifier.trust_digest() != self.context.verifier.trust_digest()',
    'config.verifier.scope_digest() != self.context.verifier.scope_digest()',
    'config.verifier.objective_digest() != self.context.verifier.objective_digest()',
    'return Err(OriginalCellEvaluationQualificationErrorV1::Binding(','Ok(())'],['if !std::ptr::eq(','Ok(())']),
 order('fn receipt_evidence(',['match self','Self::Independent =>',
    'LearningIterationEvidenceClientV1::readback(trainer, snapshot, receipt).await?',
    'Self::Operation(original)','if !std::ptr::eq(original.trainer.as_ref(), trainer)',
    'snapshot != &original.context.training','config.training != original.context.training',
    'config.scope != original.context.scope','config.signing.verifier.trust_digest()',
    'original.context.verifier.trust_digest()','config.signing.verifier.scope_digest()',
    'original.context.verifier.scope_digest()','config.signing.verifier.objective_digest()',
    'original.context.verifier.objective_digest()',
    'return Err(LearningOriginalOwnerErrorV1::Binding(',
    'Ok(original.context.training_evidence.clone())']),
]
new_rows.append({'path':OP,'required':['pub(crate) struct TrainingOperation',
    'trainer: Arc<LearningIterationEvidenceClientV1>', 'context: Context',
    'pub(crate) enum TrainingRead', 'Independent', "Operation(&'a TrainingOperation)"],
    'forbidden':['pub struct TrainingOperation','pub fn','pub async fn','impl Clone for TrainingOperation',
        'Deserialize','Serialize','SigningKey','File::open','UnixStream::connect','permit_all',
        'if false','FnOnce','FnMut','into_inner(', 'try_clone(', 'transmute'],
    'required_function_order':op_functions})
new_rows.append({'path':FACTORY,'required':[], 'forbidden':['SigningKey','File::open','UnixStream::connect',
    'LearningEvidenceVerifierV1::new','TrainingOperation {','permit_all','if false'],
    'required_function_order':[order('fn into_host_from_original_training_readback(',[
        'self,','LearningIterationCoordinatorV1::from_snapshot(dataset.snapshot().clone())',
        '.record(', 'training.receipt().clone()', 'OriginalCellEvaluationReceiptOwnerV1::original_host_profile(&self)',
        'panel.fenced || receipt.training != *actual.snapshot()',
        'for member in std::iter::once(&panel.primary).chain(&panel.retention)',
        'original.training != *actual.snapshot()', 'original.training_evidence != *training.attestation()',
        'original.scope != receipt.scope','original.verifier.trust_digest()',
        'original.verifier.scope_digest()', 'original.verifier.objective_digest()',
        'OriginalCellQ24TrainingReadbackConnectionV1::bind_original_training(',
        'panel.primary.trainer = Arc::clone(&trainer)', 'for member in &mut panel.retention',
        'member.trainer = Arc::clone(&trainer)',
        'OriginalCellEvaluationHostV1::from_original_receipt_owner(self, panel)?',
        '.shared_training = Some(trainer)', 'Ok(host)',
    ])]})
new_rows.append({'path':EXPORT,'required':['impl Owners','Body {','fn member('],
    'forbidden':['SigningKey','File::open','UnixStream::connect','permit_all','if false','TrainingOperation {'],
    'required_function_order':[
        order('fn original_model_material(',['if self.fenced','Err(Error::CommitUncertain)',
            'let result = self.read_original_model_material(context).await','self.fence_result(result)'],
            ['if self.fenced','let result =','self.fence_result(result)']),
        order('fn read_original_model_material(',['let started_at = self.current_time()?',
            'context.authenticate(started_at)?','self.begin_training_operation(context).await?',
            'Some(original) => TrainingRead::Operation(original)','None => TrainingRead::Independent',
            '.read_original_completion(context, super::super::wire::Action::Readback, training)',
            'members.push(member(', '&self.panel.primary', 'observed.primary()',
            'for ((owner, observed), binding)',
            'members.push(member(owner, observed, *binding, started_at)?)',
            'let body = Body', 'let bytes = body.encode()?',
            'let after = self.read_panel(training).await?', 'if after != observed',
            'return Err(Error::CommitUncertain)', 'if let Some(original) = operation',
            'TrainingOperation::finish(original).await?', 'self.finish_original_completion(',
            'let current = self.current_time()?', 'require_clock(started_at, current)?',
            'self.authenticate_panel(&after, current)?',
            'super::verify::material(context, &evaluation, &bytes, current)?','Ok(bytes)',
        ],['let started_at =','context.authenticate(started_at)?','let operation =',
            'let (evaluation, observed) =','let body =','let bytes =','let after =',
            'if after != observed','if let Some(original) = operation','let evaluation =',
            'let current =','super::verify::material(','Ok(bytes)']),
        order('fn member(',['let config = &owner.qualification.config',
            'CellEvaluationRunnerV1::original_model_commitments(', '&owner.runner',
            'observed.evaluation()', 'observed.qualification()',
            'OriginalCircuitEvaluationCohortReadbackV1::original_model_commitment(',
            '&owner.cohort', '&observed.cohort', 'let snapshots = [',
            '.candidate', '.snapshot()', '.fixed_expert', '.snapshot()',
            'let record = observed.qualification().comparison()',
            '.zip([&record.candidate, &record.fixed_expert])', '.zip(&observed.scopes)',
            '.digest()', 'arm.snapshot_digest', 'snapshot.manifest_digest',
            '.manifest', '.digest()', '&snapshot.scope != scope',
            'return Err(Error::Binding(', 'Ok(Member {',
            'record: serde_json::to_vec(observed.qualification().comparison())?',
            'snapshots: serde_json::to_vec(&snapshots)?',
            'holdout: projection.holdout().to_vec()', 'decision: projection.decision().to_vec()',
            'qualification: projection.qualification().to_vec()',
            'generator: learning_owner_evidence::encode(', 'evaluator: learning_owner_evidence::encode(',
            'execution: learning_owner_evidence::encode(',
            'OriginalProductEvaluationExecutionEvidenceV1::signing_payload(execution)',
            'execution.attestation()', 'OriginalProductEvaluationExecutionEvidenceV1::original_record(execution)',
            'freeze: learning_owner_evidence::encode(&freeze_payload, &freeze_evidence)?',
        ]),
    ]})

new_rows.append({'path':CONNECTION,
    'required':['channel: Mutex<Option<Channel>>','next: u64','retained: Mutex<Option<Digest32>>'],
    'forbidden':['SigningKey','UnixStream::connect','File::open','permit_all','if false',
        'impl Clone for OriginalCellEvaluationModelMaterialClientV1','pub channel:', 'pub(crate) channel:'],
    'required_function_order':[
        order('fn read_current(',['self.read_current_with_clock(now).await'],['self.read_current_with_clock(now).await']),
        order('fn read_current_with_clock(',['.channel','.try_lock()', '.take()',
            'let started_at = clock()?', 'require_clock(self.observed_at, started_at)?',
            'wire::context_binding(&self.context, started_at)? != self.binding',
            'let expected = self', 'wire::binding(&self.context, original, started_at)?',
            'let cancellation = Cancelled(', 'tokio::task::spawn_blocking(move ||',
            'transfer(&mut channel, binding, &cancelled)?', 'channel.peer.check_peer_lifetime()?',
            'Err(Error::Missing | Error::Pending) if expected.is_some()',
            'return Err(Error::CommitUncertain)', 'let current = clock()?',
            'require_clock(started_at, current)?',
            'self.authenticate_material(bytes, &expected, current)?',
            'self.retain_completed_material(channel, material, current)?',
            'drop(cancellation)', 'Ok(material)',
        ]),
        order('fn authenticate_material(',['super::codec::Body::decode(&bytes)?',
            'decode_original_owner_snapshot_v1(', '&body.snapshot',
            'crate::learning_owner_evidence::decode(&body.evaluation)?',
            'super::super::wire::authenticate_completed(&self.context, snapshot, signed, current)?',
            '.is_some_and(|original| original != &evaluation)', 'return Err(Error::Binding(',
            'verify::material(&self.context, &evaluation, &bytes, current)?',
            'let digest = Digest32::of_bytes(&bytes)', 'OriginalCellEvaluationModelMaterialV1 {',
            'observed_at: current', 'Ok(material)',
        ],['let body =','let snapshot =','let (_, signed) =','let evaluation =',
            'verify::material(','let digest =','Ok(material)']),
        order('fn retain_completed_material(',['material.authenticate_current(current)?',
            'let digest = material.binding()', 'self.retained.try_lock()',
            'retained.is_some_and(|old| old != digest)', 'return Err(Error::CommitUncertain)',
            '*retained = Some(digest)', '*self.expected.try_lock()',
            'Some(material.original_evaluation().clone())', '*self.channel.try_lock()',
            'Some(channel)', 'Ok(material)',
        ],['material.authenticate_current(current)?','let digest =','let mut retained =',
            'if retained.is_some_and(', '*retained =','*self.expected.try_lock()',
            '*self.channel.try_lock()', 'Ok(material)']),
        order('fn request(',['!(1..=128).contains(&channel.next)',
            'wire::Request::new(channel.next, binding, read)', 'bytes.len() > 16_384',
            'channel.peer.check_peer_lifetime()?', 'cancelled.load(Ordering::Acquire)',
            'let response = channel.peer.request(&bytes)?', 'response.len() > 16_384',
            'response.request != request','channel.next += 1','Ok(response.outcome)',
        ]),
        order('fn transfer(',['let transfer = channel.next',
            'let bytes = read_pages(channel, binding, cancelled)?',
            'finish_transfer(channel, binding, transfer, &bytes, cancelled)?','Ok(bytes)',
        ],['let transfer =','let bytes =','finish_transfer(','Ok(bytes)']),
        order('fn finish_transfer(',['let commitment = Digest32::of_bytes(bytes).to_string()',
            'match request(', 'channel,','binding,','wire::Read::Finish',
            'transfer,','digest: commitment.clone()', 'cancelled,',
            'wire::Outcome::Completed','original == transfer && total == bytes.len() && digest == commitment',
            '_ => Err(Error::CommitUncertain)',
        ]),
        order('fn read_pages(',['let transfer = channel.next',
            'request(channel, binding, wire::Read::Begin, cancelled)?',
            'for index in 0..MAX_PAGES','wire::Outcome::Page',
            'original != transfer', 'received as usize != index',
            'offset != result.len()', 'offset != index * PAGE_BYTES',
            'complete == 0','complete > MAX_BYTES',
            'total.is_some_and(|saved| saved != complete)',
            'digest.as_ref().is_some_and(|saved| saved != &commitment)',
            'bytes.len() > PAGE_BYTES.div_ceil(3) * 4',
            'STANDARD_NO_PAD','if offset >= complete','STANDARD_NO_PAD.encode(&decoded) != bytes',
            'decoded.len() != PAGE_BYTES.min(complete - offset)',
            'result.extend_from_slice(&decoded)', 'if result.len() == complete',
            'Digest32::of_bytes(&result).to_string() != commitment',
            'return Ok(result)', 'if index + 1 == MAX_PAGES',
            'wire::Read::Page', 'index: (index + 1) as u32',
            'Err(Error::CommitUncertain)',
        ]),
    ]})

new_rows.append({'path':MODEL_READ,'required':[
    "pub(crate) struct OriginalCellEvaluationModelReadV1<'a>",
    "client: &'a OriginalCellEvaluationModelMaterialClientV1", 'channel: Channel',
    'material: OriginalCellEvaluationModelMaterialV1','cancellation: Cancelled'],
    'forbidden':['pub struct','pub fn','pub async fn','Clone','Deserialize','Serialize',
        'SigningKey','UnixStream::connect','File::open','permit_all','if false',
        'state.retained','*self.expected','*self.channel','*self.retained'],
    'required_function_order':[
        order('fn begin_model_read(',['self.begin_model_read_with_clock(now).await'],
            ['self.begin_model_read_with_clock(now).await']),
        order('fn begin_model_read_with_clock(',['.channel','.try_lock()', '.take()',
            'let started_at = clock()?', 'require_clock(self.observed_at, started_at)?',
            'wire::context_binding(&self.context, started_at)? != self.binding',
            'let expected = self', 'wire::binding(&self.context, original, started_at)?',
            'let transfer = channel.next','let cancellation = Cancelled(',
            'tokio::task::spawn_blocking(move ||',
            'read_pages(&mut channel, binding, &cancelled)?', 'channel.peer.check_peer_lifetime()?',
            'Err(Error::Missing | Error::Pending) if expected.is_some()',
            'return Err(Error::CommitUncertain)', 'let current = clock()?',
            'require_clock(started_at, current)?',
            'self.authenticate_material(bytes, &expected, current)?',
            '.is_some_and(|original| original != material.binding())',
            'Ok(OriginalCellEvaluationModelReadV1 {', 'client: self','channel,','material,',
            'transfer,','started_at,','cancellation,',
        ],['let mut channel =','let started_at =','require_clock(self.observed_at, started_at)?',
            'let transfer =','let cancellation =','let result =','let current =',
            'require_clock(started_at, current)?','let material =','Ok(OriginalCellEvaluationModelReadV1 {']),
        order('fn material(',['&self','&OriginalCellEvaluationModelMaterialV1','&self.material']),
        order('fn finish(',['self','self.finish_with_clock(now).await'],['self.finish_with_clock(now).await']),
        order('fn finish_with_clock(',['self,','let Self {','mut channel','material,',
            'transfer,','started_at,','cancellation,','} = self',
            'Arc::clone(&cancellation.0)', 'client.binding', 'tokio::task::spawn_blocking(move ||',
            'finish_transfer(&mut channel, binding, transfer, &material.bytes, &cancelled)?',
            'channel.peer.check_peer_lifetime()?', 'let (channel, material) = result',
            'let current = clock()?', 'require_clock(started_at, current)?',
            'client.retain_completed_material(channel, material, current)?',
            'drop(cancellation)', 'Ok(material)',
        ],['let Self {','let cancelled =','let binding =','let result =','let current =',
            'require_clock(started_at, current)?','let material =','drop(cancellation)','Ok(material)']),
    ]})

for identifier,symbol,definition,callers in new_boundaries:
    receiver,method=symbol.rsplit('::',1)
    new_rows_for_boundary={'id':identifier,'symbol':symbol,'receiver_type':receiver,
        'definition_path':definition,'definition_markers':['fn '+method],
        'product_callers':callers,'caller_markers':[]}
    blocks.append(render('boundary',new_rows_for_boundary))
for row in new_rows: blocks.append(render('protected_file',row))

result=''.join(blocks).rstrip()+'\n'
marker='required_boundary_ids = ['
start=result.index(marker)+len(marker)
result=result[:start]+''.join(toml(x[0])+', ' for x in new_boundaries)+result[start:]
after=tomllib.loads(result)
assert len({b['id'] for b in after['boundary']})==len(after['boundary'])
path.write_text(result)
print({'boundaries':len(after['boundary']), 'protected_rows':len(after['protected_file']),
    'added_boundaries':[b[0] for b in new_boundaries], 'added_protected':len(new_rows)})
