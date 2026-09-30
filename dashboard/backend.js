const path=require('path');
function entry(root){return path.join(process.env.FACTORY_ENGINE_HOME||root,'factory.py');}
function python(){return process.env.ROAD_RESCUE_PYTHON||'python';}
module.exports={entry,python};
