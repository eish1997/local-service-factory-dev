const {app,BrowserWindow}=require('electron'),fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..');process.env.ROAD_RESCUE_FACTORY_HOME=root;process.env.ROAD_RESCUE_DASHBOARD_TEST='1';require('../main');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function run(){await app.whenReady();const win=BrowserWindow.getAllWindows()[0],js=s=>win.webContents.executeJavaScript(s);for(let i=0;i<100;i++){if(await js('Boolean(document.querySelector(".project-tab"))'))break;await pause(100);}
 await js('document.querySelector(".project-tab").dispatchEvent(new MouseEvent("contextmenu",{bubbles:true,clientX:100,clientY:200}));document.querySelector(".context-menu button").click()');
 assert.equal(await js('getComputedStyle(document.querySelector(".action-dialog>div")).display'),'block');assert.ok(await js('document.querySelector(".action-dialog input").getBoundingClientRect().width>400'));
 fs.writeFileSync(path.join(root,'.runtime/delete-dialog.png'),(await win.webContents.capturePage()).toPNG());await js('document.querySelector(".action-dialog header button").click();document.getElementById("key-settings").click()');
 for(let i=0;i<100;i++){if(await js('Boolean(document.querySelector(".action-dialog select"))'))break;await pause(100);}
 assert.equal(await js('document.querySelector(".action-dialog select").selectedOptions[0].textContent'),'tinysnow');
 const saved=await js('document.querySelectorAll(".key-saved").length');assert.ok(saved>0);
 assert.ok(await js('document.querySelector(".action-dialog").textContent.includes("gpt-image-2-4k")'));
 assert.ok(await js('document.querySelector(".global-concurrency").nextElementSibling.classList.contains("monitor-updated")'));
 await js('document.querySelector(".action-dialog header button").click();document.getElementById("key-settings").click()');
 for(let i=0;i<100;i++){if(await js('Boolean(document.querySelector(".key-saved"))'))break;await pause(100);}
 assert.equal(await js('document.querySelectorAll(".key-saved").length'),saved);
 fs.writeFileSync(path.join(root,'.runtime/keys-dialog.png'),(await win.webContents.capturePage()).toPNG());
 await js('document.querySelector(".action-dialog header button").click();document.getElementById("update-settings").click()');
 for(let i=0;i<100;i++){if(await js('document.querySelector(".action-dialog")?.textContent.includes("1.3.0")'))break;await pause(100);}
 assert.ok(await js('document.querySelector(".action-dialog").textContent.includes("维护端")'));
 fs.writeFileSync(path.join(root,'.runtime/updates-dialog.png'),(await win.webContents.capturePage()).toPNG());app.exit(0);
}run().catch(e=>{fs.writeFileSync(path.join(root,'.runtime/actions-layout-error.txt'),e.stack);app.exit(1);});
