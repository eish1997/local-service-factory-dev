const test=require('node:test'),assert=require('node:assert/strict');
const {validateBuildConfig}=require('../tools/build-config');
const cfg=require('../../distribution/update-config.json'),pkg=require('../package.json'),lock=require('../package-lock.json');
test('checked-in unified configuration passes without building',()=>validateBuildConfig(cfg,pkg,lock));
test('stale staging or package configuration fails before building',()=>{
 for(const changed of [{...cfg,owner:'other'},{...cfg,software_repo:'other'},{...cfg,rules_repo:'other'},{...cfg,app_version:'0.0.0'},{...cfg,public_keys:{}}])assert.throws(()=>validateBuildConfig(changed,pkg,lock));
 assert.throws(()=>validateBuildConfig(cfg,pkg,{...lock,version:'0.0.0'}));
 assert.throws(()=>validateBuildConfig(cfg,pkg,{...lock,packages:{'':{version:'0.0.0'}}}));
});
