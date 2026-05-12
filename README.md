# BC-CY-Bot

[![Release](https://img.shields.io/badge/release-v1.0.0--beta.2-blue)](https://github.com/ARi1059/BC-CY-Bot/releases/tag/v1.0.0-beta.2)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-154%20passed-brightgreen)](TESTING.md)

一次性入群邀请审核 Telegram Bot —— 引导式申请、双消息审核、回群密钥救济、出击报告归档、日志频道审计，
并提供完整的 **报销系统**（wizard + 审核 + 红包口令转发 + 月预算 + 周/月报）。

> 当前版本 **v1.0.0-beta.2**（报销金额按邀请人差异化），详细变更见 [CHANGELOG.md](CHANGELOG.md)。
>
> **📘 上手三件套**：
> - [搭建文档 DEPLOYMENT.md](DEPLOYMENT.md) — 从零部署到生产
> - [操作手册 OPERATIONS.md](OPERATIONS.md) — 所有业务流程 + 流程图
> - [E2E 测试清单 TESTING.md](TESTING.md) — 上线前逐项验证
>
> 详细需求规格见 [REQUIREMENTS.md](REQUIREMENTS.md)。

---

## 功能概览

- 申请人 `/start`：引导式 wizard（**禁用媒体组、严格单张提交**），3 项材料 → 预览 → 提交
- 邀请人审核：**双消息推送**（媒体组 + caption 报告 / 申请人信息 + 审核按钮），通过/拒绝二选一
- 自审型 / 代审型：代审型广播给所有管理员，**先到先得 + 行锁**
- 一次性入群链接：`member_limit=1`，24h 有效（超级管理员可在 `[⚙️ 系统配置]` 调整）
- chat_member 监听：实际入群即落库；**异常入群（实际入群 ID ≠ 申请人 ID）触发告警**
- **回群密钥**（救济通道）：账号丢失/封禁后凭密钥换新链接，**同 ID 拦截 + 7 条校验 + 原账号清理（踢/封）**
- 日志频道 / 出击报告频道：6 类事件卡片，禁止打扰频道观察者
- 主/副管理员分层：仅超级管理员可任命副管理员与转让身份
- 邀请人 `/panel` + 管理员 `/admin`：内联按钮全程引导，零命令记忆成本

---

## 技术栈

| 项 | 选型 |
|----|------|
| 语言 | Python 3.11+ |
| Bot 框架 | python-telegram-bot v21+ (async, 含 JobQueue) |
| 数据库 | PostgreSQL 15（生产）/ SQLite（开发） |
| ORM | SQLAlchemy 2.0 (async) |
| 迁移 | Alembic |
| 配置 | pydantic-settings + `.env` |
| 哈希 | argon2-cffi（回群密钥）|
| 日志 | structlog |
| 进程管理 | systemd（生产）|
| 运行环境 | 原生 Python 3.11+ venv + 原生 PostgreSQL 15+ |

---

## 快速开始

> 完整搭建文档（含每一步命令）见 [DEPLOYMENT.md](DEPLOYMENT.md)。下面只列骨架。

```bash
# 1. 系统包（Debian 12+ / Ubuntu 22.04+）
sudo apt update && sudo apt install -y python3 python3-venv \
  postgresql postgresql-contrib build-essential libpq-dev git

# 2. 建库 + 建账号
sudo -u postgres psql -c "CREATE ROLE bccy LOGIN PASSWORD '强密码';"
sudo -u postgres createdb -O bccy bccy

# 3. 建运行账号 + 拉代码
sudo useradd --system --shell /usr/sbin/nologin --home /opt/BC-CY-Bot bccy
sudo git clone https://github.com/ARi1059/BC-CY-Bot.git /opt/BC-CY-Bot
sudo chown -R bccy:bccy /opt/BC-CY-Bot
cd /opt/BC-CY-Bot
sudo -u bccy git checkout v1.0.0-beta.2

# 4. 装依赖
sudo -u bccy python3 -m venv .venv
sudo -u bccy .venv/bin/pip install .

# 5. 配置 .env
sudo -u bccy cp .env.example .env
sudo chmod 600 .env
sudo -u bccy nano .env    # 填 BOT_TOKEN / DATABASE_URL / INITIAL_SUPER_ADMIN_ID

# 6. 装 systemd + 启动
sudo cp contrib/bccy-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bccy-bot
sudo journalctl -u bccy-bot -f    # 等 super_admin_ensured
```

验证：
- Telegram 私聊 Bot 发 `/start` → 欢迎卡片
- 超管发 `/admin` → 管理面板（含 `[⚙️ 系统配置]`）
- 邀请人发 `/panel` → 个人面板（需先在 `/admin → 邀请人管理` 添加）

---

## 环境变量清单

| 变量 | 必填 | 说明 |
|------|:--:|------|
| `BOT_TOKEN` | ✅ | Telegram Bot Token |
| `DATABASE_URL` | ✅ | 生产：`postgresql+asyncpg://bccy:密码@127.0.0.1:5432/bccy`；开发：`sqlite+aiosqlite:///./bccy_bot.db` |
| `INITIAL_SUPER_ADMIN_ID` | ✅ | 初始超级管理员 Telegram 数字 ID（首次启动写入；后续启动若与 DB 中超管不一致则**强制覆盖**） |
| `LOG_LEVEL` | ⭕ | 默认 `INFO`（可选 DEBUG/WARNING/ERROR）|
| `TIMEZONE` | ⭕ | 默认 `Asia/Shanghai` |

---

## 升级流程

```bash
cd /opt/BC-CY-Bot
sudo -u bccy git fetch --tags
sudo -u bccy git checkout v1.0.0-beta.2
sudo -u bccy .venv/bin/pip install --upgrade .
sudo systemctl restart bccy-bot
sudo journalctl -u bccy-bot -f          # 确认 alembic upgrade head + super_admin_ensured
```

`bccy-bot.service` 在 `ExecStartPre` 会自动跑 `alembic upgrade head`，每次启动都会同步 schema。

---

## 应急换超管（账号丢失 / 被封）

1. SSH 登录服务器
2. 编辑 `/opt/BC-CY-Bot/.env`，把 `INITIAL_SUPER_ADMIN_ID` 改为**新超管的 Telegram 数字 ID**
3. 重启 Bot：`sudo systemctl restart bccy-bot`
4. Bot 启动时检测到 `INITIAL_SUPER_ADMIN_ID` 与数据库当前超管不一致，会**强制覆盖**：
   - 旧超管降级为副管理员（保留权限）
   - 新 ID 升级为超管
   - 操作写入 `audit_logs.action='override_super_admin'`，actor 标记为 `env_override`

完整设计见 [REQUIREMENTS.md §4.6](REQUIREMENTS.md)。

---

## 数据库备份

### 备份（每日定时任务示例）

```bash
sudo install -d -o bccy -g bccy /opt/BC-CY-Bot/backups
sudo -u postgres pg_dump bccy | gzip > /opt/BC-CY-Bot/backups/backup-$(date +%F).sql.gz
```

放入 root cron：

```cron
0 3 * * * /usr/bin/pg_dump -U bccy -h 127.0.0.1 bccy 2>>/opt/BC-CY-Bot/backups/dump.err | gzip > /opt/BC-CY-Bot/backups/backup-$(date +\%F).sql.gz && find /opt/BC-CY-Bot/backups -name "backup-*.sql.gz" -mtime +30 -delete
```

### 恢复

```bash
sudo systemctl stop bccy-bot       # 先停 Bot 避免写冲突
gunzip -c backup-2026-05-12.sql.gz | sudo -u postgres psql bccy
sudo systemctl start bccy-bot
```

---

## 本地开发

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# 用 SQLite 跑本地，免 PostgreSQL
export BOT_TOKEN=...
export DATABASE_URL=sqlite+aiosqlite:///./bccy_bot.db
export INITIAL_SUPER_ADMIN_ID=...

.venv/bin/alembic upgrade head
.venv/bin/python -m bccy_bot
```

测试：

```bash
.venv/bin/pytest tests/ -v
```

---

## 端到端联调清单

部署后建议按 [TESTING.md](TESTING.md) 逐项验证。所有联调用例覆盖：

1. ✅ 自审型完整流（申请 → 邀请人审核 → 链接 → 入群 → 日志频道 → 出击报告频道）
2. ✅ 代审型完整流（同上 + 多管理员并发，验证行锁）
3. ✅ 回群密钥完整流（正常账号被踢出旧群）
4. ✅ 回群密钥完整流（注销账号被永久封禁 + 加入黑名单）
5. ✅ 同 ID 拦截（原账号用密钥被拒）
6. ✅ 频率限制（密钥 1h/5 失败锁、claimer 24h/3 成功上限）
7. ✅ 黑名单拦截（被拉黑用户 `/start` 静默拒绝）
8. ✅ 链接过期未用（24h 后自动标记 + 日志频道告警）
9. ✅ 超级管理员 `.env` 换人
10. ✅ 副管理员越权拦截（点击 `[⚙️ 系统配置]` 被服务端拒绝）

---

## 项目结构

```
BC-CY-Bot/
├── REQUIREMENTS.md             需求规格
├── DEPLOYMENT.md               搭建文档（从零部署）
├── OPERATIONS.md               操作手册（含所有流程图）
├── CHANGELOG.md                版本变更记录
├── README.md                   本文件
├── TESTING.md                  端到端联调清单
├── contrib/bccy-bot.service    systemd unit 模板
├── alembic/                    数据库迁移
├── src/bccy_bot/
│   ├── config.py               pydantic-settings
│   ├── bot.py                  Application 装配
│   ├── db/models/              13 张表（每张一文件）
│   ├── repositories/           CRUD 层
│   ├── services/               业务编排
│   │   ├── wizard_service          申请人引导式状态机
│   │   ├── audit_service           审核（含双消息 / 行锁）
│   │   ├── invite_link_service     一次性链接
│   │   ├── recovery_key_service    回群密钥（7 条校验）
│   │   ├── account_cleanup_service 原账号踢/封
│   │   ├── link_tracking_service   chat_member 监听 + sweep
│   │   ├── log_channel_service     6 类事件卡片
│   │   ├── attack_report_service   出击报告转发
│   │   └── stats_service           邀请人 + 全局统计
│   ├── handlers/
│   │   ├── user/                   /start, wizard, recovery
│   │   ├── inviter/                /panel, audit
│   │   ├── admin/                  /admin + 11 子模块
│   │   └── common/                 chat_member 监听
│   ├── keyboards/                  Inline Keyboard 工厂
│   └── utils/                      retry, awaiting, tg_user, ...
└── tests/unit/                 92 用例
```

---

## 许可证

私有项目。
