const test=require('node:test'),assert=require('node:assert/strict'),fs=require('fs'),path=require('path'),crypto=require('crypto'),{EventEmitter}=require('events');
const {createService,canonical}=require('../update-service');
function fixture(){
 fs.mkdirSync(path.resolve(__dirname,'../../.runtime'),{recursive:true});
 const home=fs.mkdtempSync(path.resolve(__dirname,'../../.runtime/update-node-'));const root=path.join(home,'data'),installed=path.join(home,'installed');fs.mkdirSync(root);fs.mkdirSync(installed);fs.writeFileSync(path.join(installed,'app.exe'),'old-version');
 const binary=path.join(home,'new.exe');fs.writeFileSync(binary,'new-installer');
 const keys=crypto.generateKeyPairSync('ed25519'),raw=keys.publicKey.export({format:'der',type:'spki'}).subarray(-32).toString('base64');
 const payload={kind:'software',version:'1.3.0',sha256:crypto.createHash('sha256').update('new-installer').digest('hex')};
 const envelope={payload,key_id:'test',signature:crypto.sign(null,Buffer.from(canonical(payload)),keys.privateKey).toString('base64')};
 const app=new EventEmitter();app.isPackaged=true;app.getVersion=()=> '1.2.0';app.getPath=()=>path.join(installed,'app.exe');
 const updater=new EventEmitter();let downloads=0,installs=0,active=false,requestedUrl=null;
 updater.setFeedURL=()=>{};updater.checkForUpdates=async()=>({isUpdateAvailable:true,updateInfo:{version:'1.3.0'}});
 updater.downloadUpdate=async()=>{downloads++;await Promise.all(updater.listeners('update-downloaded').map(fn=>fn({version:'1.3.0',downloadedFile:binary})));};
 updater.quitAndInstall=()=>installs++;
 const service=createService({app,root,updater,hasActiveTasks:()=>active,configuration:{app_version:'1.2.0',owner:'test',software_repo:'releases',public_keys:{test:raw},check_interval_hours:6},fetchRelease:async url=>{requestedUrl=url;return envelope;},runCommand:async()=>({software_version:'1.2.0'})});
 return {home,root,app,updater,service,envelope,binary,sign:()=>{envelope.signature=crypto.sign(null,Buffer.from(canonical(envelope.payload)),keys.privateKey).toString('base64');},requestedUrl:()=>requestedUrl,downloads:()=>downloads,installs:()=>installs,active:value=>active=value};
}
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
