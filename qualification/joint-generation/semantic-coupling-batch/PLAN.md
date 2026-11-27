# Fixed payload-free batch-coupling cost qualification

The preceding actual-model study found a structural control gain but charged
1.175713CPU for6192scalar coupling/transport/binding requests. Original independent
table formation was much cheaper and not an equal kernel. Optimize that measured
implementation bottleneck without another model/validation experiment.

Add a batched path for the SAME opt-in coupling profile: check model binding once,
vectorize transport/residual table operations,retain raw andCDF-normalized1e-12
marginal guards. Original scalar helper,profile identity/default andsampler remain
unchanged. No new target,decoder,model update,utility,rho or scientific gate.

Six literal tests before benchmark:all36commands andidentity/permuted semantics,
scalar law parity,zeroresidual diagonal,inputimmutability/normalized marginals,
near-normalized rejection,explicit binding/shape/input rejection,fixedCDF draw parity.
Fixtures are formula-defined literal arrays only,no train/validation/Test datasets.

Fixed benchmark:1008rows=36commands x28,permuted observed image semantics,positive/
identical/one-hot/disjoint cases from the published deterministic fixture formula.
Warm up BOTH methods on12rows once. Then5paired repeats,alternating scalar-first
andbatch-first. No best-time selection or repetition after viewing results. Scalar
andbatch return matching text,image,joint,CDF-total andprofile identity. Scalar
arrays/metadata conversion andbatch binding/guard work are charged within their
measured calls. Comparison andsampling checks outside timed calls remain inside
whole-child CPU. This is deliberately a table/profile microbenchmark,NOT end-to-end
generator speed or newquality/generalization evidence.

For every timed row require raw output difference<=1e-12,actualCDF-normalized law
difference<=1e-12,andbothCDF marginals<=1e-12. Require same profile identity and
unchanged inputs. Three supplied uniforms check each pair of first-row samplers.
Performance gate:median(batch CPU)/median(scalar CPU)<=.5,at least2x speedup,only if
all parity tests pass. Report all5timings,not minimum; failure stays failure.

Counts:5040timed tables perimplementation plus12warmup each,20160normalized marginal
checks,30sampler draws,0modelrestores/updates/decodedimages/dataset rows. Six test
fixture work is additional and included in whole wait4. No numerical checks before
source freeze/static review. Exact source allowlist,no payloads/network/descendants.

One completely waited child under existing NEW synthetic-only shared lock,CPU0,
one numerical thread,10CPU/60wall/512MiB/4MiB. Refusal/failure stops without retry.
Whole CPU,user/system,wall,RSS and supervisor observed prefix reported; tail and
source/review costs unknown,not zero. Do not transfer benchmark speedup to earlier
actual-model tables without a separate evaluation. Prior control success and NDU
failure remain unchanged; this qualification cannot repair or rename those gates.
