"""Coherent cover layouts; deterministic rotation prevents adjacent layout repeats."""

from tools import variable_catalog
import random

COMPOSITIONS = [
    dict(id='front_medium_left_work', camera='街对面约8至12米平视近乎正面拍，偏离门店中轴，不做对称广告构图', scale='中景，门店约占画面宽度75%，招牌高度约占15%至20%', subject='动作主体在左侧中下部，右侧是通行空间', activity='一名师傅在左侧门口蹲着检查拆下的轮胎，家用车稳固支撑在旁边，其他师傅如出现只在该工位协助', vehicle='救援车如出现，只露右侧远处少量车尾，不作为前景主体', foreground='前景仅窄段路缘，没有大块空地'),
    dict(id='right_near_depth', camera='从门店右前方约5至7米向左侧看，平视稍低，完整招牌可见，店内纵深明显，不用超广角', scale='近中景，门店占宽度85%左右，招牌高度不超过25%', subject='师傅在左侧门内中景，右侧近处仅局部车身', activity='刚完成救援，师傅在门内左侧将拖车带收回工具箱，不打开机盖、不另设修车人物', vehicle='救援车如出现，仅右边缘局部平板，不露大车头', foreground='右侧局部车身自然截断，不超过画面宽度15%，不挡门头'),
    dict(id='distant_street_context', camera='从街对面约15至20米平视拍，用普通手机两倍取景，门店略偏右，保留邻铺关系，不俯拍', scale='环境中景，门店约占画面宽度60%，电话仍须清楚，不能拉远到文字无法读', subject='师傅是门内较小人物，不在前景，入口完整', activity='一名师傅在门内工作台检查便携应急电源及线夹，其他师傅如出现仅在旁协助，不展示新维修事件', vehicle='救援车如出现停在店面左侧中景，尺寸服从远拍距离', foreground='只留短段路面，下方不堆大车头或大片空地'),
    dict(id='left_oblique_center_work', camera='从左侧约8米斜向右拍约20度，手机平视，非夸张梯形招牌', scale='中景，门店约占画面宽度75%，招牌约占画面高度18%', subject='师傅在中央偏下工位，车和工具车分列其两侧，左侧留通道', activity='师傅侧身在家用车打开的机盖旁使用便携电源搭电，电源稳放工具车，线夹连接合理，其他人如出现只协助同一辆车', vehicle='救援车如出现仅在右侧后景，不与家用车挤成展示阵列', foreground='前景少量作业地面和真实气管，不摆一排工具'),
    dict(id='slight_high_open_bay', camera='从对面正常人行台阶上平视稍向下拍，约10米距离，仅轻微高机位，不航拍，不用超广角', scale='门店约占画面宽度70%，门前工位可见，屋顶不占大块画面', subject='师傅和工具在右侧中景，左侧开间或门口保持可见，不能站在右前景遮满画面', activity='刚结束服务，师傅在右侧门口工具车上清点套筒和扳手，其他人如出现只协助收纳，没有另开机盖事件', vehicle='救援车如出现位于左侧中景，保持真实通行宽度', foreground='前景仅台阶边和少量水泥地，不人为框景'),
    dict(id='eye_level_interior_activity', camera='从门店正前方约7至10米平视记录，镜头向左偏移少许，招牌近水平，重点是门内动作和内外明暗', scale='中近景，门店约占画面宽度80%，完整招牌高度约占18%，不拍成巨幅招牌特写', subject='师傅在门内深处中央，前景无人，只见工作现场进深', activity='师傅在门内家用车侧面检查轮胎气压，气管连到旁边空压机，其他师傅如出现只协助同一工位，不做机盖搭电', vehicle='救援车如出现仅画面边缘少量车身，门口不放完整车辆', foreground='入口及地面自然延伸，没有近景人物和车头')
]


@variable_catalog.managed('road_rescue',finish_result=False)
def choose_composition(group_index, variant=0, first_group_index=1089):
    order = list(range(len(COMPOSITIONS)))
    random.Random(f'road_composition_v1:{variant}').shuffle(order)
    # A fixed shuffled cycle also differs across cycle boundaries and subset runs.
    return dict(COMPOSITIONS[order[(group_index-first_group_index) % len(order)]])
