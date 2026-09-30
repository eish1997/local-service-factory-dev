"""Isolated, licensed single-image connectivity tests, without business overlays."""

import hashlib
import io
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

import image_generate
from tools import category_image_production as production


def run(config, prompt, slot, runtime_root, output_root, *, confirm_paid=False,
        confirm_third_party=False):
    if not confirm_paid:
        raise RuntimeError('Single-image testing requires explicit paid confirmation')
    if config.get('provider') == 'relay' and not confirm_third_party:
        raise RuntimeError('Relay testing requires third-party confirmation')
    if not prompt.strip() or slot < 1:
        raise ValueError('A prompt and one positive key slot are required')
    test_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + secrets.token_hex(4)
    evidence = Path(runtime_root) / 'image_tests' / test_id
    evidence.mkdir(parents=True, exist_ok=False)
    output = Path(output_root) / test_id
    output.mkdir(parents=True, exist_ok=False)
    license_path = evidence / 'license.json'
    record = {
        'version': 1, 'license_id': test_id, 'status': 'active', 'one_time': True,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'approved_count': 1, 'approved_request_budget': 1,
        'approved_model': config['model'], 'approved_quality': config['quality'],
        'approved_size': config['api_size'], 'approved_provider': config['provider'],
        'approved_base_url': config.get('base_url', ''),
        'start_index': 1, 'end_index': 1, 'api_key_slots': [slot],
        'sdk_max_retries': 0, 'auto_retry_limit': 0,
        'prompt': prompt, 'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
        'third_party_confirmed': confirm_third_party, 'output_dir': str(output),
    }
    production.atomic_json(license_path, record)
    result = {'test_id': test_id, 'status': 'preparing', 'request_count': 0,
              'model': config['model'], 'api_key_slot': slot, 'license': str(license_path)}
    result_path = evidence / 'result.json'
    production.atomic_json(result_path, result)
    client = None
    try:
        clients = production.openai_clients_by_slot(config, [slot])
        client = clients[0][1]
        image_generate.consume_execution_license(license_path, 1, config, 1, 1)
        result.update(status='requesting', request_count=1)
        production.atomic_json(result_path, result)
        # Exactly one generation call; the shared client disables SDK retries.
        payload = image_generate.generate_one(client, config, prompt)
        raw_path = output / 'response.bin'
        raw_path.write_bytes(payload)
        with Image.open(io.BytesIO(payload)) as image:
            image.load()
            actual_size = list(image.size)
            target = output / 'test_image.png'
            image.save(target, format='PNG')
        expected_size = [int(value) for value in config['api_size'].split('x')]
        result.update(status='completed' if actual_size == expected_size else 'size_mismatch',
                      image=str(target), size=actual_size, expected_size=expected_size,
                      image_sha256=hashlib.sha256(target.read_bytes()).hexdigest())
    except Exception as error:
        # Provider exception text can contain secrets or signed URLs; store only type/status.
        result.update(status='failed', error_type=type(error).__name__,
                      http_status=getattr(error, 'status_code', None))
    finally:
        if client is not None:
            client.close()
        result['finished_at'] = datetime.now(timezone.utc).isoformat()
        production.atomic_json(result_path, result)
    return result
