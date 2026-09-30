from __future__ import annotations

import unittest

import generate_home_appliance_groups as home_groups


class HomeApplianceGroupTests(unittest.TestCase):
    def test_latest_cover_rules_include_physical_phone_and_real_shop(self) -> None:
        prompt, scene = home_groups.cover_prompt(26, "13317195304")
        self.assertIn("真实中国街边家电维修小门店", prompt)
        self.assertIn("realistic_mobile_documentary_v2", prompt)
        self.assertIn("家电维修", prompt)
        self.assertIn("13317195304", prompt)
        self.assertIn("真实物理招牌", prompt)
        self.assertIn("绝不能像后期平面贴字", prompt)
        self.assertIn("中间约一条横向区域", prompt)
        self.assertIn("画面底部约四分之一", prompt)
        self.assertTrue(scene["logo"])
        self.assertEqual(scene["visual_style_version"], "realistic_mobile_documentary_v2")
        self.assertEqual(scene["category_config_version"], "home_appliance_repair_category_content_v1")

    def test_fifty_groups_have_unique_cover_and_detail_compositions(self) -> None:
        covers, details, groups, production = home_groups.build_records(
            26,
            50,
            "13317195304",
        )
        self.assertEqual(len(covers), 50)
        self.assertEqual(len(details), 400)
        self.assertEqual(len(groups), 50)
        self.assertEqual(len(production), 450)
        self.assertEqual(len({item["prompt_sha256"] for item in [*covers, *details]}), 450)
        self.assertEqual(len({item["scene"]["composition_signature"] for item in covers}), 50)
        self.assertEqual(len({item["scene"]["logo"] for item in covers}), 50)
        for category in home_groups.DETAILS:
            category_records = [item for item in details if item["slug"] == category["slug"]]
            self.assertEqual(len(category_records), 50)
            self.assertEqual(
                len({item["scene"]["composition_signature"] for item in category_records}),
                50,
            )

    def test_production_records_keep_local_text_overlays(self) -> None:
        _, _, _, production = home_groups.build_records(26, 1, "13317195304")
        cover = production[0]
        self.assertEqual(cover["phone_bar_text"], "13317195304")
        self.assertEqual(cover["expected_text"], ["家电维修", "13317195304"])
        self.assertEqual(cover["visual_style_version"], "realistic_mobile_documentary_v2")
        self.assertEqual(
            [item["local_label"] for item in production[1:]],
            [item["title"] for item in home_groups.DETAILS],
        )
        self.assertTrue(all(item["visual_style_version"] == "realistic_mobile_documentary_v2" for item in production))


if __name__ == "__main__":
    unittest.main()
