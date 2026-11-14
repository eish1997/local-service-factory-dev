/* Never build or publish as a side effect of development. */
const fs=require('fs'),path=require('path'),{spawnSync}=require('child_process');
if(!process.argv.includes('--confirm-build'))throw Error('需要用户明确要求构建安装包，然后传入 --confirm-build');
const root=path.resolve(__dirname,'../..'),stage=process.env.FACTORY_DISTRIBUTION_STAGE;
if(!stage||!fs.existsSync(path.join(stage,'python/python.exe'))||!fs.existsSync(path.join(stage,'engine/factory.py')))throw Error('先准备并验证独立 Python 和生成引擎暂存目录');
const cfg=JSON.parse(fs.readFileSync(path.join(stage,'engine/distribution/update-config.json'),'utf8'));
if(!Object.keys(cfg.public_keys).length)throw Error('正式安装包必须绑定发布验证公钥');
const pkg=JSON.parse(fs.readFileSync(path.join(root,'dashboard/package.json'),'utf8'));
const lock=JSON.parse(fs.readFileSync(path.join(root,'dashboard/package-lock.json'),'utf8'));
require('./build-config').validateBuildConfig(cfg,pkg,lock);
const provenance=require('./build-provenance');
const sourceSha=provenance.sourceIdentity(root);
provenance.validateStage(stage,sourceSha);
const build=pkg.build;
// Use the installed, lockfile-selected Electron distribution instead of fetching it again.
build.electronDist=path.join(root,'dashboard/node_modules/electron/dist');
if(process.env.FACTORY_DISTRIBUTION_OUTPUT)build.directories={...build.directories,output:path.resolve(process.env.FACTORY_DISTRIBUTION_OUTPUT)};
build.extraResources=[{from:path.join(stage,'engine'),to:'engine'},{from:path.join(stage,'python'),to:'python'}];
const file=path.join(root,'.runtime','nsis-build-config.json');fs.writeFileSync(file,JSON.stringify(build));
const result=spawnSync(process.execPath,[require.resolve('electron-builder/cli'), '--win','nsis','--x64','--publish','never','--config',file],{cwd:path.join(root,'dashboard'),stdio:'inherit',shell:false});
if(result.error)throw result.error;
if(result.status!==0)throw Error('安装包构建失败或被中断');
if(provenance.sourceIdentity(root)!==sourceSha)throw Error('构建期间源码提交已变化');
provenance.validateStage(stage,sourceSha);
provenance.recordBuild(path.resolve(root,'dashboard',build.directories.output),cfg,sourceSha);
