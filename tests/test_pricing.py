def test_midnight_reset_and_no_reset_on_scan(clean):
    stop=clean.pricing['stays'][0]
    assert [(s['day'],s['code'],s['minutes'],s['cents']) for s in stop['segments']]==[
        ('2026-11-30','FREE',10,0),('2026-11-30','BASE',10,200),
        ('2026-12-01','BASE',15,375),('2026-12-01','UPGRADE',10,500)]
    assert stop['due_cents']==1075


def test_cross_switch_stop_prices_each_minute_at_its_effective_version(clean):
    # 12/01 00:00 切换：同一停靠 11/30 分钟沿用旧费率，12/01 分钟进入新版。
    stop=clean.pricing['stays'][0]
    assert [(s['rate_version'],s['rate_cents']) for s in stop['segments']]==[
        ('rate-2026-11',0),('rate-2026-11',20),('rate-2026-12',25),('rate-2026-12',50)]


def test_new_stop_same_day_cross_berth_reuses_tier(clean):
    stop=clean.pricing['stays'][2]
    assert stop['berth']=='B-02'
    assert [(x['code'],x['cents'],x['rate_version']) for x in stop['segments']]==[('UPGRADE',750,'rate-2026-12')]


def test_deleted_appointment_never_spends_free_minutes(dirty):
    stop=dirty.pricing['stays'][1]
    assert stop['due_cents']==555
    assert [(s['day'],s['minutes']) for s in stop['segments']]==[('2026-11-30',14),('2026-12-01',11)]
    assert all(s['code']=='BASE' for s in stop['segments'])
    assert [s['rate_version'] for s in stop['segments']]==['rate-2026-11','rate-2026-12']


def test_disputed_time_is_not_charged(dirty):
    stop=dirty.pricing['stays'][3]
    assert [(x['code'],x['minutes'],x['cents']) for x in stop['segments']]==[
        ('BERTH_OVERLAP',2,0),('UPGRADE',2,100)]


def test_zero_charge_for_all_reserved_ten_minutes(clean):
    from app.billing.rates import price
    from app.curb.timeaxis import M
    stop=clean.identity['stays'][0]
    r=price([stop | {'end':stop['start']+10*M}],{},clean.ratebook)[0]
    assert (r['due_cents'],r['segments'][0]['minutes'])==(0,10)


def test_stay_segment_split_conserves_minutes_and_cost(dirty):
    for line in dirty.pricing['stays']:
        assert line['minutes']==sum(x['minutes'] for x in line['segments'])
        assert line['due_cents']==sum(x['rate_cents']*x['minutes'] for x in line['segments'])


def test_switch_scenarios_keep_historical_and_new_rate_totals(dirty):
    switch=dirty.pricing['switch']
    by_version={s['rate_version']:s for s in switch['scenarios']}
    # 旧费率整体重算即 CURB-1.0 历史应收 2240，新版统一计价为 2800。
    assert by_version['rate-2026-11']['due_cents']==2240
    assert by_version['rate-2026-12']['due_cents']==2800
    # 实际应收按停靠时刻混合取价，介于两版之间。
    assert switch['actual_due_cents']==2680
    assert by_version['rate-2026-11']['delta_cents']==2240-2680
    assert by_version['rate-2026-12']['delta_cents']==2800-2680


def test_switch_never_rewrites_minutes_before_cutover(clean):
    # 跨切换停靠在旧费率假设下的应收等于逐分钟旧价，确认切换不倒改历史分钟。
    stop=clean.pricing['stays'][0]
    old_minutes=sum(s['cents'] for s in stop['segments'] if s['rate_version']=='rate-2026-11')
    assert old_minutes==200
    scenario=next(s for s in clean.pricing['switch']['scenarios'] if s['rate_version']=='rate-2026-11')
    line=next(x for x in scenario['lines'] if x['stay']==stop['stay'])
    assert line['due_cents']==900
