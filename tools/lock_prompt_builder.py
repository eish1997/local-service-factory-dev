"""Pure lock-service builders shared by generation and dashboard preview."""
from tools import variable_catalog

@variable_catalog.managed("lock_service","cover")
def cover_prompt(variant, services, phones):
    service_text = ' '.join(services[:4])
    return f"真实中国街边开锁换锁门店首图，竖版9:16，手机实拍质感，不是海报、插画或精致连锁店。门店外观：{variant['facade']}。拍摄方式：{variant['angle']}。招牌配色：{variant['palette']}。主招牌文字醒目，写“开锁 换锁 配钥匙”；副招牌或玻璃贴字加入服务项目：{service_text}。店内或门口可见钥匙板、锁芯柜、智能锁样品、汽车钥匙壳、工具箱和小柜台。画面中间区域保留给后期电话条，不要把关键人脸、主要服务文字或核心锁具放在正中覆盖区域。门头招牌、玻璃贴字或门口服务牌上也要自然出现联系电话：{phones[0]}，数字必须清楚。不要生成价格、品牌名、人名、二维码、备案字样或未确认区域名称；中间仍会由后期再叠加醒目电话条。避免高度相似模板，真实街边小店环境，轻微旧墙面、玻璃反光和自然杂物可以保留。"

@variable_catalog.managed("lock_service","detail")
def detail_prompt(base_prompt, group_index, position):
    return f'{base_prompt} 作为第{group_index}组第{position}张详情图，画面与同组其他详情图保持服务行业一致，但人物姿态、室内外环境、工具摆放、拍摄距离和光线要有变化，避免同质化。'

