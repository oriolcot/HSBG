const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('assets/app.js', 'utf8');
const fn = html.split('\n').find(line => line.includes('async function waitForCareerResult(jobId)'));
(async () => {
  const partial = {matches:[{season:18}],scannedSeasons:[18],unavailableSeasons:[]};
  const final = {...partial,scannedSeasons:[18,19]};
  const messages = [{status:'queued',result:partial},{status:'running',result:partial},{status:'completed',result:final}];
  const renders = [];
  const context = {API_BASE_URL:'',wait:async()=>{},status:{textContent:''},
    renderCareerResults:(result,pending)=>renders.push({result,pending}),
    fetch:async()=>({ok:true,json:async()=>messages.shift()})};
  vm.createContext(context);vm.runInContext(fn,context);
  const result = await context.waitForCareerResult('test');
  assert.equal(result,final);
  assert.equal(renders.length,2);
  assert.ok(renders.every(r=>r.pending && r.result===partial));
  assert.match(context.status.textContent,/Historical results ready/);
  console.log('PASS: UI displays partial history while queued and running, then returns final result');
})().catch(error=>{console.error(error);process.exitCode=1;});
const freshness = html.split('\n').filter(line => line.includes('function resultFreshness(') || line.includes('function snapshotLabel(')).join('\n');
const freshnessContext = {};
vm.createContext(freshnessContext);
vm.runInContext(freshness, freshnessContext);
assert.match(freshnessContext.resultFreshness({dataMode:'live',checkedAt:'2026-01-01T00:00:00Z'}), /^Blizzard checked:/);
assert.match(freshnessContext.resultFreshness({capturedAt:'2026-01-01T00:00:00Z'}), /^Current leaderboard updated:/);
assert.equal(freshnessContext.resultFreshness(undefined), '');
console.log('PASS: freshness labels distinguish direct lookups from saved snapshots');
const warningContext = {};
vm.createContext(warningContext);
vm.runInContext(html.split('\n').find(line=>line.includes('function partialLookupWarning(')),warningContext);
assert.match(warningContext.partialLookupWarning([{found:true,incomplete:true}]),/Partial lookup/);
assert.match(warningContext.partialLookupWarning({incompleteSeasons:[19],matches:[{season:19}]}),/Partial lookup/);
assert.equal(warningContext.partialLookupWarning([{found:true}]),'');
assert.equal(warningContext.partialLookupWarning({matches:[],incompleteSeasons:[]}),'');
console.log('PASS: partial results warn even when players were found');
