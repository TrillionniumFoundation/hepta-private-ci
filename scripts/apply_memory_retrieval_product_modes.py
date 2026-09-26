#!/usr/bin/env python3
"""Apply one reviewed native product-mode patch to exact source objects.

The caller must compile/test the generated commit. This script never promotes
production status, weakens owner revalidation, or fabricates independent review.
"""
from pathlib import Path
import hashlib

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'codex-rs/hepta-agentd/src'
EXPECTED = {
    'config.rs': 'afb9cac35db1c57d58edb3b31c6beee31bab2560',
    'runtime.rs': 'b3d9131f5b07c7f3d1f61c82657512985e7033ad',
    'cognitive_retrieval_context.rs': 'a6995df0f244b71aee16948d02a47d60de70c20a',
    'cognitive_context.rs': '361a0d86354714b400cb278713a1728ddeec4370',
}

def once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f'non-unique reviewed anchor: {old[:100]!r}')
    return text.replace(old, new)

def rust_block_end(text, start):
    # Used only for the reviewed simple mode gate, which has no brace strings.
    opening = text.index('{', start)
    depth = 1
    for index in range(opening + 1, len(text)):
        depth += (text[index] == '{') - (text[index] == '}')
        if depth == 0:
            return index + 1
    raise RuntimeError('unclosed reviewed gate')

def main():
    values = {}
    for name, expected in EXPECTED.items():
        data = (SRC / name).read_bytes()
        actual = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if actual != expected:
            raise RuntimeError(f'exact-source conflict: {name} {actual}')
        values[name] = data.decode()

    s = values['config.rs']
    s = once(s, '    Compatibility,\n    HnmfRequired,',
        '    Compatibility,\n    HnmfShadow,\n    HnmfCanary,\n    HnmfRequired,')
    s = once(s, 'matches!(self, Self::HnmfRequired)',
        'matches!(self, Self::HnmfShadow | Self::HnmfCanary | Self::HnmfRequired)')
    s = once(s, '        "hnmf-required" => Ok(CognitiveRetrievalMode::HnmfRequired),',
        '        "hnmf-shadow" => Ok(CognitiveRetrievalMode::HnmfShadow),\n'
        '        "hnmf-canary" => Ok(CognitiveRetrievalMode::HnmfCanary),\n'
        '        "hnmf-required" => Ok(CognitiveRetrievalMode::HnmfRequired),')
    s = once(s, 'must be compatibility or hnmf-required',
        'must be compatibility, hnmf-shadow, hnmf-canary or hnmf-required')
    values['config.rs'] = s

    s = values['cognitive_retrieval_context.rs']
    s = once(s, 'pub trait CurrentMemoryRetrievalContext: Send + Sync {',
        'pub trait CurrentMemoryRetrievalContext: Send + Sync {\n'
        '    /// Trusted composition selects delivery; a request cannot select its arm.\n'
        '    fn delivers_hnmf(&self, _owner: &AgentId) -> bool { true }\n')
    values['cognitive_retrieval_context.rs'] = s

    s = values['runtime.rs']
    anchor = '    require_cognitive_retrieval_context_for_mode(retrieval_mode, retrieval_context.is_some())?;'
    s = once(s, anchor, anchor + '\n'
        '    let retrieval_context = retrieval_context.map(|reader| {\n'
        '        crate::retrieval_product_mode::route(retrieval_mode, reader)\n'
        '    });')
    start = s.index('fn require_cognitive_retrieval_context_for_mode(')
    end = rust_block_end(s, start)
    s = s[:start] + '''fn require_cognitive_retrieval_context_for_mode(
    mode: CognitiveRetrievalMode,
    configured: bool,
) -> Result<(), AgentdError> {
    if mode.requires_current_context() == configured {
        return Ok(());
    }
    let message = if mode.requires_current_context() {
        "HNMF-required retrieval profile (including shadow/canary composition) requires a current authenticated retrieval context"
    } else {
        "compatibility retrieval profile cannot attach an HNMF context"
    };
    Err(AgentdError::Invalid(message.to_string()))
}''' + s[end:]
    values['runtime.rs'] = s

    s = values['cognitive_context.rs']
    s = once(s, '''    let retrieval_context = match current_retrieval {
        Some(current) => Some(load_retrieval_context(current, owner, body_generation).await?),
        None => None,
    };''', '''    let delivers_hnmf = current_retrieval.is_some_and(|current| current.delivers_hnmf(owner));
    let retrieval_context = match current_retrieval {
        Some(current) => match load_retrieval_context(current, owner, body_generation).await {
            Ok(context) => Some(context),
            Err(error) if delivers_hnmf => return Err(error),
            Err(_) => None, // An unavailable shadow cannot poison compatibility delivery.
        },
        None => None,
    };''')
    s = once(s, '        .map(AcquiredRetrievalContext::binding_digest);',
        '        .filter(|_| delivers_hnmf)\n        .map(AcquiredRetrievalContext::binding_digest);')
    s = once(s, 'if learning_sink.is_some() && retrieval_context.is_none()',
        'if learning_sink.is_some() && current_retrieval.is_none()')
    start = s.index('    if let Some(context) = &retrieval_context {')
    end = s.index('    let mut response = CognitiveContextSnapshot {', start)
    old = s[start:end]
    execution_end = old.index('        let selection_order = execution')
    execution = old[:execution_end]
    execution = once(execution, '    if let Some(context) = &retrieval_context {',
        '    let execution = match &retrieval_context {\n'
        '        Some(context) => (|| -> Result<_, CognitiveContextError> {')
    execution = once(execution, '        let execution = execute_owner_observation(',
        '        let execution = execute_owner_observation(')
    execution += '''            Ok(execution)
        })(),
        None => Err(CognitiveContextError::RetrievalContextUnavailable),
    };
    match execution {
        Ok(execution) => {
'''
    middle_start = old.index('        let selection_order = execution')
    middle_end = old.index('    } else {\n        observed.sort_by(', middle_start)
    middle = old[middle_start:middle_end]
    middle = once(middle, '        observed.retain(|candidate| {',
        '        if delivers_hnmf {\n        observed.retain(|candidate| {')
    tail = old[middle_end:]
    tail = once(tail, '    } else {\n        observed.sort_by(',
        '        }\n        }\n'
        '        Err(error) if delivers_hnmf => return Err(error),\n'
        '        Err(_) => {}\n'
        '    }\n'
        '    if !delivers_hnmf {\n        observed.sort_by(')
    s = s[:start] + execution + middle + tail + s[end:]
    s = once(s, '    if let Some(sink) = learning_sink {',
        '    if let Some(sink) = learning_sink.filter(|_| pending_assignment.is_some()) {')
    s = once(s, '        let delivered_candidates = response\n            .items\n            .iter()',
        '        let delivered_candidates = response\n            .items\n            .iter()\n'
        '            .filter(|_| delivers_hnmf)')
    anchor = '        let context_exposed = !delivered_candidates.is_empty();'
    s = once(s, anchor, '''        // A shadow assignment is evidence only. Neither compatibility records
        // nor a compatibility ranker may be labeled as HNMF treatment/exposure.
        if !delivers_hnmf {
            downstream_policy_digest = None;
            delivery_propensity = ProbabilityQ32::ONE;
        }
''' + anchor)
    s = once(s, '        tokio::task::spawn_blocking(move || {\n            sink.append_with_delivery_policy(',
        '        let appended = tokio::task::spawn_blocking(move || {\n            sink.append_with_delivery_policy(')
    old = '''        .await
        .map_err(|_| CognitiveContextError::RetrievalLearningUnavailable)?
        .map_err(|_| CognitiveContextError::RetrievalLearningUnavailable)?;'''
    new = '''        .await
        .map_err(|_| CognitiveContextError::RetrievalLearningUnavailable)
        .and_then(|result| result.map_err(|_| CognitiveContextError::RetrievalLearningUnavailable));
        if delivers_hnmf {
            appended?;
        } else if appended.is_err() {
            tracing::warn!("shadow retrieval assignment append unavailable; no exposure recorded");
        }'''
    s = once(s, old, new)
    s = once(s, '    let retrieval_context_digest = match current_retrieval {',
        '    let retrieval_context_digest = match current_retrieval.filter(|reader| reader.delivers_hnmf(owner)) {')
    values['cognitive_context.rs'] = s

    lib = (SRC / 'lib.rs').read_text()
    values['lib.rs'] = once(lib, 'mod cognitive_retrieval_context;',
        'mod cognitive_retrieval_context;\nmod retrieval_product_mode;')
    tests = (SRC / 'cognitive_context_hnmf_tests.rs').read_text()
    if 'cognitive_context_mode_tests.rs' in tests:
        raise RuntimeError('mode tests already wired')
    values['cognitive_context_hnmf_tests.rs'] = tests + '\n#[path = "cognitive_context_mode_tests.rs"]\nmod mode_tests;\n'
    for name, text in values.items():
        (SRC / name).write_text(text)
    print('Applied exact product-mode source patch:', ', '.join(sorted(values)))

if __name__ == '__main__':
    main()
