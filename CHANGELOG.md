# Changelog

本文件遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 风格，
版本号遵循 [PEP 440](https://peps.python.org/pep-0440/) 与 [SemVer](https://semver.org/lang/zh-CN/)。

---

## Unreleased

### Changed
- **部署形态从 Docker 切换为原生 systemd + 原生 PostgreSQL**。`Dockerfile` 与 `docker-compose.yml` 移除；新增 `contrib/bccy-bot.service` systemd unit 模板。
- DEPLOYMENT.md / README.md / TESTING.md / OPERATIONS.md 全部刷新为 systemd 路径与 `journalctl` 日志检索方式。
- `.env.example` 的 `DATABASE_URL` 默认值改为本机 PostgreSQL 连接串；移除 Docker 专属的 `POSTGRES_PASSWORD`。

### Migration
旧的 Docker 部署 → 新原生部署的迁移路径：
1. `docker compose exec -T postgres pg_dump -U bccy bccy > backup.sql` 导出现有数据
2. 在目标主机按 [DEPLOYMENT.md §2–§3](DEPLOYMENT.md) 装原生 PG + 建账号 + 建 db
3. `psql -U bccy -h 127.0.0.1 -d bccy -f backup.sql` 恢复数据
4. `pip install .` + 装 systemd unit 后 `systemctl enable --now bccy-bot`
5. 验证 `journalctl -u bccy-bot` 看到 `super_admin_ensured` → 成功

> 旧的 docker-compose stack 可保留几天作为应急回滚来源，再删除。

---

## [1.0.0-beta.2] - 2026-05-12

报销金额从"全局一档"切换为"按邀请人差异化"。每位邀请人在 100 / 150 / 200 元三档中由超级管理员选定其一；
申请人 `/reimburse` 时自动按其入群邀请人的档位结算，不再让申请人选金额。

### Added
- `inviters.reimbursement_tier_cents` 新列（NOT NULL，server_default `10000` = 100 元），新建迁移 `a1b2c3d4e5f6`
- `REI_TIER_VALUES_CENTS = (10000, 15000, 20000)` 与 `REI_TIER_LABELS` 常量（写死，不允许任意金额）
- `inviter_repo.update_tier(session, inviter, cents)` 辅助函数，含三档校验
- 邀请人添加 wizard 新增"步骤 7/7 · 选择报销档位"，对应 callback `admin:inviters:at:<cents>`
- 邀请人管理列表每行新增「💰 调档位」子键盘（callback `admin:inviters:to:<id>` 打开，`admin:inviters:tv:<id>:<cents>` 落库）
- 单元测试：`test_inviter_tier_defaults_to_100_yuan`、`test_inviter_tier_create_with_value_and_update_tier`、`test_precheck_uses_inviter_tier`（参数化覆盖三档）、`test_precheck_no_inviter_tier_when_application_has_no_inviter`

### Changed
- `precheck()` 通过 `application.inviter_id → inviter.reimbursement_tier_cents` 取金额；
  `PreCheckResult.fixed_amount_cents` 改名为 `amount_cents`
- 报销主面板与系统配置面板显示"金额档位：由各邀请人独立设定（100/150/200 元）"，指引到「🎓 邀请人管理」
- 邀请人列表每行的标签按钮文案带上"💰{tier}元"，肉眼可读

### Removed
- 全局 `SK_REI_FIXED_AMOUNT_CENTS` 设置项 + `get/set_fixed_amount_cents` 辅助函数
- 报销系统配置面板的「✏️ 设置固定金额」按钮、`AWAIT_REI_AMOUNT` 状态、`on_set_amount` 处理器
- `test_settings_*` 中针对 fixed_amount 的断言；保留新增的 inviter tier 用例
- 已部署实例升级时，migration 一并 `DELETE FROM settings WHERE key='reimbursement_fixed_amount_cents'`

### Upgrade
```bash
git pull
git checkout v1.0.0-beta.2
docker compose build bot
docker compose up -d bot
docker compose logs -f bot   # 确认 alembic upgrade head 到 a1b2c3d4e5f6
```
升级后请在「🎓 邀请人管理」检查每位邀请人的档位（默认 100 元），按需调整。

---

## [1.0.0-beta.1] - 2026-05-12

首个公开 Beta。完整覆盖 v1 入群审核（M0–M10）与 v2 报销系统（M11–M14），
148/148 单元测试通过，99 个 handler 注册，PostgreSQL/SQLite 双数据库验证。

### 核心能力（v1：一次性入群邀请审核）

- **申请人 wizard**：`/start` 引导式 3 项材料提交，严格单张、禁用媒体组、预览后提交
- **邀请人审核**：双消息推送（媒体组+caption 报告 / 申请人信息+审核按钮），
  通过/拒绝二选一，长报告（>1024 字）自动降级为三消息
- **自审 / 代审双模式**：代审型广播全部管理员，DB 行锁 `SELECT FOR UPDATE` 保证先到先得
- **一次性邀请链接**：`member_limit=1`，TTL 可在面板调节（默认 24h，1–168h clamp）
- **chat_member 监听**：实际入群即落库；申请人 ID ≠ 入群 ID 触发异常告警
- **回群密钥救济**：argon2 哈希存储，7 条校验顺序、同 ID 拦截、频率限制、
  原账号自动踢/封 + 注销账号识别 + 本地黑名单写入
- **日志频道 / 出击报告频道**：6 类事件卡片，链接 URL 脱敏，永不打扰频道观察者
- **主/副管理员分层**：仅超管可任命副管理员与转让身份，`uq_one_super_admin` 部分唯一索引保证唯一
- **超管应急换人**：`.env` 中 `INITIAL_SUPER_ADMIN_ID` 与 DB 不一致时强制覆盖
- **邀请人面板**：`/panel` 个人统计（接单数、通过率 Top 10、近期记录）
- **管理员面板**：`/admin` 11 子模块，所有写操作落 `audit_logs`

### 核心能力（v2：报销系统）

- **报销 wizard**：用户 `/reimburse` 引导提交 3 项材料，4 层预校验
  （全局开关 / 必须有 approved 申请 / 不能有进行中申请 / 冷却 / 月预算）
- **资格成员校验**：群/超群/频道任意一项满足即可，bot_data 5 分钟缓存（仅 success）
- **审核 + 红包转发**：审核通过 → 等待管理员粘贴支付宝口令（5 分钟时效）→ 自动转发申请人
- **月预算 + 重置日**：金额统一以分（cents）存储，避免浮点误差；
  每天 00:00:05 检查重置日，每月自动回填预算余额
- **周报 / 月报**：JobQueue 每日 00:05/00:10 触发，周一/月 1 号才推送给所有超管
- **管理面板**：`[💰 报销管理]` 入口 → 待审核 / 待付款补发 / 历史 / 系统配置 / 资格列表 / 用户冷却覆盖
- **用户冷却覆盖**：单用户白名单格式 `user_id days [notes]`，upsert 写入

### 工程基线

- Python 3.11+ / python-telegram-bot v21+（实测 22.7）/ SQLAlchemy 2.0 async
- 13+5=18 张表 + 4 个 Alembic migration（初始 schema、审核消息、链接过期标记、报销基础设施）
- 多阶段 Dockerfile（builder + runtime，非 root 运行）
- `docker compose up -d --build` 一键启动，环境变量统一 `.env`
- 148 个单元测试，覆盖服务层全部业务路径与状态机分支
- 70+ 端到端联调用例（TESTING.md），含报销 §14 全流程

### 已知限制

- 回群密钥管理 UI 仍是占位（管理面板 §M5），密钥仅可在 audit_logs 间接查询
- 用户主动重置密钥（1 次/天频控）—— `recovery_reset_throttle` 表已就绪，handler 未上线
- 仅中文文案，未做 i18n
- 申请材料后台导出（CSV）未实现

### 升级 / 部署

```bash
git pull
docker compose build bot
docker compose up -d bot
docker compose logs -f bot   # 等待 super_admin_ensured + alembic upgrade head
```

部署后请按 [TESTING.md](TESTING.md) 走 v1 + v2 E2E 全套用例。

---

[1.0.0-beta.2]: https://github.com/ARi1059/BC-CY-Bot/releases/tag/v1.0.0-beta.2
[1.0.0-beta.1]: https://github.com/ARi1059/BC-CY-Bot/releases/tag/v1.0.0-beta.1
