import pytest

from app.billing.ratebook import build_ratebook
from app.billing.rates import LEGACY_BOOK, price, switch_difference
from app.problems import DocketError
from app.source.packet import bundle
from app.clearing import Clearing


def test_ratebook_picks_latest_version_not_after_minute():
    book = build_ratebook([
        {'version': 'old', 'effective_at': '2026-11-01T00:00+08:00',
         'base_cents': 20, 'upgrade_cents': 40},
        {'version': 'new', 'effective_at': '2026-12-01T00:00+08:00',
         'base_cents': 25, 'upgrade_cents': 50},
    ])
    from app.curb.timeaxis import minute
    assert book.version_at(minute('2026-11-30T23:59+08:00')).version == 'old'
    assert book.version_at(minute('2026-12-01T00:00+08:00')).version == 'new'
    assert book.version_at(minute('2026-12-01T00:01+08:00')).version == 'new'


@pytest.mark.parametrize('bad', [
    [],
    [{'version': 'only', 'effective_at': '2026-12-01T00:00+08:00', 'base_cents': 0, 'upgrade_cents': 40}],
    [{'version': 'only', 'effective_at': '2026-12-01T00:00+08:00', 'base_cents': 20, 'upgrade_cents': -1}],
    [{'version': 'a', 'effective_at': '2026-12-01T00:01+08:00', 'base_cents': 20, 'upgrade_cents': 40},
     {'version': 'a', 'effective_at': '2026-12-01T00:00+08:00', 'base_cents': 20, 'upgrade_cents': 40}],
    [{'version': 'b', 'effective_at': 'not-a-time', 'base_cents': 20, 'upgrade_cents': 40}],
    'nope',
])
def test_invalid_ratebook_is_rejected(bad):
    with pytest.raises(DocketError) as err:
        build_ratebook(bad)
    assert err.value.code == 'RATEBOOK_BAD'


def test_survey_without_rates_falls_back_to_legacy_book(tmp_path):
    files = bundle('clean')
    import json
    survey = json.loads(files['survey'])
    del survey['rates']
    files['survey'] = json.dumps(survey, ensure_ascii=False)
    clearing = Clearing(files, b'legacy')
    assert clearing.ratebook is LEGACY_BOOK
    assert clearing.pricing['due_cents'] == 2100


def test_bad_ratebook_rolls_back_and_keeps_prior_archive(client):
    # 先成功落档一份。
    first = client.post('/api/dockets', json={'sample': 'dirty'}).json()
    assert first['reused'] is False
    # 非法费率表整单失败，历史留档数量不增、旧版仍可读。
    files = bundle('dirty')
    import json
    survey = json.loads(files['survey'])
    survey['rates'][0]['base_cents'] = 0
    files['survey'] = json.dumps(survey, ensure_ascii=False)
    bad = client.post('/api/dockets', json={'bundle': files})
    assert (bad.status_code, bad.json()['code']) == (422, 'RATEBOOK_BAD')
    history = client.get('/api/dockets').json()['dockets']
    assert [row['key'] for row in history] == [first['key']]
    assert client.get('/api/dockets/' + first['key']).status_code == 200


def test_same_inputs_and_rate_version_rerun_adds_no_archive(client):
    a = client.post('/api/dockets', json={'sample': 'dirty'}).json()
    b = client.post('/api/dockets', json={'sample': 'dirty'}).json()
    assert a['key'] == b['key'] and b['reused'] is True
    assert len(client.get('/api/dockets').json()['dockets']) == 1
    # 留档内的费率版本表与证据摘要保持不变。
    record = client.get('/api/dockets/' + a['key']).json()
    assert [v['version'] for v in record['manifest']['rate_versions']] == ['rate-2026-11', 'rate-2026-12']


def test_changed_rate_version_creates_separate_archive_without_touching_history(client):
    import json
    files = bundle('clean')
    survey = json.loads(files['survey'])
    # 先以带区分标记的原件落档，避免与会话内其他 clean 留档撞键。
    survey['name'] = '费率切换隔离区'
    first = client.post('/api/dockets', json={'bundle': {**files, 'survey': json.dumps(survey, ensure_ascii=False)}}).json()
    survey['rates'][1]['base_cents'] = 30
    second = client.post('/api/dockets', json={'bundle': {**files, 'survey': json.dumps(survey, ensure_ascii=False)}}).json()
    assert second['key'] != first['key'] and second['reused'] is False
    keys = [row['key'] for row in client.get('/api/dockets').json()['dockets']]
    assert first['key'] in keys and second['key'] in keys
    # 旧留档的证据未被新费率倒改。
    old = client.get('/api/dockets/' + first['key']).json()
    assert old['evidence']['pricing']['due_cents'] == first['money']['due_cents'] == 2555
    assert second['money']['due_cents'] != 2555


def test_historical_archive_segments_keep_old_rate_before_cutover(client):
    key = client.post('/api/dockets', json={'sample': 'dirty'}).json()['key']
    record = client.get('/api/dockets/' + key).json()
    cross = next(s for s in record['evidence']['pricing']['stays']
                 if {seg['rate_version'] for seg in s['segments']} == {'rate-2026-11', 'rate-2026-12'})
    before = [seg for seg in cross['segments'] if seg['day'] == '2026-11-30' and seg['code'] != 'FREE']
    assert all(seg['rate_version'] == 'rate-2026-11' and seg['rate_cents'] == 20 for seg in before)


def test_switch_difference_reports_both_versions(dirty):
    result = switch_difference(dirty.identity['stays'], dirty.coverage[1], dirty.ratebook)
    names = [s['rate_version'] for s in result['scenarios']]
    assert names == ['rate-2026-11', 'rate-2026-12']
    assert result['actual_due_cents'] == 2680


def test_segments_carry_rate_version_for_dispute_and_free(clean):
    priced = price(clean.identity['stays'], {}, clean.ratebook)
    for stay in priced:
        assert all(seg['rate_version'].startswith('rate-2026-') for seg in stay['segments'])
