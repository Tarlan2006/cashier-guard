// Synthetic browser checks: no bank images or browser screenshots.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const template=fs.readFileSync(process.argv[2]||'ml1/scene_mvp/transfer_control.html','utf8');
const fixture={session_id:'synthetic-session',source_video_sha256:'synthetic-sha',source_name:'synthetic',candidate_ids:[1,3],initial_frame_index:0,validation_plan:{plan_id:'synthetic',sha256:'synthetic'},frames:[{timestamp_sec:1,width:400,height:800,persons:[],image:'data:image/jpeg;base64,'}]};
const point={xy:[.35,.5],label:1,source:'human_click_on_visible_target_or_distractor'};
const target={bbox:[.3,.4,.5,.6],timestamp_sec:1,source:'human_box_on_visible_target',points:[point]};
function environment(initial={}){
 const nodes={},storage=new Map(Object.entries(initial)),downloads=[];
 const ctx=new Proxy({},{get:()=>()=>{}});
 function element(id){return nodes[id]??= {value:'',checked:false,textContent:'',open:false,width:400,height:800,appendChild(){},getContext(){return ctx},getBoundingClientRect(){return {left:0,top:0,width:400,height:800}}}}
 for(const id of ['target','mode','view'])element(id).value={target:'cash',mode:'box',view:'hands'}[id];
 element('absence-confirmed');element('confirmed');
 element('tracks').checked=true;
 const scope={document:{getElementById:element,createElement:type=>type==='a'?{click(){downloads.push({name:this.download,blob:scope.lastBlob})}}:{value:'',textContent:''}},localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},Image:class{set src(x){if(this.onload)this.onload()}},Blob:class{constructor(parts){this.text=parts.join('');scope.lastBlob=this}},URL:{createObjectURL:()=> 'blob:synthetic',revokeObjectURL(){}},setTimeout(){},Date};
 vm.createContext(scope);vm.runInContext(template.match(/<script>([\s\S]*)<\/script>/)[1].replace('__PAYLOAD__',JSON.stringify(fixture)),scope);
 return {scope,nodes,downloads,storage,call:code=>vm.runInContext(code,scope)};
}
const key='sam-transfer-control-synthetic-session',targets=Object.fromEntries(['cash','cashier_hand','client_hand'].map(k=>[k,target]));
let e=environment({[key]:JSON.stringify(targets),[key+'-state-v2']:JSON.stringify({cashier:'1',client:'3',index:0})});
assert.equal(e.nodes.cashier.value,'1');assert.equal(e.nodes.client.value,'3');assert.equal(e.call('Object.keys(targets).length'),3);
e.call('save()');let data=JSON.parse(e.downloads.at(-1).blob.text);
assert.equal(data.confirmed,false);assert.equal(data.profile_kind,'hand_transfer_scene');assert.equal(Object.keys(data.targets).length,3);assert.equal(e.downloads.at(-1).name,'synthetic-session-transfer-draft.json');
assert.equal(e.nodes.json.value,e.downloads.at(-1).blob.text);
e.nodes.confirmed.checked=true;e.call('save()');data=JSON.parse(e.downloads.at(-1).blob.text);
assert.equal(data.confirmed,true);assert.equal(data.transfer_direction_supplied,false);assert.deepEqual(data.roles,{cashier_ids:[1],client_ids:[3]});assert.equal(data.targets.cash.points.length,1); // A negative point is optional.
e.nodes['absence-confirmed'].checked=true;e.call('save()');assert.equal(JSON.parse(e.downloads.at(-1).blob.text).profile_kind,'hand_transfer_scene'); // Main save never exports absence.
e.call('saveAbsence()');data=JSON.parse(e.downloads.at(-1).blob.text);assert.equal(data.client_present,false);assert.equal(e.call('Object.keys(targets).length'),3);
e.nodes.client.value='1';e.call('rolesChanged();save()');assert.equal(JSON.parse(e.downloads.at(-1).blob.text).confirmed,false);
e=environment();e.nodes.cashier.value='1';e.nodes.client.value='3';e.call('rolesChanged()');
e.call('canvas.onclick({clientX:40,clientY:100});canvas.onclick({clientX:180,clientY:400})');assert.equal(e.call('targets.cash.points.length'),0);
e.nodes.mode.value='positive';e.call('canvas.onclick({clientX:80,clientY:200})');assert.equal(e.call('targets.cash.points[0].label'),1);
const saved=JSON.parse(e.storage.get(key));assert.ok(saved.cash.bbox[0]<saved.cash.bbox[2]);assert.ok(saved.cash.bbox[1]<saved.cash.bbox[3]);
e.nodes.confirmed.checked=true;e.call('save()');assert.equal(JSON.parse(e.downloads.at(-1).blob.text).confirmed,false); // Missing hands cannot become confirmed.
console.log('PASS: restored boxes and roles; drafts always export; JSON fallback; optional negative point; separate absence action; two-click and point drawing; invalid roles and missing hands blocked.');
