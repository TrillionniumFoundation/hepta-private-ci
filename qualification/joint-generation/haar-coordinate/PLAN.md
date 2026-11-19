# Fixed orthonormal Haar coordinates at adaptation boundary

SOURCE ONLY qualification. One predetermined2x2/channel basis, not a factorprior,
risk reweighting, dimensionreduction ortransformsearch. For each8x8x3 RGB input,
the fourspatial positions(a,b;c,d) receive LL,LH,HL,HH using
H=(1/2)[++++;+-+-;++--;+--+]. Rowmajorpixel/channelordering isfixed. H isorthogonal,
symmetric andselfinverse. Tencommandfeatures remainunchanged byhelper; inherited
SourceSceneModel mask stillzeros them before encoder. Full192pixelcoordinates
retained: samefunctionclass andsameparametercount, not newlabels/semanticprior.
Known lowview usesconstant2x2blocks, so its detailcoefficients areexactlyzero for
boundedrepresentablefixtureinputs. That is a source-recipe property, notproof of
improvedgeneration or a newlydiscovered statisticalrelation.

## Conversion, identities and chain
Only explicit exactraw SourceSceneModel may convert at adaptationboundary.
If originalrowinput x andencoder W, usex'=xH andW'=H^T W forfirst192rows; leave
10commandrows/head/bias/decoderunchanged. Thusx'W'=xW inexactarithmetic. Conversion
copiesallparams, recordsoriginaldigest andresetsAdam moments/updates justlikeoldclone;
no inheritedoptimizerrotation orsecrettraining. Samefunction atboundary onlyup to
prospectivefiniteprecision tolerance, notbitwise oldmodeldigestcompatibility.
Newmode/schema/profile-bounddigest, cleanclone preservesalreadyconvertedweights
WITHOUT applyingHagain. DefaultSource untouched; checkpointsave/loadrejectbeforeI/O.
Rawforward/gradients use inheritedJointModel withone inputtransform per _input call,
no doublemask or additionalnetworkforward. Transformcalls/rows andencoderconversion
calls recorded. Encodergradient backmapping isH gradW'; otherparametergradients
unchanged. Fixed SGDstep iscovariant inexactarithmetic; finiteprecisionchecked.
DiagonalAdam isnotrotationinvariant: momentcoordinatewise square/division/epsilon
canchangeupdates. A constructedone-step example demonstrates difference, NOT that
it improvesloss,generation, scientificgates or isunbiased. OriginalAdam normclipping
isalso unchanged; orthogonal norminvariance is anexact-arithmetic statement.

## Finite domain
Strictfixedshape,N1..65536 finitefloat inputs. Transformedcoefficients maynegative
oroutside[0,1], so helperdoes NOT clip them. No epsilon, floor, rangeprojection or
underflowrepair. Finiteinput sums canoverflow; nonfinite outputsrejectwholecall.
The basisconstantandlayout arefixedinprofile; wrongprofile/mode/shape rejected.
Originalsourceparameters mustfinite. Numericalchain is real-valuedreference,
not derivative ofbinary64 rounding. No renderer/data.py/modelpayload allowed.

## Eleven fixed literal tests
OldSource5 byte-exact plus6new:
1 full192basis orthogonality/symmetry/involution; normpreservation/immutability.
2 lowview exactdetailzeros/LL=2blockvalue, helpercommandbytesunchanged, Source
  commandblindoutputs ANDgradients withtransformedpixelinput.
3 conversionfromsourcewithnonemptyAdamhistory preservesfunction/decoder/otherparams,
  exactparamcount, newidentity, clone/noalias andcleanmoments; no doubleconversion.
4 transformbackencodergradientequivalence,7actualencoder/head/bias FDcoordinates,
  oneSGDstep covariancetoindependentlyconvertedrawmodel.
5 constructedoneAdamstep withfixedencodergradient givesdifferentmappedupdate,
  no scientificqualitymeasurement orclaim.
6 shape/nonfinite/overflow/wrongmode/wrongsource/doubleconversion/checkpointrefusals.
Fixedalgebraictol2e-15 (norm2e-14absolute/2e-15relative), function/gradient/SGD3e-15,
FDstep1e-6/error2e-7. Literaltoyinitializations/optimizerupdates actualcounts inRESULT;
manualSGD fixture addsoneexplicitparameterstep permodel, outsideAdamupdatecounter,
reported separately andinsidechildCPU.0restored/scientificmodels/data rows.

## Boundaries and next step
10CPU/30wall/512MiB/4MiB CPU0singlethread/existingnonblockinglock,fullwait4/no retry.
Sourceauditallowlist,no data.py/renderer/payload/network/descendants. Imports/tests/
alltoy/transform/hash/outputcost includedwholechild; prep/review/supervisortail
additionalnotzero. ProducerSOURCE/ASTonly: no imports/numericalexecution/locks/push.
Independentreview plusseparateonce-run admission required beforequalification.

LaterA-control experiment, notincludedhere, would sharefixedrawSourcepretraining
andconvertONLYat adaptationboundary withresetAdam forbothraw/Haararms. Retain
sameoriginallabels/static300adapt/anchor/calibration/serving/gates, fixonebasis,
charge allconversion/transformwork and requirestrongrawcontrol exacthistorical
recovery. No newfactorpartition/rho/epoch/seed/threshold tuning orNDUsuccessclaim.
