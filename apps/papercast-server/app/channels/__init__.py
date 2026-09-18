"""渠道层（L3 发布）：一份物料 → 三个平台的统一投递契约。

见 base.py 顶部的分层说明；常用入口：
    from .channels import registry, Materials
    channels, problems = registry.resolve_targets(settings, run.config.publish.targets)
"""

from .base import Channel, Delivery, HttpChannel, Materials, Preflight
from . import registry, routes

__all__ = [
    "Channel",
    "Delivery",
    "HttpChannel",
    "Materials",
    "Preflight",
    "registry",
    "routes",
]
