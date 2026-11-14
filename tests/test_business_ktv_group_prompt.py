import unittest

from tools.business_ktv.group_prompt import DECOR_STYLES, SCALES, SHOTS, assemble_group, select_group


GROUP = {
    "store_name": "晚叙",
    "phone": "13407128962",
    "services": ["商务宴请", "派对聚会", "公司团建"],
    "building": "这是竖向木饰面的窄店，单开木框玻璃门。",
    "photo": "机位贴在门的左侧近处，只拍进半扇门和半块招牌。",
    "light": "蓝调傍晚",
    "typeface": "一种哑光白色宋体",
    "sign_layout": "店名在上，用途一行，电话单独大行",
    "street": "左侧有邻店和行道树，轿车停在远处路边",
    "materials": "外立面和室内都是木饰面、直木前台和木地板。",
    "lobby": "大厅也是木墙和直木前台，走廊铺木地板。",
    "room": "包厢三面木饰面，低矮皮沙发，木茶几。",
    "guest_clothes": "从背后看，男客穿深色夹克、女客穿晚礼服。",
    "staff_posts": "一位服务人员在前台低头工作，另一位穿同样制服站在走廊口等候。",
    "singer_look": "成年女歌手穿深色礼服，头发整齐，脸和手完整。",
    "room_side": "客人从沙发左侧看向房间里侧。",
    "lobby_name": "不写店名：大厅画面里不出现店名，也不写其它招牌文字。",
    "scale": "窄开间，门洞只容两人并排，招牌只盖这一扇门，大厅只有几步进深。",
    "style": "直纹木饰",
    "grade": "高档",
}

NEXT_GROUP = {
    **GROUP,
    "store_name": "听潮",
    "building": "这是居民楼一层底商，入口在楼梯旁边。",
    "photo": "机位在马路斜对面、略低，门脸放在画面下半。",
    "light": "白天侧光",
    "typeface": "一种黑体",
    "sign_layout": "店名在门楣左侧，用途和电话分列门边铭牌",
    "street": "上层住宅窗户和湿润人行道",
    "materials": "涂料墙、直木柜台和偏低吊顶，没有铜框和大理石。",
    "lobby": "大厅吊顶偏低，前台是直木柜台，墙是涂料。",
    "room": "包厢偏小，沙发贴墙，是翻新过的小包厢。",
    "scale": "两开间，门脸占两个开间，招牌横跨这两个开间，大厅能并排站两位服务人员。",
    "style": "青砖",
    "grade": "小区",
}


class GroupPromptAssemblyTests(unittest.TestCase):
    def test_layers_stay_separate(self):
        rows = assemble_group(GROUP)
        self.assertEqual([row["id"] for row in rows], [shot["id"] for shot in SHOTS])
        storefront, lobby = rows[0], rows[1]
        self.assertEqual(storefront["layers"], ["medium", "viewpoint", "facade", "action", "sign", "exclude"])
        self.assertIn("13407128962", storefront["parts"]["sign"])
        self.assertNotIn("13407128962", storefront["parts"]["action"])
        self.assertIn("背影", storefront["parts"]["action"])
        self.assertNotIn("sign", lobby["layers"])
        self.assertNotIn("13407128962", lobby["prompt"])
        self.assertIn("服务人员", lobby["parts"]["action"])
        self.assertNotIn("女歌手", lobby["prompt"])
        self.assertIn("不放客人", lobby["parts"]["exclude"])
        self.assertIn("第一人称", rows[2]["parts"]["viewpoint"])
        self.assertIn("包厢门", rows[2]["parts"]["action"])
        for row in rows[2:]:
            self.assertNotIn("13407128962", row["prompt"])
            self.assertNotIn("18271918609", row["prompt"])
        self.assertNotIn("18271918609", storefront["prompt"])
        self.assertIn("晚叙", storefront["parts"]["sign"])
        self.assertIn("副标题单独一行写商务会所", storefront["parts"]["sign"])
        self.assertNotIn("晚叙商务会所", storefront["parts"]["sign"])
        self.assertNotIn("晚叙", lobby["prompt"])
        self.assertIn("大厅不写商务会所", lobby["prompt"])
        for row in rows[2:]:
            self.assertNotIn("晚叙", row["prompt"])
            self.assertNotIn("商务会所", row["prompt"])
            self.assertIn("不写店名", row["prompt"])
        shown = assemble_group({**GROUP, "lobby_name": "写出店名：前台立牌或前台背后可以出现同一块店名，只写这一处，不做成第二块大门招牌。"})
        self.assertIn("晚叙", shown[1]["prompt"])
        self.assertIn("商务会所", shown[1]["prompt"])
        self.assertNotIn("晚叙", shown[2]["prompt"])
        self.assertNotIn("商务会所", shown[2]["prompt"])

    def test_adjacent_group_must_change_several_axes(self):
        changed_name = {**GROUP, "store_name": "听潮"}
        with self.assertRaises(ValueError):
            assemble_group(changed_name, previous=GROUP)
        rows = assemble_group(NEXT_GROUP, previous=GROUP)
        self.assertIn("听潮", rows[0]["parts"]["sign"])
        self.assertIn("白天侧光", rows[0]["parts"]["facade"])
        self.assertIn("马路斜对面", rows[0]["parts"]["facade"])
        self.assertIn("直木柜台", rows[1]["parts"]["venue"])
        self.assertIn("翻新过的小包厢", rows[2]["parts"]["venue"])
        self.assertIn("窄开间", assemble_group(GROUP)[0]["parts"]["facade"])
        self.assertIn("两开间", rows[0]["parts"]["facade"])
        self.assertIn("两开间", rows[2]["parts"]["venue"])
        with self.assertRaises(ValueError):
            assemble_group({**NEXT_GROUP, "scale": GROUP["scale"]}, previous=GROUP)
        with self.assertRaises(ValueError):
            assemble_group({**NEXT_GROUP, "style": GROUP["style"]}, previous=GROUP)

    def test_phone_and_services_are_checked(self):
        with self.assertRaises(ValueError):
            assemble_group({**GROUP, "phone": "1340"})
        with self.assertRaises(ValueError):
            assemble_group({**GROUP, "services": ["商务宴请", "派对聚会"]})

    def test_new_variables_are_selected_together(self):
        first = select_group(7, "13407128962")
        second = select_group(8, "13407128962", previous=first["variables"])
        self.assertEqual(len(first["shots"]), 7)
        self.assertIn(first["variables"]["guest_clothes"], first["shots"][0]["prompt"])
        self.assertIn(first["variables"]["staff_posts"], first["shots"][1]["prompt"])
        self.assertIn(first["variables"]["singer_look"], first["shots"][2]["prompt"])
        self.assertNotIn(first["variables"]["singer_look"], first["shots"][1]["prompt"])
        changed = [key for key in ("store_name", "building", "light", "typeface", "sign_layout", "street") if first["variables"][key] != second["variables"][key]]
        self.assertGreaterEqual(len(changed), 4)
        for key in ("building", "photo", "lobby", "room", "scale", "style", "grade"):
            self.assertNotEqual(first["variables"][key], second["variables"][key])
        self.assertGreaterEqual(len(DECOR_STYLES), 20)
        self.assertEqual(len(SCALES), 3)
        self.assertEqual({item["grade"] for item in DECOR_STYLES}, {"高档", "小区"})
        self.assertGreaterEqual(sum(item["grade"] == "小区" for item in DECOR_STYLES), 10)
        self.assertEqual(len({item["name"] for item in DECOR_STYLES}), len(DECOR_STYLES))
        covered = {select_group(i, "13407128962")["variables"]["style"] for i in range(len(DECOR_STYLES))}
        self.assertEqual(covered, {item["name"] for item in DECOR_STYLES})
        left = select_group(30, "13407128962")
        right = select_group(31, "13407128962")["variables"]
        self.assertNotEqual(left["variables"]["scale"], right["scale"])
        self.assertNotEqual(left["variables"]["style"], right["style"])
        self.assertIn(left["variables"]["materials"], left["shots"][0]["prompt"])
        self.assertIn("副标题单独一行写商务会所", left["shots"][0]["prompt"])
        self.assertIn(left["variables"]["grade"], ("高档", "小区"))
        self.assertNotIn("商务会所", left["shots"][2]["prompt"])
        self.assertIn(left["variables"]["lobby"], left["shots"][1]["prompt"])
        self.assertIn(left["variables"]["room"], left["shots"][2]["prompt"])
        self.assertIn(first["variables"]["scale"], first["shots"][0]["prompt"])
        self.assertIn(first["variables"]["scale"], first["shots"][1]["prompt"])
        self.assertIn(first["variables"]["photo"], first["shots"][0]["prompt"])
        self.assertIn(first["variables"]["lobby"], first["shots"][1]["prompt"])
        self.assertNotIn(first["variables"]["room"], first["shots"][1]["prompt"])
        self.assertIn(first["variables"]["room"], first["shots"][2]["prompt"])
        name = first["variables"]["store_name"]
        self.assertIn(len(name), (2, 3))
        lengths = {len(select_group(i, "13407128962")["variables"]["store_name"]) for i in range(4)}
        self.assertEqual(lengths, {2, 3})
        self.assertIn(name, first["shots"][0]["prompt"])
        for shot in first["shots"][2:]:
            self.assertNotIn(name, shot["prompt"])
        if first["variables"]["lobby_name"].startswith("写出店名"):
            self.assertIn(name, first["shots"][1]["prompt"])
        else:
            self.assertNotIn(name, first["shots"][1]["prompt"])

    def test_shared_group_matches_project_contract(self):
        import json
        from pathlib import Path
        from tools import task_library as lib
        from tools import variable_catalog as vc
        from tools.task_groups import build_group
        root = Path(__file__).resolve().parents[1]
        definition = json.loads((root / "projects/business_ktv/project.json").read_text(encoding="utf-8"))
        group = definition["content_group"]
        rows = build_group("business_ktv", 1401, "13407128962", vc.load("business_ktv"), lib.business_config("business_ktv"))
        self.assertEqual(len(rows), group["generation_unit_count"])
        self.assertEqual([row["service_role"] for row in rows], [item["role"] for item in group["roles"]])
        self.assertEqual(rows[0]["kind"], "cover")
        self.assertIn("13407128962", rows[0]["prompt"])
        self.assertNotIn("18271918609", rows[0]["prompt"])
        self.assertTrue(all("13407128962" not in row["prompt"] for row in rows[1:]))
        self.assertIn("拍照：", rows[0]["prompt"])
        self.assertIn("的大厅", rows[1]["prompt"])
        self.assertIn("的包厢", rows[2]["prompt"])
        self.assertIn("背影", rows[0]["prompt"])
        self.assertIn("不放客人", rows[1]["prompt"])
        self.assertNotIn("缤纷果盘", "\n".join(row["prompt"] for row in rows))
