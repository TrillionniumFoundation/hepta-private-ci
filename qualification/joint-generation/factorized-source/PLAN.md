# Canonical attribute-factorized source model — qualification only

Representation-only prospective intervention; no new risk objective or serving law.
Same202->32->two12 raw logits/192pixel learned decoder, exact same tensor count and
initialization as SourceSceneModel; same commandblind copiedinput last10zeros.
Additional known source-label factorization prior: canonicalclass k maps to
(k//4,(k//2)%2,k%2). Sourceclass already determines these attributes, so no additional
labels, renderer or target at inference; nevertheless this is stronger semantic
structure knowledge and not free information or a general RGB foundationmodel.

Each raw softmax p is explicitly normalized, attribute marginals m are formed,
product q_k=product_a m[a,attr_a(k)] is explicitly normalized again. Strictpositive
finite policies, exactcanonical schema, normalization/marginalclosure tolerance
1e-12; product underflow/nonfinite rejected, no epsilon/floor/repair. Generalfinite
precision reference, not derivative of binary64 rounding. Changedjoint may hurt:
output freedom drops from11 to4 perhead, discarding7 correlation degrees. Same
parameter count is NOT the same functionclass or capacity expansion. All rawlogit
parameters can affect marginals but nonidentifiable correlation directions remain.
Canonical source label attributes are NOT guaranteed decodedsemantics. Serving must
still observe actuallearneddecoder and use unchanged transport/coupling/FITcalibration.
Marginal preservation alone is not generation correctness.

## Exact chain and model integration
Incoming g is a virtual factor-logit gradient, alreadymean; require finite matching
shape and abs(row sum)<=1e-12, reject arbitrary probability gradients. Center
h=g-q sum(g) explicitly to retain productnormalization and finite residuals. For
mathematically proper gradients this sum iszero. This implements the derivative
of the normalizedfactor policy, not a rounding derivative.
G[a,v]=sum_{y:attr_a(y)=v}h_y;
chain_k=sum_a (p_k/m[a,attr_a(k)])G[a,attr_a(k)];
dL/drawlogit_k=chain_k-p_k sum(chain).
Only bounded conditional p/m ratios, never standalone1/m. No extra batchmean:
upstream A/anchor/supervised gradients already include it. The final subtraction
retains rawsoftmax/normalization. Both forwardnormalizations are differentiated.

FactorizedSourceModel overrides forward/gradients, not raw _forward. Each calls
JointModel._forward exactly once, with inherited commandmask, preventing recursive
or double factorization. Backprop pulls bothheads then uses original encoder chain;
no additional rawforward versus original. Inheritedsupervised_step uses projected
CE andq-onehot; inheritedtrain_step dispatches new gradients. Existing supervised
loss's maximum(prob,1e-300) convention remains unchanged; literalFD uses safeinterior
probabilities and does not claim differentiability of that floor at extreme inputs.
Decoder unchanged. Explicit mode/profile key differentiates digests; clones preserve
mode/tensors withclean moments. Save/load deliberately unsupported before I/O;
no checkpoint compatibility. Projection/pullback/rawforward calls and rows separately
counted in each factor model; qualification globaltoy-init count includes clones.

## Eleven literal tests, no scientific data
Five old SourceScene tests byte-exact plus6 new tests: normalizedprojection,
attribute marginals/productfixedpoint/idempotence/correlatedjoint change;48 fullhead
FD coordinates for fixedzero-sum virtual-logit cotangents;8 bothhead partial
transport A+.2ordinaryanchor FD coordinates;7 maskedmodel encoder/text/image/bias
supervisedCE AND7actualmodel partialA+.2anchor FD coordinates; sameparams/init/count, decoderunchanged, commandblind
inputimmutable, allkeep/fullsettransportinteraction, clone/mode/digest/checkpoint and exactrawforward/projection/pullback
work; invalidshape/mode/nonfinite/rawzeros/canonicalpermutation/positive-underflow
rejections. Canonicalorder only, arbitraryclass-axis permutations notsupported.
FixedFDstep1e-6, helpergradtol3e-8/modeltol2e-7/algebraictol2e-15. No prospective
claim bitwise for normalization/idempotence. Toymodel initialization and a few
literal updates are realcost, counted and fully in child; not falsely0models.
No data.py/renderer/payload in sourceallowlist, only hand x/y/reward and modelsource.

5CPU/30wall/512MiB/4MiB CPU0 singlethread, originalsyntheticlock nonblocking;
fullwait4/no retries/network/descendants. Allimports/tests/toyupdates/hash/output
insidechild costs; review/preparation/supervisortail additional notzero. Producer
source/AST only, no imports/numerics/modelpayload/dataset/lock/push. Independent
review and separateonce-run admission before execution.

## Later science outline, not part of qualification
DirectA versusfactorA across originalfour fold/seed cells,8models8 ownpretrainedbases,
300decoder/500sourceCE/300adapt, same labels/staticgroupedsampler/ordinaryanchor/
oldFITcalibration/knownnoise/originalfive gates. Direct4base/4A historicalexact
controls; matchedinitial tensors fornewfactor mode. Candidateextra priorknowledge,
projection/pullbackcomputations and all8base prep explicitly charged. No NDU arm or
new source labels/thresholds/serving law; launch requires its own review and budget.

## v2 pre-execution completion and later canonical admission
Unexecutedv1 remains immutable. v2 fixes the public cotangent contract to near-zero
row-sum virtualfactorlogit gradients, adds actualmodel A+anchor parameterFD and
allkeep/fullset transport interaction in existingtests (still11total). Later science
must verify actualdecodedobserver text ANDimage maps exactly canonical0..11 for
BOTH direct/factor decoderbases, before interpreting factorhead. Failwhole ifnot,
no remap/relabel/selection; recordmaps. Sourceclass labels address bothheads in
original supervised_step, makingcanonicalindex a legitimate trainingprior, not an
assumption that decoder learned it correctly. Equalinitialtensors do NOT imply
equalinitialpredictions: factorprojection generally changes jointdistributions.
