"""Read commands must never initialize catalog files or snapshots."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch
from tools import variable_catalog as vc

class CatalogReadOnly(unittest.TestCase):
    def test_missing_catalog_reads_defaults_without_writes(self):
        missing=vc.ROOT/'.runtime'/('readonly-missing-project-test-'+uuid.uuid4().hex)
        missing.mkdir()
        definition=(vc.project_dir('lock_service')/'project.json').read_bytes()
        (missing/'project.json').write_bytes(definition)
        with patch.object(vc,'project_dir',return_value=missing), patch.object(vc,'initialize',side_effect=AssertionError('read must not initialize')):
            for operation in ('list','history'):
                output=io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(vc.cli(argparse.Namespace(operation=operation,category='lock_service')),0)
                self.assertTrue(json.loads(output.getvalue())['ok'])
        self.assertEqual([p.name for p in missing.iterdir()],['project.json'])
        self.assertEqual((missing/'project.json').read_bytes(),definition)

if __name__=='__main__': unittest.main()
