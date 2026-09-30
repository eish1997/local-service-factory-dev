/* Never build or publish as a side effect of development. */
const fs=require('fs'),path=require('path'),{spawnSync}=require('child_process');
if(!process.argv.includes('--confirm-build'))throw Error('需要用户明确要求构建安装包，然后传入 --confirm-build');
const root=path.resolve(__dirname,'../..'),stage=process.env.FACTORY_DISTRIBUTION_STAGE;
if(!stage||!fs.existsSync(path.join(stage,'python/python.exe'))||!fs.existsSync(path.join(stage,'engine/factory.py')))throw Error('先准备并验证独立 Python 和生成引擎暂存目录');
const cfg=JSON.parse(fs.readFileSync(path.join(stage,'engine/distribution/update-config.json'),'utf8'));
if(!Object.keys(cfg.public_keys).length)throw Error('正式安装包必须绑定发布验证公钥');
const pkg=JSON.parse(fs.readFileSync(path.join(root,'dashboard/package.json'),'utf8'));
if(cfg.app_version!==pkg.version)throw Error('界面与独立引擎版本不一致，请重新准备暂存目录');
const build=pkg.build;
// Use the installed, lockfile-selected Electron distribution instead of fetching it again.
build.electronDist=path.join(root,'dashboard/node_modules/electron/dist');
if(process.env.FACTORY_DISTRIBUTION_OUTPUT)build.directories={...build.directories,output:path.resolve(process.env.FACTORY_DISTRIBUTION_OUTPUT)};
build.extraResources=[{from:path.join(stage,'engine'),to:'engine'},{from:path.join(stage,'python'),to:'python'}];
const file=path.join(root,'.runtime','nsis-build-config.json');fs.writeFileSync(file,JSON.stringify(build));
const result=spawnSync(process.execPath,[require.resolve('electron-builder/cli'), '--win','nsis','--x64','--publish','never','--config',file],{cwd:path.join(root,'dashboard'),stdio:'inherit',shell:false});
process.exitCode=result.status||0;
