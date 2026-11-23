# 深度登记 卸货泊位结算板

- 规模：中型
- 核心规则：先将跨传感器的同车同泊位占用取并集，再按到达时有效预约和本地自然日收费，保留逐单差价。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 停靠与预约采信 | 检查原结构、重复及同号冲突 | `GET /api/cases/dirty/intake` | `app/source/csvscan.py` `app/curb/detections.py` | `tests/test_intake.py` |
| M2 车牌匿名关联 | 用车辆代号关联到达时的预约版本 | `GET /api/cases/dirty/identity` | `app/source/plates.py` `app/curb/bookings.py` | `tests/test_identity.py` |
| M3 占用区间重建 | 查并集、去重分钟与争议格 | `GET /api/cases/dirty/occupancy` | `app/curb/merge.py` `app/curb/grid.py` | `tests/test_occupancy.py` |
| M4 首免与升级价计算 | 选择一次停靠查看跨日收费分段及采用的费率版本 | `GET /api/cases/dirty/pricing` | `app/billing/rates.py` `app/billing/ratebook.py` | `tests/test_pricing.py` `tests/test_rate_switch.py` |
| M5 应实收和泊位对账 | 查看逐单差价、费率切换应收对照、游离回执与泊位容量 | `GET /api/cases/dirty/settlement` | `app/billing/settle.py` `app/billing/payments.py` | `tests/test_settlement.py` |
| M6 批次留档复跑 | 原子落档、查历史及重放 | `POST /api/dockets` | `app/archive/docket.py` `app/archive/rerun.py` | `tests/test_docket.py` |
| M7 理赔证据签发 | 签发并核验脱敏证据、摘要与勾稽 | `GET /api/export/{key}` | `app/archive/appeal.py` `app/archive/canonical.py` | `tests/test_appeal.py` |

## 陷阱登记

| TRAP | 现象 | 直接处理的误差 | 处理 | 位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-02 | 杆侧 CSV 带 BOM | 识别首列失败 | 首位剥离 | `app/source/csvscan.py` | `tests/test_intake.py::test_started_with_bom` |
| TRAP-04 | 重复表头 | 表头被记作一次停靠 | 分段计数 | `app/source/csvscan.py` | `tests/test_intake.py::test_repeated_header_and_physical_count` |
| TRAP-05 | 残缺列含明文车牌 | 内容错列或隔离区泄露车牌 | 结构隔离、保留摘要 | `app/source/csvscan.py` | `tests/test_intake.py::test_ragged_row_keeps_hash_not_plaintext` |
| TRAP-07 | 回执金额 NULL | 误记零元回执 | 无效金额隔离并保留原值 | `app/billing/payments.py` | `tests/test_settlement.py::test_null_amount_never_looks_like_paid_zero` |
| TRAP-08 | 编号 0001 或 0007 | 数字转换丢零 | 原字符串贯穿 | `app/curb/detections.py` | `tests/test_intake.py::test_front_zero_id_survives_intake` |
| TRAP-11 | 同一时刻不同时区 | 分槽或重复占用 | 标准 UTC 对齐 | `app/curb/timeaxis.py` | `tests/test_occupancy.py::test_mixed_offsets_share_minute` |
| TRAP-14 | 同一检测编号出现两个结束时刻 | 输入顺序改变结果 | 冲突整组隔离 | `app/source/dedup.py` | `tests/test_intake.py::test_conflicting_sensor_event_never_last_wins` |
| TRAP-19 | 同泊多车和同车跨泊并存 | 多扣泊位分钟或漏掉争议 | 在各泊位分钟以同泊多车优先 | `app/curb/grid.py` | `tests/test_occupancy.py::test_collision_priority_matches_both_berths` |
| TRAP-23 | 两杆结束和开始同一分钟 | 重算端点或将一次停靠切开 | 半开并连续合并 | `app/curb/merge.py` | `tests/test_occupancy.py::test_touching_scans_single_stay` |
| TRAP-26 | 12/01 费率切换后跨零点补正 | 整单按新费率倒改已签收历史账 | 逐分钟取生效版本，历史分钟沿用旧费率 | `app/billing/rates.py` `app/billing/ratebook.py` | `tests/test_rate_switch.py::test_cross_switch_stop_prices_each_minute_at_its_effective_version` |
| TRAP-27 | 新费率表金额或时刻非法 | 半切换状态覆盖旧版 | 事务前校验，整单 `RATEBOOK_BAD` 回滚 | `app/billing/ratebook.py` `app/archive/rerun.py` | `tests/test_rate_switch.py::test_bad_ratebook_rolls_back_and_keeps_prior_archive` |
| TRAP-28 | 同原件重跑或费率表变更 | 重复留档或覆盖历史证据 | 归档键含费率版本指纹，变更另立留档 | `app/archive/rerun.py` | `tests/test_rate_switch.py::test_same_inputs_and_rate_version_rerun_adds_no_archive` |

## 对账规则

- 脏样检测源 27 = 格式可读 25 + 重复表头 1 + 列数隔离 1。可读 25 再扣车牌 1、范围与重复编号等 4，采信 20。
- 应管 240 = 空闲 133 + 争议 7 + 首免 10 + 基础价 68 + 升级价 22。分钟结构不随费率切换变化。
- 脏样按停靠时刻适用费率实际应收 2680 分；若整窗统一按旧版 `rate-2026-11`（20/40）计价为 2240 分，统一按新版 `rate-2026-12`（25/50）计价为 2800 分。实收 2310 分 − 实际应收 2680 分 = 逐单差价 −370 分，游离回执 140 分另列。
- 归档键以规则版本、费率版本指纹和输入全摘要生成，留档提交为单事务。重复提交取原运行快照，原件或费率表变动产生不同记录。

## 已知边界

只使用完整杆侧区间，传感器失明但缺少额外证据的分钟按空闲计算；覆盖不完整的窗口应由外部系统重采。回执关联使用准确到达分钟，不模糊猜测。退款、法定票据签章及跨区共享付费档位由外部流程处理。
