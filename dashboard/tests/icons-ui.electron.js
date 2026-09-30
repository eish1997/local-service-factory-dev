const {app,BrowserWindow}=require('electron');
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..');
process.env.ROAD_RESCUE_FACTORY_HOME=root;process.env.ROAD_RESCUE_DASHBOARD_TEST='1';
require('../main');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function run(){
 await app.whenReady();const win=BrowserWindow.getAllWindows()[0];
 for(let n=0;n<100;n++){if(await win.webContents.executeJavaScript('document.querySelectorAll("#project-tabs button").length===8 && document.querySelectorAll(".task-card").length>0'))break;await pause(150);}
 const result=await win.webContents.executeJavaScript(`(()=>{
 const ids=['task-select-all','task-clear','task-plan','task-start','task-pause','task-resume','task-retry','task-refresh'];
 return ids.map(id=>{const b=document.getElementById(id),i=b.querySelector('.ui-icon'),s=getComputedStyle(i);return {id,width:s.width,height:s.height,mask:s.maskImage,label:b.getAttribute('aria-label')};});})()`);
 assert.equal(result.length,8);for(const r of result){assert.equal(r.width,'18px');assert.equal(r.height,'18px');assert.ok(r.mask.includes('/lucide/'));assert.ok(r.label);}
 await win.webContents.executeJavaScript('document.getElementById("task-select-all").click()');
 assert.ok(await win.webContents.executeJavaScript('!document.getElementById("task-plan").disabled'));
 await win.webContents.executeJavaScript('document.getElementById("task-clear").click();document.getElementById("task-new").click()');
 assert.equal(await win.webContents.executeJavaScript('document.getElementById("task-create-dialog").open'),true);
 await win.webContents.executeJavaScript('document.getElementById("task-create-close").click()');
 fs.writeFileSync(path.join(root,'.runtime/icons-ui.png'),(await win.webContents.capturePage()).toPNG());
 fs.writeFileSync(path.join(root,'.runtime/icons-ui-result.json'),JSON.stringify({ok:true,icons:result.length,noGeneration:true}));app.exit(0);
}
run().catch(e=>{fs.writeFileSync(path.join(root,'.runtime/icons-ui-result.json'),JSON.stringify({ok:false,error:e.stack}));app.exit(1);});
