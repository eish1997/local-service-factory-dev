import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image
from tools import single_image_test as module


class SingleImageTestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = dict(model='gpt-image-2.5-flare', provider='relay',
                           base_url='https://example.test/v1', quality='medium',
                           api_size='16x24', output_format='png')

    def run_test(self, **kwargs):
        return module.run(self.config, 'A kitten', 1, self.root / 'runtime',
                          self.root / 'output', **kwargs)

    def test_confirmation_required_before_any_files_or_client(self):
        with patch.object(module.production, 'openai_clients_by_slot') as clients:
            for flags in ({}, {'confirm_paid': True}):
                with self.assertRaises(RuntimeError):
                    self.run_test(**flags)
            clients.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_one_request_consumes_license_and_saves_image(self):
        payload = io.BytesIO()
        Image.new('RGB', (16, 24)).save(payload, 'PNG')
        client = Mock()
        def generate(client_arg, config, prompt):
            license_path = next((self.root / 'runtime/image_tests').glob('*/license.json'))
            self.assertEqual(json.loads(license_path.read_text())['status'], 'consumed')
            self.assertEqual(prompt, 'A kitten')
            return payload.getvalue()
        with patch.object(module.production, 'openai_clients_by_slot', return_value=[(1, client)]) as clients, \
             patch.object(module.image_generate, 'generate_one', side_effect=generate) as generate_one:
            result = self.run_test(confirm_paid=True, confirm_third_party=True)
        clients.assert_called_once_with(self.config, [1])
        generate_one.assert_called_once()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['request_count'], 1)
        self.assertTrue(Path(result['image']).is_file())
        client.close.assert_called_once()

    def test_failure_does_not_retry_or_store_exception_secret(self):
        with patch.object(module.production, 'openai_clients_by_slot', return_value=[(1, Mock())]), \
             patch.object(module.image_generate, 'generate_one', side_effect=RuntimeError('SECRET')) as generate:
            result = self.run_test(confirm_paid=True, confirm_third_party=True)
        generate.assert_called_once()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(json.loads(Path(result['license']).read_text())['status'], 'consumed')
        self.assertNotIn('SECRET', json.dumps(result))
