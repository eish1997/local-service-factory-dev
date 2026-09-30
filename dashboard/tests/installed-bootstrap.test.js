const test=require('node:test'),assert=require('node:assert/strict'),fs=require('fs'),path=require('path');
const {initialize,registry}=require('../installed-runtime');
test('first launch is offline, separates private data and preserves it on later launch',()=>{
 const source=path.resolve(__dirname,'../..'),stage=process.env.FACTORY_TEST_DISTRIBUTION_STAGE||JSON.parse(fs.readFileSync(path.join(source,'.runtime/runtime-smoke-current.json'),'utf8')).root;
 const home=fs.mkdtempSync(path.join(source,'.runtime/bootstrap-test-'));
 const app={getPath:()=>home,getVersion:()=> '1.3.0'};
 const root=initialize(app,stage);assert.equal(registry(root).projects.length,8);
 const pointer=path.join(root,'.runtime/updates/active_rules.json');assert.equal(JSON.parse(fs.readFileSync(pointer)).version,'1');
 const env=path.join(root,'.env');fs.writeFileSync(env,'OPENAI_API_KEY=isolated-bootstrap-key\n');
 fs.writeFileSync(path.join(root,'.runtime/hidden_projects.json'),JSON.stringify({projects:['pet_transport']}));
 initialize(app,stage);assert.equal(fs.readFileSync(env,'utf8'),'OPENAI_API_KEY=isolated-bootstrap-key\n');assert.equal(registry(root).projects.length,7);
 assert.ok(process.env.ROAD_RESCUE_PYTHON.startsWith(stage));
});
