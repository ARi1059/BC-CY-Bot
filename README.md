# BC-CY-Bot

[![Release](https://img.shields.io/badge/release-v1.0.0--beta.1-blue)](https://github.com/ARi1059/BC-CY-Bot/releases/tag/v1.0.0-beta.1)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-148%20passed-brightgreen)](TESTING.md)

一次性入群邀请审核 Telegram Bot —— 引导式申请、双消息审核、回群密钥救济、出击报告归档、日志频道审计，
并提供完整的 **报销系统**（wizard + 审核 + 红包口令转发 + 月预算 + 周/月报）。

> 当前版本 **v1.0.0-beta.1**（首个公开 Beta），详细变更见 [CHANGELOG.md](CHANGELOG.md)。
> 详细需求见 [REQUIREMENTS.md](REQUIREMENTS.md)，开发过程见 [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md)。

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
| 容器 | Docker + docker-compose |

---

## 快速开始（Docker）

### 1. 准备 Bot Token 与初始管理员 ID

- 在 [@BotFather](https://t.me/BotFather) 创建 Bot，拿到 Token
- 将 Bot 拉入目标群组并设为管理员（赋"邀请用户"权限，未来需"封禁"权限做密钥清理）
- 在 Telegram 私聊 [@userinfobot](https://t.me/userinfobot) 拿到您的 Telegram **数字 ID**（初始超级管理员）

### 2. 配置 `.env`

```bash
cp .env.example .env
# 编辑 .env，填入下列必填项：
#   BOT_TOKEN=123456:ABC...
#   INITIAL_SUPER_ADMIN_ID=123456789
#   POSTGRES_PASSWORD=随机强密码
```

`.env` 已在 `.gitignore` 中排除，不会被提交。

### 3. 启动

```bash
docker compose up -d --build
docker compose logs -f bot         # 看日志确认 super_admin_ensured
```

首次启动会自动：
- 初始化 PostgreSQL
- `alembic upgrade head` 建表
- 把 `INITIAL_SUPER_ADMIN_ID` 写入 `admins` 表（role='super'）

### 4. 验证

- Telegram 私聊 Bot 发送 `/start` → 看到欢迎卡片
- 超级管理员发送 `/admin` → 进入管理面板
- 邀请人发送 `/panel` → 进入个人面板（需先在 `/admin` → 邀请人管理添加）

---

## 环境变量清单

| 变量 | 必填 | 说明 |
|------|:--:|------|
| `BOT_TOKEN` | ✅ | Telegram Bot Token |
| `INITIAL_SUPER_ADMIN_ID` | ✅ | 初始超级管理员 Telegram 数字 ID（首次启动写入；后续启动若与 DB 中超管不一致则**强制覆盖**） |
| `DATABASE_URL` | ⭕ | 默认由 docker-compose 注入 PostgreSQL 连接串；开发可用 `sqlite+aiosqlite:///./bccy_bot.db` |
| `LOG_LEVEL` | ⭕ | 默认 `INFO`（可选 DEBUG/WARNING/ERROR）|
| `TIMEZONE` | ⭕ | 默认 `Asia/Shanghai` |
| `POSTGRES_PASSWORD` | ⭕ | docker-compose 启动 postgres 服务时使用，默认 `bccy`（**生产请改强密码**）|

---

## 升级流程

```bash
git pull
docker compose build bot
docker compose up -d bot           # 重建 Bot 容器，PostgreSQL 容器保持
docker compose logs -f bot         # 确认迁移成功 + super_admin_ensured
```

容器启动命令是 `alembic upgrade head && python -m bccy_bot`，新版本带的 schema 变更会自动应用。

---

## 应急换超管（账号丢失 / 被封）

1. SSH 登录服务器
2. 编辑 `.env`，把 `INITIAL_SUPER_ADMIN_ID` 改为**新超管的 Telegram 数字 ID**
3. 重启 Bot：`docker compose restart bot`
4. Bot 启动时检测到 `INITIAL_SUPER_ADMIN_ID` 与数据库当前超管不一致，会**强制覆盖**：
   - 旧超管降级为副管理员（保留权限）
   - 新 ID 升级为超管
   - 操作写入 `audit_logs.action='override_super_admin'`，actor 标记为 `env_override`

完整设计见 [REQUIREMENTS.md §4.6](REQUIREMENTS.md)。

---

## 数据库备份

### 备份（每日定时任务示例）

```bash
docker compose exec -T postgres pg_dump -U bccy bccy | gzip > backup-$(date +%F).sql.gz
```

放入 cron：

```cron
0 3 * * * cd /path/to/BC-CY-Bot && docker compose exec -T postgres pg_dump -U bccy bccy | gzip > backups/backup-$(date +\%F).sql.gz
```

### 恢复

```bash
docker compose down bot      # 先停 Bot 避免写冲突
gunzip -c backup-2026-05-12.sql.gz | docker compose exec -T postgres psql -U bccy bccy
docker compose up -d bot
```

---

## 本地开发

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"

# 用 SQLite 跑本地：
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
├── DEVELOPMENT_PLAN.md         开发计划与执行日志
├── CHANGELOG.md                版本变更记录
├── README.md                   本文件
├── TESTING.md                  端到端联调清单
├── docker-compose.yml
├── Dockerfile
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
