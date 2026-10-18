// Synthetic UI behavior only; no bank images.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const template=fs.readFileSync(process.argv[2],'utf8');
const frame={timestamp_sec:1,width:400,height:800,image:'data:image/jpeg;base64,'};
const payload={review_session:'test',protocol_sha256:'p',previous_storage_key:'previous',cases:[0,1].map(i=>({session_id:'s'+i,sha256:'v'+i,name:'X-'+i,duration_sec:3,video_file:'synthetic.mov',frames:[frame]}))};
const nodes={},storage=new Map([['previous',JSON.stringify({s0:{comment:'preserved previous annotations'},foreign:{comment:'another video'}})]]),downloads=[],context=new Proxy({},{get:()=>()=>{}});
function element(id){return nodes[id]??={value:'',checked:false,textContent:'',width:400,height:800,currentTime:0,pause(){},appendChild(){},getContext(){return context},getBoundingClientRect(){return {left:0,top:0,width:400,height:800}}}}
element('view').value='hands';
const scope={document:{getElementById:element,createElement:t=>t==='a'?{click(){downloads.push(scope.blob)}}:{value:'',textContent:''}},Image:class{set src(v){if(this.onload)this.onload()}},localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},Blob:class{constructor(p){this.text=p.join('');scope.blob=this}},URL:{createObjectURL:()=> 'blob:synthetic',revokeObjectURL(){}},setTimeout(){},Date};
vm.createContext(scope);vm.runInContext(template.match(/<script>([\s\S]*)<\/script>/)[1].replace('__PAYLOAD__',JSON.stringify(payload)),scope);
const call=c=>vm.runInContext(c,scope);
assert.equal(nodes.comment.value,'preserved previous annotations');assert.equal(call('reviews.foreign'),undefined);
call('save()');let data=JSON.parse(downloads.at(-1).text);assert.equal(data.confirmed,false);assert.equal(nodes.json.value,downloads.at(-1).text);
nodes.complete.value='yes';nodes.presentation.value='not_observed';nodes.device.value='unknown';call('changed()');nodes.confirmed.checked=true;call('changed(false);switchCase(1)');
nodes.complete.value='no';nodes.presentation.value='presentation_seen';nodes.start.value='1';nodes.end.value='2';nodes.device.value='possible_device_use';call('changed()');
call('canvas.onclick({clientX:50,clientY:100});canvas.onclick({clientX:150,clientY:300})');nodes['object-kind'].value='card_like_unknown';call('changed()');nodes.confirmed.checked=true;call('changed(false);save()');
data=JSON.parse(downloads.at(-1).text);assert.equal(data.confirmed,true);assert.equal(data.cases[0].physical_document_observation,'not_observed');assert.equal(data.cases[1].document_seed.object_kind,'card_like_unknown');assert.equal(data.cases[1].complete_operation_visible,'no');
assert.ok(data.cases.every(c=>c.legal_violation_label===null&&c.identity_verification_status==='unknown_no_bank_record'));assert.equal(data.face_recognition_used,false);
nodes.end.value='100';call('changed();save()');assert.equal(JSON.parse(downloads.at(-1).text).confirmed,false);
call('switchCase(0)');assert.equal(nodes.presentation.value,'not_observed');assert.equal(nodes.confirmed.checked,true);
console.log('PASS: two-clip restoration, draft export, JSON fallback, two-click seed, interval validation, absence never produces identity/violation verdict.');
