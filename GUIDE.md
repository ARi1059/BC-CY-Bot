# BC-CY-Bot 综合手册

> 适用版本：**v1.0.0-beta.4**
> 适用读者：超级管理员 / 副管理员 / 邀请人 / 报销老师 / 口令发放员 / 申请人 / 运维
> 部署形态：原生 Python 3.11+ + 原生 PostgreSQL 15+ + systemd（不使用 Docker）

本手册是 BC-CY-Bot 的**单一权威文档**：覆盖功能、部署、首次配置、业务流程、管理员后台、运维、故障排查。

---

## 目录

- [§1 项目介绍](#1-项目介绍)
- [§2 角色与权限矩阵](#2-角色与权限矩阵)
- [§3 部署指南（从零到生产）](#3-部署指南从零到生产)
- [§4 首次配置](#4-首次配置)
- [§5 入群审核流程](#5-入群审核流程)
- [§6 报销系统流程](#6-报销系统流程)
- [§7 回群密钥救济](#7-回群密钥救济)
- [§8 管理员后台](#8-管理员后台)
- [§9 升级、备份与故障排查](#9-升级备份与故障排查)
- [§10 命令速查与状态码](#10-命令速查与状态码)

---

## §1 项目介绍

BC-CY-Bot 是一款 Telegram 入群邀请审核 + 报销发放机器人，包含两大业务：

### 1.1 入群审核（v1）

- 申请人 `/start` 引导式提交 3 项材料（约课记录、上课手势、出击报告），严格单张、禁用媒体组
- 邀请人或管理员**双消息推送**审核（媒体组 + caption 报告 / 申请人信息 + 审核按钮）
- **自审型**（邀请人本人审）/ **代审型**（所有管理员先到先得 + 行锁）
- 审核通过 → 自动签发**一次性邀请链接**（`member_limit=1`，默认 24h 失效）
- `chat_member` 监听实际入群，**申请人 ID ≠ 入群 ID** 触发异常告警
- 出击报告自动转发到归档频道；6 类事件卡片推送日志频道

### 1.2 报销系统（v2，beta.3 起独立）

- **报销已与入群审核解耦**：只要通过资格校验即可申请，**无需先通过入群审核**
- 申请人 `/reimburse` → 引导式 wizard：先选**报销老师** → 提交 3 项材料 → 审核 → 发放
- 金额由所选**报销老师档位**（100/150/200 元）决定，wizard 创建时快照
- 审核通过后向**口令发放员**（独立角色）DM「待发放摘要 + 输入口令」按钮；未配置时回退到原管理员输入
- 申请人收到的口令以 `<code>` 包裹（点击/长按复制）
- 月预算 + 冷却天数 + 资格校验（用户必须**同时**是所有资格群/频道成员，AND 语义）
- 月预算自动重置（每月指定日 00:00）+ 周报/月报自动推送给所有超管

### 1.3 救济与审计

- **回群密钥**：账号丢失/被封后凭密钥换新链接；同 ID 拦截 + 7 条校验 + 原账号清理（踢/永封）
- **日志频道**：6 类事件卡片，链接 URL 脱敏（前缀 + ****）
- **出击报告频道**：审核通过时仅转发出击报告文本
- 所有写操作落 `audit_logs`，含 actor / action / target / details / created_at
- **应急换超管**：通过 `.env` 的 `INITIAL_SUPER_ADMIN_ID` 与 DB 不一致时强制覆盖

### 1.4 技术栈

| 项 | 选型 |
|----|------|
| 语言 | Python 3.11+ |
| Bot 框架 | python-telegram-bot v21+ (async + JobQueue) |
| 数据库 | PostgreSQL 15（生产）/ SQLite（开发） |
| ORM | SQLAlchemy 2.0 (async) |
| 迁移 | Alembic |
| 配置 | pydantic-settings + `.env` |
| 哈希 | argon2-cffi（回群密钥） |
| 日志 | structlog（结构化 JSON） |
| 进程管理 | systemd |

---

## §2 角色与权限矩阵

| 角色 | 标识 | 主要能力 |
|---|---|---|
| **申请人** | 普通 Telegram 用户 | `/start` 申请入群、`/reimburse` 申请报销、用回群密钥救济 |
| **邀请人** | `inviters.telegram_user_id` 命中 | `/panel` 查看个人接单统计；自审型可审核归属自己的申请 |
| **报销老师** | `reimburse_teachers`（独立表，beta.3 起） | 仅作为报销 wizard 选择项，决定金额档位；不参与任何审核 |
| **口令发放员** | `SK_REI_PAYMENT_RELAY_TELEGRAM_ID`（beta.4 起） | 审核通过后接 DM 输入支付宝口令；可选，未配置时由审核管理员输入 |
| **副管理员** | `admins.role='sub'`，可多人 | `/admin` 全部读 + 大部分写；**不可改系统配置、不可任命/转让超管** |
| **超级管理员** | `admins.role='super'`，**全局唯一** | 全部权限，含系统配置、邀请人/老师/群组管理、报销系统配置、任命副管理员、转让超管 |

> 一个 Telegram 用户可以同时担任多个角色（如同时是邀请人和管理员），角色不互斥。
> 主/副管理员业务能力**完全平权**，差异仅体现在「管理员管理」子模块（副管理员只读）。

---

## §3 部署指南（从零到生产）

预计耗时 30–60 分钟。目标系统：Debian 12+ / Ubuntu 22.04+。

### 3.1 准备清单

| 项 | 要求 |
|---|---|
| 服务器 | 1 vCPU / 1 GB 内存起步，可 ssh |
| Python | 3.11+ |
| PostgreSQL | 15+（127.0.0.1:5432） |
| Telegram | 1 个 Bot Token（@BotFather）+ 你的数字 ID |
| 目标群 | Bot 已被设为管理员的私密群 |
| 日志/出击报告频道（可选）| 各 1 个，Bot 必须是管理员且勾选 Post Messages |
| 报销资格条目（如启用报销） | 广播频道 × N + 资格群 × N，Bot 加入并设为管理员（私有 chat 必需） |

Bot 走 Polling，**无入站端口需求**，仅需出站 HTTPS 到 `api.telegram.org`。

### 3.2 Telegram 侧准备

1. **创建 Bot**：私聊 [@BotFather](https://t.me/BotFather) → `/newbot` → 取 Token；建议 `/setprivacy` → `Disable`
2. **取数字 ID**：私聊 [@userinfobot](https://t.me/userinfobot) → 记下 `id`（作为 `INITIAL_SUPER_ADMIN_ID`）
3. **目标群**：建私密群 → 加 Bot → 群设置 → 管理员 → 至少勾选 `Invite Users via Link` + `Ban Users`
4. **频道**：日志/出击报告频道把 Bot 加为管理员 + Post Messages；报销资格频道/群把 Bot 加为管理员（私有 chat 必需，以便 `getChatMember`）

### 3.3 服务器侧

#### 3.3.1 系统包

```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip postgresql postgresql-contrib build-essential libpq-dev git curl
```

验证：

```bash
python3 --version                  # ≥ 3.11
psql --version                     # ≥ 15
systemctl is-active postgresql     # active
```

#### 3.3.2 建库 + 建账号

```bash
sudo -u postgres psql <<'EOF'
CREATE ROLE bccy WITH LOGIN PASSWORD '请改成强密码';
CREATE DATABASE bccy OWNER bccy ENCODING 'UTF8';
GRANT ALL PRIVILEGES ON DATABASE bccy TO bccy;
\c bccy
GRANT ALL ON SCHEMA public TO bccy;
EOF
```

强密码可用 `openssl rand -base64 24` 生成。

#### 3.3.3 运行账号

```bash
sudo useradd --system --shell /usr/sbin/nologin --home /opt/BC-CY-Bot bccy
```

### 3.4 拉代码 + 装依赖

```bash
sudo git clone https://github.com/ARi1059/BC-CY-Bot.git /opt/BC-CY-Bot
sudo chown -R bccy:bccy /opt/BC-CY-Bot
cd /opt/BC-CY-Bot
sudo -u bccy git checkout v1.0.0-beta.4

sudo -u bccy python3 -m venv .venv
sudo -u bccy .venv/bin/pip install --upgrade pip
sudo -u bccy .venv/bin/pip install .
```

### 3.5 写 `.env`

```bash
sudo -u bccy cp .env.example .env
sudo chmod 600 .env
sudo -u bccy nano .env
```

填入：

```dotenv
BOT_TOKEN=123456789:AAH...
DATABASE_URL=postgresql+asyncpg://bccy:你设置的强密码@127.0.0.1:5432/bccy
INITIAL_SUPER_ADMIN_ID=987654321
LOG_LEVEL=INFO
TIMEZONE=Asia/Shanghai
```

### 3.6 装 systemd 服务

```bash
sudo cp /opt/BC-CY-Bot/contrib/bccy-bot.service /etc/systemd/system/bccy-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now bccy-bot
sudo journalctl -u bccy-bot -f
```

等待日志出现：

```
INFO  alembic.runtime.migration Running upgrade ... -> <head>, ...
INFO  bccy_bot.bot  super_admin_ensured action=created admin_id=<你的ID>
```

`bccy-bot.service` 在 `ExecStartPre` 会自动跑 `alembic upgrade head`，每次启动同步 schema。

### 3.7 验证 Bot 在线

| 步骤 | 预期 |
|---|---|
| 私聊 Bot 发 `/start` | 欢迎卡片，含 `[🚀 开始申请入群]` `[🔑 使用回群密钥]` `[💰 申请报销]` |
| 超管私聊 Bot 发 `/admin` | 管理面板（含 `[⚙️ 系统配置]`） |

两条都通过 = 上线成功。

### 3.8 环境变量清单

| 变量 | 必填 | 说明 |
|------|:--:|------|
| `BOT_TOKEN` | ✅ | Telegram Bot Token |
| `DATABASE_URL` | ✅ | 生产：`postgresql+asyncpg://bccy:密码@127.0.0.1:5432/bccy`；开发：`sqlite+aiosqlite:///./bccy_bot.db` |
| `INITIAL_SUPER_ADMIN_ID` | ✅ | 初始超级管理员 Telegram 数字 ID；后续启动若与 DB 中超管不一致则**强制覆盖** |
| `LOG_LEVEL` | ⭕ | 默认 `INFO`（可选 DEBUG/WARNING/ERROR） |
| `TIMEZONE` | ⭕ | 默认 `Asia/Shanghai` |

---

## §4 首次配置

由超级管理员在 Telegram 内完成，全程内联按钮，无命令行操作。

```
1. 添加目标群组
   /admin → [👥 群组管理] → [➕ 添加群组] → 转发该群任一条消息

2. 绑定日志频道
   /admin → [📡 日志频道] → [➕ 绑定频道] → 转发该频道任一条消息

3. 绑定出击报告频道
   /admin → [📋 出击报告频道] → [➕ 绑定频道] → 转发该频道任一条消息

4. 添加首位邀请人（5 步 wizard，beta.3 起简化）
   /admin → [🎓 邀请人管理] → [➕ 添加邀请人]
   ├─ 1/5  Telegram ID（或 /skip 表示挂名）
   ├─ 2/5  显示名（如 "张老师"）
   ├─ 3/5  选择目标群组
   ├─ 4/5  多选所需材料（约课记录 / 上课手势 / 出击报告）
   └─ 5/5  选审核模式：👤 自审型 / 🏢 代审型
   ⚠️ 挂名邀请人（步骤 1 用 /skip）只能用代审型

5. （报销可选）报销系统配置
   /admin → [💰 报销管理] → [📋 系统配置]
   ├─ [▶️ 开启总开关]
   ├─ [✏️ 设置月预算]  → 发 5000 表示 5000 元
   ├─ [♻️ 重置当前月余额至月预算]
   ├─ [✏️ 设置冷却天数]（默认 7）
   ├─ [✏️ 设置预算重置日]（默认每月 1 号）
   └─ [✏️ 设置口令发放员]（输入发放员 Telegram 数字 ID；可选）

6. （报销可选）报销老师管理（beta.3 起，独立于邀请人）
   /admin → [👨‍🏫 报销老师管理] → [➕ 添加报销老师]
   ├─ 1/4  username（必填，唯一）
   ├─ 2/4  显示名
   ├─ 3/4  组别名
   └─ 4/4  档位（100 / 150 / 200 元）

7. （报销可选）资格列表（含广播频道 + 资格群，AND 语义）
   /admin → [💰 报销管理] → [🎯 资格列表] → [➕ 添加资格群/频道]
   逐项转发对应群/频道的任一条消息
   ⚠️ 用户必须同时是所有 active 条目的成员，缺一即拒
```

> 💡 配完后用一个测试账号走一遍 `/start` 完整 E2E 烟测试（申请 → 审核 → 链接 → 入群 → 日志频道事件）。

---

## §5 入群审核流程

### 5.1 申请人 wizard

```
/start → 欢迎卡片 → [🚀 开始申请入群]
       → 选邀请人 → wizard_step=1
       → 上传材料 1（单张）→ 校验 → step=2
       → 上传材料 2 → step=3
       → ...
       → 预览卡片 → [✅ 确认提交] / [✏️ 重新提交] / [« 上一步] / [❌ 取消]
       → status=pending → 推送审核者
```

**关键规则**：

| 规则 | 说明 |
|---|---|
| **严格单张提交** | 媒体组（一次选多张）一律拒收，要求单张重发 |
| **类型严格匹配** | 约课记录/上课手势 要求 `photo`；出击报告 要求 `text`；错配立即提示 |
| **同时只能有 1 个进行中申请** | 重复 `/start` 续上当前 wizard 步骤，不重启 |
| **黑名单静默拒绝** | 不显示"你被拉黑"，防探测 |
| **从陈旧消息点按钮安全** | 状态以 DB 为准，过期按钮自动失效 |

### 5.2 自审型审核

申请提交后，邀请人立即收到**两条消息**：

1. 媒体组（图片合并）+ caption 是出击报告全文（>1024 字自动降级为 3 条消息）
2. 申请人信息卡片 + `[✅ 通过] [❌ 拒绝] [👁 重发审核材料]`

- 点 ✅ → 创建一次性链接 + 出击报告转发归档频道 + 私聊申请人发链接 + 日志频道事件
- 点 ❌ → Bot 提示输入原因（或 `/skip` 跳过）→ 拒绝 + 私聊申请人发原因
- 点 👁 → 再次推送两条消息（永远可点，便于换设备查看）

### 5.3 代审型审核（多管理员先到先得）

申请提交后，Bot 广播给**所有管理员**（主+副）。

- 第一个点 `[✅ 通过]` 的管理员获得审核权（PostgreSQL `SELECT FOR UPDATE` 行锁）
- 其他管理员的消息边缘化为 `⏩ 已被 @管理员A 处理`
- **拒绝原因仅对 acting 管理员可见**，不外泄给其他管理员（避免管理员之间互相反向打分）

### 5.4 一次性链接生命周期

| 状态 | 触发 |
|---|---|
| `created` | approve_application |
| `used` | chat_member 监听到入群 |
| `expired` | TTL 到期（默认 24h，可在 `[⚙️ 系统配置]` 调 1–168h） |
| `revoked` | 管理员手动撤销（M5，未上线） |

每 5 分钟有一个 sweep job 扫 `expired AND notified_at IS NULL`，推日志频道告警并标记 `notified_at`。

日志频道展示链接时**脱敏**：`https://t.me/+ABCD****`，平衡可追溯与防外泄。

### 5.5 异常入群检测

Bot 订阅 `CHAT_MEMBER` 更新，加入判定：`old_status ∈ {left, banned} AND new_status ∈ {member, administrator, owner, restricted}`。

- 实际入群 ID == 申请人 ID → 正常，日志频道 `🚪 链接已使用` 卡片
- 实际入群 ID ≠ 申请人 ID → **异常告警**，写 `invite_links.is_anomaly=true` + 日志频道告警

告警**仅记录、不自动处理**。管理员看日志频道决定是否手动踢出 + 加黑名单。

---

## §6 报销系统流程

### 6.1 申请人侧（5 层预校验）

```
/reimburse 或欢迎卡片 [💰 申请报销]
       → 黑名单校验（静默拒绝）
       → 预校验：
         1. 总开关 on?       否 → "报销功能未启用"
         2. 月预算 > 0?       否 → "月预算未设"
         3. 没有进行中报销?    有 wizard → 续上；有 pending → 提示
         4. 冷却已过?         未过 → "还需等待 X 天"
         5. 月预算 ≥ 老师档位? 否 → "本月预算不足"
       → 资格校验：所有 active 资格条目都在?
         否 → "⚠️ 您不符合报销资格，请联系管理员。"（beta.4 起通用文案，防探测）
       → 进入 wizard：
         step 1  选报销老师（决定金额档位）
         step 2  上传约课记录（单张图片）
         step 3  上传上课手势（单张图片）
         step 4  发送出击报告（文本）
         → 预览 → [✅ 确认提交] → status=pending → 推送所有管理员
```

**金额来源**（beta.3 起）：由 wizard step 1 所选**报销老师**的 `reimbursement_tier_cents`（100/150/200 元）决定，wizard 创建时**快照**到 `reimbursement_requests.amount_cents`，之后调档位不影响进行中/已发放的报销。

**资格校验缓存**：成功结果缓存 5 分钟（bot_data），失败不缓存 —— 用户加群后下次 `/reimburse` 立即生效。

### 6.2 管理员审核 + 口令发放（两阶段）

```
报销 status=pending → 广播给所有管理员（双消息：媒体组 + 按钮）

管理员点 [✅ 通过] (Phase 1: approve_step1)
  → SELECT FOR UPDATE 行锁
  → 月预算复检：余 ≥ amount?
    └ 否 → 自动 reject（is_budget_reject=true），不扣预算
    └ 是 → 扣减预算 + status='approved'
  → 派发 (Phase 2 入口)：
    └ 已配口令发放员 + DM 成功 → 发给口令发放员（[🧧 输入口令] 按钮）
    └ 未配置 / DM 失败       → 回退给审核管理员
  → 接收方收到提示，5 分钟内粘贴支付宝口令文本
    └ 5 分钟内输入 → confirm_payment → 转发申请人（行内 <code> 包裹）+ status='paid' + 日志频道
    └ /cancel / 超时 → 状态停 approved，进 [💸 待付款] 列表手动补发
```

**口令永不入日志频道**：`log_channel_service.push_reimbursement_event kind='paid'` 仅显示金额 + 审核人 + 申请人。

**补发口令**：当 Phase 2 失败/超时 → 状态停在 `approved`。`/admin → [💰 报销管理] → [💸 待付款] → [💸 补发口令]` → 重置 5 分钟等待 → 重新粘贴 → 完成。

### 6.3 月预算 + 周报/月报（JobQueue）

- **预算重置**：每日 00:00:05 检查 `today == reset_day`，是 → `monthly_remaining = monthly_budget`
- **周报**：每日 00:05 检查 `today == 周一`，是 → DM 所有超管（上周 7 天数据）
- **月报**：每日 00:10 检查 `today == 1 号`，是 → DM 所有超管（上月数据）

报表内容：申请数 / 5 状态分布 / 总发放金额 / 月剩余 / 报销次数 Top 5 申请人。

---

## §7 回群密钥救济

申请人首次通过审核时会拿到一把**回群密钥**（一次性、argon2 哈希存储）。账号丢失/被封时凭密钥重新申请新链接。

### 7.1 流程

```
新账号 /start → [🔑 使用回群密钥] → 粘贴密钥
       → 7 条校验顺序（任一失败 → 拒绝）：
         1. 同 ID 拦截：当前账号 ID == owner ID → 拒绝（原账号没丢就别用密钥）
         2. 黑名单：静默拒绝
         3. 找不到匹配 active key：拒绝
         4. key.status != 'active'：拒绝
         5. inviter 已停用：拒绝
         6. 单密钥失败频控（1h / 5 次）：锁定
         7. 单 claimer 成功频控（24h / 3 次）：拒绝
       → 全部通过 → 清理原账号：
         normal             → 永久封禁（beta.3 起，原 kick→ban）
         deactivated 注销   → 踢 + 永封 + 写本地黑名单
         not_in_group       → skip
         is_admin           → skip + 告警
         no_permission      → 失败 + 告警，不阻塞
         unknown            → 保守仅踢
       → 生成新一次性链接 + 新 chained key 给新账号
       → 原 key status='used'，新 key.previous_key_id 链上原 key
       → 日志频道 `🔑 回群密钥使用` 卡片
```

### 7.2 同 ID 拦截（最强规则）

如果当前账号 ID == 该密钥的 `owner_telegram_id`，**直接拒绝**。原账号没丢就不该用密钥；若原账号真要重入群，去找邀请人重新申请。

### 7.3 chained key

- 密钥用过即 `status='used'`，自动生成**新密钥**给新账号
- `chained_keys.owner_telegram_id` = 新账号 ID
- `chained_keys.original_owner_telegram_id` = 始终是首次申请人 ID（完整审计链）

---

## §8 管理员后台

`/admin` 主面板（超管/副管同进入，按角色显示按钮）：

| 模块 | 说明 |
|---|---|
| 👥 群组管理 | 添加/删除目标群组 |
| 🎓 邀请人管理 | 5 步 wizard 添加邀请人 / 启停 / 删除 |
| 👨‍🏫 报销老师管理 | 4 步 wizard 添加老师 / 调档位 / 改组别 / 启停 / 删除 |
| 🚫 黑名单 | 添加/移除（拉黑后 `/start` 静默拒绝） |
| 📡 日志频道 | 绑定/解绑 |
| 📋 出击报告频道 | 绑定/解绑 |
| 💰 报销管理 | 系统配置 / 待审核 / 待付款补发 / 历史 / 资格列表 / 用户冷却覆盖 |
| 👮 管理员管理 | （仅超管）任命/撤销副管理员 + 转让超管 |
| ⚙️ 系统配置 | （仅超管）一次性链接 TTL / 报销开关等全局参数 |

### 8.1 邀请人管理（5 步 wizard）

```
1/5  Telegram ID（或 /skip 挂名）
2/5  显示名
3/5  选目标群
4/5  多选材料类型
5/5  选审核模式（👤 自审型 / 🏢 代审型）
```

> 挂名邀请人（步骤 1 `/skip`）**必须**用代审型，否则没人能审。

### 8.2 报销老师管理（beta.3 起，独立于邀请人）

```
1/4  username（必填，唯一）
2/4  显示名
3/4  组别名
4/4  档位（100 / 150 / 200 元）
```

调档位**不回溯**：仅影响后续新建报销 wizard 的金额；进行中/已落地的报销保持原 amount_cents。

### 8.3 主/副管理员管理 + 超管转让

```
任命副管理员：/admin → [👮 管理员管理] → [➕ 任命副管理员] → 输入 Telegram ID
撤销副管理员：行内 [🗑 撤销] → 二次确认 → DELETE
转让超管：    行内 [🎖 转让超管] → 二次确认
  → 当前超管降为 sub（满足 uq_one_super_admin 部分唯一索引）
  → 目标 ID 升为 super
  → audit_logs 写 action='transfer_super_admin'
```

`uq_one_super_admin`：`CREATE UNIQUE INDEX uq_one_super_admin ON admins (role) WHERE role = 'super'`，任何时候都只能有 1 个 super。

### 8.4 应急换超管（原账号丢失）

无法点 `[🎖 转让超管]` 时，走 `.env` 强制覆盖：

```bash
sudo vim /opt/BC-CY-Bot/.env       # 改 INITIAL_SUPER_ADMIN_ID 为新账号 ID
sudo systemctl restart bccy-bot
sudo journalctl -u bccy-bot | grep super_admin_ensured
# → action=override_super_admin
```

效果：原超管自动降为副管（保留账号）；新 ID 升为超管；`audit_logs.action='override_super_admin'`、actor 标记为 `env_override`。

### 8.5 邀请人个人面板 `/panel`

邀请人本人私聊 Bot 发 `/panel` 看自己接单统计：

- 接单总数 + 已决 + 通过率（`approved / (approved + rejected)`，不计 pending/cancelled）
- 通过率 Top 10（按总数 desc，同总数按通过率 desc）
- 最近 10 条审核记录（可点 `[👁 重发某条审核材料]`，权限校验 `inviter_id` 匹配）

---

## §9 升级、备份与故障排查

### 9.1 升级流程

```bash
cd /opt/BC-CY-Bot
sudo -u bccy git fetch --tags
sudo -u bccy git checkout v1.0.0-beta.4
sudo -u bccy .venv/bin/pip install --upgrade .
sudo systemctl restart bccy-bot
sudo journalctl -u bccy-bot -f
```

`bccy-bot.service` 的 `ExecStartPre` 会自动跑 `alembic upgrade head`，无需手动迁移。跨大版本（v1.x → v2.x）前一定先备份。

### 9.2 备份策略

#### 手动备份

```bash
sudo install -d -o bccy -g bccy /opt/BC-CY-Bot/backups
sudo -u postgres pg_dump bccy | gzip > /opt/BC-CY-Bot/backups/backup-$(date +%F).sql.gz
```

#### 自动每日备份（cron）

```bash
sudo crontab -u bccy -e
```

加入：

```cron
0 3 * * * /usr/bin/pg_dump -U bccy -h 127.0.0.1 bccy 2>>/opt/BC-CY-Bot/backups/dump.err | gzip > /opt/BC-CY-Bot/backups/backup-$(date +\%F).sql.gz && find /opt/BC-CY-Bot/backups -name "backup-*.sql.gz" -mtime +30 -delete
```

凌晨 3 点备份，保留 30 天。

#### 恢复

```bash
sudo systemctl stop bccy-bot
gunzip -c backup-2026-05-12.sql.gz | sudo -u postgres psql bccy
sudo systemctl start bccy-bot
```

### 9.3 日志与监控

```bash
sudo journalctl -u bccy-bot -f                    # 实时
sudo journalctl -u bccy-bot --since "1 hour ago"
sudo journalctl -u bccy-bot | grep ERROR
sudo systemctl status bccy-bot                    # active (running) = 正常
sudo systemctl is-active bccy-bot
```

日志为结构化 JSON（structlog），关键字段：`event`、`user_id`、`application_id`、`reimbursement_id`、`reviewer_id`。进程崩溃由 `Restart=always` 兜底，5 秒后自动拉起。

### 9.4 故障排查

| 现象 | 排查 |
|---|---|
| systemd `code=exited, status=1/FAILURE` | ExecStartPre alembic 失败 → 多半 DATABASE_URL 错或 PostgreSQL 没起 |
| 日志出现 `Unauthorized` | `.env` 里 BOT_TOKEN 拼错或已被 revoke |
| 日志出现 `Permission denied .env` | `sudo chmod 600 .env; chown bccy:bccy .env` |
| PostgreSQL `peer authentication failed` | `.env` 里 host 写 `127.0.0.1` 而不是 `localhost`（避开 peer 认证） |
| "无法创建邀请链接" | Bot 在目标群没"邀请用户"权限 → 补 |
| 用户发 `/reimburse` 收 "未启用" | 总开关没开（`[💰 报销管理] → [📋 系统配置] → [▶️ 开启总开关]`） |
| `/reimburse` 收 "月预算未设" | 月预算 = 0，去配置面板设 |
| 审核者粘贴口令后 5 分钟无响应 | 状态超时；点 `[💸 待付款] → [💸 补发口令]` 重置 |
| 口令发放员收不到 DM | 发放员**必须先私聊 Bot 至少 1 次**，否则 Bot 无法发起会话；DM 失败会自动 fallback 到原审核管理员 |
| 资格校验提示通用文案、不告诉缺哪个 | beta.4 起的设计（防探测），具体缺失项写到 structlog；管理员查日志 `eligibility_check_*` |

### 9.5 完全重建 / 完全清空

```bash
# 重建（保留数据）
sudo systemctl stop bccy-bot
sudo -u bccy .venv/bin/pip install --force-reinstall .
sudo systemctl start bccy-bot

# 完全清空（⚠️ 会丢数据，仅开发/测试）
sudo systemctl stop bccy-bot
sudo -u postgres psql -c 'DROP DATABASE bccy;'
sudo -u postgres psql -c 'CREATE DATABASE bccy OWNER bccy ENCODING UTF8;'
sudo systemctl start bccy-bot
```

### 9.6 安全建议

| 项 | 建议 |
|---|---|
| `.env` 权限 | `chmod 600 /opt/BC-CY-Bot/.env` |
| 数据库密码 | 强密码（≥ 24 字符）；仅在 `.env` 中保存 |
| 数据库不暴露 | PostgreSQL 默认仅监听 127.0.0.1；不要改 `listen_addresses` 暴露公网 |
| Bot Token | 同对待 root 密码；泄露即 `/revoke` @BotFather 重新生成 |
| 备份加密 | `gpg -c backup.sql.gz`，密钥与服务器分离存储 |
| 超管账号 | 多准备 2–3 个备用，纸面保存不进仓库 |
| systemd 加固 | unit 自带 `NoNewPrivileges` / `ProtectSystem=strict` / `ProtectHome` / `PrivateTmp` |
| 系统更新 | 每月 `apt update && apt upgrade`，重点关注 openssl / python3 / postgresql |

---

## §10 命令速查与状态码

### 10.1 命令

| 命令 | 谁能用 | 作用 |
|---|---|---|
| `/start` | 任何人 | 入口：申请入群 / 回群密钥 / 申请报销 |
| `/admin` | 管理员 | 管理面板 |
| `/panel` | 邀请人 | 个人统计面板 |
| `/reimburse` | 任何人（beta.3 起解耦） | 进入报销 wizard |
| `/cancel` | 任何场景 | 取消当前进行中的多步输入 |
| `/skip` | 邀请人添加 / 拒绝原因 | 跳过当前可选字段 |

### 10.2 状态码

#### applications.status

| 值 | 含义 |
|---|---|
| `wizard` | 申请人正在 wizard 中，未提交 |
| `pending` | 已提交，待审核 |
| `approved` | 已通过 |
| `rejected` | 已拒绝 |
| `cancelled` | 申请人主动取消 |

#### reimbursement_requests.status

| 值 | 含义 |
|---|---|
| `wizard` | wizard 中 |
| `pending` | 已提交，待审核 |
| `approved` | 已通过，等口令发放 |
| `rejected` | 已拒绝（含预算不足自动拒绝） |
| `cancelled` | 申请人主动取消 |
| `paid` | 已发放（口令已转给申请人） |

#### admins.role

| 值 | 含义 |
|---|---|
| `super` | 超级管理员（全局唯一） |
| `sub` | 副管理员（多人） |

#### inviters.review_mode

| 值 | 含义 |
|---|---|
| `self` | 自审型 |
| `admin_delegated` | 代审型 |

#### recovery_keys.status

| 值 | 含义 |
|---|---|
| `active` | 可用 |
| `used` | 已使用 |
| `revoked` | 已撤销 |
| `reset` | 已被用户主动重置（M5 占位） |

#### recovery_keys.cleanup_action

| 值 | 含义 |
|---|---|
| `kick` | 已踢（历史值，beta.3 起 normal 路径已改 ban） |
| `ban` | 永久封禁（beta.3 起 normal/deactivated 统一） |
| `skip_not_in_group` | 跳过：不在群里 |
| `skip_admin` | 跳过：是管理员，不动 |
| `failed_no_permission` | 失败：Bot 无权限 |
| `pending` | 等待中（理论上不会停在这） |

### 10.3 报销 settings keys

| key | 默认 | 说明 |
|---|---|---|
| `reimbursement_global_enabled` | false | 总开关 |
| `reimbursement_monthly_budget_cents` | 0 | 月预算（分） |
| `reimbursement_monthly_remaining_cents` | 0 | 当前余额（分） |
| `reimbursement_budget_reset_day` | 1 | 每月哪天 00:00 重置（1–28） |
| `reimbursement_default_cooldown_days` | 7 | 默认冷却（1–90） |
| `SK_REI_PAYMENT_RELAY_TELEGRAM_ID` | 0 | 口令发放员 Telegram 数字 ID（0 = 未配置） |

### 10.4 报销老师档位

| 常量 | 值（分） | 元 |
|---|---|---|
| `REI_TIER_100_CENTS` | 10000 | 100 |
| `REI_TIER_150_CENTS` | 15000 | 150 |
| `REI_TIER_200_CENTS` | 20000 | 200 |

仅这三档允许；其他值会被拒绝（`ValueError`）。

### 10.5 项目结构

```
BC-CY-Bot/
├── README.md                   项目门面
├── GUIDE.md                    本文件（综合手册）
├── contrib/bccy-bot.service    systemd unit 模板
├── alembic/                    数据库迁移
├── pyproject.toml
├── .env.example
├── src/bccy_bot/
│   ├── config.py               pydantic-settings
│   ├── bot.py                  Application 装配
│   ├── db/models/              数据表（每张一文件）
│   ├── repositories/           CRUD 层
│   ├── services/               业务编排
│   │   ├── wizard_service          申请人引导式状态机
│   │   ├── audit_service           审核（含双消息 / 行锁 / relay 派发）
│   │   ├── invite_link_service     一次性链接
│   │   ├── recovery_key_service    回群密钥（7 条校验）
│   │   ├── account_cleanup_service 原账号踢/永封
│   │   ├── link_tracking_service   chat_member 监听 + sweep
│   │   ├── log_channel_service     6 类事件卡片
│   │   ├── attack_report_service   出击报告转发
│   │   ├── reimburse_teacher_*     报销老师 CRUD
│   │   └── stats_service           邀请人 + 全局统计
│   ├── handlers/
│   │   ├── user/                   /start, wizard, recovery, /reimburse
│   │   ├── inviter/                /panel, audit
│   │   ├── admin/                  /admin + 子模块
│   │   └── common/                 chat_member 监听
│   ├── keyboards/                  Inline Keyboard 工厂
│   └── utils/                      retry, awaiting, tg_user, ...
└── tests/                      单元测试
```

---

## 附录：常见错误场景

| 场景 | 现象 | 处理 |
|---|---|---|
| 用户重复 `/start` | 续上 wizard 当前步骤，不重置 | 设计如此 |
| 用户从陈旧消息点按钮 | 按 DB 当前状态响应，过期自动失效 | 设计如此 |
| 邀请人停用但有 pending 申请 | 自审型卡住 | 临时切代审型，或重启 inviter |
| 报销老师调档位 | 进行中/已落地报销金额不变 | 设计如此（amount_cents 是快照） |
| 管理员粘贴口令超时 | 状态停 approved | 进 `[💸 待付款]` 补发 |
| 口令发放员未先私聊 Bot | DM 失败 → fallback 给审核管理员 | 让发放员先私聊 Bot 一次 |
| 资格校验失败提示通用 | 不告诉缺哪个 | beta.4 起设计；管理员查 structlog 找 `missing_chat_names` |
| 同 1 个 Telegram 账号既是邀请人又是申请人 | 行为冲突 | 不支持，业务上禁止 |
