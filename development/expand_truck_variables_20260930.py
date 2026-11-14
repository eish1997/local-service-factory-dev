"""Prepare a local truck catalog edit; save through factory.py variables save.

No generation, deletion, release or network operations.
"""
import copy
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import variable_catalog as vc


def prepare():
    catalog=copy.deepcopy(vc.load('truck_rescue'))
    defaults={d['id']:d for d in vc.defaults('truck_rescue')['dimensions']}
    for d in catalog['dimensions']:
        # Migrate the corrected role/status contract; preserve all old candidate values.
        for key in ('roles','status'):
            d[key]=copy.deepcopy(defaults[d['id']][key])
    additions={
      'DETAIL_CAMERAS':[
        ['wheel_height','从安全警戒区外略低于腰部拍车轮外侧，操作点清楚，不钻车底、不用极端广角'],
        ['door_side','从驾驶室车门外侧斜拍车侧作业，门框只占边缘，工具接触点仍可见'],
        ['side_long','从作业区外侧稍远的手机机位拍摄，重卡车侧形成纵深，人物位于中景'],
        ['tool_side','从工具设备所在一侧斜拍师傅与故障部位，设备只是业务所需，不排列成展台']],
      'LOCATIONS':[
        ['truck_stop','普通货车服务站独立硬化检修区，背景为低矮服务房，远离进出车辆通道'],
        ['factory_loading','工厂装卸院落外围封闭检修位，与正在装卸的车辆和人员完全分开'],
        ['county_freight','县城货运集散点的平整独立维修空地，背景为旧库房与普通铁门'],
        ['fleet_yard','运输车队停车院内划出的维修位，停稳车辆与通行车道分隔，无车队商标'],
        ['highway_service','高速服务区许可维修点的隔离硬化工位，无行车道和应急车道作业']],
      'LIGHTS':[
        ['early_clear','日出后天色已亮的普通晨光，作业区清楚，非剪影，地面干燥'],
        ['noon_shade','晴天中午在检修棚阴影边缘作业，背景稍亮但操作部位可辨，无强HDR'],
        ['side_window','白昼维修棚侧窗与门洞自然光，亮度稍有不均，关键接触点清晰']],
      'WORKWEAR':['穿洗旧的深棕耐磨工装和防护手套','穿浅灰工装外套配深灰工作裤，袖口自然磨损'],
      'LEARNED_COMPOSITIONS':[
        ['vehicle_side_depth',[0,10,7],'以重卡车侧和工位纵深为主，人物自然靠近故障处，门头在上方完整可读'],
        ['doorframe_edge',[3,10,11],'从门框外侧记录当前作业，门框只形成一侧边缘，不遮挡电话和动作'],
        ['canopy_transition',[4,0,10],'用普通雨棚边缘与门内明暗过渡呈现空间，作业和门头仍可辨，不加电影光'],
        ['open_yard',[8,11,5],'表现独立硬化工位和门店之间的自然距离，少量空地不变成对称空旷广场'],
        ['workpoint_context',[3,10,2],'关注侧边故障作业点，同时留出足够门店背景，关键动作和电话不被叠字遮住']],
      'HEAVY_VEHICLES':['重型冷藏载货车，冷藏箱封闭且无品牌','6×4重型牵引车，连接普通集装箱半挂车，无标识'],
      'OTHER_VEHICLES':['中型厢式货车','中型仓栅载货车','中型冷藏货车，箱体关闭','中型平板货车，空载','轻型栏板货车','轻型仓栅货车','轻型冷藏厢式货车','中型平头货车，普通封闭货箱'],
      'SIGN_MATERIALS':[
        ['普通镀锌薄板与真实折边，实体哑光字固定在板上','浅灰底深蓝字，联系区少量暗红'],
        ['普通搪瓷金属板，接缝与固定螺钉自然可见','暗绿底米白字，不用金色镀铬'],
        ['普通硬质PVC字固定在涂漆金属主板上，无灯带','米黄色底黑字，电话区克制深绿'],
        ['旧式喷漆钢板主招牌，边框和墙面连接真实','白底深棕字，电话信息区暗红']],
      'SIGN_LAYOUTS':[
        '完整店名位于主板上半部，电话与服务小字在下半部左右分开，所有文字保持在同一板内',
        '主标题正常横排居左，主板右侧留独立电话联系区，下沿为一行服务词，不生成图标',
        '主标题完整横排居中，下方先是服务小字，再是同一板内电话联系行，不拆分号码',
        '长条主板左侧为完整店名，右侧为电话，下沿服务词连续排布，板面不过度拥挤',
        '主板上沿留少量正常边距，店名完整横排，下方联系区自然偏右，服务词位于左下'],
      'SIGN_WEAR':[
        '主板正常使用，表面只有少量雨痕，文字与电话号码完整清楚',
        '刚做过普通清洁，板面自然有轻微擦拭痕，不做光亮展厅质感',
        '主板边角有轻微漆面磨损，文字区完整，无断字和掉号',
        '普通旧招牌局部褪色但主文字保持足够对比，电话每一位清楚',
        '板面平整，固定螺钉附近有轻微使用痕迹，不整块锈蚀',
        '上边沿少量灰尘，字面干净可读，没有统一重污渍',
        '一处正常维修过的板缝在空白边缘可见，不穿过主标题或电话'],
      'BACKGROUND_ELEMENTS':[
        {'id':'stacked_pallets','description':'已有仓储背景墙边少量普通空托盘，仅作次要静物，不堵通道'},
        {'id':'warehouse_trolley','description':'远处独立装卸通道旁一辆停稳的普通手推车，不进入维修区'},
        {'id':'closed_neighbour','description':'背景边缘一扇普通邻铺关闭的卷帘门，无可读招牌'},
        {'id':'yard_fence','description':'场地边缘少量普通围栏与自然磨损，只在原环境容许时出现'},
        {'id':'distant_worker','description':'一名远处工作人员沿允许通行区域自然走动，不围观维修、不摆拍'},
        {'id':'awning_edge','description':'既有库房或邻铺的一小段普通雨棚边缘，不另造招牌和建筑'}],
      'SNAPSHOT_FLAWS':[
        {'id':'minor_highlight','description':'非文字区天空少量高光溢出，作业和主招牌曝光正常，电话不发白','weight':10},
        {'id':'edge_softness','description':'照片最边缘的非关键背景略软，故障部位与招牌文字清楚，不做专业虚化','weight':10},
        {'id':'uneven_metering','description':'室内外自动测光稍不均，门内暗部保留自然层次，关键动作与号码不被压黑','weight':10},
        {'id':'minor_foreground','description':'画面边缘一小段已有门框自然入镜，完整招牌、号码和作业接触点无遮挡','weight':10},
        {'id':'offcenter','description':'手机取景主体稍偏一侧，空白边距不完全均匀，不改变已有机位和事件，招牌完整','weight':10}],
    }
    additions['CAPTURE_DEVICES']=[
        {'id':'budget_daylight','name':'入门手机白昼主摄','description':'普通入门手机白昼主摄，明暗过渡略生硬，色彩自然，文字清晰，无强HDR与虚化'},
        {'id':'older_ios_main','name':'较早款手机自然主摄','description':'较早款手机主摄日常记录，中性略暖白平衡，普通锐度，真实纹理和电话清楚'},
        {'id':'phone_two_times','name':'普通手机两倍焦段','description':'普通手机两倍焦段中景，透视压缩适量，非长焦商业摄影，保持既定站位和招牌可读'},
        {'id':'phone_standard_auto','name':'普通手机自动模式','description':'普通手机默认自动模式随手拍，曝光轻微不均，正常色彩，无美颜，无夸张夜景合成'}]
    additions['PHOTO_TREATMENTS']=[
        {'id':'neutral_low_contrast','name':'中性低对比','color':'中性色温与正常色相，饱和度稍收敛','tone':'适量降低对比，亮暗仍有真实层次，招牌不泛灰','texture':'普通手机清楚纹理，不柔焦、不磨皮'},
        {'id':'warm_clear','name':'轻暖清楚','color':'轻微暖白平衡，肤色自然，招牌颜色保持原色','tone':'中等对比，暗部自然，不做HDR与商业光效','texture':'正常手机锐度，细节清楚，不添加颗粒和光晕'}]
    envdim=next(d for d in catalog['dimensions'] if d['source']=='COVER_ENVIRONMENTS')
    environments=[
        ('freight_service_row','货运市场服务铺','货运市场外围普通宽门洞服务铺','普通抹灰低层建筑与较宽卷帘门，门前有退让工位','旧仓库侧墙与关闭的邻铺门','street'),
        ('fleet_workshop','车队院内维修铺','普通运输车队院内维修门店','一层砖墙维修房与高门洞，主招牌在真实维修门上方','院墙和远处独立通行车道','yard'),
        ('truck_stop_shop','国道货车服务点','国道旁货车服务点内独立维修铺，远离行车道','普通单层水泥房与钢雨棚，宽门洞无豪华装修','服务房侧墙和普通隔离栏','yard'),
        ('warehouse_service','仓储园配套维修铺','仓储园边缘普通货车配套维修门店','两开间普通钢结构工位与压型板墙，门头真实固定','库房侧墙和装卸棚远景','yard')]
    additions['COVER_ENVIRONMENTS']=[]
    for ident,name,setting,facade,neighbours,area in environments:
        x=copy.deepcopy(envdim['options'][0]['value'])
        x.update(id=ident,name=name,setting=setting,facade=facade,neighbours=neighbours,camera_area=area,
                 activity='安静正常营业，无必须出现的车流人群',edge='建筑侧边自然边缘')
        additions['COVER_ENVIRONMENTS'].append(x)

    fileprefix='projects/truck_rescue/cover_scene_library.json:'
    additions[fileprefix+'locations']=[
        '县城货运集散点外围普通宽门洞维修门店','普通车队停车院内货车维修门店',
        '国道货车服务点内与道路隔离的维修门店','仓储园边缘普通货车配套维修门店']
    additions[fileprefix+'sign_color_schemes']=[
        '普通浅灰金属底，深蓝实体文字，联系区克制暗红','普通暗绿板面，米白文字，不使用金色和灯带',
        '普通米黄底，深棕哑光字，电话区白底深棕字','普通浅蓝灰板面，深灰字与白色联系区']
    additions[fileprefix+'sign_information_layouts']=additions['SIGN_LAYOUTS']
    additions[fileprefix+'sign_accent_details']=[
        '主板空白边缘一条普通细色线，不添加徽章、标志或复杂图标',
        '联系区用同一主板的少量留白区分，不增加悬浮横幅',
        '主标题下方一条克制细分隔线，电话完整位于主板内',
        '电话信息区采用普通实底色块，与实体板一体，无发光或UI圆角']
    additions[fileprefix+'sign_installation_details']=[
        '板面通过普通金属支架固定在门楣上，少量螺钉真实，不浮空',
        '主板两侧普通角钢支撑与墙面连接清楚，文字不跨支架',
        '主板下边沿正常折边与短支撑杆可见，不附加第二块招牌',
        '实体字固定点与普通涂漆板面自然结合，边缘保留少量真实厚度']

    # Six genuinely different action phases per role, with compatible vehicles/tools.
    events={
      '货车没油救援':[
        ('fuel_port_check','柴油动力重型载货车','diesel','air','师傅在车侧检查已关闭油箱盖周围外观，密闭柴油容器在吸油垫上，软管未接入；车辆熄火停稳','检修灯、密闭合规柴油容器、吸油垫、手套和轮挡'),
        ('fuel_ground_prepare','柴油动力重型牵引车','diesel','air','师傅在外侧安全工位核对转移设备连接与防静电措施，软管封好，尚未向车辆补油','专用封闭转移设备、防静电软管、防护手套和轮挡'),
        ('fuel_hose_route','柴油动力重型仓栅车','diesel','air','工作人员整理已经关闭阀门的防静电软管走向，软管不绕车轮，不进入通行道，仅表现补油前准备','合规柴油容器、防静电软管、吸油垫、轮挡和警示锥'),
        ('fuel_disconnect','柴油动力重型厢式车','diesel','air','补油结束后设备已关闭，师傅在油箱口外封闭软管端口，容器密闭，无液体洒漏','封闭转移设备、软管封口、接液垫、防护手套和轮挡'),
        ('fuel_container_secure','燃油动力中型栏板货车','combustion','unspecified','师傅把补油后已封好的合规燃油容器固定在服务车收纳位，故障车已熄火，软管封好','匹配燃料的封闭容器、固定带、封口软管和手套'),
        ('fuel_cap_verify','燃油动力轻型厢式货车','combustion','hydraulic','师傅在车侧确认油箱盖已旋紧，手持灯检查无洒漏，补油设备关闭并收纳','工作灯、接液垫、封闭容器、手套和轮挡')],
      '货车爆胎救援':[
        ('blowout_tread','重型载货车，后外胎胎面严重破损','combustion','air','师傅在车轮外侧用灯观察胎面裂口，车轮着地，人员不在车底，不进行补胎或拆轮','检修灯、防割手套、重型轮挡和警示锥'),
        ('blowout_clearance','重型半挂货车，外侧后胎爆裂','unspecified','air','师傅从安全外侧用检查镜观察破损轮胎与挡泥板间隙，手不接触锋利胎体','检查镜、工作灯、防割手套和轮挡'),
        ('blowout_rim_check','重型厢式载货车，外侧后胎瘪塌','combustion','air','师傅从侧面用灯检查可见轮辋边缘是否受损，不顶升、不拆轮，不塞胶条','手持灯、安全手套、轮挡和警示锥'),
        ('blowout_plan','重型平板货车，后轮胎侧壁破裂','unspecified','air','师傅站在警戒区内观察破损位置并和另一人员指向安全支撑区，工具尚未顶升车辆','工作灯、额定重型支撑设备、轮挡和警示锥'),
        ('blowout_medium_inspect','中型栏板货车，后胎明显爆裂','combustion','unspecified','师傅在轮胎侧面蹲下照看受损胎体，双手远离裂口，备用轮尚未搬到操作点','检修灯、防割手套、轮挡和警示锥'),
        ('blowout_light_record','轻型厢式货车，后外胎侧壁破裂','combustion','hydraulic','师傅站在车侧观察破损胎体与轮辋，车辆着地停稳，记录夹无可读文字，不进行修补','记录夹、手持灯、手套和轮挡')],
      '货车换轮胎':[
        ('wheel_support_check','重型载货车，车轮尚未拆卸','combustion','air','师傅在车侧核对额定重型支撑的受力位置，车辆停稳，车轮未悬空，人员不在车底','额定重型千斤顶、支撑架、轮挡和防护手套'),
        ('wheel_trolley','重型半挂货车，适配备用轮在搬运架上','unspecified','air','两名师傅在坚实工位上把备用轮搬运架推到车侧，车轮尚未拆下，不徒手举大轮胎','重型车轮搬运架、适配备用轮、轮挡和手套'),
        ('wheel_remove_outer','重型仓栅车，外侧车轮准备取下','combustion','air','车轴由额定重型支撑架可靠承托，师傅从外侧用搬运架承托松开后的完整外轮，不在车底','额定重型支撑架、搬运架、匹配套筒和轮挡'),
        ('wheel_final_check','重型牵引车，新轮已经落地','combustion','air','师傅站在车侧逐项复核已落地车轮螺母，扭力扳手与一枚螺母真实接触，无顶升动作','重型扭力扳手、匹配套筒、轮挡和手套'),
        ('wheel_medium_position','中型栏板货车，备用轮由搬运架承托','unspecified','unspecified','车轴有可靠额定支撑，师傅在车轮外侧用搬运架调整备用轮与轮毂位置，不把手放在夹缝','匹配支撑架、车轮搬运架、手套和轮挡'),
        ('wheel_light_finish','轻型厢式货车，新轮已着地','combustion','hydraulic','师傅在车侧用匹配扭力扳手复核已装好车轮，顶升工具退出，旧轮在安全收纳区','匹配扭力扳手、套筒、轮挡和手套')],
      '货车发动机故障':[
        ('engine_connector','柴油重型平头载货车，驾驶室翻起可靠锁止','diesel','air','师傅站在车侧用灯检查可接近线束插接件外观，发动机停机，手不接触旋转部件','检修灯、检查镜、防护手套和轮挡'),
        ('engine_hose_view','柴油重型牵引车，驾驶室已翻起锁止','diesel','air','师傅在外侧观察停机发动机可见软管与卡箍外观，不拆卸热管、不加油搭电','工作灯、检查镜、手套和轮挡'),
        ('engine_scan_review','柴油重型厢式车，驾驶室安全翻起锁止','diesel','air','师傅站在车侧查看已连接的诊断平板，另一手扶住平板边缘，连接线接诊断接口','商用车诊断平板、匹配连接线、防护手套和轮挡'),
        ('engine_belt_visual','柴油重型仓栅车，驾驶室翻起可靠锁止','diesel','air','师傅在车侧用工作灯观察停机发动机外侧可见皮带区域，不伸手进皮带夹缝，不启动发动机','工作灯、检查镜、防护手套和轮挡'),
        ('engine_medium_connector','中型平头栏板货车，驾驶室翻起且锁止','combustion','unspecified','师傅用灯检查可接近的低压线束接头外观，车辆断开启动操作，动作只在车侧','工作灯、绝缘手套、检查镜和轮挡'),
        ('engine_light_codes','轻型平头厢式货车，驾驶室按车型结构翻起锁止','combustion','hydraulic','师傅在车侧读取诊断设备的故障状态，不同时拆发动机或补油，手部与设备接触真实','匹配诊断设备、连接线、手套和轮挡')],
      '卡车搭电':[
        ('jump_device_match','重型载货车，侧置低压蓄电池箱打开','combustion','air','师傅在车侧核对关闭的辅助电源与24V低压系统额定规格，线夹绝缘保护且未连接','匹配24V辅助电源、绝缘跨接线、手套和轮挡'),
        ('jump_terminal_view','重型牵引车，低压电池端子可接近','combustion','air','师傅用检修灯检查低压端子外观，启动设备关闭，尚未搭接线夹，无火花','检修灯、匹配24V设备、绝缘手套和轮挡'),
        ('jump_route_check','重型厢式货车，辅助线尚未接通','combustion','air','师傅核对粗跨接线走向远离旋转和高温部件，线夹端部绝缘保护，电源关闭','匹配24V低压启动设备、粗跨接线、绝缘护具和轮挡'),
        ('jump_completed_read','重型仓栅货车，低压跨接连接完成','combustion','air','师傅站在车侧读取辅助设备电压显示，双手远离已连接线夹，线缆真实接端子和指定接地点','匹配24V商用车启动设备、绝缘粗线、护目镜和轮挡'),
        ('jump_medium_verify','中型厢式货车，低压电池箱打开','combustion','unspecified','师傅核对电池标识与辅助电源额定电压，线夹未连接，不固定宣称24V，无高压充电枪','匹配额定电压的辅助电源、万用表、绝缘手套和轮挡'),
        ('jump_light_voltmeter','轻型栏板货车，低压电池可接近','combustion','hydraulic','师傅用万用表测量低压电池电压，探针真实接测点，启动设备关闭，跨接线未连接','万用表、匹配额定电压辅助设备、绝缘手套和轮挡')],
      '货车刹车故障':[
        ('brake_air_connector','重型载货车，明确为空气制动系统','combustion','air','师傅在车侧可接近的气路接头观察检漏液形成的细小气泡，车辆驻车固定，不拆带压管线','检漏液、工作灯、重型轮挡和防护手套'),
        ('brake_air_hose','重型牵引车，明确为空气制动系统','combustion','air','师傅在外侧用灯检查可见气路软管外观和固定点，不拆管、不钻车底，不出现制动液壶','工作灯、检查镜、手套和重型轮挡'),
        ('brake_air_dashboard','重型厢式载货车，明确为空气制动系统','combustion','air','师傅站在打开车门外读取静止车辆的制动报警与诊断状态，车轮固定，不开车测试','商用车制动诊断设备、连接线、轮挡和警示锥'),
        ('brake_trailer_coupling','重型半挂货车，明确为空气制动系统','combustion','air','师傅从牵引车侧边可接近位置观察挂车空气管接头外观，车辆停稳，不拆带压管线','检修灯、检查镜、手套和重型轮挡'),
        ('brake_medium_reservoir','中型厢式货车，明确为液压制动系统','combustion','hydraulic','师傅用灯从可接近处观察制动液储液壶液位，不打开制动回路，不混用空气制动设备','工作灯、防护手套、轮挡和液压制动诊断设备'),
        ('brake_light_hose_view','轻型栏板货车，明确为液压制动系统','combustion','hydraulic','师傅在车轮外侧用检查镜观察可见液压制动软管的磨损情况，车轮着地，不拆卸管线','检查镜、手持灯、液压制动诊断工具、手套和轮挡')]
    }
    for role,values in events.items(): additions['EVENTS.'+role]=[list(x) for x in values]
    additions['COVER_EVENTS']=[
        {'id':'cover_air_check','action':'重型牵引车停在门侧独立硬化工位，师傅站在车侧用灯检查可见气路软管外观，轮挡到位，不拆带压管线','state':'门洞打开，通道空出，店内普通工具柜自然使用','placement':'检查镜与工作灯只在本次气路检查部位使用，不添加油桶或备用胎'},
        {'id':'cover_battery_measure','action':'重型厢式货车停稳，师傅在车侧低压电池箱旁用万用表检查电压，匹配24V启动设备关闭且尚未搭接','state':'正常营业，操作在门侧独立工位，不挡进出通道','placement':'万用表探针接触测点，未接线夹有绝缘防护，启动设备在车旁干燥处'}]

    changed=[]
    for d in catalog['dimensions']:
        values=additions.get(d['source'],[])
        if not values: continue
        if d.get('status')!='active': continue
        known={vc.uid(o['value']) for o in d['options']}
        for value in values:
            if vc.uid(value) in known: continue
            d['options'].append({'id':'expanded_'+vc.uid(value),'name':vc.option_name(value,len(d['options'])),
              'value':value,'schema':vc.schema(value),'weight':1.0,'enabled':True,'conditions':[]})
            known.add(vc.uid(value))
        if len(d['options'])<10: raise ValueError('扩展不足10项：'+d['source'])
        changed.append((d['source'],len(d['options'])))
    vc.validate(catalog)
    target=ROOT/'.runtime/truck_variable_expansion_request.json'
    target.write_text(json.dumps({'catalog':catalog,'expected_revision':catalog['revision']},ensure_ascii=False),encoding='utf8')
    print(json.dumps({'request':str(target),'changed':changed},ensure_ascii=False))


if __name__=='__main__': prepare()
