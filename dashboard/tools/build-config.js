/* Pure preflight: no installer creation or network access. */
function validateBuildConfig(cfg,pkg,lock){
 if(!cfg.public_keys||!Object.keys(cfg.public_keys).length)throw Error('正式安装包必须绑定发布验证公钥');
 if(cfg.app_version!==pkg.version||lock.version!==pkg.version||lock.packages?.['']?.version!==pkg.version)throw Error('界面、锁文件与独立引擎版本不一致');
 const feeds=pkg.build?.publish;
 if(!Array.isArray(feeds)||feeds.length!==1||feeds[0].provider!=='github'||feeds[0].owner!==cfg.owner||feeds[0].repo!==cfg.software_repo)throw Error('安装包与引擎更新仓库不一致');
 if(cfg.rules_repo!==cfg.software_repo)throw Error('统一仓库的规则与软件入口不一致');
}
module.exports={validateBuildConfig};
