"""Licensed single-photo adapter using the existing factory API client and request."""
import hashlib
import io
from pathlib import Path
from PIL import Image
import image_generate
from tools import category_image_production as production


class ApiGenerator:
    backend = 'api'

    def __init__(self, config, slots):
        if (not slots or any(type(slot) is not int or slot < 1 for slot in slots)
                or len(set(slots)) != len(slots)):
            raise ValueError('正式样片必须显式指定可用Key槽位，禁止空列表扩展')
        self.api_config = {k: config.get(k, '') for k in ('model','quality','api_size','provider','base_url','output_format')}
        self.model = config['model']
        self.key_slots = slots
        self.clients = {}
        self.license_path = None

    def bind(self, state, directory, create=False):
        binding = {'job_id': state['job_id'], 'category_id': state['category_id'], 'planned_images': state['planned_images'],
                   'max_requests': state['max_requests'], 'api_config': self.api_config, 'key_slots': self.key_slots,
                   'vision_session': state['config']['vision_session']}
        self.license_path = Path(directory)/'license.json'
        if create:
            production.write_new_license(self.license_path, {**binding, 'one_time': True, 'status': 'active',
                'authorization': state['authorization'], 'used_requests': 0, 'created_at': production.now_iso(),
                'sdk_max_retries': 0})
        license = production.load_json(self.license_path)
        if any(license.get(k) != v for k,v in binding.items()):
            raise ValueError('本任务许可证与恢复配置不一致，禁止调用API')
        if license['used_requests'] > state['max_requests']:
            raise ValueError('许可证预算已损坏')

    def prepare_request(self, state, row, slot):
        license = production.load_json(self.license_path)
        if license['status'] != 'active' or slot not in license['key_slots']:
            raise ValueError('没有有效一次性许可或Key不在授权范围')
        if not 1 <= state['request_count'] <= license['max_requests'] or state['request_count'] <= license['used_requests']:
            raise ValueError('请求重复或超出任务预算')
        if not 1 <= row['index'] <= license['planned_images'] or row['attempts'] > 3:
            raise ValueError('目标或重试超出授权范围')
        if hashlib.sha256(row['prompt'].encode()).hexdigest() != row['prompt_sha256']:
            raise ValueError('提示词哈希不匹配')
        license.update(used_requests=state['request_count'], last_prompt_sha256=row['prompt_sha256'], last_slot=slot)
        production.atomic_json(self.license_path, license)

    def generate(self, record, slot):
        if slot not in self.clients:
            self.clients[slot] = production.openai_clients_by_slot(self.api_config, [slot])[0][1].with_options(timeout=180)
        payload = image_generate.generate_one(self.clients[slot], self.api_config, record['prompt'])
        from group_production import save_generated_image
        save_generated_image(Path(record['path']).with_suffix('.provider.bin'), payload)
        # Preserve exact provider bytes; validate decodability before materializing.
        with Image.open(io.BytesIO(payload)) as image:
            image.load()
            if min(image.size) < 512:
                raise ValueError('返回图片尺寸过小')
            record['provider_result'] = {'size': list(image.size), 'format': image.format,
                'requested_size': self.api_config['api_size'], 'source_sha256': hashlib.sha256(payload).hexdigest()}
            output = io.BytesIO()
            image.save(output,format='PNG')
        return output.getvalue()

    def finish(self, state):
        if self.license_path and self.license_path.exists():
            license = production.load_json(self.license_path)
            if state['status'] in ('completed','budget_exhausted'):
                license.update(status='consumed', finished_at=production.now_iso())
            production.atomic_json(self.license_path, license)
        for client in self.clients.values():
            client.close()
        self.clients.clear()
