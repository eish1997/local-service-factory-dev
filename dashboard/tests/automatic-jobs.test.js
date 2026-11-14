const assert=require('node:assert/strict'),test=require('node:test'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {readLibraryJobs}=require('../tasks'),{inspectJob}=require('../monitor');
test('automatic children stay hidden while their licence counts and live progress belong to parent',()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'factory-auto-job-'));
 const category='truck_rescue',batch='batch_fixture',tid='parent',child='batch_revision_auto_'+ 'a'.repeat(28),childId='auto-'+ 'a'.repeat(28);
 const home=path.join(root,'prompts/library',category),parentFile=path.join(home,batch,'tasks',tid,'task.json');
 const write=(file,value)=>{fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,JSON.stringify(value));};
 const task={id:tid,category,batch,pid:123,status:'recovering',created_at:'2026-10-04T00:00:00Z',updated_at:'2026-10-04T00:00:00Z',groups:[1],slots:[1],config:{model:'offline'},requests_used:8,max_requests:14,total_units:7,completed_units:6,auto_complete:{enabled:true,max_requests:28},resume_summary:{blocked_count:1},auto_recovery:{children:{[childId]:{batch:child,round:1,group:1,position:2}}}};
 try{
  write(parentFile,task);
  write(path.join(home,child,'batch.json'),{automatic_repair_parent:{batch,task:tid}});
  write(path.join(home,child,'tasks',childId,'license.json'),{requests_used:4});
  write(path.join(home,child,'tasks',childId,'task.json'),{id:childId,category,batch:child,pid:123,status:'running',updated_at:'2026-10-04T00:09:30Z'});
  let jobs=readLibraryJobs(root);assert.equal(jobs.length,1);assert.equal(jobs[0].requests_used,12);assert.equal(jobs[0].request_budget,42);assert.equal(jobs[0].updated_at,'2026-10-04T00:09:30Z');assert.equal(jobs[0].failed,1);
  assert.equal(inspectJob(jobs[0],root,{nowMs:Date.parse('2026-10-04T00:10:00Z'),probe:()=>true}).health,'live');
  task.status='completed';task.completed_units=7;task.resume_summary.blocked_count=0;write(parentFile,task);
  jobs=readLibraryJobs(root);assert.equal(jobs[0].updated_at,task.updated_at);assert.equal(jobs[0].failed,0);assert.equal(jobs[0].completed,7);
 }finally{assert.equal(path.dirname(path.resolve(root)),path.resolve(os.tmpdir()));assert.ok(path.basename(root).startsWith('factory-auto-job-'));fs.rmSync(root,{recursive:true,force:true});}
});
