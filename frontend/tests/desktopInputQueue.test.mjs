import assert from 'node:assert/strict';
import test from 'node:test';
import { DesktopInputQueue } from '../src/pages/automations/DesktopInputQueue.ts';
const step=(action,text='')=>({id:crypto.randomUUID(),action,text});
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
test('serialized direct input preserves rapid text and navigation order', async()=>{
 const first=deferred(), calls=[],busy=[];const q=new DesktopInputQueue(async s=>{calls.push({...s});if(calls.length===1)await first.promise;return true;},v=>busy.push(v),()=>assert.fail('unexpected rejection'));
 q.enqueue(step('click'));q.enqueue(step('type_text','中'));q.enqueue(step('type_text','文😀'));q.enqueue(step('press_key'));q.enqueue(step('type_text','tail'));
 assert.equal(calls.length,1);let drained=false;const done=q.settled().then(()=>drained=true);await Promise.resolve();assert.equal(drained,false);first.resolve();await done;
 assert.deepEqual(calls.map(x=>[x.action,x.text]),[['click',''],['type_text','中文😀'],['press_key',''],['type_text','tail']]);assert.deepEqual(busy,[true,false]);
});
test('an uncertain/failed input discards later queued writes without retrying', async()=>{
 const first=deferred(), calls=[];const q=new DesktopInputQueue(async s=>{calls.push(s);await first.promise;return false;},()=>{},()=>{});
 q.enqueue(step('click'));q.enqueue(step('type_text','must not type'));first.resolve();await q.settled();assert.equal(calls.length,1);
});
test('clearing an old surface cannot dispatch its pending input', async()=>{
 const first=deferred(),calls=[];const q=new DesktopInputQueue(async s=>{calls.push(s);await first.promise;return true;},()=>{},()=>{});
 q.enqueue(step('click'));q.enqueue(step('type_text','old'));q.clear();first.resolve();await q.settled();assert.equal(calls.length,1);
});
test('pending input is bounded by complete text size and queue length', async()=>{
 const first=deferred(),rejections=[];const q=new DesktopInputQueue(async()=>{await first.promise;return true;},()=>{},s=>rejections.push(s));
 q.enqueue(step('click'));assert.equal(q.enqueue(step('type_text','x'.repeat(8000))),true);assert.equal(q.enqueue(step('type_text','y')),false);q.clear();
 for(let i=0;i<64;i++)assert.equal(q.enqueue(step('press_key')),true);assert.equal(q.enqueue(step('press_key')),false);assert.equal(rejections.length,2);q.clear();first.resolve();await q.settled();
});
test('a thrown transport failure clears pending writes and settles its owner',async()=>{
 const first=deferred(),calls=[],errors=[];const q=new DesktopInputQueue(async s=>{calls.push(s);await first.promise;throw Error('offline');},()=>{},m=>errors.push(m));
 q.enqueue(step('click'));q.enqueue(step('type_text','skip'));first.resolve();await q.settled();assert.equal(calls.length,1);assert.equal(errors.length,1);
});
