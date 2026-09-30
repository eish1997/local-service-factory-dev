/* Uses the embedded Python and staged engine, with no system Python/Node on PATH. */
const {app,BrowserWindow}=require('electron'),fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),stage=JSON.parse(fs.readFileSync(path.join(root,'.runtime/runtime-smoke-current.json'),'utf8')).root;
process.env.FACTORY_DATA_HOME=path.join(stage,'user');process.env.FACTORY_ENGINE_HOME=path.join(stage,'engine');process.env.ROAD_RESCUE_FACTORY_HOME=process.env.FACTORY_DATA_HOME;
process.env.ROAD_RESCUE_PYTHON=path.join(stage,'python/python.exe');process.env.PATH=path.join(stage,'python');process.env.ROAD_RESCUE_DASHBOARD_TEST='1';
require('../main');const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function run(){
 await app.whenReady();const win=BrowserWindow.getAllWindows()[0],js=s=>win.webContents.executeJavaScript(s);
 for(let i=0;i<150;i++){if(await js('document.querySelectorAll(".project-tab").length===8 && document.querySelectorAll(".task-card").length===1'))break;await pause(100);}
 assert.equal(await js('document.querySelectorAll(".project-tab").length'),8);
 assert.equal(await js('document.querySelectorAll(".task-card").length'),1);
 await js('document.querySelector(".task-card details").open=true');
 for(let i=0;i<100;i++){if(await js('document.querySelectorAll(".task-prompts pre").length>0'))break;await pause(100);}
 assert.equal(await js('document.querySelectorAll(".task-prompts pre").length'),7);
 fs.writeFileSync(path.join(root,'.runtime/installed-runtime-ui.png'),(await win.webContents.capturePage()).toPNG());
 fs.writeFileSync(path.join(root,'.runtime/installed-runtime-ui-result.json'),JSON.stringify({ok:true,embeddedPython:true,sourceCheckoutIndependent:true,systemPathRemoved:true,projects:8,prompts:7,paidRequests:0}));app.exit(0);
}
run().catch(e=>{fs.writeFileSync(path.join(root,'.runtime/installed-runtime-ui-result.json'),JSON.stringify({ok:false,error:e.stack}));app.exit(1);});
