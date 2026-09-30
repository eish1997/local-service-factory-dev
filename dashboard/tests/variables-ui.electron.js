/* Real Electron + IPC + Python. External save targets an isolated test catalog. */
const { app, BrowserWindow, ipcMain } = require('electron');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { spawnSync } = require('child_process');
const assert = require('node:assert/strict');
const root=path.resolve(__dirname,'../..');
const packaged=process.argv.includes('--packaged');
const base=packaged?'../dist-shared-tasks/win-unpacked/resources/app.asar':'..';
const { runVariables }=require(`${base}/variables`);
const fixture=fs.mkdtempSync(path.join(root,'.runtime/variable-readonly-ui-'));
const fixtureProject=path.join(fixture,'road_rescue');fs.mkdirSync(fixtureProject);
fs.copyFileSync(path.join(root,'projects/road_rescue/variable_catalog.json'),path.join(fixtureProject,'variable_catalog.json'));
fs.copyFileSync(path.join(root,'projects/road_rescue/project.json'),path.join(fixtureProject,'project.json'));
// Only this test process redirects variable reads/writes to the isolated road catalog.
fs.writeFileSync(path.join(fixture,'factory.py'),`import sys\nfrom pathlib import Path\nsys.path.insert(0,${JSON.stringify(root)})\nfrom tools import variable_catalog as vc\noriginal=vc.project_dir\nvc.project_dir=lambda category: Path(__file__).parent/'road_rescue' if category=='road_rescue' else original(category)\nimport factory\nfactory.main()\n`);
const hash=file=>crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const catalogs=fs.readdirSync(path.join(root,'projects')).map(p=>path.join(root,'projects',p,'variable_catalog.json')).filter(p=>fs.existsSync(p));
const before=catalogs.map(hash);
process.env.ROAD_RESCUE_FACTORY_HOME=root;
process.env.ROAD_RESCUE_DASHBOARD_TEST='1';
require(`${base}/main`);
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function run(){
  await app.whenReady();const win=BrowserWindow.getAllWindows()[0];
  ipcMain.removeHandler('variables:request');ipcMain.handle('variables:request',(_,request)=>runVariables(fixture,request));
  const js=code=>win.webContents.executeJavaScript(code);
  async function until(code){for(let n=0;n<150;n++){if(await js(code))return;await pause(100);}throw new Error(`UI timeout: ${code}: ${await js('document.getElementById("variable-status")?.textContent')}`);}
  await until('Boolean(document.getElementById("variables-page"))');
  await js('document.getElementById("variables-page").click()');
  await until('document.querySelectorAll("#variable-project option").length===8 && document.querySelectorAll("#variable-types button").length>2');
  assert.equal(await js('document.getElementById("variables-page").textContent'),'变量一览');
  assert.equal(await js('document.querySelectorAll("#variable-content input,#variable-content textarea,#variable-save,#variable-preview,#variable-add-type,#variable-history").length'),0);
  for(const operation of ['save','restore','preview','validate','initialize']){
    assert.equal(await js(`window.roadRescue.variables({operation:${JSON.stringify(operation)},category:'road_rescue'}).then(()=>false,()=>true)`),true);
  }
  assert.equal(await js(`window.roadRescue.variables({operation:'list',category:'road_rescue',payload:{catalog:{}}}).then(()=>false,()=>true)`),true);
  await js(`document.getElementById('variable-role').value='detail';document.getElementById('variable-role').dispatchEvent(new Event('change'))`);
  const road=await runVariables(fixture,{operation:'list',category:'road_rescue'});
  assert.equal(await js(`document.querySelectorAll('#variable-types button').length`),road.dimensions.filter(d=>d.roles.includes('detail')).length+1);
  await js(`document.getElementById('variable-role').value='';document.getElementById('variable-role').dispatchEvent(new Event('change'));document.getElementById('variable-filter').value='legacy';document.getElementById('variable-filter').dispatchEvent(new Event('change'))`);
  assert.equal(await js(`document.querySelectorAll('#variable-types button').length`),road.dimensions.filter(d=>d.status==='legacy').length+1);
  await js(`document.getElementById('variable-filter').value='';document.getElementById('variable-filter').dispatchEvent(new Event('change'))`);
  const projects=await runVariables(fixture,{operation:'projects'});
  for(const p of projects){
    await js(`document.getElementById('variable-project').value=${JSON.stringify(p.id)};document.getElementById('variable-project').dispatchEvent(new Event('change'))`);
    const data=await runVariables(fixture,{operation:'list',category:p.id});
    await until(`document.querySelectorAll('#variable-types button').length===${data.dimensions.length+1} && document.getElementById('variable-status').textContent.includes('只读展示')`);
  }
  await js(`document.getElementById('variable-project').value='road_rescue';document.getElementById('variable-project').dispatchEvent(new Event('change'))`);
  await until(`document.querySelectorAll('#variable-types button').length>20`);
  await js(`const search=document.getElementById('variable-search');search.value='门面环境';search.dispatchEvent(new Event('input'));document.querySelector('#variable-types button').click();document.querySelector('#variable-content details').open=true;document.querySelector('main').scrollTop=160`);
  const scroll=await js("document.querySelector('main').scrollTop");
  const data=JSON.parse(fs.readFileSync(path.join(fixtureProject,'variable_catalog.json'),'utf8'));
  const d=data.dimensions.find(d=>d.name==='门面环境');d.description='Agent 已更新：只读页面自动刷新测试';
  const result=spawnSync('python',['-X','utf8',path.join(fixture,'factory.py'),'variables','save','--category','road_rescue'],{input:JSON.stringify({catalog:data,expected_revision:data.revision}),encoding:'utf8',windowsHide:true,cwd:root});
  assert.equal(result.status,0,result.stdout+result.stderr);
  await until(`document.getElementById('variable-content').textContent.includes('Agent 已更新：只读页面自动刷新测试')`);
  assert.equal(await js('document.getElementById("variable-search").value'),'门面环境');
  assert.equal(await js('document.querySelector("#variable-content details").open'),true);
  assert.ok(Math.abs(await js("document.querySelector('main').scrollTop")-scroll)<3);
  await js('document.getElementById("gallery-page").click()');
  assert.equal(await js('document.getElementById("gallery-panel").hidden'),false);
  await until('document.querySelectorAll("#gallery .thumb").length>0');
  await js('document.querySelector("#gallery .thumb").click()');
  for(let i=0;i<50&&BrowserWindow.getAllWindows().length<2;i++)await pause(100);
  const viewer=BrowserWindow.getAllWindows().find(w=>w!==win);assert.ok(viewer);
  for(let i=0;i<80;i++){if(await viewer.webContents.executeJavaScript('Boolean(document.getElementById("image")?.naturalWidth)'))break;await pause(100);}
  assert.ok(await viewer.webContents.executeJavaScript('document.getElementById("image").naturalWidth>0'));
  await viewer.webContents.executeJavaScript('document.getElementById("next").click()');
  await pause(200);assert.ok(await viewer.webContents.executeJavaScript('document.getElementById("counter").textContent.startsWith("2 /")'));
  await viewer.webContents.executeJavaScript('document.getElementById("close").click()');
  await js('document.getElementById("variables-page").click()');
  await pause(700);
  await js('document.getElementById("compact-toggle").click()');
  await until('document.body.classList.contains("compact")');
  await js('document.getElementById("compact-toggle").click()');
  await until('!document.body.classList.contains("compact")');
  assert.equal(await js('document.querySelector("#variable-content details").open'),true);
  // Capture unmodified real project data for visual review.
  ipcMain.removeHandler('variables:request');ipcMain.handle('variables:request',(_,request)=>runVariables(root,request));
  await js('document.getElementById("variable-reload").click()');
  await until(`!document.getElementById('variable-content').textContent.includes('Agent 已更新：只读页面自动刷新测试')`);
  await js("document.querySelector('main').scrollTop=0");
  await pause(150);
  fs.writeFileSync(path.join(root,'.runtime/variable-readonly-ui.png'),(await win.webContents.capturePage()).toPNG());
  assert.deepEqual(catalogs.map(hash),before);
  fs.writeFileSync(path.join(root,'.runtime/variable-readonly-ui-result.json'),JSON.stringify({ok:true,packaged,businesses:8,readOnlyIPC:true,externalAgentSaveReflected:true,filtersExpansionScrollPreserved:true,compactMode:true,imageViewer:true,roleAndStatusFilters:true,productionCatalogsUnchanged:true}));
  app.exit(0);
}
run().catch(error=>{fs.writeFileSync(path.join(root,'.runtime/variable-readonly-ui-result.json'),JSON.stringify({ok:false,error:error.stack}));app.exit(1);});
