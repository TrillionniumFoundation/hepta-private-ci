#!/usr/bin/env python3
"""One-shot exact-object migration; generated Rust is committed and tested.
No production, independent acceptance, calibration or SLO claim is issued.
"""
from pathlib import Path
import hashlib
import subprocess

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / 'codex-rs/hepta-memory-retrieval/src'
M = ROOT / 'codex-rs/hepta-memory/src'
EXPECTED = {
    R / 'generation_bound.rs': '2ec831c6369ef30b726e295650d50b76dda5fca7',
    R / 'generation_bound_v2.rs': '65f1a869b2ffd04bdd6bbcde95bcaa725dc04acf',
    R / 'generator.rs': 'dc5ccaee3ffa5fae36a62594627c293e9d7fbfec',
    M / 'cognitive_retrieval_observation.rs': '560783823aa390a1ee4767f05d6a2f0551cdd120',
    M / 'cognitive_retrieval_adapter.rs': '255461531b165634463de79f4aee92f1de6ffc08',
}

def replace(text, old, new, count=1):
    if text.count(old) != count:
        raise RuntimeError(f'anchor conflict: expected {count}: {old[:100]!r}')
    return text.replace(old, new)

def main():
    for path, expected in EXPECTED.items():
        data = path.read_bytes()
        actual = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if actual != expected:
            raise RuntimeError(f'exact source conflict: {path.relative_to(ROOT)} {actual}')
    values = {}
    paths = [ROOT / p for p in subprocess.check_output(
        ['git', 'ls-files', 'codex-rs'], cwd=ROOT, text=True).splitlines() if p.endswith('.rs')]
    for path in paths:
        if path.name in {'explicit_evidence_tests.rs', 'cognitive_retrieval_proposition_tests.rs'}:
            continue  # These new fixtures already use the explicit native fields.
        text = path.read_text()
        if 'contradiction_group_digest' not in text:
            continue
        if not (path.is_relative_to(R) or path == M / 'cognitive_retrieval_adapter.rs'):
            if 'contradiction_group_digest:' in text or 'contradiction_group_digests:' in text:
                raise RuntimeError(f'new native literal requires reviewed migration: {path}')
            continue
        lines = []
        for line in text.splitlines(keepends=True):
            stripped = line.strip()
            indent = line[:len(line) - len(line.lstrip())]
            if stripped.startswith('pub contradiction_group_digest:') or stripped.startswith('pub contradiction_group_digests:'):
                lines.append(indent + 'pub contradiction_evidence: Vec<crate::ContradictionEvidenceV1>,\n')
            elif stripped in {'contradiction_group_digests: BTreeSet<Digest32>,', 'contradiction_group_digest: Option<Digest32>,'}:
                lines.append(indent + 'contradiction_evidence: BTreeSet<crate::ContradictionEvidenceV1>,\n')
            elif stripped.startswith('contradiction_group_digest:') or stripped.startswith('contradiction_group_digests:'):
                if 'BTreeSet::new()' in stripped:
                    expr = 'BTreeSet::new()'
                elif path.name == 'generator.rs' and 'candidate.contradiction_group_digest' in stripped:
                    expr = 'candidate.contradiction_evidence.iter().copied().collect()'
                elif 'self.contradiction_group_digest' in stripped:
                    expr = 'self.contradiction_evidence.into_iter().collect()'
                elif 'entry.contradiction_group_digests' in stripped:
                    expr = 'entry.contradiction_evidence.clone()'
                else:
                    expr = 'Vec::new()'
                lines.append(indent + f'contradiction_evidence: {expr},\n')
            lines.append(line)
        values[path] = ''.join(lines)

    p = R / 'generation_bound.rs'
    text = values[p]
    for anchor, validation in [
        ('        ensure_digest("candidate_support", self.support_digest)?;', '        super::validate_contradiction_evidence(&self.contradiction_evidence)?;'),
        ('            observed_channels.extend(entry.channels.iter().copied());', '            super::validate_contradiction_evidence(&entry.contradiction_evidence)?;'),
        ('            ensure_digest("selection_record", selection.record_digest)?;', '            super::validate_contradiction_evidence(&selection.contradiction_evidence)?;'),
    ]:
        text = replace(text, anchor, validation + '\n' + anchor)
    text = replace(text, '        builder.support_digests.insert(candidate.support_digest);',
        '        builder.contradiction_evidence.extend(candidate.contradiction_evidence);\n'
        '        builder.support_digests.insert(candidate.support_digest);')
    text = text.replace('hepta.retrieval-candidate-union.v1', 'hepta.retrieval-candidate-union.v2')
    text = text.replace('hepta.recall-packet.v1', 'hepta.recall-packet.v2')
    for name in ('entry', 'selection'):
        anchor = f'            push_len(&mut bytes, {name}.contradiction_group_digests.len());'
        text = replace(text, anchor,
            f'            super::encode_contradiction_evidence(&mut bytes, &{name}.contradiction_evidence);\n' + anchor)
    values[p] = text

    p = R / 'generation_bound_v2.rs'
    text = values[p]
    start = text.index('impl RetrievalChannelCandidateV1 {')
    end = text.index('pub fn build_candidate_union(', start)
    text = text[:start] + '''impl RetrievalChannelCandidateV1 {
    #[must_use]
    pub fn contradiction_evidence(&self) -> &[ContradictionEvidenceV1] {
        &self.contradiction_evidence
    }
}

impl CandidateUnionEntryV1 {
    #[must_use]
    pub fn contradiction_evidence(&self) -> &[ContradictionEvidenceV1] {
        &self.contradiction_evidence
    }
}

pub(crate) fn validate_contradiction_evidence(
    evidence: &[ContradictionEvidenceV1],
) -> Result<(), RecallErrorV1> {
    if evidence.len() > 64 {
        return Err(RecallErrorV1::CandidateLimitExceeded);
    }
    if evidence.iter().any(|item| item.proposition_digest.is_zero())
        || evidence.windows(2).any(|pair| pair[0] >= pair[1])
    {
        return Err(RecallErrorV1::NonCanonicalCollection("explicit_contradiction_evidence"));
    }
    Ok(())
}

pub(crate) fn encode_contradiction_evidence(bytes: &mut Vec<u8>, evidence: &[ContradictionEvidenceV1]) {
    bytes.extend_from_slice(&(evidence.len() as u64).to_be_bytes());
    for item in evidence {
        bytes.extend_from_slice(item.proposition_digest.as_array());
        bytes.push(match item.polarity {
            ContradictionPolarityV1::Supports => 0,
            ContradictionPolarityV1::Opposes => 1,
        });
    }
}

''' + text[end:]
    header_end = text.index('\nuse std::collections::BTreeMap;')
    text = ('//! Policy-admitted native recall with explicit owner-issued statement stances.\n'
            '//! Union/packet commitments bind the actual proposition/polarity pairs.\n'
            '//! Legacy group digests are uninterpreted compatibility metadata.\n' + text[header_end:])
    text = replace(text, '.filter(|entry| entry.weighted_score >= policy.minimum_total_score)',
        '.filter(|entry| entry.weighted_score > FixedQ32::ZERO\n'
        '            && entry.weighted_score >= policy.minimum_total_score)')
    text += '\n#[cfg(test)]\n#[path = "explicit_evidence_tests.rs"]\nmod explicit_evidence_tests;\n'
    values[p] = text

    p = R / 'generator.rs'
    text = values[p]
    text = replace(text, '            ensure_digest("generator_candidate_support", candidate.support_digest)?;',
        '            crate::generation_bound::validate_contradiction_evidence(&candidate.contradiction_evidence)\n'
        '                .map_err(GeneratorErrorV1::Recall)?;\n'
        '            ensure_digest("generator_candidate_support", candidate.support_digest)?;')
    text = replace(text, '                value.support_digests.insert(candidate.support_digest);',
        '                value.contradiction_evidence.extend(candidate.contradiction_evidence.iter().copied());\n'
        '                value.support_digests.insert(candidate.support_digest);')
    text = replace(text, '        let mut bytes = b"hepta.retrieval-merged-support.v1".to_vec();',
        '        let mut bytes = b"hepta.retrieval-merged-support.v2".to_vec();\n'
        '        crate::generation_bound::encode_contradiction_evidence(\n'
        '            &mut bytes, &self.contradiction_evidence.iter().copied().collect::<Vec<_>>());')
    values[p] = text

    p = R / 'generation_bound_semantic_tests.rs'
    text = values[p]
    text = replace(text, '        contradiction_evidence: Vec::new(),',
        '        // Fixture stances are explicit; production never infers from channels.\n'
        '        contradiction_evidence: proposition.map(|proposition_digest| ContradictionEvidenceV1 {\n'
        '            proposition_digest,\n'
        '            polarity: if channel == RetrievalChannelV1::ContradictionSupport {\n'
        '                ContradictionPolarityV1::Opposes\n'
        '            } else { ContradictionPolarityV1::Supports },\n'
        '        }).into_iter().collect(),')
    values[p] = text

    p = M / 'cognitive_retrieval_adapter.rs'
    text = values[p]
    text = replace(text, '                contradiction_evidence: Vec::new(),',
        '                contradiction_evidence: observed.contradiction_evidence.clone(),')
    text = replace(text, '                contradiction_group_digest: (semantic_channel\n'
        '                    == RetrievalChannelV1::ContradictionSupport)\n'
        '                    .then(|| owner_contradiction_group_digest(owner_observation_digest)),',
        '                contradiction_group_digest: None,')
    text = replace(text, 'const OWNER_CONTRADICTION_DOMAIN: &[u8] = b"hepta.sqlite.retrieval-contradiction-group.v1";\n', '')
    start = text.index('fn owner_contradiction_group_digest(')
    end = text.index('\n#[cfg(test)]', start)
    values[p] = text[:start] + text[end:]

    p = M / 'cognitive_retrieval_observation.rs'
    text = p.read_text()
    text = replace(text, 'use super::*;\n', 'use super::*;\n\n#[path = "cognitive_retrieval_propositions.rs"]\nmod propositions;\n')
    text = replace(text, 'pub struct ObservedRetrievalCandidate {\n',
        'pub struct ObservedRetrievalCandidate {\n'
        '    #[serde(serialize_with = "propositions::serialize_evidence")]\n'
        '    pub contradiction_evidence: Vec<codex_hepta_memory_retrieval::ContradictionEvidenceV1>,\n')
    text = replace(text, '            .map(|candidate| ObservedRetrievalCandidate {\n',
        '            .map(|candidate| ObservedRetrievalCandidate {\n'
        '                contradiction_evidence: Vec::new(),\n')
    text = replace(text, '        observed.sort_by(|left, right| {',
        '        for candidate in &mut observed {\n'
        '            candidate.contradiction_evidence = propositions::read_evidence(\n'
        '                &mut transaction, self.owner_agent_id.as_str(), &candidate.revalidation,\n'
        '                request.now_unix_seconds,\n'
        '            ).await?;\n'
        '        }\n'
        '        observed.sort_by(|left, right| {')
    values[p] = replace(text, 'hepta:cognitive:retrieval-observation:v1', 'hepta:cognitive:retrieval-observation:v2')

    p = M / 'cognitive_retrieval_adapter_tests.rs'
    text = p.read_text()
    old = '        contradiction.candidates[0]\n            .contradiction_group_digest\n            .is_some()'
    text = replace(text, old, '        contradiction.candidates[0].contradiction_evidence.is_empty()\n'
        '            && contradiction.candidates[0].contradiction_group_digest.is_none()')
    values[p] = text + '\n#[path = "cognitive_retrieval_proposition_tests.rs"]\nmod proposition_tests;\n'
    for path, text in values.items():
        path.write_text(text)
    print('Migrated explicit evidence in', len(values), 'reviewed Rust files.')
    for path in sorted(values):
        print(path.relative_to(ROOT))

if __name__ == '__main__':
    main()
