const test=require('node:test'),assert=require('node:assert/strict'),fs=require('fs'),path=require('path'),crypto=require('crypto');
const {validateStage,recordBuild}=require('../tools/build-provenance');
function fixture(){const root=path.resolve(__dirname,'../../.runtime');fs.mkdirSync(root,{recursive:true});return fs.mkdtempSync(path.join(root,'provenance-test-'));}
test('stage identity and complete file inventory must match',()=>{
 const stage=fixture(),engine=path.join(stage,'engine');fs.mkdirSync(engine);fs.writeFileSync(path.join(engine,'factory.py'),'fixture');
 const sha='a'.repeat(40),digest=crypto.createHash('sha256').update('fixture').digest('hex');
 fs.writeFileSync(path.join(stage,'stage-provenance.json'),JSON.stringify({source_sha:sha,engine_files:{'factory.py':digest}}));
 validateStage(stage,sha);
 assert.throws(()=>validateStage(stage,'b'.repeat(40)));
 fs.writeFileSync(path.join(engine,'factory.py'),'changed');assert.throws(()=>validateStage(stage,sha));
 fs.writeFileSync(path.join(engine,'factory.py'),'fixture');fs.writeFileSync(path.join(engine,'unexpected.py'),'extra');assert.throws(()=>validateStage(stage,sha));
});
test('build record hashes every required artifact and refuses missing files',()=>{
 const folder=fixture(),cfg={app_version:'1.4.18',owner:'test',software_repo:'unified'};
 assert.throws(()=>recordBuild(folder,cfg,'a'.repeat(40)));
 for(const name of ['LocalServiceFactory-1.4.18-setup.exe','LocalServiceFactory-1.4.18-setup.exe.blockmap','latest.yml'])fs.writeFileSync(path.join(folder,name),'test artifact');
 const record=recordBuild(folder,cfg,'a'.repeat(40));assert.equal(Object.keys(record.files).length,3);assert.equal(record.repository.repo,'unified');
 assert.deepEqual(JSON.parse(fs.readFileSync(path.join(folder,'build-provenance.json'),'utf8')),record);
});
