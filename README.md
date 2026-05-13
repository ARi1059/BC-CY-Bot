# BC-CY-Bot

[![Release](https://img.shields.io/badge/release-v1.0.0--beta.4-blue)](https://github.com/ARi1059/BC-CY-Bot/releases/tag/v1.0.0-beta.4)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)

一次性入群邀请审核 Telegram Bot —— 引导式申请、双消息审核、回群密钥救济、出击报告归档、日志频道审计，并提供完整的 **报销系统**（wizard + 审核 + 红包口令转发 + 月预算 + 周/月报）。

> 当前版本 **v1.0.0-beta.4**（口令发放员角色 + 行内代码口令 + 资格失败通用化）
>
> **📘 完整文档（功能 + 部署 + 操作）见 [GUIDE.md](GUIDE.md)**

---

## 功能概览

- **入群审核**：申请人 `/start` 引导式提交 3 项材料；自审型 / 代审型双模式；一次性邀请链接（`member_limit=1`，默认 24h）；`chat_member` 实际入群追踪 + 异常告警
- **报销系统**（与入群审核解耦）：申请人 `/reimburse` 选报销老师 → 提交材料 → 审核 → 口令发放员 DM 输入支付宝口令 → 行内代码转发给申请人；月预算 + 冷却天数 + 资格校验（AND 语义）+ 周/月报
- **回群密钥救济**：账号丢失/封禁后凭密钥换新链接；同 ID 拦截 + 7 条校验 + 原账号清理（踢/永封）
- **日志频道 / 出击报告频道**：6 类事件卡片，链接 URL 脱敏，禁止打扰频道观察者
- **管理员分层**：超管全局唯一（可转让，可经 `.env` 强制覆盖）；副管理员业务平权但不可任命/转让超管
- **零命令记忆**：所有操作通过 Inline 按钮完成，命令仅作入口（`/start`、`/admin`、`/panel`、`/reimburse`）

## 技术栈

Python 3.11+ · python-telegram-bot v21+ (async + JobQueue) · PostgreSQL 15 / SQLite · SQLAlchemy 2.0 async · Alembic · pydantic-settings · argon2-cffi · structlog · systemd

## 快速开始

> 完整搭建步骤见 [GUIDE.md §3](GUIDE.md#3-部署指南从零到生产)。

```bash
# 1. 系统包（Debian 12+ / Ubuntu 22.04+）
sudo apt update && sudo apt install -y python3 python3-venv postgresql postgresql-contrib build-essential libpq-dev git

# 2. 建库 + 建账号
sudo -u postgres psql -c "CREATE ROLE bccy LOGIN PASSWORD '强密码';"
sudo -u postgres createdb -O bccy bccy

# 3. 建运行账号 + 拉代码
sudo useradd --system --shell /usr/sbin/nologin --home /opt/BC-CY-Bot bccy
sudo git clone https://github.com/ARi1059/BC-CY-Bot.git /opt/BC-CY-Bot
sudo chown -R bccy:bccy /opt/BC-CY-Bot
cd /opt/BC-CY-Bot
sudo -u bccy git checkout v1.0.0-beta.4

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

- 私聊 Bot 发 `/start` → 欢迎卡片
- 超管发 `/admin` → 管理面板（含 `[⚙️ 系统配置]`）
- 邀请人发 `/panel` → 个人面板（需先在 `/admin → 邀请人管理` 添加）

## 环境变量

| 变量 | 必填 | 说明 |
|------|:--:|------|
| `BOT_TOKEN` | ✅ | Telegram Bot Token |
| `DATABASE_URL` | ✅ | 生产：`postgresql+asyncpg://bccy:密码@127.0.0.1:5432/bccy`；开发：`sqlite+aiosqlite:///./bccy_bot.db` |
| `INITIAL_SUPER_ADMIN_ID` | ✅ | 初始超级管理员 Telegram 数字 ID；后续启动若与 DB 不一致则**强制覆盖** |
| `LOG_LEVEL` | ⭕ | 默认 `INFO` |
| `TIMEZONE` | ⭕ | 默认 `Asia/Shanghai` |

## 本地开发

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

export BOT_TOKEN=...
export DATABASE_URL=sqlite+aiosqlite:///./bccy_bot.db
export INITIAL_SUPER_ADMIN_ID=...

.venv/bin/alembic upgrade head
.venv/bin/python -m bccy_bot
.venv/bin/pytest tests/ -v
```

## 文档

- [GUIDE.md](GUIDE.md) — 综合手册（功能 / 部署 / 首次配置 / 业务流程 / 管理员后台 / 升级备份 / 故障排查 / 命令速查）
- [`contrib/bccy-bot.service`](contrib/bccy-bot.service) — systemd unit 模板

## 许可证

私有项目。
