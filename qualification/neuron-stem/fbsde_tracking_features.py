"""Bounded local-participant feature reuse; NOT a quotient of global event order.

Only the explicit tracking grammar's ordinal marker is normalized. Original event
text, ordering, source checks and final answers remain with the existing executor.
A cache is bound to one frozen pipeline/scope/generation, never a global service.
"""
import re
import time
from four_gate_common import digest, require

LEGACY = 'ordinal_sensitive_v1'
LOCAL = 'local_participant_v2'
PROFILES = (LEGACY, LOCAL)
_PATTERN = re.compile(r'(First|Then|Next|After that|Finally), '
                      r'(SELF|OTHER) and (SELF|OTHER) '
                      r'(swap books|switch partners|swap balls|swap their gifts|trade positions)\.')


def canonical(text, profile):
    require(profile in PROFILES and type(text) is str and 0 < len(text) <= 512,
            'bounded versioned participant text')
    if profile == LEGACY:
        return text
    match = _PATTERN.fullmatch(text)
    require(match is not None, 'unsupported local-participant grammar')
    return 'Then, ' + text.split(', ', 1)[1]


class ParticipantFeatures:
    """Study-process cache of immutable features, not permission or model authority."""
    def __init__(self, torch, encode_many, width, binding, profile=LEGACY):
        require(type(width) is int and 1 <= width <= 4096 and profile in PROFILES, 'feature dimensions/profile')
        require(set(binding) == {'encoder', 'scope', 'generation'} and
                all(type(binding[k]) is str and 0 < len(binding[k]) <= 256 for k in ('encoder', 'scope')) and
                type(binding['generation']) is int and binding['generation'] > 0, 'complete feature binding')
        self.torch, self.encode_many, self.width, self.profile = torch, encode_many, width, profile
        self.binding = digest({'pipeline': binding, 'profile': profile})
        self.entries, self.records, self.batches = {}, [], []

    def get(self, texts, binding):
        from four_gate_capture import tensor_digest
        require(binding == self.binding, 'stale/cross-scope feature binding')
        require(type(texts) is list and 1 <= len(texts) <= 7, 'bounded current-proposal inventory')
        before = len(self.batches)
        keys = [canonical(t, self.profile) for t in texts]
        missing = list(dict.fromkeys(k for k in keys if k not in self.entries))
        require(len(self.entries) + len(missing) <= 512, 'feature capacity exhausted')
        groups = [[k] for k in missing] if self.profile == LEGACY else ([missing] if missing else [])
        new = {}
        for group in groups:
            cpu, wall = time.process_time_ns(), time.perf_counter_ns()
            row = {'index': len(self.batches), 'binding': self.binding, 'texts': group,
                   'status': 'started', 'vectors_sha256': None}
            self.batches.append(row)
            try:
                values = self.encode_many(group)
                require(tuple(values.shape) == (len(group), self.width) and
                        self.torch.isfinite(values).all().item(), 'finite batch feature contract')
                row['vectors_sha256'] = tensor_digest(values)
                for slot, key in enumerate(group):
                    new[key] = (values[slot].detach().clone(), row['index'], slot)
                row['status'] = 'encoded'
            except Exception as error:
                row.update(status='failed', error_type=type(error).__name__)
                raise
            finally:
                row['cpu_ns'] = time.process_time_ns()-cpu
                row['wall_ns'] = time.perf_counter_ns()-wall
        # No partially validated batch enters the cache. Returned copies prevent caller mutation.
        self.entries.update(new)
        for key, (value, index, slot) in new.items():
            self.records.append({'text': key, 'vector_sha256': tensor_digest(value),
                                 'batch_index': index, 'batch_slot': slot})
        output = self.torch.stack([self.entries[k][0] for k in keys])
        receipt = {'binding': self.binding, 'source_texts_sha256': digest(texts),
                   'canonical_texts_sha256': digest(keys), 'keys': keys,
                   'unique_misses': len(missing), 'requested_rows': len(keys),
                   'before_batches': before, 'after_batches': len(self.batches),
                   'slots': [[self.entries[k][1], self.entries[k][2]] for k in keys]}
        return output, receipt


def audit_features(plan, batches, proposals):
    """Recompute deduplication and actual slot reuse without importing Torch or an Encoder."""
    binding = plan['feature_binding']; profile = plan['feature_profile']; seen = {}
    for i, row in enumerate(batches):
        require(row['index'] == i and row['binding'] == binding and row['status'] == 'encoded',
                'complete source-bound encoding batch')
        keys = row['texts']
        require(1 <= len(keys) <= (1 if profile == LEGACY else 7) and len(keys) == len(set(keys)), 'batch inventory')
        for j, key in enumerate(keys):
            require(canonical(key, profile) == key and key not in seen, 'duplicate/noncanonical physical encoding')
            seen[key] = [i, j]
    misses = 0; previous_end = None
    for row in proposals:
        r = row['features']; originals = row['source_slot_texts']
        keys = [canonical(t, profile) for t in originals]
        require(r['binding'] == binding and r['source_texts_sha256'] == digest(originals) and
                r['keys'] == keys and r['canonical_texts_sha256'] == digest(keys), 'proposal feature drift')
        before, after = r['before_batches'], r['after_batches']
        require(type(before) is int and type(after) is int and 0 <= before <= after <= len(batches)
                and (previous_end is None or before == previous_end), 'encoding chronology')
        previous_end = after
        needed = list(dict.fromkeys(k for k in keys if seen[k][0] >= before))
        actual = [key for b in batches[before:after] for key in b['texts']]
        require(needed == actual and r['unique_misses'] == len(needed), 'unrequested or hidden encoding')
        require(all(seen[k][0] < after for k in keys), 'future feature used')
        require(r['slots'] == [seen[k] for k in keys] and r['requested_rows'] == len(keys), 'forward slot drift')
        require(0 <= r['unique_misses'] <= len(set(keys)), 'invalid observed misses')
        require(row['returned'] == (row['cpu_ns'] <= 100_000_000), 'original proposal budget mismatch')
        misses += r['unique_misses']
    return {'proposal_count': len(proposals), 'proposal_unique_misses': misses,
            'physical_forward_calls': len(batches), 'physical_encoded_rows': len(seen),
            'source_bound_slots_valid': True, 'production_promotion_permitted': False}
