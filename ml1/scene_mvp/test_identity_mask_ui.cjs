// Run report JS locally without displaying or emitting any images.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const page=fs.readFileSync(process.argv[2],'utf8'),nodes={},downloads=[];
function node(id){return nodes[id]??={value:'',checked:false,src:'',textContent:''}}
const scope={document:{getElementById:node,createElement:()=>({click(){downloads.push({name:this.download,text:scope.blob.text})}})},Blob:class{constructor(parts){this.text=parts.join('');scope.blob=this}},URL:{createObjectURL:()=> 'blob:local',revokeObjectURL(){}},setTimeout(){},setInterval(){},clearInterval(){},Date};
vm.createContext(scope);vm.runInContext(page.match(/<script>([\s\S]*)<\/script>/)[1],scope);const run=code=>vm.runInContext(code,scope);
run('save()');let d=JSON.parse(downloads.at(-1).text);assert.equal(d.confirmed,false);assert.equal(nodes.json.value,downloads.at(-1).text);
node('answer').value='correct_on_reviewed_frames';node('confirmed').checked=true;run('save()');d=JSON.parse(downloads.at(-1).text);assert.equal(d.confirmed,true);assert.equal(d.review_kind,'identity_mask_review');assert.equal(d.review_scope,'user_reviewed_sampled_frames_only');assert.equal(d.approved_for_rule_engine,false);
nodes.answer.value='incorrect_on_reviewed_frames';run('save()');d=JSON.parse(downloads.at(-1).text);assert.equal(d.human_mask_review,'incorrect_on_reviewed_frames');assert.equal(d.confirmed,true);
console.log('PASS: draft and confirmed exports, JSON fallback, source scope and negative human feedback preserved.');
