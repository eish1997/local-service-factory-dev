"""Assemble one business-KTV group as separate prompt layers.

Indoor empty-room prompts stay in scene.py. Variable pools below are the
seven-image group only. Phone numbers are never candidates.
"""

from __future__ import annotations

import random

from tools import variable_catalog

REQUIRED = (
    "store_name",
    "phone",
    "services",
    "building",
    "photo",
    "light",
    "typeface",
    "sign_layout",
    "street",
    "materials",
    "lobby",
    "room",
    "guest_clothes",
    "staff_posts",
    "singer_look",
    "room_side",
    "lobby_name",
    "scale",
    "style",
    "grade",
)
VARY_TOGETHER = ("store_name", "building", "light", "typeface", "sign_layout", "street")
MIN_AXIS_CHANGES = 4
SCALE_CLASSES = ("窄开间", "两开间", "整层临街")

# Kept so the saved variable catalog binding still validates. New groups compose
# names from STORE_NAME_HEADS and STORE_NAME_TAILS instead of sampling this list.
STORE_NAMES = (
    "招牌店名只写晚叙。",
    "招牌店名只写听潮。",
    "招牌店名只写南枝。",
    "招牌店名只写月白。",
    "招牌店名只写澄宴。",
    "招牌店名只写拾光。",
)
STORE_NAME_HEADS = (
    "店名首字用晚。",
    "店名首字用听。",
    "店名首字用南。",
    "店名首字用月。",
    "店名首字用澄。",
    "店名首字用拾。",
    "店名首字用归。",
    "店名首字用慢。",
    "店名首字用半。",
    "店名首字用青。",
    "店名首字用木。",
    "店名首字用巷。",
)
STORE_NAME_TAILS = (
    "店名次字用叙。",
    "店名次字用潮。",
    "店名次字用枝。",
    "店名次字用白。",
    "店名次字用宴。",
    "店名次字用光。",
    "店名次字用声。",
    "店名次字用里。",
    "店名次字用社。",
    "店名次字用舍。",
    "店名次字用间。",
    "店名次字用楼。",
)
STORE_NAME_MIDDLES = (
    "店名中字用溪。",
    "店名中字用禾。",
    "店名中字用安。",
    "店名中字用年。",
    "店名中字用歌。",
    "店名中字用灯。",
    "店名中字用庭。",
    "店名中字用望。",
    "店名中字用临。",
    "店名中字用初。",
    "店名中字用川。",
    "店名中字用未。",
)
LOBBY_NAMES = (
    "写出店名：前台立牌或前台背后可以出现同一块店名，店名下面一行写副标题商务会所，字号小于店名。只写这一处，不做成第二块大门招牌。",
    "不写店名：大厅画面里不出现店名，也不写商务会所。",
)
# Scale and decoration are crossed. BUILDINGS and MATERIALS stay only so the
# saved variable catalog binding still validates; new groups do not sample them.
SCALES = (
    {
        "name": "窄开间",
        "line": "窄开间，只有一个开间，一扇门，招牌只盖住这一开间，大厅进深短。",
        "building": "门脸只有一个开间，一扇门。门的材料和高度按本组装修来，不要改成另一档。",
        "photo": "机位靠近这一扇门，门脸在画面里很窄，客人背影靠近镜头。",
        "lobby": "大厅进深短，前台就在门内，旁边最多两扇关着的包厢门。",
        "room": "包厢小，沙发坐三人，茶几离人很近。",
    },
    {
        "name": "两开间",
        "line": "两开间，门脸占两个开间，招牌横跨这两个开间，大厅能并排站两位服务人员。",
        "building": "门脸占两个开间。门是一扇还是两扇、有没有台阶，按本组装修来。",
        "photo": "机位能把两个开间一起拍进画面，不要只裁成一扇门。",
        "lobby": "大厅有两开间宽，前台能并排站两位服务人员，走廊一侧能看见几扇关着的包厢门。",
        "room": "包厢比单间大一圈，沙发坐五到六人，茶几和沙发之间有一条过道。",
    },
    {
        "name": "整层临街",
        "line": "整层临街，门脸占满一整层，招牌很长，镜头退远才能拍全，大厅能看见多扇包厢门。",
        "building": "门脸占满左右邻居之间的一整层，招牌很长。是石材长门脸还是小区整层铺面，按本组装修来。",
        "photo": "机位退远，整层门脸入画，人在门前显得小，不要只拍居中一扇门。",
        "lobby": "大厅是一条较长的走廊，前台沿一侧拉长，另一侧能数出至少三扇关着的包厢门。",
        "room": "包厢明显更大，卡座能坐下八人左右，中间留出走道。",
    },
)
DECOR_STYLES = (
    {"name": "奶油石青铜玻", "grade": "高档", "facade": "这是高档门面。外墙是奶油色石材，玻璃是青铜框，上方一整块暖光招牌。", "photo": "从左侧稍斜着拍石材和青铜框。", "lobby": "大厅是奶油石墙和青铜框玻璃，前台有暖色灯带，地面是石材。", "room": "包厢是暖色石材和深色皮沙发，灯是壁灯。", "materials": "奶油石、青铜框玻璃和暖光招牌。"},
    {"name": "木饰小区铺", "grade": "小区", "facade": "这是小区铺面。外墙是竖向木条，一扇普通木框玻璃门，招牌是木牌，没有石材台阶。", "photo": "木条墙占画面一侧，门不高。", "lobby": "大厅是木墙和直木前台，地面是木地板，一盏普通灯。", "room": "包厢三面木饰，布艺沙发，壁灯。", "materials": "竖向木条、直木前台和木地板。"},
    {"name": "深铜雨棚", "grade": "高档", "facade": "这是高档门面。门上是一条深铜色雨棚，雨棚底有暖色筒灯，下面是青铜框玻璃。", "photo": "从车道一侧拍雨棚，不要居中对称。", "lobby": "大厅延续深铜和暖色筒灯，前台是金属包边的直台。", "room": "包厢是深色墙面，铜色小灯，深色皮沙发。", "materials": "深铜雨棚、青铜框玻璃和暖色筒灯。"},
    {"name": "居民楼底商", "grade": "小区", "facade": "这是居民楼一层底商。入口在楼梯旁边，楼上能看见住宅窗户，招牌做在门梁上，门不高。", "photo": "机位能看见楼上住宅窗户。", "lobby": "大厅吊顶偏低，直木柜台，墙是涂料。", "room": "包厢偏小，沙发贴墙，是翻新过的小包厢。", "materials": "涂料墙、直木柜台和偏低吊顶。"},
    {"name": "石材深门廊", "grade": "高档", "facade": "这是高档门面。门退进石材门廊里，门廊顶是暖色藻井，尽端是玻璃门。", "photo": "镜头看进门廊，一根墙或柱子占画面一侧。", "lobby": "大厅接在门廊后面，石材墙，暖色筒灯，前台在侧面。", "room": "包厢是石材墙和深色皮卡座，灯光偏暖。", "materials": "石材门廊、暖色藻井和玻璃门。"},
    {"name": "水刷石铺面", "grade": "小区", "facade": "这是小区铺面。外墙是水刷石，门套是普通木框，招牌是门楣上的窄牌。", "photo": "水刷石墙面占画面大块。", "lobby": "大厅墙是涂料，前台是直木柜台，地面是水泥。", "room": "包厢墙是涂料，沙发是布艺。", "materials": "水刷石外墙、直木柜台和水泥地面。"},
    {"name": "石墙水景", "grade": "高档", "facade": "这是高档门面。一侧是深色石墙，暖色金属字和洗墙灯，旁边是通长玻璃，门前有一浅水池。", "photo": "机位在水池一端，门脸斜着入画。", "lobby": "大厅能看见通长玻璃和深色石材，前台暖灯，地面是石材。", "room": "包厢是深色石材和皮沙发，灯光暖。", "materials": "深色石墙、暖色金属字和门前浅水。"},
    {"name": "青砖铺面", "grade": "小区", "facade": "这是沿街铺面。外墙是青砖，黑木框玻璃门，招牌是门楣上的一块横匾。", "photo": "青砖墙占画面左半。", "lobby": "大厅一侧露着青砖，前台是深色直木台，地面是水泥。", "room": "包厢一面留青砖，其余是深色木板，布艺沙发。", "materials": "青砖、黑木框、直木台和水泥地面。"},
    {"name": "深色木饰铜灯", "grade": "高档", "facade": "这是高档门面。外墙是深色木饰面，配窄铜灯，门是青铜框，招牌是金属字。", "photo": "深色木墙和铜灯占画面一侧。", "lobby": "大厅是深色木墙，前台是木面铜边直台，灯偏暖。", "room": "包厢是深色木饰，深色皮沙发，铜壁灯。", "materials": "深色木饰、铜灯和青铜框门。"},
    {"name": "红砖铺面", "grade": "小区", "facade": "这是小区铺面。外墙是红砖，招牌是白底木牌，门是普通玻璃门。", "photo": "红砖墙占画面一侧。", "lobby": "大厅有一段红砖墙，前台是原色直木台，地面是地砖。", "room": "包厢墙是浅涂料，沙发是灰色布艺。", "materials": "红砖、白底木牌和原色木台。"},
    {"name": "铜板门头", "grade": "高档", "facade": "这是高档门面。大面是深铜板，浅色金属字装在铜板上，入口是玻璃门。", "photo": "铜板占满招牌那一面。", "lobby": "大厅有铜板和石材，前台是金属包边直台，灯光暖。", "room": "包厢是深色墙，局部铜板，深色皮沙发。", "materials": "深铜板、浅色金属字和玻璃门。"},
    {"name": "灰涂料灯箱", "grade": "小区", "facade": "这是小区铺面。外墙是灰涂料，招牌是普通横条灯箱，门是一扇玻璃门。", "photo": "灰墙和灯箱占满门侧。", "lobby": "大厅是灰涂料墙，前台在侧面，顶上是筒灯。", "room": "包厢墙是灰涂料，卡座是深色布艺。", "materials": "灰涂料、横条灯箱和侧面直台。"},
    {"name": "青铜玻璃幕墙", "grade": "高档", "facade": "这是高档门面。整面是青铜框玻璃幕墙，室内暖光透出来，上面是灯带石材额。", "photo": "玻璃幕墙占满门脸，室内暖光可见。", "lobby": "大厅就在玻璃后面，石材地面，前台暖灯。", "room": "包厢墙是深色石材，皮沙发，暖灯。", "materials": "青铜框玻璃幕墙和灯带石材额。"},
    {"name": "米白涂料铺", "grade": "小区", "facade": "这是小区铺面。外墙是米白涂料，招牌是横条灯箱，旁边可以有卷帘门。", "photo": "白墙和灯箱在白天显得普通。", "lobby": "大厅是白墙和日光灯，前台是浅色直台。", "room": "包厢墙是浅色，沙发是棕色布艺。", "materials": "米白涂料、横条灯箱和浅色直台。"},
    {"name": "石柱门廊", "grade": "高档", "facade": "这是高档门面。入口两侧是两根石柱，柱身有暖色上照灯，柱间是玻璃门。", "photo": "一根石柱挡在画面前景。", "lobby": "大厅接在石柱后面，石材墙，暖色筒灯，前台在一侧。", "room": "包厢是石材墙和深色皮卡座。", "materials": "石柱、暖色上照灯和柱间玻璃门。"},
    {"name": "白瓷砖铺面", "grade": "小区", "facade": "这是老小区铺面。外墙贴白色小瓷砖，招牌是铝边灯箱。", "photo": "白瓷砖缝在画面里清楚。", "lobby": "大厅墙裙是白瓷砖，前台是贴面板直台，灯是日光灯。", "room": "包厢墙是白墙，沙发是布艺。", "materials": "白瓷砖、铝边灯箱和贴面板直台。"},
    {"name": "洞石", "grade": "高档", "facade": "这是高档门面。外墙是洞石，暖色洗墙灯打出孔洞，门是青铜框玻璃。", "photo": "洞石肌理占画面一侧。", "lobby": "大厅有一面洞石，前台是浅色石材直台，灯光暖。", "room": "包厢主墙是洞石，沙发是浅色皮。", "materials": "洞石、暖色洗墙灯和青铜框玻璃。"},
    {"name": "铝塑板铺面", "grade": "小区", "facade": "这是小区铺面。门头是普通铝塑板，接缝平直，字贴在板上。", "photo": "铝塑板接缝在画面里能看见。", "lobby": "大厅是石膏板吊顶和涂料墙，前台是普通贴面直台。", "room": "包厢是涂料墙和布艺沙发。", "materials": "铝塑板门头、石膏板吊顶和贴面直台。"},
    {"name": "深色大理石", "grade": "高档", "facade": "这是高档门面。外墙是深色大理石，线性暖灯嵌在石缝，门是玻璃，玻璃后能看见前台。", "photo": "大理石墙面占画面大半。", "lobby": "大厅是深色大理石，前台是石材直台，灯带暖。", "room": "包厢是深色大理石，深色皮沙发。", "materials": "深色大理石、石缝线性暖灯和玻璃门。"},
    {"name": "卷帘社区铺", "grade": "小区", "facade": "这是社区底商。玻璃门旁边有卷帘，墙是浅色涂料，招牌是横条灯箱。", "photo": "卷帘和玻璃门并排，不要拍成石材门廊。", "lobby": "大厅偏亮，白墙，日光灯，前台是浅色直台。", "room": "包厢墙是浅色，沙发是棕色布艺，屏幕不大。", "materials": "浅色涂料、卷帘、横条灯箱和日光灯。"},
    {"name": "庭院低墙", "grade": "高档", "facade": "这是高档门面。门前是一道低石墙和几盏庭院暖灯，后面是玻璃门里的前台。", "photo": "低石墙和庭院灯在前景，不挡店名。", "lobby": "大厅是石材和暖灯，前台清楚，植物只在角落。", "room": "包厢是石材和皮沙发，角落有一盆植物。", "materials": "低石墙、庭院暖灯和玻璃门里的前台。"},
    {"name": "水泥门脸", "grade": "小区", "facade": "这是普通铺面。外墙是水泥原色，门是黑色铁框玻璃门，招牌是黑底白字。", "photo": "水泥墙占画面一侧。", "lobby": "大厅是水泥墙和水泥地面，前台是一条木板直台。", "room": "包厢一面是水泥墙，沙发是灰布。", "materials": "水泥墙、黑铁框门和木板直台。"},
    {"name": "浅色石材", "grade": "高档", "facade": "这是高档门面。外墙是浅色石材，细金属字，字距宽松，灯光安静。", "photo": "浅色石墙在暖灯下显得干净。", "lobby": "大厅是浅色石材，前台是同色石材直台，线性暖灯。", "room": "包厢是浅色石材，浅色皮沙发。", "materials": "浅色石材、细金属字和线性暖灯。"},
    {"name": "花砖旧铺", "grade": "小区", "facade": "这是旧小区铺面。门口有花砖，墙是旧涂料，招牌是木牌，门不高。", "photo": "门口花砖占前景一角。", "lobby": "大厅地面有一小片花砖，前台是旧木直台，墙是旧涂料。", "room": "包厢地面有花砖，沙发是布艺，茶几是旧木。", "materials": "花砖地面、旧涂料和旧木直台。"},
)
BUILDINGS = (
    "这是竖向木饰面的窄店，单开木框玻璃门，招牌是木牌深色字，没有石材铜框。",
    "这是居民楼一层底商，入口在楼梯旁边，门脸窄，楼上能看见住宅窗户，招牌做在门梁上。",
    "这是街角店，两面有窗，入口开在转角，门套是深色木框，墙是水刷石。",
    "门退进墙里，外面是一条深门廊和两根普通柱子，招牌在门廊顶上，门是单扇玻璃门。",
    "这是社区底商，浅色涂料墙，玻璃门旁边有卷帘门，招牌是横条灯箱。",
    "这是青砖门脸的窄店，门是黑色木框玻璃门，招牌是门楣上的一块横匾，砖缝清楚。",
)
EXTERIOR_LIGHTS = (
    "白天侧光，招牌和门套都看得清。",
    "雨夜路灯，地面有湿反光，门头灯单独照着招牌。",
    "黄昏天光还在，室内暖灯已经亮起。",
    "蓝调傍晚，天色和门头灯同时可见。",
)
TYPEFACES = (
    "一种能看清的宋体，整块招牌没有第二种字体。",
    "一种能看清的黑体，整块招牌没有第二种字体。",
    "一种能看清的标宋，整块招牌没有第二种字体。",
    "一种能看清的仿宋，整块招牌没有第二种字体。",
)
SIGN_LAYOUTS = (
    "店名在门楣上方，用途和电话分成门边两列。",
    "店名在左，用途在右，电话单独占招牌底部一行。",
    "店名居中，用途紧贴店名下方，电话放到门套侧铭牌。",
    "店名和用途叠在门楣，电话横在门槛上方的门梁上。",
)
STREETS = (
    "左侧有邻店橱窗和行道树，车辆停在远处路边。",
    "上层住宅窗户开着，人行道上有行人经过但不挡门。",
    "雨后路面发暗，街对面是普通底商，门口地面留空。",
    "街角转过去还能看见下一家店的侧墙。",
)
MATERIALS = (
    "外立面和室内都是木饰面、直木前台和木地板，没有弧形石材前台。",
    "涂料墙、直木柜台和偏低吊顶，没有铜框和大理石。",
    "水刷石外墙、深色木门套、转角直台。",
    "灰涂料、普通柱子、侧面直台和筒灯。",
    "浅色涂料、横条灯箱、浅色直台和日光灯。",
    "青砖、黑木框、直木台和水泥地面。",
)
EXTRA_SERVICES = (
    "用途只写这三项：商务宴请、派对聚会、欢唱包厢。",
    "用途只写这三项：商务宴请、派对聚会、公司团建。",
    "用途只写这三项：商务宴请、派对聚会、朋友欢聚。",
    "用途只写这三项：商务宴请、派对聚会、生日小聚。",
)
GUEST_CLOTHES = (
    "从背后看，男客穿深色夹克、女客穿晚礼服。",
    "从背后看，男客穿针织衫外套、女客穿深色长裙。",
    "从背后看，两人穿大衣和短裙，像刚下车来玩。",
    "从背后看，男客没打领带，女客提着小包。",
)
STAFF_POSTS = (
    "一位服务人员在前台低头工作，另一位穿同样制服站在走廊口等候。",
    "一位服务人员站在前台后面整理台面，走廊里没有第二个人。",
    "两位服务人员都在前台内侧，一个看台面，一个侧身对着走廊。",
)
SINGER_LOOKS = (
    "成年女歌手穿深色礼服，头发整齐，脸和手完整。",
    "成年女歌手穿浅色连衣裙，侧身对着客人，脸和手完整。",
    "成年女歌手穿黑色上衣，长发披在一侧，脸和手完整。",
    "成年女歌手穿暖色短裙，站在沙发前方，脸和手完整。",
)
ROOM_SIDES = (
    "客人从沙发左侧看向房间里侧。",
    "客人坐在茶几右侧，视线对着歌手和屏幕侧面。",
    "包厢门在画面左后方，歌手在右侧前方。",
    "沙发靠右墙，点歌屏在斜前方，不占满画面。",
)

MEDIUM = "一张中国城市里的竖版手机照片。用新提示词从头生成，不修改已有图片。"
THIRD_PERSON = "第三人称。镜头不是客人自己的眼睛。"
FIRST_PERSON = "第一人称。镜头就是客人自己的眼睛，不把客人的正脸写成主角。"

SHOTS = (
    {
        "id": "01_storefront",
        "role": "门头",
        "viewpoint": "third",
        "layers": ("medium", "viewpoint", "facade", "action", "sign", "exclude"),
        "action": (
            "大楼外面。大门开着，门里只看见前台大厅，能看见接待台和灯。"
            "客人正在往门里走，只写背影：脸朝门，不回头，不看镜头，不站着摆拍。"
            "可以有门童站在门内、面向客人。车辆停在远处路边，不能堵在门口。"
            "机位按本组拍照句执行，不要每张都站在客人身后正对大门。"
        ),
        "exclude": (
            "门里不出现包厢沙发、话筒、点歌屏或有人唱歌。"
            "客人不穿西装、不拿公文包，不一排同事面对面说话。"
            "不写未确认的价格、地址或其他号码。"
        ),
    },
    {
        "id": "02_lobby",
        "role": "大厅",
        "viewpoint": "third",
        "layers": ("medium", "viewpoint", "venue", "action", "exclude"),
        "action": "主体是环境：前台、墙面材料、灯光、地面，以及一侧走廊和关着的包厢门。服务人员不看镜头摆拍。",
        "exclude": "不放客人。不放话筒、点歌屏或唱歌的人。不写电话和广告。店名只按本组大厅店名句决定。",
    },
    {
        "id": "03_enter_room",
        "role": "进包厢门",
        "viewpoint": "first",
        "layers": ("medium", "viewpoint", "venue", "action", "exclude"),
        "action": "推开的是包厢门，不是大楼大门，门里是包厢。成年女歌手转过身看向进门的人。",
        "exclude": "脸必须完整，五官清楚，光线自然。禁止崩脸、重影和糊掉的五官。画面里不写店名。",
    },
    {
        "id": "04_sit",
        "role": "入座",
        "viewpoint": "first",
        "layers": ("medium", "viewpoint", "venue", "action", "exclude"),
        "action": "人已经坐在包厢沙发上。眼前是茶几、包厢和准备唱歌的成年女歌手。",
        "exclude": "不出现客人自己的正脸。脸和手结构完整。画面里不写店名。",
    },
    {
        "id": "05_listen",
        "role": "看美女听歌",
        "viewpoint": "first",
        "layers": ("medium", "viewpoint", "venue", "action", "exclude"),
        "action": "从侧面看成年女歌手唱歌，一支麦克风在她手里。",
        "exclude": "脸完整。手和麦克风结构清楚。画面里不写店名。",
    },
    {
        "id": "06_offer_mic",
        "role": "美女递麦",
        "viewpoint": "first",
        "layers": ("medium", "viewpoint", "venue", "action", "exclude"),
        "action": "女歌手把另一支麦克风递向镜头。两支麦克风都要能看清。",
        "exclude": "手和脸完整。手指数量和关节结构正确。画面里不写店名。",
    },
    {
        "id": "07_duet",
        "role": "深情合唱",
        "viewpoint": "first",
        "layers": ("medium", "viewpoint", "venue", "action", "exclude"),
        "action": "和成年女歌手一起唱，镜头前有两支麦克风。",
        "exclude": "不把客人正脸写成画面主角。脸和手结构完整。画面里不写店名。",
    },
)


def _clean(value, key):
    text = str(value).strip()
    if not text:
        raise ValueError(f"{key} 不能为空")
    return text


def _name_char(value, key):
    text = _clean(value, key)
    marker = "用"
    if marker not in text:
        raise ValueError("店名变量要写成「用」加一个字")
    char = text.split(marker, 1)[1].strip("。")
    if len(char) != 1:
        raise ValueError("店名每一段只取一个字")
    return char


def compose_store_name(head, tail, middle=""):
    """Join a head, an optional middle, and a tail. The subtitle stays off the name."""
    name = _name_char(head, "store_name_head")
    if middle:
        name += _name_char(middle, "store_name_middle")
    name += _name_char(tail, "store_name_tail")
    if len(name) not in (2, 3) or "商务会所" in name:
        raise ValueError("店名用两到三个字，商务会所只作副标题")
    return name


def _short_store_name(value):
    text = _clean(value, "store_name")
    for prefix in ("招牌店名只写", "主标题只写"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip("。")
            break
    if len(text) not in (2, 3) or "商务会所" in text:
        raise ValueError("店名用两到三个字，商务会所只作副标题")
    return text


def _services(value):
    if isinstance(value, str):
        body = value.split("：", 1)[-1].strip("。")
        items = [item.strip() for item in body.split("、") if item.strip()]
    else:
        items = [_clean(item, "services") for item in value]
    if len(items) < 3 or len(set(items)) != len(items):
        raise ValueError("用途至少三项，且不能重复")
    if "商务宴请" not in items or not any("派对" in item for item in items):
        raise ValueError("用途必须包含商务宴请和派对，并再写至少一项其他用途")
    line = value.strip() if isinstance(value, str) else "用途只写这三项：" + "、".join(items) + "。"
    return tuple(items), line


def _group(raw):
    incoming = dict(raw)
    if "services" not in incoming and incoming.get("service_line"):
        incoming["services"] = incoming["service_line"]
    missing = [key for key in REQUIRED if key not in incoming]
    if missing:
        raise ValueError("缺少本组字段：" + "、".join(missing))
    group = {key: incoming[key] for key in REQUIRED}
    group["store_name"] = _short_store_name(group["store_name"])
    group["store_name_line"] = _clean(incoming.get("store_name_line") or incoming["store_name"], "store_name")
    if not (group["store_name_line"].startswith("招牌店名只写") or group["store_name_line"].startswith("主标题只写")):
        group["store_name_line"] = f"主标题只写{group['store_name']}。"
    phone = _clean(group["phone"], "phone")
    if len(phone) != 11 or not phone.isdigit():
        raise ValueError("门头电话必须是该次任务确认的11位数字")
    group["phone"] = phone
    services, service_line = _services(incoming.get("service_line") or group["services"])
    group["services"] = services
    group["service_line"] = service_line
    for key in ("building", "photo", "light", "typeface", "sign_layout", "street", "materials", "lobby", "room", "guest_clothes", "staff_posts", "singer_look", "room_side", "lobby_name", "scale", "style", "grade"):
        group[key] = _clean(group[key], key)
    _scale_class(group["scale"])
    if group["grade"] not in ("高档", "小区"):
        raise ValueError("档次只能是高档或小区")
    if not (group["lobby_name"].startswith("写出店名") or group["lobby_name"].startswith("不写店名")):
        raise ValueError("大厅店名句要以写出店名或不写店名开头")
    return group


def _scale_class(text):
    body = _clean(text, "scale").strip("。")
    for name in SCALE_CLASSES:
        if body.startswith(name):
            return name
    raise ValueError("规模必须从窄开间、两开间、整层临街里选")


def _compose_venue(scale, style):
    """Cross one store scale with one decoration style."""
    return {
        "scale": scale["line"],
        "style": style["name"],
        "grade": style["grade"],
        "building": scale["building"] + style["facade"],
        "photo": scale["photo"] + style["photo"],
        "lobby": scale["lobby"] + style["lobby"],
        "room": scale["room"] + style["room"],
        "materials": style["materials"],
    }


def _parts(shot, group):
    action = shot["action"]
    if shot["id"] == "01_storefront":
        action += group["guest_clothes"]
    elif shot["id"] == "02_lobby":
        action += group["staff_posts"]
    parts = {
        "medium": MEDIUM,
        "viewpoint": THIRD_PERSON if shot["viewpoint"] == "third" else FIRST_PERSON,
        "action": action,
        "exclude": shot["exclude"],
    }
    if "facade" in shot["layers"]:
        parts["facade"] = f"规模：{group['scale']}建筑：{group['building']}拍照：{group['photo']}时间与光：{group['light']}街道：{group['street']}材料：{group['materials']}"
    if "venue" in shot["layers"]:
        if shot["id"] == "02_lobby":
            if group["lobby_name"].startswith("写出店名"):
                shown = f"店名只写{group['store_name']}。副标题在店名下面写商务会所，字号小于店名，不要拼进店名。"
            else:
                shown = "大厅不写商务会所。"
            parts["venue"] = f"这是这家店的大厅，与门头同一家店，规模与门头一致：{group['scale']}{group['lobby']}{group['lobby_name']}{shown}"
        else:
            parts["venue"] = f"这是这家店的包厢，与门头同一家店，规模是{_scale_class(group['scale'])}，画面里不写店名：{group['room']}{group['singer_look']}{group['room_side']}"
    if "sign" in shot["layers"]:
        digits = " ".join(group["phone"])
        parts["sign"] = (
            f"{group['store_name_line']}副标题单独一行写商务会所，字号小于店名，同一字体，不要把这四个字拼进店名。"
            f"{group['typeface']}排版：{group['sign_layout']}"
            f"{group['service_line']}电话大字：{group['phone']}。按位核对：{digits}。"
        )
    return parts


def assemble_group(group, previous=None):
    """Return seven prompts. Each prompt is the named layers joined in order."""
    current = _group(group)
    if previous is not None:
        prior = _group(previous)
        if current["grade"] == prior["grade"] or _scale_class(current["scale"]) == _scale_class(prior["scale"]) or current["style"] == prior["style"] or any(current[key] == prior[key] for key in ("building", "photo", "lobby", "room")):
            raise ValueError("相邻两组要同时更换档次、规模、装修风格、拍照、大厅和包厢")
        changed = [key for key in VARY_TOGETHER if current[key] != prior[key]]
        if len(changed) < MIN_AXIS_CHANGES:
            raise ValueError("相邻两组门头至少同时更换店名、建筑、光线、字体、排版、街道中的四项")
    rows = []
    for shot in SHOTS:
        parts = _parts(shot, current)
        rows.append({
            "id": shot["id"],
            "role": shot["role"],
            "viewpoint": shot["viewpoint"],
            "layers": list(shot["layers"]),
            "parts": parts,
            "prompt": "\n".join(parts[name] for name in shot["layers"]),
        })
    return rows


@variable_catalog.managed("business_ktv", "detail", finish_result=False)
def select_group(seed, phone, previous=None):
    """Pick one value from each new group variable, then assemble seven prompts."""
    rng = random.Random(seed)
    pools = {
        "light": EXTERIOR_LIGHTS,
        "typeface": TYPEFACES,
        "sign_layout": SIGN_LAYOUTS,
        "street": STREETS,
        "service_line": EXTRA_SERVICES,
        "guest_clothes": GUEST_CLOTHES,
        "staff_posts": STAFF_POSTS,
        "singer_look": SINGER_LOOKS,
        "room_side": ROOM_SIDES,
        "lobby_name": LOBBY_NAMES,
    }
    scales = tuple(SCALES)
    styles = tuple(DECOR_STYLES)
    if len(styles) < 20:
        raise ValueError("装修风格至少要有20套")
    if len({item["name"] for item in styles}) != len(styles):
        raise ValueError("装修风格名称不能重复")
    if len(scales) < 2:
        raise ValueError("门店规模至少要有两档")
    for attempt in range(80):
        scale = scales[(seed + attempt) % len(scales)]
        style = styles[(seed + attempt * len(scales)) % len(styles)]
        if previous is not None:
            prior = _group(previous)
            if style["name"] == prior["style"] or style["grade"] == prior["grade"] or _scale_class(scale["line"]) == _scale_class(prior["scale"]):
                continue
        chosen = {key: rng.choice(tuple(pool)) for key, pool in pools.items()}
        chosen.update(_compose_venue(scale, style))
        middle = rng.choice(tuple(STORE_NAME_MIDDLES)) if (int(seed) + attempt) % 2 else ""
        chosen["store_name"] = compose_store_name(rng.choice(tuple(STORE_NAME_HEADS)), rng.choice(tuple(STORE_NAME_TAILS)), middle)
        if previous is not None and chosen["store_name"] == _group(previous)["store_name"]:
            continue
        chosen["phone"] = phone
        try:
            shots = assemble_group(chosen, previous=previous)
        except ValueError:
            continue
        return {"variables": _group(chosen), "shots": shots}
    raise ValueError("相邻两组要同时更换档次、规模、装修风格、拍照、大厅和包厢")
