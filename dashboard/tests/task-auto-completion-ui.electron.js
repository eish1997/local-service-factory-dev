/* Actual IPC, renderer and isolated workers; simulated image API only. */
const {app,BrowserWindow}=require('electron');
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict'),{spawnSync}=require('child_process');
const root=path.resolve(__dirname,'../..'),fixture=fs.mkdtempSync(path.join(root,'.runtime/task-auto-ui-'));
const python=process.env.ROAD_RESCUE_PYTHON||'python';
const failureMode=process.env.ROAD_RESCUE_AUTO_UI_FAILURE==='1';
fs.writeFileSync(path.join(fixture,'factory.py'),String.raw`import sys,io,json,time,collections
from pathlib import Path
sys.path.insert(0,${JSON.stringify(root)})
from tools import task_library as lib,variable_catalog as vc,task_worker as worker
from PIL import Image
configs={p['id']:lib.business_config(p['id']) for p in vc.projects()}
lib.ROOT=Path(__file__).parent
lib.business_config=lambda c:configs[c]
lib.api_config=lambda:{'model':'offline-test','api_size':'1024x1536','quality':'medium','output_format':'png'}
lib.readiness=lambda *a:([],[1])
def payload():
 out=io.BytesIO();Image.new('RGB',(1024,1536),'gray').save(out,format='PNG');return out.getvalue()
def render(category,batch,data,rows,snapshot):
 for row in rows:
  for pos in {u['delivery_position'] for u in row['units']}:
   units=[u for u in row['units'] if u['delivery_position']==pos]
   if not all(worker.raw_valid(category,batch,row['group'],u) for u in units):continue
   kind='triptych' if units[0]['kind']=='triptych_panel' else units[0]['kind']
   target=lib.delivery_path(category,batch,row['group'],pos,kind);target.parent.mkdir(parents=True,exist_ok=True)
   Image.new('RGB',worker.images.parse_size(units[0]['final_size']),'blue').save(target)
   lib.write(target.with_suffix('.validation.json'),{'status':'pending','service_role':units[0].get('service_role'),'postprocess_record':{'sources':[str(lib.unit_raw(category,batch,row['group'],u)) for u in units]}})
if len(sys.argv)>1 and sys.argv[1]=='fixture':
 b=lib.assemble({'category':'truck_rescue','count':1,'phone':'{已确认电话}','seed':1401})
 print(json.dumps({'category':b['category'],'batch':b['id']}));raise SystemExit(0)
if sys.argv[1:2]==['stock-fixture']:
 from tools import raw_library as stock
 b=lib.batches('truck_rescue')[0];u=lib.selected(lib.batch_dir('truck_rescue',b['id']),b,[1])[0]['units'][0]
 a=stock.register('truck_rescue',b['id'],1,u)
 for number in range(100):
  clone=dict(a);clone['id']=lib.digest({'fixture':a['id'],'page':number});lib.write(stock.index_file('truck_rescue',clone['id']),clone)
 print('STOCK_FIXTURE_OK');raise SystemExit(0)
if sys.argv[1:2]==['revision-fixture']:
 from tools.task_actions import prepare_replacement
 b=lib.batches('truck_rescue')[0]
 child=prepare_replacement({'category':'truck_rescue','batch':b['id'],'group':1,'position':3,'request_id':'offline-title-revision'})
 req={'category':'truck_rescue','batch':child['id'],'groups':[1],'auto_complete':False}
 lib.launch=lambda *a:99999999
 p=lib.plan(req);t=lib.start({**req,'plan_sha256':p['plan_sha256'],'request_id':'offline-title-start','authorization':'execute_selected_groups'})
 code=worker.run('truck_rescue',child['id'],t['id'],generate=lambda *a:payload(),clients=[(1,object())],render=render)
 if code:raise RuntimeError('offline revision failed')
 print('REVISION_FIXTURE_OK');raise SystemExit(0)
import factory
if len(sys.argv)>2 and sys.argv[2]=='worker':
 args=factory.build_parser().parse_args();p,b=lib.load_batch(args.category,args.batch);units=lib.selected(p,b,[1])[0]['units'];bad=units[3]['prompt'];calls=collections.Counter()
 class Blocked(Exception):pass
 def generate(c,cfg,prompt):
  calls[prompt]+=1;time.sleep(3 if ${failureMode?'True':'False'} and prompt==bad else 2 if prompt==bad else .15)
  if ${failureMode?'True':'False'} and prompt==bad:
   error=Blocked('provider-secret-response');error.status_code=450+calls[prompt];raise error
  if prompt==bad and calls[prompt]<6:raise TimeoutError('timed out')
  if prompt==bad and calls[prompt]==6:
   deadline=time.monotonic()+30
   while not (lib.ROOT/'board-observed-six').exists():
    if time.monotonic()>deadline:raise RuntimeError('fixture did not observe the running board')
    time.sleep(.05)
  return payload()
 raise SystemExit(worker.run(args.category,args.batch,args.task,generate=generate,clients=[(1,object())],render=render))
factory.main()
`);
const prepared=spawnSync(python,['-X','utf8',path.join(fixture,'factory.py'),'fixture'],{encoding:'utf8',windowsHide:true});
assert.equal(prepared.status,0,prepared.stdout+prepared.stderr);const target=JSON.parse(prepared.stdout);
fs.mkdirSync(path.join(fixture,'projects'),{recursive:true});fs.mkdirSync(path.join(fixture,'output'),{recursive:true});fs.copyFileSync(path.join(root,'projects/registry.json'),path.join(fixture,'projects/registry.json'));
process.env.ROAD_RESCUE_FACTORY_HOME=fixture;process.env.ROAD_RESCUE_DASHBOARD_TEST='1';process.env.ROAD_RESCUE_PYTHON=python;
delete process.env.FACTORY_ENGINE_HOME;delete process.env.FACTORY_DATA_HOME;
require('../main');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function run(){
 await app.whenReady();const win=BrowserWindow.getAllWindows()[0],pageErrors=[];
 // The isolated test may stay hidden. Electron's disabled background throttling
 // keeps Page Visibility visible so this fixture can verify the board's real
 // polling path without foregrounding a window or altering production code.
 win.webContents.setBackgroundThrottling(false);
 win.webContents.on('console-message',(_e,_l,message)=>{if(message.includes('Uncaught'))pageErrors.push(message);});
 const js=async s=>{
  fs.writeFileSync(path.join(fixture,'verification-progress.json'),JSON.stringify({at:new Date().toISOString(),stage:'renderer',code:s.slice(0,180)}));
  let timer;try{return await Promise.race([win.webContents.executeJavaScript(s),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('renderer observation stalled: '+s.slice(0,180))),15000);})]);}finally{clearTimeout(timer);}
 };
 async function until(code){for(let i=0;i<300;i++){if(await js(code))return;await pause(100);}throw Error('timeout '+code);}
 await until('document.querySelectorAll("#project-tabs button").length===8');
 assert.equal(await js('document.hidden'),false);
 await js(`document.querySelector('#project-tabs [data-project="truck_rescue"]').click()`);
 await until('document.querySelectorAll(".task-card").length===1');
 assert.equal(await js('document.getElementById("task-reuse-rate").value'), '');
 await js('document.getElementById("queue-open").click()');
 await until('document.querySelector(".production-dialog[open] .queue-column h3").textContent==="待开始 7"');
 assert.equal(await js('document.querySelectorAll(".production-dialog[open] .raw-card").length'),7);
 assert.equal(await js('Array.from(document.querySelectorAll(".production-dialog[open] .raw-card strong")).filter(n=>n.textContent.includes("三拼来源")).length'),3);
 await js('document.querySelector(".production-dialog[open]").close()');
 await js('document.getElementById("task-select-all").click();document.getElementById("task-plan").click()');
 await until('document.getElementById("task-plan-info").hidden===false');
 const planText=await js('document.getElementById("task-plan-info").textContent');
 for(const text of ['整批最高请求 42 次','额度内持续补齐'])assert.ok(planText.includes(text),planText);
 assert.equal(planText.includes('轮'),false);
 await js('document.getElementById("task-request-cap").value="43";document.getElementById("task-request-cap").dispatchEvent(new Event("input"))');
 assert.equal(await js('document.getElementById("task-start").disabled'),true);
 await js('document.getElementById("task-request-cap").value="42";document.getElementById("task-request-cap").dispatchEvent(new Event("input"));document.getElementById("task-plan").click()');
 await until('document.getElementById("task-start").disabled===false');
 win.setSize(820,750);await pause(150);assert.equal(await js('innerWidth'),820);assert.equal(await js('document.documentElement.scrollWidth<=innerWidth'),true);
 fs.writeFileSync(path.join(root,'.runtime/task-auto-plan-ui.png'),(await win.webContents.capturePage()).toPNG());
 await js('document.getElementById("task-start").click()');
 await until('document.querySelectorAll(".task-job").length===1');
 const tasksDir=path.join(fixture,'prompts/library',target.category,target.batch,'tasks');
 let taskfile;
 for(let i=0;i<200;i++){
  const ids=fs.existsSync(tasksDir)?fs.readdirSync(tasksDir):[];if(ids.length)taskfile=path.join(tasksDir,ids[0],'task.json');
  if(taskfile&&JSON.parse(fs.readFileSync(taskfile,'utf8')).status===(failureMode?'completed_with_errors':'recovering'))break;
  await pause(100);
 }
 assert.ok(taskfile);assert.equal(JSON.parse(fs.readFileSync(taskfile,'utf8')).status,failureMode?'completed_with_errors':'recovering');
 await js('document.getElementById("task-refresh").click()');
 if(!failureMode){
 await until('document.querySelector(".task-job-body").textContent.includes("自动补齐中")');
 await until('document.getElementById("title-state").textContent==="自动补齐中"');
 assert.equal(await js('document.querySelector(".task-job-body>span").textContent.includes("不会重复付费生成")'),false);
 assert.equal(await js('document.getElementById("task-pause").disabled'),false);
 assert.equal(await js('document.getElementById("task-resume").disabled'),true);
 assert.equal(await js('document.getElementById("task-target").options.length'),1);
 assert.equal(await js('document.querySelectorAll(".task-job").length'),1);
 }
 await js('document.getElementById("queue-open").click()');
 if(!failureMode){
  await until('Array.from(document.querySelectorAll(".production-dialog[open] .queue-column h3")).some(n=>n.textContent==="已完成 6")');
  fs.writeFileSync(path.join(fixture,'board-observed-six'),'verified');
 }
 await until(`Array.from(document.querySelectorAll(".production-dialog[open] .queue-column h3")).some(n=>n.textContent===${JSON.stringify(failureMode?'已完成 6':'已完成 7')})`);
 if(failureMode){
  await until('Array.from(document.querySelectorAll(".production-dialog[open] .queue-column h3")).some(n=>n.textContent==="进行中 1")');
  assert.equal(await js('Array.from(document.querySelectorAll(".production-dialog[open] .queue-column h3")).some(n=>n.textContent==="待开始 0")'),true);
 }
 assert.equal(await js('document.querySelectorAll(".production-dialog[open] .raw-card").length'),7);
 assert.equal(await js('document.documentElement.scrollWidth<=innerWidth'),true);
 fs.writeFileSync(path.join(root,'.runtime/task-raw-board-ui.png'),(await win.webContents.capturePage()).toPNG());
 await js('document.querySelector(".production-dialog[open]").close()');
 assert.equal(await js('document.documentElement.scrollWidth<=innerWidth'),true);
 fs.writeFileSync(path.join(root,'.runtime/task-auto-running-ui.png'),(await win.webContents.capturePage()).toPNG());
 if(failureMode){
  for(let i=0;i<300;i++){if(JSON.parse(fs.readFileSync(taskfile,'utf8')).status==='completed_with_errors')break;await pause(100);}
  const state=JSON.parse(fs.readFileSync(taskfile,'utf8'));
  assert.equal(state.status,'completed_with_errors');assert.equal(state.requests_used,7);assert.equal(state.auto_recovery.requests_used,0);assert.equal(state.completed_units,6);
  await js('document.getElementById("task-refresh").click()');
  await until('document.querySelector(".task-job").dataset.status==="completed_with_errors"');
  await until('document.getElementById("title-progress").textContent.startsWith("6/7")&&document.getElementById("title-progress").textContent.includes("请求7/42")');
  await until('document.getElementById("title-state").textContent==="执行已停止 · 原图待完成"');
  await js('document.querySelector(".task-recovery").open=true');
  const text=await js('document.querySelector(".task-recovery").textContent');
  assert.equal(text.includes('第 2 轮补缺'),false);assert.ok(text.includes('HTTP 451'),text);assert.equal(text.includes('HTTP 453'),false);assert.equal(text.includes('provider-secret-response'),false);
  assert.equal(await js('document.getElementById("task-resume").disabled'),true);
  assert.equal(await js('document.getElementById("task-target").options.length'),1);
  assert.equal(await js('document.documentElement.scrollWidth<=innerWidth'),true);assert.deepEqual(pageErrors,[]);
  await js('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
  assert.equal(await js('document.querySelector(".task-recovery").open'),true);
  fs.writeFileSync(path.join(root,'.runtime/task-auto-failure-ui.png'),(await win.webContents.capturePage()).toPNG());
  fs.writeFileSync(path.join(root,'.runtime/task-auto-failure-ui-result.json'),JSON.stringify({ok:true,fixture,completed:6,failed:1,totalRequests:7,totalMaxRequests:42,latestFailureHTTP:451,latestFailureRound:0,stableRejectionNotRepeated:true,providerExceptionHidden:true,visibleParentTasks:1,narrowWidth:820,pageErrors,actualPaidRequests:0}));app.exit(0);return;
 }
 for(let i=0;i<300;i++){if(JSON.parse(fs.readFileSync(taskfile,'utf8')).status==='completed')break;await pause(100);}
 const state=JSON.parse(fs.readFileSync(taskfile,'utf8'));
 assert.equal(state.status,'completed');assert.equal(state.completed_units,7);assert.equal(state.requests_used,8);assert.equal(state.auto_recovery.requests_used,4);assert.equal(Object.keys(state.auto_recovery.children).length,2);
 assert.equal(state.auto_complete.mode,'continuous');assert.equal(state.auto_complete.total_max_requests,42);
 const sharedBudget=JSON.parse(fs.readFileSync(path.join(path.dirname(taskfile),'budget.json'),'utf8'));
 assert.equal(sharedBudget.reservations.length,12);assert.equal(sharedBudget.maximum,42);
 const jobs=require('../tasks').readLibraryJobs(fixture);assert.equal(jobs.length,1);assert.equal(jobs[0].requests_used,12);assert.equal(jobs[0].request_budget,42);assert.equal(jobs[0].failed,0);
 await js('document.getElementById("task-refresh").click()');
 await until('document.querySelector(".task-job-body").textContent.includes("请求 12/42")');
 await until('document.getElementById("title-progress").textContent.startsWith("7/7")');
 await until('document.querySelector(".task-job").dataset.status==="completed"');
 assert.equal(await js('document.querySelector(".task-recovery")===null'),true);
 assert.equal(await js('document.querySelectorAll(".task-image img").length'),5);
 assert.equal(await js('document.getElementById("task-target").options.length'),1);
 assert.equal(await js('document.querySelectorAll(".task-job").length'),1);
 await js('document.getElementById("queue-open").click()');
 await until('document.querySelector(".production-dialog[open] .queue-column:nth-child(3) h3").textContent==="已完成 7"');
 await js('document.querySelectorAll(".production-dialog[open] .queue-column:nth-child(3) details")[3].open=true');
 await until('document.querySelectorAll(".production-dialog[open] .queue-column:nth-child(3) details")[3].textContent.includes("本素材累计请求 6")');
 const rawDetail=await js('document.querySelectorAll(".production-dialog[open] .queue-column:nth-child(3) details")[3].textContent');
 assert.ok(rawDetail.includes('补齐尝试 1'),rawDetail);assert.ok(rawDetail.includes('补齐尝试 2'),rawDetail);
 assert.ok(rawDetail.includes('整批共享额度'),rawDetail);
 assert.ok(rawDetail.includes('本素材累计请求 6 次'),rawDetail);assert.equal(rawDetail.includes('provider-secret-response'),false);
 await js('document.querySelectorAll(".production-dialog[open] .queue-column:nth-child(3) .raw-card")[3].scrollIntoView({block:"start"})');
 await js('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');
 fs.writeFileSync(path.join(root,'.runtime/task-raw-details-ui.png'),(await win.webContents.capturePage()).toPNG());
 await js('document.querySelector(".production-dialog[open]").close()');
 const revisionFixture=spawnSync(python,['-X','utf8',path.join(fixture,'factory.py'),'revision-fixture'],{encoding:'utf8',windowsHide:true});assert.equal(revisionFixture.status,0,revisionFixture.stdout+revisionFixture.stderr);
 await js('document.getElementById("task-refresh").click()');
 await until('document.getElementById("title-progress").textContent.startsWith("7/7")&&document.getElementById("title-progress").textContent.includes("请求13/44")');
 assert.equal(await js('document.getElementById("title-progress").textContent.startsWith("1/1")'),false);
 await until('document.querySelector(".production-metrics").textContent.includes("库复用")&&document.querySelector(".production-metrics").textContent.includes("断点保留")');
 const seeded=spawnSync(python,['-X','utf8',path.join(fixture,'factory.py'),'stock-fixture'],{encoding:'utf8',windowsHide:true});assert.equal(seeded.status,0,seeded.stdout+seeded.stderr);
 await js('document.getElementById("raw-library-open").click()');
 await until('document.querySelectorAll(".production-dialog[open] .raw-stock article").length===100');
 await js('Array.from(document.querySelectorAll(".production-dialog[open] button")).find(b=>b.textContent==="加载更多原图").click()');
 await until('document.querySelectorAll(".production-dialog[open] .raw-stock article").length===101');
 await js('document.querySelector(".production-dialog[open] .raw-stock img").click()');
 await until('document.querySelector(".raw-preview-dialog[open] img")?.naturalWidth===1024');
 assert.equal(await js('document.documentElement.scrollWidth<=innerWidth'),true);
 await js('document.querySelector(".raw-preview-dialog[open]").close()');
 fs.writeFileSync(path.join(root,'.runtime/task-raw-library-ui.png'),(await win.webContents.capturePage()).toPNG());
 await js('document.querySelector(".production-dialog[open]").close()');
 assert.equal(await js('document.documentElement.scrollWidth<=innerWidth'),true);
 assert.deepEqual(pageErrors,[]);
 fs.writeFileSync(path.join(root,'.runtime/task-auto-completed-ui.png'),(await win.webContents.capturePage()).toPNG());
 fs.writeFileSync(path.join(root,'.runtime/task-auto-completion-ui-result.json'),JSON.stringify({ok:true,fixture,mainMaxRequests:14,completionMode:"continuous",repairLicences:2,sharedBudgetValidated:true,repairMaxRequests:28,totalMaxRequests:42,mainRequests:8,repairRequests:4,totalRequests:12,completed:7,failed:0,visibleParentTasks:1,narrowWidth:820,stockPaging:101,stockOriginalPreview:true,cardDetailsSharedIPC:true,automaticBoardPolling:true,boardCompletionTransition:[6,7],testBackgroundThrottling:false,testWindowVisible:win.isVisible(),singleRevisionKeepsCanonicalTotal:true,afterRevisionRequests:13,afterRevisionMaximum:44,pageErrors,actualPaidRequests:0}));
 app.exit(0);
}
run().catch(async e=>{let diagnostic;try{diagnostic=await Promise.race([BrowserWindow.getAllWindows()[0].webContents.executeJavaScript(`({hidden:document.hidden,context:dashboardTaskContext(),title:document.getElementById('title-progress').textContent,dialogs:Array.from(document.querySelectorAll('dialog[open]')).map(d=>({title:d.querySelector('h2')?.textContent,summary:d.querySelector('p')?.textContent,columns:Array.from(d.querySelectorAll('.queue-column h3')).map(n=>n.textContent)}))})`),pause(3000).then(()=>({unavailable:'renderer observation timed out'}))]);}catch{}fs.writeFileSync(path.join(root,`.runtime/task-auto-${failureMode?'failure':'completion'}-ui-result.json`),JSON.stringify({ok:false,error:e.stack,fixture,diagnostic}));app.exit(1);});
