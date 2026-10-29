const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
class Element {
 constructor(id){this.id=id;this.value='';this.options=[];this.children=[];this.style={};this.dataset={};this.attrs={};this.listeners={};this.classList={toggle(){}};this.parentElement={hidden:false};this.hidden=false;this.checked=false;this.disabled=false;}
 get selectedIndex(){return this.options.findIndex(o=>o.value===this.value);}
 replaceChildren(...children){this.children=children;if(['mode','region','season'].includes(this.id)){this.options=children;this.value=children[0]?.value||'';}}
 add(option){this.options.push(option);}
 append(...children){this.children.push(...children);}
 appendChild(child){this.children.push(child);return child;}
 setAttribute(key,value){this.attrs[key]=value;}
 removeAttribute(key){delete this.attrs[key];}
 addEventListener(event,fn){this.listeners[event]=fn;}
 focus(){this.focused=true;}
 requestSubmit(){return this.listeners.submit({preventDefault(){}});}
}
const ids=['mode','region','season','btags','history-search','history-control','history-help','search-button','status-text','results-container','results-toolbar','results-summary','copy-button','search-form','results-context','results-empty','results-panel','support-panel','support-link'];
const el=Object.fromEntries(ids.map(id=>[id,new Element(id)]));
class Option{constructor(text,value){this.text=text;this.value=value;}}
el.mode.replaceChildren(new Option('Solo','battlegrounds'),new Option('Duos','battlegroundsduo'));
el.region.replaceChildren(new Option('Americas','US'),new Option('Europe','EU'));
el.season.replaceChildren(new Option('Current season','current'));
const live=new Element('live'),requests=[];
const context={document:{getElementById:id=>el[id],querySelectorAll:()=>[],querySelector:()=>live,createElement:()=>new Element('created')},window:{location:{origin:'https://example.test'},setTimeout,clearTimeout},Option,AbortController,URLSearchParams,navigator:{clipboard:{writeText:async()=>{}}},fetch:(url,options)=>new Promise(resolve=>requests.push({url,options,resolve})),console};
vm.createContext(context);vm.runInContext(fs.readFileSync('assets/app.js','utf8'),context);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const response=(payload,ok=true)=>({ok,json:async()=>payload});
(async()=>{
 assert.equal(requests.length,1);assert.equal(el['search-button'].disabled,true);
 el.region.value='EU';el.region.listeners.change();assert.equal(requests.length,2);assert.equal(requests[0].options.signal.aborted,true);
 requests[1].resolve(response({currentSeason:20,seasons:[20,19],dataMode:'snapshot'}));await tick();
 requests[0].resolve(response({currentSeason:18,seasons:[18,17],dataMode:'live'}));await tick();
 assert.equal(el.season.options[0].text,'Current season · Season 20');assert.equal(live.textContent,'Scheduled updates · 30 min');assert.equal(el['search-button'].disabled,false);
 el.btags.value='';await context.searchLobby();assert.equal(requests.length,2);assert.equal(el.btags.attrs['aria-invalid'],'true');
 el.btags.value=Array.from({length:21},(_,i)=>'name'+i).join(',');await context.searchLobby();assert.equal(requests.length,2);
 el.btags.value='Rain';el['search-form'].requestSubmit();await tick();assert.equal(requests.length,3);assert.equal(el.mode.disabled,true);assert.equal(el.region.disabled,true);assert.equal(el.btags.disabled,true);assert.equal(el['results-container'].attrs['aria-busy'],'true');assert.equal(el['results-panel'].attrs['aria-busy'],'true');
 el['search-form'].requestSubmit();assert.equal(requests.length,3);
 el.region.value='US'; // Simulate a programmatic external edit during the request: result labels must remain captured.
 requests[2].resolve(response([{found:true,btag:'Rain',rank:2,rating:9000},{found:true,btag:'Rain',rank:10,rating:8500}]));await tick();
 assert.equal(el['results-summary'].textContent,'2 matches · 1 name searched');assert.equal(el['results-context'].textContent,'Europe · Solo · Current season · Season 20');assert.equal(el['results-container'].children[0].children[0].children[1].textContent,'Europe · Solo');assert.equal(el.region.disabled,false);assert.equal(el['results-container'].attrs['aria-busy'],'false');assert.equal(el['results-panel'].attrs['aria-busy'],'false');
 el.mode.listeners.change();requests[3].resolve(response({},false));await tick();assert.equal(el['search-button'].disabled,true);assert.equal(el['status-text'].dataset.state,'seasons-error');assert.equal(el['results-container'].children.length,0);assert.equal(el['results-context'].textContent,'Americas · Solo');
 el.mode.listeners.change();requests[4].resolve(response({currentSeason:20,seasons:[20,19],dataMode:'snapshot'}));await tick();assert.equal(el['search-button'].disabled,false);assert.equal(el['results-panel'].hidden,true);assert.equal(el['results-empty'].hidden,false);assert.equal(el['results-context'].textContent,'');
 let prevented=false;el.btags.listeners.keydown({key:'Enter',ctrlKey:true,metaKey:false,preventDefault(){prevented=true;}});assert.ok(prevented);assert.equal(requests.length,6);
 requests[5].resolve(response([{found:false,btag:'Rain',error:'Not found in this snapshot'}]));await tick();assert.equal(el['results-summary'].textContent,'0 matches · 1 name searched');assert.equal(el['results-panel'].hidden,false);assert.equal(el['results-empty'].hidden,true);
 // Exercise timeouts through the actual submit handlers, including control recovery and partial history.
 const timeoutSet=context.window.setTimeout,timeoutClear=context.window.clearTimeout,savedFetch=context.fetch,pendingTimers=new Map();
 context.window.setTimeout=(fn,ms)=>{if(ms>=30000){const token={};pendingTimers.set(token,{fn,ms});return token;}if(ms===1800){queueMicrotask(fn);return 'instant-poll';}return timeoutSet(fn,ms);};
 context.window.clearTimeout=token=>{if(pendingTimers.has(token))pendingTimers.delete(token);else if(token!=='instant-poll')timeoutClear(token);};
 const hangUntilAborted=(url,options)=>new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(Object.assign(new Error('aborted'),{name:'AbortError'}))));
 context.fetch=hangUntilAborted;
 const stalledSearch=context.searchLobby();const searchDeadline=[...pendingTimers.values()].find(timer=>timer.ms===120000);assert.ok(searchDeadline);searchDeadline.fn();await stalledSearch;
 assert.match(el['status-text'].textContent,/request took too long/);assert.equal(el['search-button'].disabled,false);assert.equal(el.btags.disabled,false);assert.equal(el['results-panel'].attrs['aria-busy'],'false');
 el['history-search'].checked=true;
 const stalledCareer=context.searchLobby();const careerDeadline=[...pendingTimers.values()].find(timer=>timer.ms===30000);assert.ok(careerDeadline);careerDeadline.fn();await stalledCareer;
 assert.equal(el['status-text'].dataset.state,'error');assert.equal(el.mode.disabled,false);assert.equal(el['search-button'].disabled,false);
 let pollRequests=0;
 context.fetch=(url,options)=>{if(url.includes('/career?'))return Promise.resolve(response({status:'queued',jobId:'timeout-test'}));pollRequests++;if(pollRequests===1)return Promise.resolve(response({status:'running',result:{btag:'Rain',matches:[{season:19,btag:'Rain',rank:5,rating:9000}],scannedSeasons:[19],unavailableSeasons:[]}}));return hangUntilAborted(url,options);};
 const stalledPoll=context.searchLobby();await tick();assert.equal(pollRequests,2);assert.equal(el['results-container'].children[0].children[0].children[0].textContent,'Season 19');
 const pollDeadline=[...pendingTimers.values()].find(timer=>timer.ms===30000);assert.ok(pollDeadline);pollDeadline.fn();await stalledPoll;
 assert.match(el['status-text'].textContent,/request took too long/);assert.equal(el['results-container'].children[0].children[0].children[0].textContent,'Season 19');assert.equal(el['results-toolbar'].hidden,false);assert.equal(el['search-button'].disabled,false);assert.equal(el['results-panel'].attrs['aria-busy'],'false');
 assert.equal(pendingTimers.size,0);context.window.setTimeout=timeoutSet;context.window.clearTimeout=timeoutClear;context.fetch=savedFetch;el['history-search'].checked=false;
 console.log('PASS: search, career-start and polling timeouts unlock the form and preserve partial history');
 let seasonTimeout;const originalSet=context.window.setTimeout,originalClear=context.window.clearTimeout;context.window.setTimeout=(fn,ms)=>{if(ms===25000){seasonTimeout=fn;return 'season-timeout-test';}return originalSet(fn,ms);};context.window.clearTimeout=id=>{if(id!=='season-timeout-test')originalClear(id);};context.fetch=(url,options)=>new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(Object.assign(new Error('aborted'),{name:'AbortError'}))));el.mode.listeners.change();assert.equal(typeof seasonTimeout,'function');seasonTimeout();await tick();assert.equal(el['status-text'].dataset.state,'seasons-error');assert.match(el['status-text'].textContent,/took too long/);assert.equal(el['search-button'].disabled,true);assert.equal(el.region.disabled,false);
 console.log('PASS: seasons timeout and race/error recovery, client limits, immutable request context, form submission/shortcut, input locking, duplicate-submit guard, result visibility');
})().catch(error=>{console.error(error);process.exitCode=1;});
