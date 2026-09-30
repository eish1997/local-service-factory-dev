"""New production prompts respect persisted composition and local text plans."""
import unittest
from unittest.mock import patch

import generate_truck_rescue_groups as groups
from tools import category_image_production as production
from tools.truck_cover_typography import cover_plan
from tools.prompt_engine import CategoryPromptError


class Truck374EffectivePromptTests(unittest.TestCase):
    def record(self, index):
        library = groups._cover_library()
        variant = groups._cover_variant(library, index)
        return {
            "category_id": "truck_rescue", "group_index": index,
            "generation_kind": "cover", "cover_variant": variant,
            "prompt": groups._cover_positive_prompt(variant),
        }

    def prompt(self, record):
        with patch.object(production, "_approved_project_tuning_suffix", return_value=""):
            return production.effective_prompt(record, "13407128962")

    def test_future_full_batch_respects_each_layout_and_region(self):
        for index in range(374, 404):
            record = self.record(index)
            text = self.prompt(record)
            plan = cover_plan(index)
            phone_region = plan["center_phone_region"]
            services = plan["bottom_service_region"]
            self.assertIn(record["cover_variant"]["sign_information_layout"], text)
            self.assertIn(record["cover_variant"]["composition_emphasis"], text)
            self.assertIn("号码必须清楚准确写成“13407128962”", text)
            self.assertIn(f"中部{phone_region[1] * 100:g}%至{phone_region[3] * 100:g}%", text)
            self.assertIn(f"底部{services[1] * 100:g}%至{services[3] * 100:g}%", text)
            self.assertNotIn("中部43%至53.5%是本地电话条安全区", text)
            self.assertNotIn("推荐从上到下形成", text)
            self.assertIn("不强制门头、车间、前景工人三层同框", text)

    def test_historical_prompt_hierarchy_unchanged(self):
        text = self.prompt(self.record(373))
        self.assertIn("推荐从上到下形成两字寓意字号、行业尾缀、六类服务小字、联系电话四层信息", text)
        self.assertIn("中部43%至53.5%是本地电话条安全区", text)

    def test_future_missing_learning_version_rejected(self):
        record = self.record(374)
        record["cover_variant"].pop("reference_learning_version")
        with self.assertRaisesRegex(CategoryPromptError, "参考学习规则版本"):
            self.prompt(record)


if __name__ == "__main__":
    unittest.main()
