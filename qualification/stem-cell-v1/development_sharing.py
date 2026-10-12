"""Paired real shared-Encoder entrypoints, using the existing approved backend.

No model download/fallback or alternate cache implementation. Supply an existing
SharedStemEngine with actual pinned weights for real-model evidence. The same
physical backend is used in every arm, not N copied Encoders. Backend construction
and model load happen outside this function and MUST be charged separately.
"""

import math
import time


def compare_shared_encoding(engine, requests, *, repeats=2, cache_bytes=8 * 1024 * 1024,
                            maximum_absolute_error=0.00002):
    from shared_encoder_batch import FeatureRequest, SharedStemEngine

    if (not isinstance(engine, SharedStemEngine) or type(requests) is not tuple
            or not 1 <= len(requests) <= 4096 or type(repeats) is not int or not 2 <= repeats <= 10
            or type(cache_bytes) is not int or not 0 <= cache_bytes <= 64 * 1024 * 1024
            or type(maximum_absolute_error) not in (float, int)
            or not math.isfinite(maximum_absolute_error) or not 0 <= maximum_absolute_error <= .00002):
        raise ValueError('invalid paired Encoder comparison')
    seen, scopes = set(), set()
    for request in requests:
        if type(request) is not FeatureRequest:
            raise ValueError('existing FeatureRequest required')
        request.validate()
        if request.request_id in seen:
            raise ValueError('duplicate Encoder comparison request')
        seen.add(request.request_id)
        scopes.add(request.cache_key()[:6] + (request.representation,))
    if len(scopes) != 1:
        raise ValueError('whole-study Scope/Generation/Encoder/runtime mismatch')
    arms = ('uncached_single', 'uncached_batch', 'cached_batch')
    reports, reference = [], None
    for repetition in range(repeats):
        order = arms if repetition % 2 == 0 else tuple(reversed(arms))
        for arm in order:
            start, cpu = time.perf_counter_ns(), time.process_time_ns()
            # Fresh cache for every measured trial; no borrowed work from an arm.
            worker = SharedStemEngine(engine.backend, max_cache_bytes=cache_bytes if arm == 'cached_batch' else 0)
            size = 1 if arm == 'uncached_single' else 32
            outputs, observations, elements = [], [], 0
            for offset in range(0, len(requests), size):
                observation, features = worker.run(requests[offset:offset+size], return_features=True)
                elements += sum(len(feature.values) for feature in features)
                if elements > 4_194_304:
                    raise ValueError('retained comparison feature budget exceeded')
                observations.append(observation)
                outputs.extend(features)
            wall_ns, cpu_ns = time.perf_counter_ns() - start, time.process_time_ns() - cpu
            if len(outputs) != len(requests):
                raise ValueError('incomplete Encoder comparison')
            if reference is None:
                reference = tuple(outputs)
            error = 0.0
            for old, new in zip(reference, outputs):
                if (old.token_count != new.token_count or old.representation != new.representation
                        or len(old.values) != len(new.values)):
                    raise ValueError('batch/solo feature shape or token mismatch')
                error = max(error, max(abs(a-b) for a,b in zip(old.values, new.values)))
            if error > maximum_absolute_error:
                raise ValueError('batch/solo numerical parity exceeded; no performance acceptance')
            reports.append({'arm': arm, 'repetition': repetition, 'cpu_ns': cpu_ns, 'wall_ns': wall_ns,
                            'backend_calls': sum(o.backend_calls for o in observations),
                            'backend_batch_widths': [w for o in observations for w in o.backend_batch_widths],
                            'cache_hits': sum(o.cache_hits for o in observations),
                            'cache_estimated_bytes': worker.cache.size_bytes,
                            'maximum_absolute_error': error,
                            'simulated_encoder': any(o.simulated for o in observations)})
    return {'arms': reports, 'shared_physical_backend_instances': 1,
            'simulated_encoder': any(r['simulated_encoder'] for r in reports),
            'load_and_construction_measured': False, 'rss_measured': False,
            'same_quality_established': False, 'production_authorized': False}
