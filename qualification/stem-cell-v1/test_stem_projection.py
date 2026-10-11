import hashlib
import math
import struct
import unittest
from dataclasses import dataclass

from stem_projection import (
    Q, LIMIT, LowRankProjectionQ24, ProjectedStemEngine, project_ref,
    round_q48, q24_from_float,
)


def d(c):
    return c * 64


def feature(values, count=3, representation="mean"):
    from types import SimpleNamespace
    h = hashlib.sha256(b"hepta.stem.feature.f32.v1")
    h.update(len(values).to_bytes(8, "big"))
    canonical = []
    for x in values:
        raw = struct.pack(">f", x)
        canonical.append(struct.unpack(">f", raw)[0])
        h.update(raw)
    h.update(count.to_bytes(8, "big"))
    h.update(representation.encode("ascii"))
    return SimpleNamespace(values=tuple(canonical), token_count=count,
                           representation=representation, feature_digest=h.hexdigest())


@dataclass(frozen=True)
class Request:
    request_id: str = "req.1"
    scope_digest: str = d("1")
    generation: int = 5
    revocation_frontier_digest: str = d("2")
    encoder_digest: str = d("a")
    preprocessor_digest: str = d("b")
    runtime_digest: str = d("c")
    input_digest: str = d("d")
    representation: str = "mean"

    def validate(self):
        if not all(len(x) == 64 for x in (
                self.scope_digest, self.revocation_frontier_digest,
                self.encoder_digest, self.preprocessor_digest,
                self.runtime_digest, self.input_digest)):
            raise ValueError("bad identity")
        if self.generation < 1:
            raise ValueError("bad generation")


def spec():
    # Rank-2 identity on the first two of three input coordinates, with
    # output 1 shifted by a strictly declared +Q/8 bias.
    return LowRankProjectionQ24(
        d("a"), d("b"), d("c"), d("e"), "mean",
        3, 2, 2,
        (Q, 0, 0, 0, Q, 0),
        (Q, 0, 0, Q),
        (0, Q // 8),
    )


class Engine:
    def __init__(self, outputs):
        self.calls = 0
        self.outputs = outputs
    def run(self, requests, *, return_features=False):
        self.calls += 1
        if len({(r.scope_digest, r.generation, r.revocation_frontier_digest)
                for r in requests}) != 1:
            raise ValueError("cross-scope batch denied")
        if return_features is not True:
            raise AssertionError("feature bundle needs to be requested")
        return {"backend_calls": 1}, self.outputs[:len(requests)]


class ProjectionTests(unittest.TestCase):
    def test_digest_and_known_q24_golden(self):
        x = spec()
        self.assertEqual(x.project_q24((Q//2, -Q//4, Q//8)), (Q//2, -Q//8))
        self.assertEqual(x.project_float32((0.5, -0.25, 0.125)), (Q//2, -Q//8))
        self.assertEqual(x.digest,
            "451632b3946c1d3dd690eaf2007ad71ba00b50c49c8911854aa02be25a7838c3")
        src = feature((.5, -.25, .125))
        result = project_ref(Request(), src, x)
        self.assertEqual(result.vector_q24, (Q//2, -Q//8))
        self.assertEqual(result.projected_input_digest,
            "a61a79d9d616f28356a12dbcb1eaccbf37c7d51ae3fee807fc6d8d724150a40e")
        self.assertFalse(result.production_authorized)

    def test_ties_to_even_and_limits(self):
        self.assertEqual(round_q48(Q//2), 0)
        self.assertEqual(round_q48(3*Q//2), 2)
        self.assertEqual(round_q48(-Q//2), 0)
        self.assertEqual(round_q48(-3*Q//2), -2)
        self.assertEqual(q24_from_float(0.5), Q//2)
        for x in [float('nan'),float('inf'),-9, 9]:
            with self.assertRaises(ValueError):
                q24_from_float(x)
        with self.assertRaises(ValueError):
            round_q48(9*Q*Q)

    def test_real_768_to_256_no_slice_and_last_coordinate_visible(self):
        inp, rank, out = 768, 1, 256
        a = [0]*inp
        a[-1] = Q
        b = [0]*out
        b[-1] = Q
        x = LowRankProjectionQ24(d('a'), d('b'), d('c'), d('e'), 'mean',
                                 inp, out, rank, tuple(a), tuple(b), tuple([0]*out))
        src = tuple([0]*(inp-1)+[Q//4])
        r = x.project_q24(src)
        self.assertEqual(len(r), 256)
        self.assertEqual(r[-1], Q//4)
        self.assertEqual(r[:-1], (0,)*255)

    def test_6144_landmarks_explicit_projection(self):
        n=6144
        x = LowRankProjectionQ24(d('a'), d('b'), d('c'), d('e'), 'landmark8',
                                 n, 128, 8, tuple([0]*(n*8)), tuple([0]*(128*8)), tuple([0]*128))
        self.assertEqual(len(x.project_q24((0,)*n)),128)
        self.assertEqual(len(x.digest),64)

    def test_wrong_schema_tampered_feature_or_encoder_refused(self):
        good = feature((.5, -.25, .125))
        with self.assertRaisesRegex(ValueError, 'feature width'):
            project_ref(Request(), feature((.5,)), spec())
        with self.assertRaisesRegex(ValueError, 'source feature content'):
            altered = feature((.5, -.25, .125))
            altered.values = (.25, -.25, .125)
            project_ref(Request(), altered, spec())
        from dataclasses import replace
        with self.assertRaisesRegex(ValueError, 'incompatible frozen'):
            project_ref(replace(Request(), encoder_digest=d('f')), good, spec())
        with self.assertRaises(ValueError):
            replace(spec(), a_q24=(Q,)).digest
        with self.assertRaises(ValueError):
            replace(spec(), rank=0).digest
        with self.assertRaises(ValueError):
            replace(spec(), bias_q24=(9*Q, 0)).digest

    def test_versioning_and_scope_fence_include_revoke(self):
        from dataclasses import replace
        src = feature((.5,-.25,.125))
        a = project_ref(Request(),src,spec())
        for kwargs in [dict(scope_digest=d('f')),
                       dict(generation=6),
                       dict(revocation_frontier_digest=d('8')),
                       dict(input_digest=d('9'))]:
            b=project_ref(replace(Request(),**kwargs),src,spec())
            self.assertNotEqual(a.projected_input_digest,b.projected_input_digest)
        other=replace(spec(),bias_q24=(0,Q//4))
        b=project_ref(Request(),src,other)
        self.assertNotEqual(a.projected_input_digest,b.projected_input_digest)
        self.assertNotEqual(a.projection_digest,b.projection_digest)

    def test_cache_reuse_atomicity_and_scoped_invalidation(self):
        from dataclasses import replace
        reqs = [Request('req.1'), Request('req.2')]
        fake = Engine((feature((.5,-.25,.125)),)*2)
        from stem_projection import ProjectedStemEngine
        runner = ProjectedStemEngine(fake,spec())
        a=runner.run(reqs)
        self.assertEqual(fake.calls,1)
        self.assertEqual(a.projection_cache_hits,0)
        self.assertEqual(len({r.projected_input_digest for r in a.refs}),1)
        self.assertEqual(len({r.request_id for r in a.refs}),2)
        b=runner.run([Request('req.3')])
        self.assertEqual(b.projection_cache_hits,1)
        runner.cache.invalidate_scope(d('1'))
        c=runner.run([Request('req.4')])
        self.assertEqual(c.projection_cache_hits,0)
        d2=runner.run([replace(Request('req.5'),generation=6)])
        self.assertEqual(d2.projection_cache_hits,0)
        d3=runner.run([replace(Request('req.6'),revocation_frontier_digest=d('5'))])
        self.assertEqual(d3.projection_cache_hits,0)
        self.assertFalse(d2.production_authorized)

    def test_4096_cells_reuse_one_real_projection_in_same_scope(self):
        from stem_projection import ProjectedStemEngine
        fake = Engine((feature((.5, -.25, .125)),) * 32)
        runner = ProjectedStemEngine(fake, spec())
        projected_calls = 0
        in_batch = 0
        cache_hits = 0
        for offset in range(0, 4096, 32):
            out = runner.run([Request(f"req.{offset+i}") for i in range(32)])
            projected_calls += out.projection_calls
            in_batch += out.projection_reuses_within_batch
            cache_hits += out.projection_cache_hits
            self.assertFalse(out.production_authorized)
        self.assertEqual(fake.calls, 128)  # simulated Encoder per batch
        self.assertEqual(projected_calls, 1)
        self.assertEqual(in_batch, 31)
        self.assertEqual(cache_hits, 4064)
        self.assertEqual(runner.cache.bytes_used, 16)

    def test_preflight_denies_changed_projection_before_encoder_call(self):
        from dataclasses import replace
        fake = Engine((feature((.5,-.25,.125)),))
        runner=ProjectedStemEngine(fake,spec())
        with self.assertRaisesRegex(ValueError, 'projector/backend'):
            runner.run([replace(Request(),encoder_digest=d('f'))])
        self.assertEqual(fake.calls,0)

    def test_projection_preflights_scope_before_untrusted_engine(self):
        from dataclasses import replace
        fake=Engine((feature((.5,-.25,.125)),)*2)
        runner=ProjectedStemEngine(fake,spec())
        with self.assertRaisesRegex(ValueError, 'mixed scope'):
            runner.run([Request('req.1'), replace(Request('req.2'),scope_digest=d('8'))])
        self.assertEqual(fake.calls,0)
        with self.assertRaisesRegex(ValueError, 'mixed scope'):
            runner.run([Request('req.1'), replace(Request('req.2'),generation=8)])
        self.assertEqual(fake.calls,0)

    def test_fail_atomic_cache_on_one_bad_backend_feature(self):
        fake=Engine((feature((.5,-.25,.125)), feature((.5,))))
        runner=ProjectedStemEngine(fake,spec())
        with self.assertRaisesRegex(ValueError, 'feature width'):
            runner.run([Request('req.1'),Request('req.2')])
        self.assertEqual(runner.cache.bytes_used,0)

    def test_cache_bounded_and_corrupt_float_rejected(self):
        fake=Engine((feature((.5,-.25,.125)),))
        runner=ProjectedStemEngine(fake,spec(),maximum_projection_cache_bytes=16)
        runner.run([Request('req.1')])
        self.assertEqual(runner.cache.bytes_used,16)
        from dataclasses import replace
        runner.run([replace(Request('req.2'), input_digest=d('3'))])
        self.assertEqual(runner.cache.bytes_used,16)
        src = feature((.5,-.25,.125))
        src.values = (float('nan'), -.25, .125)
        with self.assertRaises(ValueError):
            project_ref(Request(),src,spec())

class ProjectionManifestTests(unittest.TestCase):
    def test_manifest_roundtrip_and_immutable_snapshot_identity(self):
        import tempfile
        import json
        from pathlib import Path
        from stem_projection import save_shadow_projection, load_shadow_projection
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/'projector.json'
            digest=save_shadow_projection(dest,spec(),training_lineage_digest=d('f'))
            self.assertEqual(load_shadow_projection(dest,expected_file_sha256=digest),spec())
            with self.assertRaises(FileExistsError):
                save_shadow_projection(dest,spec(),training_lineage_digest=d('f'))
            data=json.loads(dest.read_text())
            data['production_authorized']=True
            dest.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'changed/oversize'):
                load_shadow_projection(dest,expected_file_sha256=digest)
            changed=hashlib.sha256(dest.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError,'non-shadow'):
                load_shadow_projection(dest,expected_file_sha256=changed)

    def test_manifest_duplicate_key_is_not_accepted(self):
        import tempfile
        from pathlib import Path
        from stem_projection import load_shadow_projection
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'projection.json'
            p.write_text('{"schema":"foo","schema":"bar"}')
            sha=hashlib.sha256(p.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError,'duplicate projection manifest'):
                load_shadow_projection(p, expected_file_sha256=sha)


class CasProjectionCandidateTests(unittest.TestCase):
    def test_cas_candidate_exact_bytes_and_projection_digest(self):
        from stem_projection import encode_cas_projection_candidate, decode_cas_projection_candidate
        raw = encode_cas_projection_candidate(spec())
        result = decode_cas_projection_candidate(
            raw, expected_payload_sha256=hashlib.sha256(raw).hexdigest(),
            expected_projection_digest=spec().digest,
        )
        self.assertEqual(result, spec())
        self.assertIn(b'"schema":"hepta.stem.low-rank-projection-payload.v1"', raw)

    def test_cas_candidate_refuses_unknown_fields_and_changed_weights(self):
        import json
        from stem_projection import encode_cas_projection_candidate, decode_cas_projection_candidate
        raw = encode_cas_projection_candidate(spec())
        obj = json.loads(raw)
        obj["production_authorized"] = True
        tampered = (json.dumps(obj, sort_keys=True, separators=(",", ":"))+"\n").encode()
        with self.assertRaisesRegex(ValueError, "schema mismatch"):
            decode_cas_projection_candidate(
                tampered, expected_payload_sha256=hashlib.sha256(tampered).hexdigest(),
                expected_projection_digest=spec().digest)
        obj = json.loads(raw)
        obj["projection"]["a_q24"][0] += 1
        tampered = (json.dumps(obj, sort_keys=True, separators=(",", ":"))+"\n").encode()
        with self.assertRaisesRegex(ValueError, "revision"):
            decode_cas_projection_candidate(
                tampered, expected_payload_sha256=hashlib.sha256(tampered).hexdigest(),
                expected_projection_digest=spec().digest)

    def test_cas_candidate_refuses_reordered_and_duplicate_keys(self):
        from stem_projection import encode_cas_projection_candidate, decode_cas_projection_candidate
        raw = encode_cas_projection_candidate(spec())
        reordered = raw.replace(b'{"projection":', b'{"schema":"duplicate","projection":')
        with self.assertRaisesRegex(ValueError, "duplicate CAS"):
            decode_cas_projection_candidate(
                reordered, expected_payload_sha256=hashlib.sha256(reordered).hexdigest(),
                expected_projection_digest=spec().digest)
        changed = b" " + raw
        with self.assertRaisesRegex(ValueError, "canonical"):
            decode_cas_projection_candidate(
                changed, expected_payload_sha256=hashlib.sha256(changed).hexdigest(),
                expected_projection_digest=spec().digest)


if __name__ == '__main__':
    unittest.main()
