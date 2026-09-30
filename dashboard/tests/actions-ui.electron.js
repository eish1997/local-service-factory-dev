const {app,BrowserWindow}=require('electron'),fs=require('fs'),path=require('path'),assert=require('node:assert/strict'),crypto=require('crypto');
const root=path.resolve(__dirname,'../..'),fixture=JSON.parse(fs.readFileSync(path.join(root,'.runtime/shared-tasks-ui-result.json'),'utf8')).fixture;
assert.ok(fixture.startsWith(path.join(root,'.runtime/shared-ui-')));
const originalEnv=crypto.createHash('sha256').update(fs.readFileSync(path.join(root,'.env'))).digest('hex');
process.env.ROAD_RESCUE_FACTORY_HOME=fixture;process.env.ROAD_RESCUE_DASHBOARD_TEST='1';require('../main');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function run(){
 await app.whenReady();const win=BrowserWindow.getAllWindows()[0],js=s=>win.webContents.executeJavaScript(s).catch(e=>{throw Error(s+" : "+e.message);});
 async function until(s){for(let n=0;n<200;n++){if(await js(s))return;await pause(100);}throw Error('timeout '+s);}
 await until('document.querySelectorAll(".project-tab").length===8');
 await js('document.querySelector(".project-tab[data-project=pet_transport]").click()');
 await until('[...document.querySelectorAll(".batch-row")].some(b=>b.textContent.includes("100 组"))');
 await js('[...document.querySelectorAll(".batch-row")].find(b=>b.textContent.includes("100 组")).click()');await until('document.querySelectorAll(".task-card").length===100');
 async function context(selector,text){await js(`document.querySelector(${JSON.stringify(selector)}).dispatchEvent(new MouseEvent('contextmenu',{bubbles:true,clientX:450,clientY:300}));[...document.querySelectorAll('.context-menu button')].find(b=>b.textContent===${JSON.stringify(text)}).click()`);}
 await context('.task-card[data-group="6"] .task-image[data-position="1"]','删除图片');
 await js('document.querySelector(".action-dialog .danger-action").click()');await until(`document.querySelectorAll('.task-card[data-group="6"] .task-image').length===5`);
 await context('.task-card[data-group="6"] .task-card-head','删除组');await js('document.querySelector(".action-dialog .danger-action").click()');await until('document.querySelectorAll(".task-card").length===99');
 await context('.task-card[data-group="4"] .task-image[data-position="1"]','重新组装并生成此图');await until('document.querySelector(".action-dialog pre")!==null');
 assert.ok(await js('document.querySelector(".action-dialog").textContent.includes("请求上限 2")'));await js('document.querySelector(".action-dialog header button").click()');
 await js('document.getElementById("key-settings").click()');await until('document.querySelector(".action-dialog select")!==null');
 await js('[...document.querySelectorAll(".action-dialog button")].find(b=>b.textContent.includes("添加一行")).click()');
 await js('document.querySelector(".key-row input").value="isolated-ui-test-key";[...document.querySelectorAll(".action-dialog button")].find(b=>b.textContent.includes("保存并使用")).click()');await until('!document.querySelector(".action-dialog")');
 await until('document.querySelector(".global-concurrency").textContent.includes("/1")');
 await context('.project-tab[data-project="pet_transport"]','删除项目');
 assert.equal(await js('document.querySelector(".action-dialog .danger-action").disabled'),true);
 await js('const input=document.querySelector(".action-dialog input");input.value="删除错误项目";input.dispatchEvent(new Event("input"))');
 assert.equal(await js('document.querySelector(".action-dialog .danger-action").disabled'),true);
 fs.writeFileSync(path.join(root,'.runtime/actions-ui.png'),(await win.webContents.capturePage()).toPNG());
 await js('document.querySelector(".action-dialog input").value="删除宠物托运项目";document.querySelector(".action-dialog input").dispatchEvent(new Event("input"));document.querySelector(".action-dialog .danger-action").click()');await until('!document.querySelector(".project-tab[data-project=pet_transport]")');
 assert.equal(crypto.createHash('sha256').update(fs.readFileSync(path.join(root,'.env'))).digest('hex'),originalEnv);
 fs.writeFileSync(path.join(root,'.runtime/actions-ui-result.json'),JSON.stringify({ok:true,imageDelete:true,groupDelete:true,projectPhrase:true,replacementPreview:true,keySave:true,concurrency:true,productionEnvUnchanged:true,paidRequests:0}));app.exit(0);
}
run().catch(e=>{fs.writeFileSync(path.join(root,'.runtime/actions-ui-result.json'),JSON.stringify({ok:false,error:e.stack}));app.exit(1);});
