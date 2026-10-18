// Synthetic UI check: draft export remains usable without confirmation.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync(process.argv[2],'utf8'),nodes={},downloads=[];let scope;
function make(){return {value:'',checked:false,textContent:'',children:[],append(...items){this.children.push(...items)},appendChild(item){this.children.push(item)},click(){downloads.push({name:this.download,text:scope.blob.text})}}}
function node(id){return nodes[id]??=make()}
const payload={schema_version:'document-search-review/1',review_session:'synthetic',protocol_sha256:'test',candidate_manifest_sha256:'test',cards:[{key:'0',source_name:'synthetic',source_video_sha256:'a',timestamp_sec:1,image:'data:',proposals:[{bbox:[.2,.2,.4,.4]}]}]};
scope={document:{getElementById:id=>{if(!nodes[id]){for(const item of nodes.cards?.children||[])for(const child of item.children||[])if(child.id===id)nodes[id]=child}return node(id)},createElement:make},localStorage:{getItem:()=>null,setItem(){}},Blob:class{constructor(parts){scope.blob={text:parts.join('')}}},URL:{createObjectURL:()=> 'blob:local',revokeObjectURL(){}},setTimeout(){},Date};
vm.createContext(scope);vm.runInContext(html.match(/<script>([\s\S]*)<\/script>/)[1].replace('__PAYLOAD__',JSON.stringify(payload)),scope);
const run=s=>vm.runInContext(s,scope);run('save()');let data=JSON.parse(downloads.at(-1).text);assert.equal(data.confirmed,false);assert.equal(node('json').value,downloads.at(-1).text);
run("for(const item of payload.cards) document.getElementById('answer-'+item.key).value='none'");node('confirmed').checked=true;run('save()');data=JSON.parse(downloads.at(-1).text);assert.equal(data.confirmed,true);assert.equal(data.reviews[0].human_selection,'none');assert.equal(data.absence_detection_validated,false);assert.equal(data.approved_for_rule_engine,false);assert(!('image' in data.reviews[0]));
console.log('PASS: draft and confirmed exports, negative feedback, JSON fallback, source manifest; no image export or absence verdict.');
