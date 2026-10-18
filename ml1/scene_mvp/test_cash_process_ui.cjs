const fs=require('fs'),vm=require('vm'),assert=require('assert');
const nodes=new Map(),downloads=[];let blob;
function node(id){
  if(!nodes.has(id))nodes.set(id,{
    value:'',checked:false,style:{},textContent:'',appendChild(){},
    click(){downloads.push(blob.parts.join(''))},
    getBoundingClientRect(){return {left:0,top:0,width:400,height:800}},
    getContext(){return {clearRect(){},drawImage(){},strokeRect(){},fill(){},beginPath(){},arc(){}}}
  });
  return nodes.get(id)
}
const payload={review_session:'test',protocol_sha256:'p',cases:['X-13','X-14'].map(case_id=>({case_id,name:case_id+'.mov',source_session:'/local/'+case_id,source_video_sha256:case_id==='X-13'?'a'.repeat(64):'b'.repeat(64),duration_sec:3,video_file:case_id+'.mov',frames:[0,1,2].map(timestamp_sec=>({timestamp_sec,width:400,height:800,image:'data:image/jpeg;base64,FAKE'}))}))};
let code=fs.readFileSync(__dirname+'/cash_process_review.html','utf8').match(/<script>([\s\S]*)<\/script>/)[1].replace('__PAYLOAD__',JSON.stringify(payload));
const context=vm.createContext({document:{getElementById:node,createElement:()=>node('new-'+Math.random())},Image:class{set src(v){this.value=v;if(this.onload)this.onload()}},Blob:class{constructor(parts){this.parts=parts}},URL:{createObjectURL(b){blob=b;return 'blob:test'},revokeObjectURL(){}},localStorage:{getItem(){return null},setItem(){}},setTimeout(){},setInterval(){return 1},clearInterval(){}});
const run=code=>vm.runInContext(code,context);run(code);run('save()');let data=JSON.parse(downloads.at(-1));assert.equal(data.confirmed,false);assert.equal(data.cases.length,2);
function box(target){node('target').value=target;node('canvas').onclick({clientX:40,clientY:80});node('canvas').onclick({clientX:140,clientY:200})}
for(let i=0;i<2;i++){run('switchCase('+i+')');run('show(1)');for(const target of ['machine_zone','safe_zone','cash_seed'])box(target);node('confirmed').checked=true;run('stash()')}
run('save()');data=JSON.parse(downloads.at(-1));assert.equal(data.confirmed,true);assert.equal(data.cases[0].cash_anchor_sec,1);assert.deepEqual(data.cases[1].zones.cash_seed,[.1,.1,.35,.25]);assert.equal(data.cases[0].counter_use_observation,'unknown');assert.equal(data.cases[0].cash_storage_observation,'unknown');
run('switchCase(0)');assert.equal(node('confirmed').checked,true);node('target').value='cash_seed';run('clearBox(); save()');data=JSON.parse(downloads.at(-1));assert.equal(data.confirmed,false);assert.equal(data.cases[0].cash_anchor_sec,null);assert.equal(data.cases[1].confirmed,true);
console.log('PASS: draft always saves; two-click normalized boxes; sampled cash anchor; both videos preserved; unknown actions remain unknown; clearing requires new confirmation.');
