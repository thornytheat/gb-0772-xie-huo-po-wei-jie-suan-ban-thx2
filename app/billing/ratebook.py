"""费率版本表。

每个费率版本带一个生效时刻（UTC 对齐分钟）。某一计费分钟采用的费率，
取生效时刻不晚于该分钟的最新版本——即“停靠时刻适用费率”原则：跨费率
切换点的停靠，切换前的分钟沿用旧费率，切换后的分钟进入新版，补正班次
不会把整单历史分钟倒改成新费率。
"""
from dataclasses import dataclass
import re

from app.curb.timeaxis import minute
from app.problems import DocketError
from app.setup import FREE_MINUTES, TIER_LIMIT

VERSION_RE = re.compile(r'[A-Za-z0-9._-]{1,24}')


@dataclass(frozen=True)
class RateVersion:
    version: str
    effective_at: object          # UTC datetime，对齐分钟
    base_cents: int
    upgrade_cents: int
    free_minutes: int = FREE_MINUTES
    tier_limit: int = TIER_LIMIT

    def to_dict(self):
        return {'version': self.version, 'effective_at': self.effective_at.isoformat(),
                'base_cents': self.base_cents, 'upgrade_cents': self.upgrade_cents,
                'free_minutes': self.free_minutes, 'tier_limit': self.tier_limit}


@dataclass(frozen=True)
class RateBook:
    versions: tuple[RateVersion, ...]

    @property
    def current(self):
        return self.versions[-1]

    def version_at(self, when):
        """返回 when 时刻生效的费率版本（effective_at <= when 的最新版）。"""
        chosen = self.versions[0]
        for item in self.versions:
            if item.effective_at <= when:
                chosen = item
            else:
                break
        return chosen

    def rate_cents(self, code, when):
        item = self.version_at(when)
        if code == 'BASE':
            return item.base_cents, item.version
        if code == 'UPGRADE':
            return item.upgrade_cents, item.version
        return 0, item.version

    def fingerprint(self):
        return [item.to_dict() for item in self.versions]

    def named(self, name):
        for item in self.versions:
            if item.version == name:
                return item
        raise DocketError('RATE_VERSION_BAD', '留档引用了不存在的费率版本', 422)


def _positive_int(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= 1_000_000:
        raise ValueError
    return value


def build_ratebook(obj):
    """解析并校验费率版本表；任何非法项都抛 RATEBOOK_BAD，旧配置保持不变。"""
    if not isinstance(obj, list) or not 1 <= len(obj) <= 12:
        raise DocketError('RATEBOOK_BAD', '费率版本表需为 1–12 个版本的列表')
    parsed = []
    seen = set()
    previous = None
    for raw in obj:
        try:
            if not isinstance(raw, dict):
                raise ValueError
            name = raw['version']
            if not isinstance(name, str) or not VERSION_RE.fullmatch(name) or name in seen:
                raise ValueError
            seen.add(name)
            at = minute(raw['effective_at'])
            if previous is not None and at <= previous:
                raise ValueError
            previous = at
            base = _positive_int(raw['base_cents'])
            upgrade = _positive_int(raw['upgrade_cents'])
            free = _positive_int(raw.get('free_minutes', FREE_MINUTES))
            tier = _positive_int(raw.get('tier_limit', TIER_LIMIT))
        except (KeyError, TypeError, ValueError) as error:
            if isinstance(error, DocketError):
                raise
            raise DocketError('RATEBOOK_BAD', '费率版本字段、时刻或金额无效') from None
        parsed.append(RateVersion(name, at, base, upgrade, free, tier))
    return RateBook(tuple(parsed))
