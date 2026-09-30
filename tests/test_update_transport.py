import io
import os
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import URLError
from urllib.request import Request
from tools import update_protocol as p


class UpdateTransport(unittest.TestCase):
    def test_download_recovers_transient_connection_without_removing_size_limit(self):
        response = io.BytesIO(b'valid')
        response.headers = {'Content-Length': '5'}
        opener = MagicMock()
        opener.open.side_effect = [URLError('connection reset'), response]
        with patch.object(p, 'build_opener', return_value=opener):
            self.assertEqual(p.download('https://github.com/a/b', 5), b'valid')
        self.assertEqual(opener.open.call_count, 2)

    def test_oversize_response_is_not_retried(self):
        response = io.BytesIO(b'oversized')
        response.headers = {'Content-Length': '9'}
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(p, 'build_opener', return_value=opener):
            with self.assertRaises(ValueError):
                p.download('https://github.com/a/b', 5)
        self.assertEqual(opener.open.call_count, 1)

    def test_interrupted_mutation_is_not_repeated(self):
        opener = MagicMock()
        opener.open.side_effect = URLError('response lost')
        with patch.dict(os.environ, {'GH_TOKEN': 'isolated-test-token'}), patch.object(p, 'build_opener', return_value=opener):
            with self.assertRaises(URLError):
                p.github('POST', '/repos/a/b/releases', {'draft': True})
        self.assertEqual(opener.open.call_count, 1)

    def test_redirect_never_forwards_publisher_credential(self):
        request = Request('https://api.github.com/repos/a/b', headers={'Authorization': 'Bearer isolated-test-token'})
        with self.assertRaises(ValueError):
            p.Redirect().redirect_request(request, None, 302, '', {}, 'https://github.com/a/b')
