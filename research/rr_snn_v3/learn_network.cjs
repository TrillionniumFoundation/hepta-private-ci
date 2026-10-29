"use strict";
/* Fixed protocol: no heldout-based checkpoint selection or architecture tuning. */
function learnRRNetwork(N,M,C) {
  const teacher=[[.4,.35,.45,-.25,.3],[.2,-.25,.35,-.2,.25]];
  function dataset(first,count,fitted=null) {
    const byUnit=[[],[]],episodes=[],fixedUpNllByUnit=[0,0];
    for(let seed=first;seed<first+count;seed++) {
      const net=N.diagnostic(M,C,teacher,seed);net.runUntil(4);
      const records=net.records();
      records.forEach((rs,i)=>byUnit[i].push(...rs));
      const fixed=net.statistics().map(u=>u.regimes.reduce((sum,r)=>
        sum+3*r.exposure[0]-r.counts[0]*Math.log(3),0));
      fixed.forEach((value,i)=>fixedUpNllByUnit[i]+=value);
      const constant=fixed.reduce((a,b)=>a+b,0);
      const episode={seed,pulses:net.pulses().length,regimes:records.map(x=>x.length),
        fixedUpNllByUnit:fixed};
      if(fitted)episode.nll={
        initial:constant+records.reduce((sum,rows)=>sum+N.likelihood([0,0,0,0,0],rows).loss,0),
        fitted:constant+records.reduce((sum,rows,i)=>sum+N.likelihood(fitted[i],rows).loss,0),
        teacher:constant+records.reduce((sum,rows,i)=>sum+N.likelihood(teacher[i],rows).loss,0)};
      episodes.push(episode);
    }
    return {byUnit,episodes,fixedUpNllByUnit};
  }
  const train=dataset(10000,128);
  const fits=train.byUnit.map(rows=>N.fit([0,0,0,0,0],rows,
    {steps:300,learningRate:.03,l2:.01}));
  // First heldout generation occurs only after all fixed-budget fitting completes.
  const heldout=dataset(50000,128,fits.map(x=>x.theta));
  const scores=heldout.byUnit.map((rows,i)=>({
    initialNllPerEpisode:(N.likelihood([0,0,0,0,0],rows).loss+heldout.fixedUpNllByUnit[i])/128,
    fittedNllPerEpisode:(N.likelihood(fits[i].theta,rows).loss+heldout.fixedUpNllByUnit[i])/128,
    teacherNllPerEpisode:(N.likelihood(teacher[i],rows).loss+heldout.fixedUpNllByUnit[i])/128,
    trainInitialNllPerEpisode:(N.likelihood([0,0,0,0,0],train.byUnit[i]).loss+train.fixedUpNllByUnit[i])/128,
    trainFittedNllPerEpisode:(N.likelihood(fits[i].theta,train.byUnit[i]).loss+train.fixedUpNllByUnit[i])/128
  }));
  const differences=heldout.episodes.map(x=>x.nll.fitted-x.nll.initial);
  let rng=700101;const bootstrap=[];
  const uniform=()=>{rng^=rng<<13;rng^=rng>>>17;rng^=rng<<5;return (rng>>>0)/4294967296;};
  for(let b=0;b<10000;b++) {
    let sum=0;for(let group=0;group<4;group++)for(let i=0;i<32;i++)
      sum+=differences[group+4*Math.floor(uniform()*32)];
    bootstrap.push(sum/128);
  }
  bootstrap.sort((a,b)=>a-b);
  const pairedDifference={mean:differences.reduce((a,b)=>a+b,0)/128,
    interval95:[bootstrap[249],bootstrap[9749]],unit:"NLL per entire two-neuron path",
    resamplingUnit:"whole two-unit episode, stratified by four maturity/shock conditions",draws:10000,seed:700101};
  return {schema:"rr-delayed-network-learning-1",pairedDifference,protocol:"network_learning_protocol.json",
    architecture:"two finite CTMC spiking neurons with actual delayed recurrence",
    teacherWeights:teacher,learnedWeights:fits.map(x=>x.theta),scores,
    optimizer:fits.map(x=>({history:x.history,finalGradient:x.final.gradient,
      allFinite:x.theta.concat(x.final.gradient).every(Number.isFinite)})),
    trainEpisodes:train.episodes,heldoutEpisodes:heldout.episodes,
    scope:{fullPathLikelihood:true,initialResetAndCensoredIntervalsIncluded:true,
      trainableRecurrentSpikingModel:true,fullyObservedInternalJumps:true,
      absoluteNllIncludesFixedUpChannel:true,heldoutRegularization:0,terminalUtilityPolicyOptimization:false,
      matchedArchitectureComparison:false,actualFutureWindow:false}};
}
if(typeof module!=="undefined")module.exports=learnRRNetwork;
if(typeof require!=="undefined"&&require.main===module)
  console.log(JSON.stringify(learnRRNetwork(require("./delayed_network.cjs"),
    require("./event_runtime.cjs"),require("./continuation_operator.cjs")),null,2));
