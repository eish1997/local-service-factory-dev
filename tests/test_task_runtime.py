import builtins
import unittest
from unittest.mock import patch
from tools import task_library as lib

class TaskRuntime(unittest.TestCase):
    def test_missing_sdk_blocks_before_launch(self):
        original=builtins.__import__
        def importing(name,*args,**kwargs):
            if name=='openai':raise ModuleNotFoundError("No module named 'openai'",name='openai')
            return original(name,*args,**kwargs)
        with patch('image_generate.load_project_env'),patch('image_generate.configured_api_keys',return_value=['offline']),patch('builtins.__import__',side_effect=importing):
            blocks,slots=lib.readiness('road_rescue',{}, {'business':{'service_items':['服务']}})
        self.assertEqual(slots,[1])
        self.assertTrue(any('缺少依赖 openai' in b for b in blocks))

    def test_sdk_import_does_not_call_api(self):
        with patch('image_generate.load_project_env'),patch('image_generate.configured_api_keys',return_value=['offline']),patch('openai.OpenAI') as client:
            blocks,slots=lib.readiness('road_rescue',{}, {'business':{'service_items':['服务']}})
        self.assertEqual(blocks,[])
        client.assert_not_called()

if __name__=='__main__':unittest.main()
