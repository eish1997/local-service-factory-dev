const fs=require('fs'),path=require('path'),crypto=require('crypto'),{EventEmitter}=require('events');
const {createService,canonical}=require('../update-service');
function fixture(activity,suppliedRoot){
 fs.mkdirSync(path.resolve(__dirname,'../../.runtime'),{recursive:true});
 const home=fs.mkdtempSync(path.resolve(__dirname,'../../.runtime/update-node-'));const root=suppliedRoot||path.join(home,'data'),installed=path.join(home,'installed');fs.mkdirSync(root,{recursive:true});fs.mkdirSync(installed);fs.writeFileSync(path.join(installed,'app.exe'),'old-version');
 const binary=path.join(home,'new.exe');fs.writeFileSync(binary,'new-installer');
 const keys=crypto.generateKeyPairSync('ed25519'),raw=keys.publicKey.export({format:'der',type:'spki'}).subarray(-32).toString('base64');
 const payload={kind:'software',version:'1.3.0',sha256:crypto.createHash('sha256').update('new-installer').digest('hex')};
 const envelope={payload,key_id:'test',signature:crypto.sign(null,Buffer.from(canonical(payload)),keys.privateKey).toString('base64')};
 const app=new EventEmitter();app.isPackaged=true;app.getVersion=()=> '1.2.0';app.getPath=()=>path.join(installed,'app.exe');
 const updater=new EventEmitter();let downloads=0,installs=0,active=false,requestedUrl=null;
 updater.setFeedURL=()=>{};updater.checkForUpdates=async()=>({isUpdateAvailable:true,updateInfo:{version:'1.3.0'}});
 updater.downloadUpdate=async()=>{downloads++;await Promise.all(updater.listeners('update-downloaded').map(fn=>fn({version:'1.3.0',downloadedFile:binary})));};
 updater.quitAndInstall=()=>installs++;
 const service=createService({app,root,updater,hasActiveTasks:()=>active||(activity ? activity(root) : false),configuration:{app_version:'1.2.0',owner:'test',software_repo:'releases',public_keys:{test:raw},check_interval_hours:6},fetchRelease:async url=>{requestedUrl=url;return envelope;},runCommand:async()=>({software_version:'1.2.0'})});
 return {home,root,app,updater,service,envelope,binary,sign:()=>{envelope.signature=crypto.sign(null,Buffer.from(canonical(envelope.payload)),keys.privateKey).toString('base64');},requestedUrl:()=>requestedUrl,downloads:()=>downloads,installs:()=>installs,active:value=>active=value};
}
module.exports={fixture};
