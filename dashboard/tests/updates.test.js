const test=require('node:test'),assert=require('node:assert/strict'),fs=require('fs'),path=require('path');
const {fixture}=require('./update-fixture');
test('verified update waits for exit and never interrupts workers; previous app is preserved',async()=>{
 const f=fixture();await f.service.check();assert.equal(f.service.getState().state,'ready');assert.equal(f.downloads(),1);assert.equal(f.updater.autoInstallOnAppQuit,false);
 assert.equal(fs.readFileSync(path.join(f.root,'.runtime/updates/previous-app/1.2.0/app.exe'),'utf8'),'old-version');
 f.active(true);f.app.emit('before-quit',{preventDefault(){assert.fail('active task must not be interrupted');}});assert.equal(f.installs(),0);
 f.active(false);let prevented=false;f.app.emit('before-quit',{preventDefault(){prevented=true;}});assert.equal(prevented,true);assert.equal(f.installs(),1);
});
test('tampered signature never downloads or installs',async()=>{
 const f=fixture();f.envelope.payload.version='9.0.0';await f.service.check();assert.equal(f.downloads(),0);assert.equal(f.service.getState().state,'error');assert.equal(f.installs(),0);
});
test('wrong installer digest cannot become ready',async()=>{
 const f=fixture();fs.writeFileSync(f.binary,'tampered');await f.service.check();assert.equal(f.service.getState().state,'error');f.app.emit('before-quit',{preventDefault(){assert.fail('must not install');}});assert.equal(f.installs(),0);
});
test('source mode never invokes the updater',async()=>{
 const f=fixture();f.app.isPackaged=false;await f.service.check();assert.equal(f.downloads(),0);assert.equal(f.service.getState().state,'development');
});

test('manifest uses the configured public repository URL',async()=>{
 const f=fixture();await f.service.check();assert.equal(f.requestedUrl(),'https://github.com/test/releases/releases/latest/download/software-manifest.json');
});
test('signed rules manifest at Latest never starts software download',async()=>{
 const f=fixture();f.envelope.payload.kind='rules';f.sign();await f.service.check();assert.equal(f.downloads(),0);assert.equal(f.service.getState().state,'error');assert.equal(f.installs(),0);
});
test('updater version must match the signed manifest',async()=>{
 const f=fixture();f.updater.checkForUpdates=async()=>({isUpdateAvailable:true,updateInfo:{version:'8.0.0'}});await f.service.check();assert.equal(f.downloads(),0);assert.equal(f.service.getState().state,'error');
});

test('migrated software accepts a signed future software version without publishing one',async()=>{
 const f=fixture();f.app.getVersion=()=> '1.4.18';
 f.envelope.payload.version='1.4.19';f.sign();
 f.updater.checkForUpdates=async()=>({isUpdateAvailable:true,updateInfo:{version:'1.4.19'}});
 f.updater.downloadUpdate=async()=>{await Promise.all(f.updater.listeners('update-downloaded').map(fn=>fn({version:'1.4.19',downloadedFile:f.binary})));};
 await f.service.check();assert.equal(f.service.getState().state,'ready');
 assert.equal(f.service.getState().target_version,'1.4.19');assert.equal(f.installs(),0);
});

// These exercise the real before-quit handler with a stub installer, never an exe.
const nativeActive=root=>require('../tasks').hasActiveNativeTasks(root);
function nativeState(root,status,cancelled=false){
 const dir=path.join(root,'prompts/library/road_rescue/batch_native');fs.mkdirSync(dir,{recursive:true});
 fs.writeFileSync(path.join(dir,'native-execution.json'),JSON.stringify({cancelled,units:{one:{status}}}));return dir;
}
test('native activity blocks install; manual, pending and terminal states do not',async()=>{
 const f=fixture(nativeActive);await f.service.check();
 for(const status of ['pending','claimed','uncertain','failed','raw_saved','completed','cancelled','rendering']){
  nativeState(f.root,status);assert.equal(nativeActive(f.root),false,status);
 }
 nativeState(f.root,'awaiting_result');
 f.app.emit('before-quit',{preventDefault(){assert.fail('native call is active');}});assert.equal(f.installs(),0);
 nativeState(f.root,'awaiting_result',true);assert.equal(nativeActive(f.root),false);
 nativeState(f.root,'uncertain');f.app.emit('before-quit',{preventDefault(){}});assert.equal(f.installs(),1);
});
test('live native writer protects render even after cancellation or batch deletion',async()=>{
 const f=fixture(nativeActive);await f.service.check();const dir=nativeState(f.root,'rendering');
 const leases=path.join(f.root,'.runtime/native-writes');fs.mkdirSync(leases,{recursive:true});
 const lease=path.join(leases,'render.lock');fs.writeFileSync(lease,JSON.stringify({pid:process.pid}));
 for(const cancelled of [false,true]){nativeState(f.root,'rendering',cancelled);f.app.emit('before-quit',{preventDefault(){assert.fail('writer is active');}});assert.equal(f.installs(),0);}
 fs.unlinkSync(path.join(dir,'native-execution.json'));assert.equal(nativeActive(f.root),true);
 fs.unlinkSync(lease);assert.equal(nativeActive(f.root),false);
 f.app.emit('before-quit',{preventDefault(){}});assert.equal(f.installs(),1);
});
test('second check under admin lock sees a native call started after first check',async()=>{
 let checks=0;const f=fixture(root=>{checks++;if(checks===1){nativeState(root,'awaiting_result');return false;}return nativeActive(root);});
 await f.service.check();f.app.emit('before-quit',{preventDefault(){assert.fail('race must not install');}});
 assert.equal(checks,2);assert.equal(f.installs(),0);assert.equal(fs.existsSync(path.join(f.root,'.runtime/updates/installing.json')),false);
 nativeState(f.root,'completed');f.app.emit('before-quit',{preventDefault(){}});assert.equal(f.installs(),1);
});
test('native ingest holding admin lock refuses installation without discarding lock',async()=>{
 const f=fixture(nativeActive);await f.service.check();nativeState(f.root,'uncertain');
 const lock=path.join(f.root,'.runtime/task-admin.lock');fs.writeFileSync(lock,JSON.stringify({pid:process.pid}));
 f.app.emit('before-quit',{preventDefault(){assert.fail('ingest owns admin lock');}});assert.equal(f.installs(),0);assert.equal(fs.existsSync(lock),true);
 fs.unlinkSync(lock);f.app.emit('before-quit',{preventDefault(){}});assert.equal(f.installs(),1);
});

test('orphan render state and dead writer do not permanently block updates',()=>{
 const f=fixture(nativeActive);const dir=nativeState(f.root,'rendering');
 const leases=path.join(f.root,'.runtime/native-writes');fs.mkdirSync(leases,{recursive:true});
 const monitor=require('../monitor'),original=monitor.processIsAlive;
 try{
  monitor.processIsAlive=pid=>pid===process.pid;
  fs.writeFileSync(path.join(leases,'orphan.lock'),JSON.stringify({pid:2147483647}));
  fs.writeFileSync(path.join(dir,'native-render.lock'),JSON.stringify({pid:2147483647}));
  assert.equal(nativeActive(f.root),false);
  fs.writeFileSync(path.join(dir,'native-render.lock'),JSON.stringify({pid:process.pid}));assert.equal(nativeActive(f.root),true);
 }finally{monitor.processIsAlive=original;}
});
test('both main update entry points include native guard and preserve API monitor',()=>{
 const main=fs.readFileSync(path.join(__dirname,'../main.js'),'utf8');
 assert.equal((main.match(/hasActiveTasks:\(\)=>hasActiveNativeTasks\(projectRoot\)\|\|/g)||[]).length,2);
 assert.equal((main.match(/return m.claimedActive&&m.processAlive!==false/g)||[]).length,2);
});
