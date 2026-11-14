/* Actual creation form and shared IPC; private fixture, no API dispatch. */
const {app,BrowserWindow}=require('electron');
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict'),{spawnSync}=require('child_process');
const root=path.resolve(__dirname,'../..'),fixture=fs.mkdtempSync(path.join(root,'.runtime/batch-reuse-ui-'));
const resultPath=path.join(fixture,'result.json'),python=process.env.ROAD_RESCUE_PYTHON||'python',started=new Date().toISOString();
fs.writeFileSync(path.join(fixture,'factory.py'),String.raw`import sys,json
from pathlib import Path
sys.path.insert(0,${JSON.stringify(root)})
from tools import task_library as lib,variable_catalog as vc
configs={p['id']:lib.business_config(p['id']) for p in vc.projects()}
lib.ROOT=Path(__file__).parent
lib.business_config=lambda category:configs[category]
lib.api_config=lambda:{'model':'offline-form-test','api_size':'1024x1536','quality':'medium','output_format':'png'}
lib.readiness=lambda *args:([],[1])
if sys.argv[1:2]==['stock-fixture']:
 from PIL import Image
 from tools import raw_library as stock
 b=lib.batches('truck_rescue')[0]
 u=next(u for u in lib.selected(lib.batch_dir('truck_rescue',b['id']),b,[1])[0]['units'] if u['kind']=='cover')
 raw=lib.unit_raw('truck_rescue',b['id'],1,u);raw.parent.mkdir(parents=True,exist_ok=True)
 Image.new('RGB',(1024,1536),'gray').save(raw)
 lib.write(raw.with_suffix('.receipt.json'),{'prompt_sha256':u['prompt_sha256'],'raw_sha256':stock.file_hash(raw),'task':'offline-form-fixture','unit':u['id']})
 a=stock.register('truck_rescue',b['id'],1,u)
 stock.qualify({'category':'truck_rescue','asset':a['id'],'eligible':True,'authorization':'confirm_raw_reuse'})
 print('OFFLINE_STOCK_OK');raise SystemExit(0)
if sys.argv[1:3]==['tasks','start'] or sys.argv[1:3]==['tasks','worker']:raise RuntimeError('Fixture forbids generation')
import factory
factory.main()
`);
fs.mkdirSync(path.join(fixture,'projects'),{recursive:true});fs.mkdirSync(path.join(fixture,'output'),{recursive:true});
fs.copyFileSync(path.join(root,'projects/registry.json'),path.join(fixture,'projects/registry.json'));
process.env.ROAD_RESCUE_FACTORY_HOME=fixture;process.env.ROAD_RESCUE_DASHBOARD_TEST='1';process.env.ROAD_RESCUE_PYTHON=python;
delete process.env.FACTORY_ENGINE_HOME;delete process.env.FACTORY_DATA_HOME;require('../main');
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function run(){
 await app.whenReady();const win=BrowserWindow.getAllWindows()[0],errors=[];
 win.webContents.on('console-message',(_e,_l,message)=>{if(message.includes('Uncaught'))errors.push(message);});
 const js=code=>win.webContents.executeJavaScript(code);
 async function until(code){for(let n=0;n<300;n++){if(await js(code))return;await pause(100);}throw Error('timeout '+code);}
 await until('document.querySelectorAll("#project-tabs button").length===8');
 await js(`document.querySelector('#project-tabs [data-project="truck_rescue"]').click()`);
 await until('dashboardTaskContext().category==="truck_rescue"');
 const batches=()=>fs.existsSync(path.join(fixture,'prompts/library/truck_rescue'))?fs.readdirSync(path.join(fixture,'prompts/library/truck_rescue')).filter(name=>name.startsWith('batch_')).length:0;
 const results=[];
 for(const [rate,count,target]of [['',1,0],['0',1,0],['25',2,3],['100',1,7]]){
  await js('document.getElementById("task-new").click()');
  await until('document.querySelectorAll("#task-watermark-lines input").length>0');
  assert.equal(await js('document.getElementById("task-watermark-phone").textContent'),'电话：');
  assert.equal(await js('document.getElementById("task-phone").value'),'');
  assert.equal(await js('document.getElementById("task-reuse-rate").value'),'');
  const previous=batches();
  await js('document.getElementById("task-create-form").dispatchEvent(new Event("submit",{bubbles:true,cancelable:true}))');
  await until('document.getElementById("task-create-error").textContent.includes("有效 11 位手机号")');
  assert.equal(batches(),previous);
  await js(`document.getElementById('task-count').value=${JSON.stringify(String(count))};document.getElementById('task-phone').value='{已确认电话}';document.getElementById('task-reuse-rate').value=${JSON.stringify(rate)};document.getElementById('task-create-form').requestSubmit()`);
  await until(`!document.getElementById('task-create-dialog').open&&document.querySelectorAll('.task-card').length===${count}`);
  const current=await js('dashboardTaskContext().batch'),base=path.join(fixture,'prompts/library/truck_rescue',current);
  const reuse=JSON.parse(fs.readFileSync(path.join(base,'raw-reuse.json'),'utf8'));
  assert.equal(reuse.target,target);assert.equal(reuse.actual,0);assert.equal(reuse.shortfall,target);
  await js('document.getElementById("task-select-all").click();document.getElementById("task-plan").click()');
  await until('document.getElementById("task-plan-info").hidden===false');
  const text=await js('document.getElementById("task-plan-info").textContent');
  assert.ok(text.includes(`全批次复用目标 ${target}，实际 0，库存缺口 ${target}`),text);
  assert.ok(text.includes(`主任务上限 ${count*14} 次`),text);assert.ok(text.includes(`总请求上限 ${count*42} 次`),text);
  assert.ok(text.includes('库复用 0 张'),text);assert.ok(text.includes('保留已有 0 张'),text);
  assert.equal(fs.existsSync(path.join(base,'tasks')),false);assert.equal(batches(),previous+1);
  results.push({rate:rate||'blank',count,rawTargets:count*7,reuseTarget:target,actualReuse:0,shortfall:target,totalRequestCeiling:count*42});
 }
 await js('document.getElementById("task-new").click();document.getElementById("task-phone").value="{已确认电话}";document.getElementById("task-reuse-rate").value="101";document.getElementById("task-create-form").dispatchEvent(new Event("submit",{bubbles:true,cancelable:true}))');
 await until('document.getElementById("task-create-error").textContent.includes("0–100%")');assert.equal(batches(),4);
 await js('document.getElementById("task-create-cancel").click()');
 const seeded=spawnSync(python,['-X','utf8',path.join(fixture,'factory.py'),'stock-fixture'],{encoding:'utf8',windowsHide:true});assert.equal(seeded.status,0,seeded.stdout+seeded.stderr);
 await js('document.getElementById("task-new").click();document.getElementById("task-count").value="2";document.getElementById("task-phone").value="{已确认电话}";document.getElementById("task-reuse-rate").value="10";document.getElementById("task-create-form").requestSubmit()');
 await until('!document.getElementById("task-create-dialog").open&&document.querySelectorAll(".task-card").length===2');
 const partialBatch=await js('dashboardTaskContext().batch'),partialBase=path.join(fixture,'prompts/library/truck_rescue',partialBatch),partialReuse=JSON.parse(fs.readFileSync(path.join(partialBase,'raw-reuse.json'),'utf8'));
 assert.equal(partialReuse.target,1);assert.equal(partialReuse.actual,1);assert.equal(partialReuse.bindings[0].group,1);
 await js('document.querySelectorAll(".task-card input")[1].click();document.getElementById("task-plan").click()');
 await until('document.getElementById("task-plan-info").hidden===false');
 const partialText=await js('document.getElementById("task-plan-info").textContent');
 assert.ok(partialText.includes('本次 1 组'),partialText);assert.ok(partialText.includes('库复用 0 张'),partialText);
 assert.ok(partialText.includes('全批次复用目标 1，实际 1，库存缺口 0'),partialText);assert.ok(partialText.includes('总请求上限 42 次'),partialText);
 assert.equal(fs.existsSync(path.join(partialBase,'tasks')),false);assert.equal(batches(),5);win.setSize(820,750);await pause(100);
 assert.equal(await js('document.documentElement.scrollWidth<=innerWidth'),true);assert.deepEqual(errors,[]);
 fs.writeFileSync(path.join(fixture,'budget.png'),(await win.webContents.capturePage()).toPNG());
 const value={ok:true,fixture,started,finished:new Date().toISOString(),results,partialSelectionWithRealStock:{batchReuse:1,selectedReuse:0,selectedGroups:1,requestCeiling:42},phoneNeverPrefilled:true,emptyPhoneDoesNotAssemble:true,invalidRateDoesNotAssemble:true,narrowWidth:820,pageErrors:errors,actualPaidRequests:0};
 fs.writeFileSync(resultPath,JSON.stringify(value));fs.writeFileSync(path.join(root,'.runtime/queue-loop-07-form-result.json'),JSON.stringify(value));app.exit(0);
}
run().catch(error=>{const result={ok:false,fixture,started,error:error.stack};fs.writeFileSync(resultPath,JSON.stringify(result));fs.writeFileSync(path.join(root,'.runtime/queue-loop-07-form-result.json'),JSON.stringify(result));app.exit(1);});
