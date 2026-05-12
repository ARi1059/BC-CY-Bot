# BC-CY-Bot 搭建文档

> 适用版本：**v1.0.0-beta.2**
> 部署形态：**原生 Python + PostgreSQL + systemd**（不使用 Docker）
> 目标系统：Debian 12+ / Ubuntu 22.04+（apt 系；其他发行版按需替换包管理命令）
> 适用读者：第一次部署 BC-CY-Bot 的运维 / DevOps / 主理人
> 预计耗时：30–60 分钟

本文档覆盖**从零到生产可用**的全部步骤。如果你只是要升级旧版本，跳到 [§9 升级流程](#9-升级流程)。

---

## 0. 速览：你需要准备的东西

| 项 | 要求 |
|---|---|
| 服务器 | 1 台 Debian 12+ / Ubuntu 22.04+ 主机，1 vCPU / 1 GB 内存起步，能 ssh 登录 |
| Python | 3.11+（Debian 12 自带 3.11；Ubuntu 22.04 需通过 deadsnakes PPA） |
| PostgreSQL | 15+（apt 装系统包；本机监听 127.0.0.1:5432）|
| systemd | 默认就有（任何主流 Linux 发行版）|
| Telegram | 1 个 Bot Token（@BotFather）+ 你的 Telegram 数字 ID |
| 目标群 | 1 个 Bot 已被设为管理员的私密群组 |
| 日志 / 出击报告频道（可选） | Bot 主动写入：6 类事件卡片 + 出击报告归档，各 1 个 |
| 对外广播频道（可选） | 运营自己发内容；如启用报销，**用户必须订阅这些频道才能领报销**，常见 1–3 个 |
| 报销资格群（可选） | 同样作为报销资格成员校验的目标，常见 1+ 个 |

> 💡 出站只需要 HTTPS 到 `api.telegram.org`，无任何入站端口要求（Bot 是 Polling 模式）。

---

## 1. Telegram 侧准备

### 1.1 创建 Bot 并获取 Token

1. Telegram 私聊 [@BotFather](https://t.me/BotFather) → 发 `/newbot`
2. 输入 Bot 显示名（任意）→ 输入 username（必须以 `bot` 结尾，全局唯一）
3. 收到形如 `123456789:AAH...` 的 Token → 妥善保存（这是后面 `.env` 里要用的 `BOT_TOKEN`）
4. 顺手把 Bot 的隐私模式关掉，方便后续群操作：发 `/setprivacy` → 选刚才的 Bot → `Disable`

### 1.2 获取你的 Telegram 数字 ID

1. 私聊 [@userinfobot](https://t.me/userinfobot) → 它会直接回复你的 `id`（一串数字）
2. 保存这个 ID —— 这是后面 `INITIAL_SUPER_ADMIN_ID`

### 1.3 准备目标群组

1. 新建一个**私密**群组（不要"公开链接"型，因为本系统颁发的是一次性邀请链接）
2. 把刚创建的 Bot 加进群
3. 群设置 → 管理员 → 添加 Bot 为管理员，**至少勾选**这两项：
   - ✅ Invite Users via Link（邀请用户）
   - ✅ Ban Users（封禁用户 —— 注销账号清理需要）
   - 其他不勾也行
4. 记下群的 telegram_chat_id（首次启动后会通过"转发群里任一条消息给 Bot"来识别，**这里不需要预先记**）

### 1.4 准备所有相关频道

本系统涉及 **4 类频道**，按用途分两组：

**A. Bot 主动写入的内部频道（运营管理用，可选但强烈推荐）**

| 频道 | 用途 | Bot 权限要求 |
|---|---|---|
| 日志频道 | 6 类事件卡片：新申请 / 通过 / 拒绝 / 链接已用 / 链接过期 / 密钥使用 / 报销 5 状态 | 管理员 + Post Messages |
| 出击报告频道 | 仅转发申请人提交的"出击报告"文本，归档用 | 管理员 + Post Messages |

**B. 面向大众的广播频道（运营自己发内容，Bot 只校验成员身份）**

| 频道 | 用途 | Bot 权限要求 |
|---|---|---|
| 广播频道 #1 | 运营对外发布课程通知等，**报销资格强制订阅** | 管理员（仅为了 `getChatMember` 能查到成员状态）|
| 广播频道 #2 | 同上（如有多个则按此模式追加）| 同上 |

> ⚠️ **关键设计**：用户必须**同时**是所有"资格条目"（含广播频道 + 报销资格群）的成员，才能申请报销 —— AND 语义，缺一不可。这是 [REQUIREMENTS §8.5.7](REQUIREMENTS.md) 的硬约束。

#### 每个频道的通用配置步骤

1. 新建一个频道（私有/公开按运营需要）
2. 把 Bot 添加为管理员
3. A 类（日志/出击报告）勾选 **Post Messages**；B 类（广播）不需要 Post 权限，仅作为成员名册让 Bot 能 `getChatMember`
4. 不需要预先记 chat_id —— 后续在 `/admin` 面板里转发该频道任一条消息即可识别绑定

> 💡 **为什么 B 类也要把 Bot 设为管理员？** 对私有频道，Bot 必须是管理员才能查 `getChatMember`。如果是公开频道，普通成员身份也行，但管理员最稳妥。

---

## 2. 服务器侧准备

以 Debian 12 为例，全程需要 root 或 sudo 权限。

### 2.1 系统包

一行命令装齐所有依赖（直接整行复制粘贴，**不要**只复制中间几个包名 —— 反斜杠续行容易在粘贴时丢首行）：

```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip postgresql postgresql-contrib build-essential libpq-dev git curl
```

验证：

```bash
python3 --version                  # 应 ≥ 3.11
psql --version                     # 应 ≥ 15
systemctl is-active postgresql     # 应输出 active
```

> 💡 Debian 12 自带 Python 3.11；Debian 11 / Ubuntu 22.04 自带 Python 3.10，可能需要从 deadsnakes PPA 或源码装 3.11。

### 2.2 PostgreSQL：建库 + 建账号

PostgreSQL 装好后默认服务已启动。切到 `postgres` 系统账号建库：

```bash
sudo -u postgres psql <<'EOF'
CREATE ROLE bccy WITH LOGIN PASSWORD '请改成强密码';
CREATE DATABASE bccy OWNER bccy ENCODING 'UTF8';
GRANT ALL PRIVILEGES ON DATABASE bccy TO bccy;
\c bccy
GRANT ALL ON SCHEMA public TO bccy;
EOF
```

> 💡 把 `'请改成强密码'` 换成 `openssl rand -base64 24` 生成的强密码，保存好，后面 `.env` 要用。

验证可登：

```bash
PGPASSWORD='你的密码' psql -h 127.0.0.1 -U bccy -d bccy -c '\dt'
# 当前没建表，输出 "Did not find any relations." 是正常的
```

### 2.3 创建运行账号（用于 systemd 跑 Bot）

```bash
sudo useradd --system --shell /usr/sbin/nologin --home /opt/BC-CY-Bot bccy
```

不可登录、无家目录的系统账号，仅用于跑 Bot 进程。

### 2.4 防火墙（如有）

Bot 走 Polling，**不需要任何入站端口**。出站确保 TCP 443 能到 `api.telegram.org`（几乎所有云默认放行）。

---

## 3. 拉代码 + 准备运行环境

### 3.1 克隆仓库

```bash
sudo git clone https://github.com/ARi1059/BC-CY-Bot.git /opt/BC-CY-Bot
sudo chown -R bccy:bccy /opt/BC-CY-Bot
cd /opt/BC-CY-Bot
sudo -u bccy git checkout v1.0.0-beta.2   # 锁到当前最新 Beta
```

### 3.2 建虚拟环境 + 装依赖

```bash
sudo -u bccy python3 -m venv .venv
sudo -u bccy .venv/bin/pip install --upgrade pip
sudo -u bccy .venv/bin/pip install .
```

依赖（`pyproject.toml` 已声明）：`python-telegram-bot`、`SQLAlchemy[asyncio]`、`alembic`、`asyncpg`、`aiosqlite`、`pydantic-settings`、`structlog`、`argon2-cffi`、`greenlet`。

### 3.3 编写 `.env`

```bash
sudo -u bccy cp .env.example .env
sudo chmod 600 .env       # 只让 bccy 自己能读
sudo -u bccy nano .env
```

填入：

```dotenv
# 必填
BOT_TOKEN=123456789:AAH................（§1.1 拿到的）
DATABASE_URL=postgresql+asyncpg://bccy:你在§2.2用的强密码@127.0.0.1:5432/bccy
INITIAL_SUPER_ADMIN_ID=987654321        （§1.2 拿到的数字 ID）

# 可选（默认即可）
LOG_LEVEL=INFO
TIMEZONE=Asia/Shanghai
```

`.env` 已在 `.gitignore` 中排除，不会被 Git 跟踪。

### 3.4 验证（手动跑一遍迁移 + 启动）

```bash
sudo -u bccy bash -c 'set -a; source .env; set +a; .venv/bin/alembic upgrade head'
```

成功会输出 5 个 migration 顺序执行，最后到 `a1b2c3d4e5f6 (add inviter reimbursement tier)`。

试运行（前台）：

```bash
sudo -u bccy bash -c 'set -a; source .env; set +a; .venv/bin/python -m bccy_bot'
```

看到 `super_admin_ensured action=created admin_id=<你的ID>` → 一切正常，`Ctrl+C` 退出，去 §4 装 systemd。

---

## 4. 装 systemd 服务 + 启动

仓库自带一份现成的 unit 模板 `contrib/bccy-bot.service`，可直接复制。

### 4.1 部署 unit 文件

```bash
sudo cp /opt/BC-CY-Bot/contrib/bccy-bot.service /etc/systemd/system/bccy-bot.service
sudo systemctl daemon-reload
```

> 💡 如果你装在 `/opt/BC-CY-Bot` 之外的路径，需要先把 unit 里的 `WorkingDirectory` / `EnvironmentFile` / `ExecStart` 三处路径同步修改。

### 4.2 启动 + 开机自启

```bash
sudo systemctl enable --now bccy-bot
sudo systemctl status bccy-bot           # 应为 active (running)
```

### 4.3 看日志确认成功

```bash
sudo journalctl -u bccy-bot -f
```

等待出现：

```
INFO  alembic.runtime.migration Running upgrade ... -> a1b2c3d4e5f6, add inviter reimbursement tier
INFO  bccy_bot.bot  super_admin_ensured action=created admin_id=987654321
```

看到 = 成功。`Ctrl+C` 退出日志流（服务还在跑）。

### 4.4 验证 Bot 在线

| 步骤 | 预期 |
|---|---|
| 在 Telegram 私聊你的 Bot，发 `/start` | 收到欢迎卡片，含 `[🚀 开始申请入群]` `[🔑 使用回群密钥]` `[💰 申请报销]` 按钮 |
| 用 §1.2 那个超管账号私聊 Bot，发 `/admin` | 收到管理面板，含 `[⚙️ 系统配置]`（普通管理员看不到这个） |

两条通过 → Bot 上线，去 §5 配置。失败 → 看 §10 排错。

---

## 5. 首次配置（管理员侧）

按这个顺序在 Telegram 里完成所有初始化。每一步都对应面板上的一个按钮，没有命令行操作。

```mermaid
flowchart LR
  A[1. 添加群组] --> B[2. 绑定日志频道]
  B --> C[3. 绑定出击报告频道]
  C --> D[4. 添加邀请人]
  D --> E[5. 报销系统配置]
  E --> F[6. 邀请申请人测试]
```

### 5.1 添加目标群组

1. `/admin` → `[👥 群组管理]` → `[➕ 添加群组]`
2. 把 §1.3 那个目标群里任意一条消息**转发**给 Bot
3. Bot 识别 `chat_id` 后回复"群组已添加"

### 5.2 绑定日志频道

1. `/admin` → `[📡 日志频道]` → `[➕ 绑定频道]`
2. 把 §1.4 日志频道里任意一条消息转发给 Bot
3. 看到"已绑定"

### 5.3 绑定出击报告频道

同 5.2，入口是 `[📋 出击报告频道]`。

### 5.4 添加第 1 个邀请人

`/admin` → `[🎓 邀请人管理]` → `[➕ 添加邀请人]`，按 7 步引导：

| 步骤 | 操作 |
|---|---|
| 1/7 | 发送邀请人的 Telegram 数字 ID（让对方私聊 @userinfobot 拿）；或 `/skip` 表示挂名 |
| 2/7 | 发送显示名（如 "张老师"） |
| 3/7 | 发送组别名（如 "A组"） |
| 4/7 | 从按钮中选择目标群组 |
| 5/7 | 多选所需材料（约课记录 / 上课手势 / 出击报告） |
| 6/7 | 选审核模式：👤 自审型 / 🏢 代审型 |
| 7/7 | 选报销档位：💰 100 / 150 / 200 元 |

最后确认创建。

> 💡 自审型 = 邀请人本人审核自己引荐的申请人；代审型 = 所有管理员都能审核（先到先得）。如果是"挂名"邀请人（步骤 1 选 /skip），只能用代审型。

### 5.5 配置报销系统（如不需要报销可跳过）

#### 5.5.1 系统配置

`/admin` → `[💰 报销管理]` → `[📋 系统配置]`：

1. `[▶️ 开启总开关]`
2. `[✏️ 设置月预算]` → 发 `5000` 表示 5000 元
3. `[♻️ 重置当前月余额至月预算]` → 同步月剩余
4. `[✏️ 设置冷却天数]` 默认 7 天，按需调
5. `[✏️ 设置预算重置日]` 默认每月 1 号

> ⚠️ 金额不在这里设了 —— 每个邀请人的档位（100/150/200）已经在 §5.4 步骤 7 配过。修改某邀请人档位：进 `[🎓 邀请人管理]` → 该邀请人那行的 `[💰 调档位]`。

#### 5.5.2 资格列表（含广播频道 + 资格群，AND 语义）

回到 `[💰 报销管理]` → `[🎯 资格列表]` → `[➕ 添加资格群/频道]`，依次添加：

| 类型 | 来源 | 操作 |
|---|---|---|
| 广播频道 #1 | §1.4 中的对外广播频道 | 转发该频道任一条消息给 Bot |
| 广播频道 #2 | 同上 | 同上 |
| 报销资格群 | 运营内部讨论群 / 学员群 等 | 转发该群任一条消息给 Bot |

> 🚨 **AND 语义提醒**：用户必须**同时**是上面**所有**条目的成员才能申请报销。哪怕只有 1 个广播频道用户没订阅，`/reimburse` 也会被拒绝（提示"您不符合报销资格"）。
>
> 这是有意为之 —— 报销是对"持续关注"的回馈，缺一项即视为不达标。如果你想放宽某些群组，可以在面板里把对应条目"停用"（保留记录但不参与校验）。

#### 5.5.3 验证

用一个测试账号（**未**订阅广播频道）发 `/reimburse` → 应看到 `⚠️ 您不符合报销资格`。
让该账号订阅所有广播频道 + 加入资格群后再发 `/reimburse` → 应能进入 wizard。

> 💡 资格校验有 5 分钟缓存（成功结果），失败不缓存 —— 用户加群后下次 `/reimburse` 立即生效。

### 5.6 跑一次完整 E2E

最简单的烟测试：

1. 准备一个**测试账号**（不是超管，不是邀请人）
2. 测试账号私聊 Bot，发 `/start` → `[🚀 开始申请入群]` → 选张老师 → 走完 wizard 提交
3. 切到张老师账号 → 收到审核双消息 → 点 `[✅ 通过]`
4. 测试账号收到一次性入群链接 → 点进群
5. 回到日志频道看 6 类事件卡片是否到位

走通 = 系统可用。详细 E2E 清单见 [TESTING.md](TESTING.md)。

---

## 6. 备份策略

### 6.1 手动备份

```bash
sudo -u postgres pg_dump bccy | gzip > /opt/BC-CY-Bot/backups/backup-$(date +%F).sql.gz
```

或本机用 bccy 账号（密码读 `.env`）：

```bash
sudo install -d -o bccy -g bccy /opt/BC-CY-Bot/backups
sudo -u bccy bash -c '
  set -a; source /opt/BC-CY-Bot/.env; set +a
  PGPASSWORD=$(echo "$DATABASE_URL" | sed -E "s|.*://[^:]+:([^@]+)@.*|\1|") \
    pg_dump -h 127.0.0.1 -U bccy -d bccy | gzip > /opt/BC-CY-Bot/backups/backup-$(date +%F).sql.gz
'
```

文件大小通常 < 1 MB（除非邀请人/申请人量级很大）。

### 6.2 自动每日备份（cron）

```bash
sudo install -d -o bccy -g bccy /opt/BC-CY-Bot/backups
sudo crontab -u bccy -e
```

加入（用 `postgres` 账号更省事；如用 `bccy` 账号见 6.1 的等价形式）：

```cron
0 3 * * * /usr/bin/pg_dump -U bccy -h 127.0.0.1 bccy 2>>/opt/BC-CY-Bot/backups/dump.err | gzip > /opt/BC-CY-Bot/backups/backup-$(date +\%F).sql.gz && find /opt/BC-CY-Bot/backups -name "backup-*.sql.gz" -mtime +30 -delete
```

`pg_dump` 走 127.0.0.1 + 密码（密码来自 `~bccy/.pgpass` 或 `PGPASSWORD`），凌晨 3 点备份，保留 30 天。

### 6.3 恢复

```bash
sudo systemctl stop bccy-bot                           # 先停 Bot 避免写冲突
gunzip -c backup-2026-05-12.sql.gz | sudo -u postgres psql bccy
sudo systemctl start bccy-bot
```

---

## 7. 监控与日志

### 7.1 看日志

```bash
sudo journalctl -u bccy-bot -f                    # 实时
sudo journalctl -u bccy-bot --since "1 hour ago"  # 近 1 小时
sudo journalctl -u bccy-bot | grep ERROR
```

日志为结构化 JSON（structlog），关键字段：`event`、`user_id`、`application_id`、`reimbursement_id`、`reviewer_id`。

### 7.2 健康检查

```bash
sudo systemctl status bccy-bot              # active (running) = 正常
sudo systemctl is-active bccy-bot           # 单行输出，写脚本用
sudo systemctl is-enabled bccy-bot          # 是否开机自启
```

进程崩溃由 `Restart=always` 兜底，5 秒后自动拉起。

### 7.3 数据库直查（应急）

```bash
sudo -u postgres psql bccy
# \dt 看所有表
# SELECT * FROM admins;
# SELECT * FROM reimbursement_requests WHERE status='pending';
```

---

## 8. 安全建议

| 项 | 建议 |
|---|---|
| `.env` 权限 | `chmod 600 /opt/BC-CY-Bot/.env`（已在 §3.3 设过）|
| 数据库密码 | 强密码（≥ 24 字符）；仅在 `.env` 中保存 |
| 数据库不暴露 | PostgreSQL 默认仅监听 127.0.0.1；不要改 `listen_addresses` 暴露公网 |
| Bot Token | 同对待 root 密码：泄露 = 全权控制你的 Bot；泄露后立即 `/revoke` @BotFather 重新生成 |
| 备份加密 | `gpg -c backup.sql.gz`，密钥与服务器分离存储 |
| 超管账号 | 多准备 2–3 个备用账号，写进文档自己保存（不要进入仓库） |
| systemd 加固 | 自带 unit 已开 `NoNewPrivileges` / `ProtectSystem=strict` / `ProtectHome` / `PrivateTmp` |
| 系统更新 | 至少每月跑一次 `apt update && apt upgrade`，重点关注 openssl / python3 / postgresql |

---

## 9. 升级流程

```bash
cd /opt/BC-CY-Bot
sudo -u bccy git fetch --tags
sudo -u bccy git checkout v1.0.0-beta.2          # 切到目标版本
sudo -u bccy .venv/bin/pip install --upgrade .   # 同步依赖（如有变化）

sudo systemctl restart bccy-bot                  # 重启会先跑 ExecStartPre 的 alembic upgrade head
sudo journalctl -u bccy-bot -f                   # 看到 super_admin_ensured 即 OK
```

`bccy-bot.service` 里的 `ExecStartPre=...alembic upgrade head` 会在每次启动前自动应用 schema 变更，所以无需手动跑 alembic。

> ⚠️ 跨大版本升级（v1.x → v2.x）前一定先备份（§6）。

---

## 10. 故障排查

### 10.1 systemd 启动失败

```bash
sudo systemctl status bccy-bot
sudo journalctl -u bccy-bot --since "5 min ago"
```

| 现象 | 原因 |
|---|---|
| `Failed to start bccy-bot.service` + `code=exited, status=1/FAILURE` | ExecStartPre 的 alembic 失败 → 看日志，多半是 DATABASE_URL 错或 PostgreSQL 没起 |
| `Unauthorized` | `.env` 里 BOT_TOKEN 拼错 / 已被 revoke |
| `address already in use` | 不可能，本 Bot 不监听端口 |
| `Permission denied` 涉及 .env | `chmod 600 .env; chown bccy:bccy .env` |

### 10.2 Bot 启动后没收到任何消息

| 检查 | 命令 |
|---|---|
| 服务是否在跑 | `sudo systemctl is-active bccy-bot` |
| 网络是否可达 Telegram | `curl -sI https://api.telegram.org` 应返 401（说明能到 Telegram） |
| Token 是否正确 | 日志里搜 "Unauthorized"，搜到 = Token 错 |

### 10.3 PostgreSQL 起不来或连不上

```bash
sudo systemctl status postgresql
sudo journalctl -u postgresql --since "10 min ago"
PGPASSWORD='你的密码' psql -h 127.0.0.1 -U bccy -d bccy -c '\dt'
```

如果 `psql` 报 `peer authentication failed`，把 `.env` 里 host 写成 `127.0.0.1` 而不是 `localhost`（强制 TCP，避开 peer 认证）。

### 10.4 一次性链接颁发失败

| 现象 | 原因 |
|---|---|
| "无法创建邀请链接" | Bot 在目标群没有"邀请用户"权限 → 群设置补权限 |
| 链接生成但用户进不去 | 链接过期了（默认 24h），或者用户用了又退（一次性，用过即作废）|

### 10.5 报销发不出去

| 现象 | 原因 |
|---|---|
| 用户发 `/reimburse` 收到"未启用" | 总开关没开（`[💰 报销管理] → [📋 系统配置] → [▶️ 开启总开关]`）|
| "月预算未设" | 月预算 = 0，去配置面板设置 |
| "该入群申请缺少邀请人信息" | 该申请人的 application.inviter_id = NULL，数据异常 → 联系开发 |
| 审核者粘贴口令后 5 分钟没反应 | 状态超时；让审核者点 `[💸 待付款]` → `[💸 补发口令]` 重置等待态 |

### 10.6 应急换超管（原账号丢失/被封）

1. SSH 登录服务器，编辑 `/opt/BC-CY-Bot/.env`，把 `INITIAL_SUPER_ADMIN_ID` 改成**新超管的 Telegram 数字 ID**
2. `sudo systemctl restart bccy-bot`
3. 看日志：会出现 `super_admin_ensured action=override_super_admin`
4. 原超管自动降级为副管理员；新 ID 升为超管

详细机制见 [REQUIREMENTS.md §4.6](REQUIREMENTS.md)。

### 10.7 完全重建（保留数据）

```bash
sudo systemctl stop bccy-bot
cd /opt/BC-CY-Bot
sudo -u bccy .venv/bin/pip install --force-reinstall .
sudo systemctl start bccy-bot
```

### 10.8 完全清空（**会丢数据**，仅开发/测试）

```bash
sudo systemctl stop bccy-bot
sudo -u postgres psql -c 'DROP DATABASE bccy;'
sudo -u postgres psql -c 'CREATE DATABASE bccy OWNER bccy ENCODING UTF8;'
sudo systemctl start bccy-bot
```

---

## 11. 相关文档

- [README.md](README.md) — 项目总览
- [OPERATIONS.md](OPERATIONS.md) — 所有业务流程操作手册（含流程图）
- [TESTING.md](TESTING.md) — 上线 E2E 联调清单
- [REQUIREMENTS.md](REQUIREMENTS.md) — 完整需求规格
- [CHANGELOG.md](CHANGELOG.md) — 版本变更
- [`contrib/bccy-bot.service`](contrib/bccy-bot.service) — systemd unit 模板
