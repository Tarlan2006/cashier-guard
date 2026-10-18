// Inspect only JS behavior locally; no image bytes are emitted.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const page=fs.readFileSync(process.argv[2],'utf8'),code=page.match(/<script>([\s\S]*)<\/script>/)[1];
const nodes={},downloads=[];
function element(id){return nodes[id]??={value:'',checked:false,textContent:'',src:''}}
const scope={document:{getElementById:element,createElement:()=>({click(){downloads.push({name:this.download,blob:scope.blob})}})},Blob:class{constructor(parts){this.text=parts.join('');scope.blob=this}},URL:{createObjectURL:()=> 'blob:local',revokeObjectURL(){}},Date,setTimeout(){},setInterval(){return 1},clearInterval(){}};
vm.createContext(scope);vm.runInContext(code,scope);
const call=c=>vm.runInContext(c,scope),direction=call('payload.direction_mode');
element('confirmed');element('comment');
if(direction){const n=call('review.transfer_candidates.length');for(let i=0;i<n;i++)element('answer-'+i);element('start-sec');element('end-sec');element('manual-direction');element('manual-list')}else for(const k of ['cash','cashier_hand','client_hand'])element('review-'+k);
call('save()');let data=JSON.parse(downloads.at(-1).blob.text);assert.equal(data.confirmed,false);assert.equal(data.approved_for_rule_engine,false);assert.equal(data.sampled_frames_not_all_native_frames,true);assert.equal(nodes.json.value,downloads.at(-1).blob.text);
if(direction){const n=call('review.transfer_candidates.length');for(let i=0;i<n;i++)nodes['answer-'+i].value='no_transfer';nodes['start-sec'].value=String(call('frames[0].time'));nodes['end-sec'].value=String(call('frames[frames.length-1].time'));nodes['manual-direction'].value='client_to_cashier';call('addManual()');assert.equal(call('manual.length'),1);nodes['end-sec'].value='100000';call('addManual()');assert.equal(call('manual.length'),1)}else for(const k of ['cash','cashier_hand','client_hand'])nodes['review-'+k].value='correct_on_reviewed_frames';
nodes.confirmed.checked=true;call('save()');data=JSON.parse(downloads.at(-1).blob.text);assert.equal(data.confirmed,true);assert.equal(data.review_scope,direction?'sampled_timeline_human_windows_and_candidate_intervals':'user_reviewed_frames_only');
if(direction){assert.ok(data.human_event_reviews.every(e=>e.human_direction==='no_transfer'));assert.equal(data.human_additional_event_reviews[0].human_direction,'client_to_cashier');assert.equal(data.human_additional_event_reviews[0].frame_accurate_boundaries,false)}
assert.ok(data.visited_times_by_view.cash.length>=1);assert.equal(data.visited_times_by_view.client_hand.length,0); // No claim that all masks have been watched.
console.log('PASS: money review draft export, JSON fallback, limited scope, independent human answers and visited-view metadata.');
