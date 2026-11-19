# Same-law fixed command-map cache: literal parity and complete-cost microbenchmark

Priorcalibration effects reproduced acrossnewinitializations/noise,but measured
calibratedcoupling/CDF servingcost was1.55–1.71xuncalibrated. This experiment targets
implementationcost only. It cannotreplace theoriginalgeneration/NDUgates orclaim
newquality. A separate group-heldout science line is being prepared independently.

Precompileall36legalcommands x2semanticdestinationmaps andprofilebinding/hashes from
immutablemetadata. Cache neverconsumes rawpolicies,targets ordata. The sameexisting
calibratedgenerationprofile key remains; a separate cache key/schema binds fixed
implementation,maporder andallmaps. Constructor computesmaps once (72destination
calls); bytes-backed arrayviews areimmutable. Loading requires explicitgeneration
mode/model/implementation andrecomputes maps torejecttampering. Old/default APIs
unchanged. Per-call binding verifiesimmutablecache type/model andexplicitcommands;
profile/hashvalidation is amortized atcompile/load,not falselyclaimed free.

Numerical path copies the qualifiedbase andcalibration operations inexactorder,
using the same _law andcalibrate_marginals. Only mapsetup/profilehash recomputation
is cached. Allraw/CDF/marginal/support/argmax checks remain. No missing-input fallback,
thresholdchange ornew numerical graph. No old-source artifactcompatibility promise.

Six literaltests:bitwise outputtables/CDFtotals/marginals/generationkey onbatchsizes
1/36/1008 andthreefixedtemperaturepairs;same supplieduniform draws;cache serialization/
model/mode/maptamper rejection; immutablebuffers/inputimmutability; invalidinputs/
profilemixing; identicalnumericalsupport-loss refusal. No model ordata access.

Then one fixedliteralbenchmark:1008rows=36commands repeated28times,onepermutedsemantic
profile,tau_text=.5/tau_image=2,fixedpositiveprobabilities. Recordcompile,serialize,
load CPU separately. Onefullbatch warmup perimplementation,then5paired repeatswith
alternatingorder. Compareeverypair bitwise outside timedsections; reportalltimes,
median CPU andratio,no cherry-pickedminimum. Outputtables timed5040perimplementation,
warmup1008each;eachservingcall computesbase+calibratedlaw tables. Sixliterals andall
setup/warmup/checks included inwholechildcost. Compile/load break-even amortization
isreported onlyif median savedCPU positive,not assumed. Performanceacceptance fixed
cachedmedian<=.8reference median ANDbitwiseallpass; failure isretained,no retuning.
This is a batch/table/profile microbenchmark,not model-inference/endtoendlatency.

One completelywaited child,existing syntheticlock,CPU0singlethread,5CPU30wall512MiB/
4MiB,no descendants/network/retry. Sourcefreeze+independentSTATIC beforeexecution.
No model/dataset payload,training,validationorTEST. Earlierqualitygates remainfalse
wherefalse; cache speed cannotmake thempass. Historical/source/review/supervisortails
additional,not zero. No production/defaultdeployment.
