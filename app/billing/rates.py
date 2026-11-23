from collections import Counter
from datetime import UTC, datetime

from app.billing.ratebook import RateBook, RateVersion
from app.curb.timeaxis import LOCAL, M, span
from app.setup import BASE_CENTS, UPGRADE_CENTS

# 未在原件中声明费率版本表时使用的单一历史版本，保证旧原件仍可清算。
LEGACY_BOOK = RateBook((RateVersion('legacy-1.0', datetime(2000, 1, 1, tzinfo=UTC),
                                    BASE_CENTS, UPGRADE_CENTS),))


def _price_with(stops, disputes, book, fixed_version=None):
    """逐分钟核价。

    fixed_version 给出时，全部分钟强制按该版本计价（用于新旧费率对照的
    假设场景）；否则按每个分钟时刻生效的版本取价，即停靠时刻适用费率。
    """
    by_car_day = Counter()
    free_by_stay = Counter()
    by_stay = {r['stay']: [] for r in stops}
    ordered = sorted((when, s['berth'], s['stay'], s)
                     for s in stops for when in span(s['start'], s['end']))
    for when, berth, key, s in ordered:
        day = when.astimezone(LOCAL).date().isoformat()
        active = book.version_at(when)
        # 对照场景强制整窗按同一版本计价时，免额与档位也取该版本，保证口径一致。
        item = book.named(fixed_version) if fixed_version else active
        if (berth, when) in disputes:
            # 争议分钟免出账，版本标签仍记录停靠时刻的生效版本。
            code, cents, version = disputes[berth, when], 0, active.version
        elif (s['booking'] and when < s['booking']['end']
              and free_by_stay[key] < item.free_minutes):
            free_by_stay[key] += 1
            code, cents, version = 'FREE', 0, item.version
        else:
            counter = (s['vehicle'], day)
            if by_car_day[counter] < item.tier_limit:
                code, cents = 'BASE', item.base_cents
            else:
                code, cents = 'UPGRADE', item.upgrade_cents
            by_car_day[counter] += 1
            version = item.version
        by_stay[key].append((when, day, code, cents, version))
    output = []
    for s in stops:
        slices = []
        for when, day, code, cents, version in by_stay[s['stay']]:
            if not slices or (slices[-1]['day'], slices[-1]['code'],
                              slices[-1]['rate_version']) != (day, code, version):
                slices.append({'start': when.isoformat(), 'end': (when + M).isoformat(), 'day': day,
                               'code': code, 'rate_version': version, 'minutes': 0,
                               'rate_cents': cents, 'cents': 0})
            segment = slices[-1]
            segment.update(end=(when + M).isoformat(), minutes=segment['minutes'] + 1,
                           cents=segment['cents'] + cents)
        output.append(s | {'segments': slices,
                           'due_cents': sum(segment['cents'] for segment in slices)})
    return output


def price(stops, disputes, book=None):
    """按停靠时刻适用费率核价：跨切换点停靠的每分钟取当时生效版本。"""
    return _price_with(stops, disputes, book or LEGACY_BOOK)


def _versions_on_clock(book, stops):
    touched = set()
    for s in stops:
        for when in span(s['start'], s['end']):
            touched.add(book.version_at(when).version)
    return [item.version for item in book.versions if item.version in touched]


def rate_scenarios(stops, disputes, book):
    """同一原件分别按每个实际命中的费率版本整体重算，给出切换前后应收差额。

    实际应收取停靠时刻适用费率（跨切换点时为混合版本）；每个 scenario 是
    假设整窗只按某一版本统一计价的对照值，delta 为相对实际应收的差额。
    """
    actual = {item['stay']: item['due_cents']
              for item in _price_with(stops, disputes, book)}
    scenarios = []
    for name in _versions_on_clock(book, stops):
        item = book.named(name)
        rows = _price_with(stops, disputes, book, fixed_version=name)
        total = sum(r['due_cents'] for r in rows)
        scenarios.append({'rate_version': name,
                          'base_cents': item.base_cents,
                          'upgrade_cents': item.upgrade_cents,
                          'effective_at': item.effective_at.isoformat(),
                          'due_cents': total,
                          'delta_cents': total - sum(actual.values()),
                          'lines': [{'stay': r['stay'], 'due_cents': r['due_cents'],
                                     'delta_cents': r['due_cents'] - actual[r['stay']]}
                                    for r in rows]})
    return scenarios


def switch_difference(stops, disputes, book):
    """汇总同一原件在各费率版本下的应收，供清结算页核对切换差额。"""
    actual_rows = _price_with(stops, disputes, book)
    actual_due = sum(r['due_cents'] for r in actual_rows)
    scenarios = rate_scenarios(stops, disputes, book)
    applied = [{'stay': r['stay'],
                'rate_versions': sorted({seg['rate_version'] for seg in r['segments']})}
               for r in actual_rows]
    return {'actual_due_cents': actual_due, 'applied_versions': applied, 'scenarios': scenarios}
