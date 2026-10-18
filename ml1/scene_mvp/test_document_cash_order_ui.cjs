const fs=require('fs'),vm=require('vm'),assert=require('assert'),nodes={},downloads=[];let scope;
function node(id){return nodes[id]??={value:'',checked:false,currentTime:0,paused:true,textContent:'',style:{},pause(){this.paused=true},play(){this.paused=false;return Promise.resolve()}}}
scope={document:{getElementById:node,createElement:()=>({click(){downloads.push(scope.blob.text)}})},localStorage:{getItem:()=>null,setItem(){}},Blob:class{constructor(parts){scope.blob={text:parts.join('')}}},URL:{createObjectURL:()=> 'blob:local',revokeObjectURL(){}},setTimeout(){},Date};
const payload={review_session:'synthetic',source_session:'s',source_video_sha256:'v',protocol_sha256:'p',document_window:[7.5,8.5],duration_sec:20,video_file:'source.mov'};
const html=fs.readFileSync(process.argv[2],'utf8');vm.createContext(scope);vm.runInContext(html.match(/<script>([\s\S]*)<\/script>/)[1].replace('__PAYLOAD__',JSON.stringify(payload)),scope);const run=s=>vm.runInContext(s,scope);
run('save()');let d=JSON.parse(downloads.at(-1));assert.equal(d.confirmed,false);assert.equal(node('json').value,downloads.at(-1));
for(const [id,value] of Object.entries({'cash-start':'10','cash-end':'12','direction':'client_to_cashier','counter':'observed','counter-start':'13','counter-end':'16','same':'yes','manual':'unknown'}))node(id).value=value;
node('confirmed').checked=true;run('save()');d=JSON.parse(downloads.at(-1));assert.equal(d.confirmed,true);assert.deepEqual(d.counter_use_window_sec,[13,16]);assert.equal(d.identity_verification_established,false);
node('counter').value='not_observed';node('counter-start').value='';node('counter-end').value='';run('save()');d=JSON.parse(downloads.at(-1));assert.equal(d.confirmed,true);assert.equal(d.counter_use_window_sec,null);
node('video').currentTime=11.25;run("mark('cash-start')");assert.equal(node('cash-start').value,'11.250');assert.equal(node('confirmed').checked,false);
console.log('PASS: draft saving, marked native video time, cash/counter windows, counter not observed, JSON fallback, no identity verdict.');
