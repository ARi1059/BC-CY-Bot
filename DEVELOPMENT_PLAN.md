# BC-CY-Bot 开发计划

> 本计划与 [REQUIREMENTS.md](REQUIREMENTS.md) v1.0 对齐。
> **开发过程中本文档持续更新**：每完成一个子任务即勾选 ☑️；遇到偏离原设计的决策记入 §11「执行日志」。

---

## 0. 进度总览

| 阶段 | 内容 | 工期 | 状态 | 起止 |
|:----:|------|:---:|:----:|------|
| M0 | 项目脚手架 + DB schema + 配置 + Keyboard 工厂 | 1.5d | ✅ 已完成 | 2026-05-12 |
| M1 | 申请人引导式流程（禁媒体组 / 逐项 / 预览） | 2.5d | ✅ 已完成 | 2026-05-12 |
| M2 | 邀请人审核（双消息 / 通过-拒绝 / 一次性链接） | 2.5d | ✅ 已完成 | 2026-05-12 |
| M3 | 代审型路由（多管理员行锁） | 1d | ⬜ 未开始 | – |
| M4 | 链接使用追踪 + chat_member 监听 | 1d | ⬜ 未开始 | – |
| M5 | 管理员面板（含主/副分层 + 系统配置） | 2d | ⬜ 未开始 | – |
| M6 | 日志频道（5 类事件卡片） | 1d | ⬜ 未开始 | – |
| M7 | 出击报告频道（仅转发报告） | 1d | ⬜ 未开始 | – |
| M8 | 回群密钥（含原账号清理） | 2d | ⬜ 未开始 | – |
| M9 | 邀请人面板 `/panel` + 统计报表 | 1d | ⬜ 未开始 | – |
| M10 | Docker 化 + 部署文档 + 联调 | 1.5d | ⬜ 未开始 | – |

**总计 17 工作日**

状态图例：⬜ 未开始 / 🟡 进行中 / ✅ 已完成 / ⚠️ 阻塞

---

## 1. 技术栈固化

| 项 | 选型 |
|----|------|
| 语言 | Python 3.11+ |
| Bot 框架 | python-telegram-bot v21+ (async) |
| 状态机 | `ConversationHandler` + DB 快照（wizard_step）|
| 数据库 | PostgreSQL 15（生产）/ SQLite（开发） |
| ORM | SQLAlchemy 2.0 (async) + asyncpg / aiosqlite |
| 迁移 | Alembic |
| 配置 | pydantic-settings + `.env` |
| 哈希 | argon2-cffi（回群密钥）|
| 日志 | structlog + RotatingFileHandler |
| 测试 | pytest + pytest-asyncio |
| 容器 | Docker + docker-compose |
| 进程 | docker `restart: always` / systemd |

---

## 2. 目录结构（M0 完成时落地）

```
BC-CY-Bot/
├── REQUIREMENTS.md
├── DEVELOPMENT_PLAN.md
├── README.md
├── .gitignore
├── .env.example
├── pyproject.toml
├── alembic.ini
├── alembic/versions/
├── docker-compose.yml
├── Dockerfile
├── src/bccy_bot/
│   ├── __main__.py              入口
│   ├── config.py                pydantic-settings
│   ├── bot.py                   Application 装配
│   ├── db/
│   │   ├── base.py              declarative base
│   │   ├── session.py           async session factory
│   │   └── models/              一个文件一张表
│   ├── repositories/            CRUD 层
│   ├── services/                业务编排
│   │   ├── application_service.py
│   │   ├── audit_service.py
│   │   ├── invite_link_service.py
│   │   ├── recovery_key_service.py
│   │   ├── log_channel_service.py
│   │   └── attack_report_service.py
│   ├── handlers/
│   │   ├── user/                /start, wizard, /help, 回群密钥流程
│   │   ├── inviter/             /panel
│   │   ├── admin/               /admin + 各子菜单
│   │   └── common/              chat_member 监听, 错误兜底
│   ├── keyboards/               Inline Keyboard 工厂（一处统一管理）
│   ├── conversations/           wizard 状态常量
│   └── utils/
│       ├── retry.py             Telegram API 指数退避
│       ├── tg_user.py           用户状态判定（含已注销识别）
│       └── id_utils.py
└── tests/
    ├── unit/
    └── integration/
```

---

## 3. 开发原则

1. **数据库快照优先**：用户/审核状态全部落库，Bot 重启可恢复（[REQ §4.3](REQUIREMENTS.md)）
2. **Keyboard 工厂统一**：所有 InlineKeyboard 集中 `keyboards/` 下，禁止散落到 handlers
3. **服务层无 Telegram 依赖**：services/ 只接受/返回纯数据，便于单测
4. **Telegram API 调用必带重试**：通过 `utils/retry.py` 装饰器，指数退避 3 次（[REQ §4.3](REQUIREMENTS.md)）
5. **每个 callback_data 必校验权限**：副管理员不可见的按钮仍要服务端拦截（[REQ §3.3.5](REQUIREMENTS.md)）
6. **关键操作先落库后回复**：链接生成、密钥签发、审核结果（[REQ §4.3](REQUIREMENTS.md)）
7. **不写无关注释**：仅写"为何"，不写"是什么"
8. **每完成一个子任务立刻 commit**：消息按规范 `M{n}: <action>`

---

## 4. 里程碑详细任务

### M0 项目脚手架（1.5 天） ✅

**目标**：可执行的最小骨架——能连数据库、能响应 `/start`、能加载配置。

- [x] 创建 `pyproject.toml`（声明依赖：python-telegram-bot, sqlalchemy, alembic, pydantic-settings, structlog, argon2-cffi, asyncpg/aiosqlite）
- [x] 创建 `.env.example`，列出 [REQ §4.6](REQUIREMENTS.md) 所有变量
- [x] `src/bccy_bot/config.py` —— pydantic-settings 加载 `.env`
- [x] `src/bccy_bot/db/base.py` + `session.py` —— async engine + session factory
- [x] 按 [REQ §5](REQUIREMENTS.md) 创建所有 SQLAlchemy 模型（每张表一个文件）：
  - [x] groups
  - [x] inviters
  - [x] admins
  - [x] applications
  - [x] application_materials（含 `original_message_id`）
  - [x] invite_links
  - [x] blacklist
  - [x] settings
  - [x] audit_logs
  - [x] attack_report_forwards
  - [x] recovery_keys
  - [x] recovery_key_attempts
  - [x] recovery_reset_throttle
- [x] Alembic 初始化 + 生成第一个 migration（含 SQLite 部分唯一索引 `uq_one_super_admin`）
- [x] `keyboards/` 骨架（factory pattern + callback_data 命名规范）
- [x] `src/bccy_bot/__main__.py` —— 启动 Application，注册一个能回复"Hello"的 `/start`
- [x] 启动时执行 `INITIAL_SUPER_ADMIN_ID` 注入逻辑（[REQ §4.6](REQUIREMENTS.md)），4 路径验证通过：created / noop / override / override-back
- [x] `Dockerfile` + `docker-compose.yml`（含 postgres 服务）
- [ ] 真实 Telegram 联调（需用户提供 BOT_TOKEN 测试）—— 留待 M10 端到端联调阶段

**验收**：✅ 所有 13 张表建好，部分唯一索引生效；超级管理员注入幂等 + env 覆盖均通过；`build_application()` 可加载 handler。真实 `/start` 回复留待有 Bot Token 时验证。

---

### M1 申请人引导式流程（2.5 天） ✅

**目标**：用户能完整走完 `/start → 选邀请人 → 单张提交 3 项材料 → 预览 → 落库 pending`。

- [x] `handlers/user/start.py` —— 校验黑名单 / 已有 pending → 展示欢迎卡片 / 已有进行中提示
- [x] `keyboards/factory.py` —— 欢迎卡片 + 邀请人列表（分页）+ 材料步骤 + 预览 + 取消确认 + 已有申请提示
- [x] `services/wizard_service.py` —— DB-backed 状态机，CurrentStepInfo dataclass 隔离 telegram 依赖
- [x] **Step 1：选择邀请人**
  - [x] inviter_repo.list_active 读取 active 邀请人，按"昵称·组别"分页（6/页）
  - [x] 选中后 set_inviter() → application.wizard_step=1
- [x] **Step 2：逐项提交（严格 [REQ §3.1.1](REQUIREMENTS.md)）**
  - [x] 媒体组拦截：`media_group_id` 非空 → WizardError("请单张提交...")
  - [x] 类型校验：MAT_BOOKING/MAT_GESTURE = photo，MAT_REPORT = text
  - [x] 落库 application_materials，记录 `original_message_id`（M7 forwardMessage 必备）
  - [x] 进度卡片：`(i/N) 请上传【约课记录】单张图片` + `[« 上一步] [❌ 取消]`
- [x] **Step 3：预览**
  - [x] 回显材料类型 + 图标 + 文本摘要
  - [x] `[✅ 确认提交] [✏️ 重新提交] [« 上一步] [❌ 取消]`
- [x] **Step 4：提交后**
  - [x] confirm_submit() → status='pending'，submitted_at 落时
  - [x] 触发 M2 审核推送占位（TODO 已加在 `on_preview_confirm`）
- [x] 辅助命令：`/help`（命令 + 按钮双入口）；二次确认 取消申请
- [x] 单测：19 个用例覆盖所有 wizard 状态机迁移路径，全部通过

**验收**：✅ 19/19 单元测试通过（含完整 happy path、媒体组拒收、类型错配、回退、重做、取消幂等等所有路径）；16 个 handler 注册成功。

---

### M2 邀请人审核流程（2.5 天） ✅

**目标**：审核者收到双消息推送，点通过 → 申请人收到一次性链接 + 回群密钥；点拒绝 → 申请人收到通知。

- [x] `services/audit_service.py` —— 路由：
  - [x] inviter.review_mode='self' → 推送给该邀请人
  - [x] inviter.review_mode='admin_delegated' → 占位日志，M3 接管（已留 TODO）
- [x] **双消息推送**（严格 [REQ §3.2.1](REQUIREMENTS.md)）：
  - [x] 消息 ①：`sendMediaGroup`（约课记录 + 上课手势），首图 caption=出击报告
  - [x] caption > 1024 字符时降级三条消息（媒体组无 caption + 独立报告 + 按钮）
  - [x] 消息 ②：申请人元信息 + `[✅ 通过] [❌ 拒绝] [👁 重发审核材料]`
  - [x] message_id 存入 `audit_messages` 表（新增，支持多审核者 = M3 顺延扩展）
- [x] **通过流程**：
  - [x] `services/invite_link_service.py`：调 `createChatInviteLink`（取 settings 的 ttl，clamp 1–168）
  - [x] `services/recovery_key_service.py`：生成 BCCY-XXXX-XXXX-XXXX-XXXX 密钥 + Argon2id 哈希 + 幂等签发
  - [x] 私聊申请人：链接 URL 按钮 + 密钥卡片
  - [x] 编辑消息 ② 为「✅ 已通过 by @xxx · HH:MM」
  - [x] 写 audit_logs
- [x] **拒绝流程**：
  - [x] 询问"是否填写原因？" `[✏️ 填写] [⏩ 跳过]`
  - [x] 填写：bot_data 状态机 + 消息分发器优先消费拒绝原因文本
  - [x] 通知申请人 + 编辑消息 ②（含原因）
- [x] `utils/retry.py`：Telegram API 重试装饰器（RetryAfter / TimedOut / NetworkError）
- [x] 集成测试：16 个新增用例（recovery_key 8 + audit_service 8）覆盖双消息/长报告降级/代审跳过/通过/拒绝带原因/重复处理拒收

**验收**：✅ 35/35 单元测试通过（M1 19 + M2 16）；21 个 handler 注册；audit_messages 新表 + migration 已生效。

---

### M3 代审型路由（1 天）

**目标**：当 inviter.review_mode='admin_delegated' 时，审核消息广播给所有管理员，先到先得。

- [ ] `services/audit_service.py` 补全代审路由分支
- [ ] 广播：对每位 admin 各推一份双消息
- [ ] **行锁防并发**：审核动作执行前 `SELECT ... FOR UPDATE` 锁住 application，校验 status='pending'
- [ ] 一个管理员处理后：
  - [ ] 其他管理员的消息 ② 编辑为「⏩ 已被 @xxx 处理」并移除按钮
- [ ] DB 字段：applications.locked_by 仅做调试展示
- [ ] 测试：双管理员同时点击的并发场景

**验收**：模拟两个管理员同时点击通过，仅一人成功落库，另一人按钮失效。

---

### M4 链接使用追踪 + chat_member 监听（1 天）

**目标**：用户实际入群时记录到 invite_links，异常入群（非申请人）触发告警。

- [ ] `handlers/common/chat_member.py`：监听 `chat_member` 更新
- [ ] 匹配：通过 `invite_link.name`（`App-{id}`）回查 application
- [ ] 写入 invite_links.is_used / used_by_telegram_id / used_at
- [ ] **异常检测**：实际入群 ID ≠ application.applicant_telegram_id → `is_anomaly=true`
- [ ] 触发 §M6 的「🚪 链接已使用」/「⚠️ 异常告警」日志频道事件（M6 完成前先打 print 日志占位）
- [ ] 链接过期未用：定时任务（每小时）扫描，标记 expired
- [ ] 测试：模拟正常入群 / 异常入群两条路径

**验收**：用户实际入群后，invite_links 表对应行 is_used=true；异常入群标志正确。

---

### M5 管理员面板（2 天）

**目标**：`/admin` 打开按钮面板，覆盖 9 个子模块。

- [ ] `handlers/admin/panel.py` —— `/admin` 入口 + 主面板
- [ ] **权限渲染**：超级管理员看到 `[⚙️ 系统配置]`，副管理员看不到
- [ ] 每个子模块按 [REQ §3.3](REQUIREMENTS.md) 实现：
  - [ ] §3.3.2 群组管理（添加/列表/移除）
  - [ ] §3.3.3 邀请人管理（5 步引导添加 / 编辑 / 启停）
  - [ ] §3.3.4 黑名单管理
  - [ ] §3.3.5 管理员管理（主/副视图分流 + 转让身份 + 二次确认）
  - [ ] §3.3.6 日志频道绑定
  - [ ] §3.3.7 出击报告频道绑定
  - [ ] §3.3.8 待我审核（接 M3）
  - [ ] §3.3.9 全局统计（基础数字，详细图表延后）
  - [ ] §3.3.10 回群密钥管理（接 M8）
  - [ ] §3.3.11 系统配置（仅超级管理员，修改 invite_link_ttl_hours）
- [ ] callback_data 命名空间隔离 + 服务端权限校验
- [ ] 破坏性操作二次确认（[REQ §2.1 第 5 条](REQUIREMENTS.md)）

**验收**：超级管理员能用面板完成添加群组 / 添加邀请人 / 添加副管理员 / 设置日志频道 / 修改链接有效期；副管理员看不到系统配置按钮。

---

### M6 日志频道（1 天）

**目标**：5 类事件卡片实时推送到日志频道。

- [ ] `services/log_channel_service.py` —— 统一卡片渲染 + 推送
- [ ] 5 类事件接入：
  - [ ] 📥 新申请 → M1 末尾触发
  - [ ] ✅ 审核通过 → M2 通过流程触发
  - [ ] ❌ 审核拒绝 → M2 拒绝流程触发
  - [ ] 🚪 链接已使用 → M4 chat_member 事件触发
  - [ ] ⚠️ 异常告警 → M4 异常分支 + M8 密钥异常 + M5 各类失败
- [ ] 频道未配置时静默跳过 + 管理员面板顶部提示
- [ ] 推送带 `disable_notification=true`
- [ ] 失败重试 3 次

**验收**：5 种事件都能在频道看到对应卡片，格式与 [REQ §3.6.3](REQUIREMENTS.md) 一致。

---

### M7 出击报告频道转发（1 天）

**目标**：审核通过时，**仅**用 forwardMessage 把出击报告原始消息转发到频道。

- [ ] `services/attack_report_service.py`
- [ ] 触发时机：M2 通过流程末尾
- [ ] 严格边界（[REQ §3.7.3](REQUIREMENTS.md)）：
  - [ ] 仅 forwardMessage `material_type='出击报告'` 那条记录的 `original_message_id`
  - [ ] **不**转发约课记录/上课手势图片
  - [ ] **不**附加任何元信息
- [ ] 写 attack_report_forwards 表（status / channel_id 快照 / message_id）
- [ ] 跳过场景：申请无出击报告材料 / 频道未配置
- [ ] 失败重试 3 次 + 日志频道告警

**验收**：审核通过后，频道内只看到 "Forwarded from <用户>" 的出击报告文本；attack_report_forwards 表有对应记录。

---

### M8 回群密钥（2 天）

**目标**：完整实现签发、使用、清理三条链路。

- [ ] **密钥生成**：`utils/recovery_key.py`
  - [ ] 格式 `BCCY-XXXX-XXXX-XXXX-XXXX`（Base32 去除 0/O/1/I/L）
  - [ ] Argon2id 哈希
  - [ ] 唯一性碰撞检测
- [ ] **签发**（接 M2 通过流程）：
  - [ ] 首次通过生成；后续不重复
  - [ ] 推送给申请人（含复制按钮）
- [ ] **使用流程**（[REQ §3.8.3-4](REQUIREMENTS.md)）：
  - [ ] `handlers/user/recovery.py` —— `[🔑 我有回群密钥]` 入口
  - [ ] 引导输入密钥 → 7 条校验顺序表逐项执行
  - [ ] 通过 → 生成新链接 + 签发新密钥 + 标记旧密钥 used + 触发清理 + 日志频道
- [ ] **原账号清理**（[REQ §3.8.5](REQUIREMENTS.md)）：
  - [ ] `utils/tg_user.py` —— 注销账号识别（first_name 特征 + API 错误判定）
  - [ ] 决策表实现：正常+在群=踢出 / 已注销=封禁+本地黑名单
  - [ ] 例外兜底：是群管理员则跳过 / 缺权限则告警
- [ ] **频率限制**：
  - [ ] 单密钥 1h/5 次失败锁定
  - [ ] 单新 ID 24h/3 次上限
  - [ ] 用户主动重置 1 次/天
- [ ] **管理员管理**（接 M5 §3.3.10）：查询 / 重置 / 撤销
- [ ] 集成测试：完整密钥生命周期 + 同 ID 拦截 + 注销账号场景（mock）

**验收**：完整路径跑通——通过审核拿到密钥 → 用新账号兑换链接 → 旧账号在群则被踢 / 旧账号注销则被封；同 ID 使用被拒；频率限制生效。

---

### M9 邀请人面板 + 统计（1 天）

**目标**：邀请人有自己的 `/panel`，能看到待审 + 个人统计。

- [ ] `handlers/inviter/panel.py` —— `/panel` 入口
- [ ] 待审核列表（分页 6 条/页）
- [ ] 个人统计：本月/累计 审核数 / 通过数 / 拒绝数 / 链接使用率
- [ ] 全局统计完善（接 M5 §3.3.9）：各邀请人通过率、密钥签发/使用/撤销数

**验收**：邀请人 `/panel` 能看到自己名下待审 + 统计数字。

---

### M10 Docker 化 + 部署 + 联调（1.5 天）

**目标**：一键部署到生产，所有功能端到端联调通过。

- [ ] 完善 `docker-compose.yml`（含 healthcheck、restart 策略）
- [ ] 完善 `Dockerfile`（多阶段构建、非 root 用户）
- [ ] `README.md` 部署文档：环境变量清单 / 启动步骤 / 升级步骤 / 应急换超管步骤
- [ ] 数据库备份方案文档
- [ ] **端到端联调清单**：
  - [ ] 自审型完整流（申请 → 审核 → 链接 → 入群 → 日志频道 → 出击报告频道）
  - [ ] 代审型完整流（同上 + 多管理员并发）
  - [ ] 回群密钥完整流（正常账号场景）
  - [ ] 回群密钥完整流（注销账号场景，需真实测试号）
  - [ ] 黑名单拦截
  - [ ] 链接过期未用
  - [ ] 超级管理员 .env 换人
  - [ ] 副管理员越权拦截

**验收**：清空数据后，按 README 一键部署，所有联调项目通过。

---

## 5. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|:----:|------|
| Telegram API 限频 / 网络抖动 | 中 | 全量请求带 `utils/retry.py` 指数退避；关键操作落库后再调 API |
| 注销账号识别误判 | 高 | 不确定时按"正常"降级处理（仅踢不封）；记录 cleanup_old_account_status='unknown' |
| 多管理员并发审核竞态 | 高 | DB 行锁 `SELECT FOR UPDATE`；状态机校验 status='pending' |
| 媒体组 caption 1024 超限 | 低 | 三消息降级方案 |
| 密钥被截图泄露 | 中 | 同 ID 拦截 + 频控 + 管理员可撤销 |
| 超级管理员账号被封 | 高 | .env `INITIAL_SUPER_ADMIN_ID` 强制覆盖机制；启动时检测差异自动换人 |

---

## 6. 测试策略

| 层级 | 范围 | 工具 |
|------|------|------|
| 单元 | 服务层业务逻辑、纯函数（密钥生成、注销识别、状态机） | pytest |
| 集成 | repository + DB | pytest-asyncio + 内存 SQLite |
| 端到端 | 走 Telegram 真实接口的关键路径 | 手工 + 测试号 |

**覆盖率目标**：服务层 ≥ 80%，handlers 不强制（手工测）。

---

## 7. Commit / 分支规范

- 主分支 `main`，每个 M 一个特性分支：`feature/M{n}-{slug}`
- Commit 格式：`M{n}: <action>`，例如 `M1: add wizard step 2 media validation`
- 每完成一个子任务（一个勾选框）即 commit 一次

---

## 8. 文档维护约定

| 文档 | 何时更新 |
|------|---------|
| REQUIREMENTS.md | 仅需求变更时；每次变更必须 bump 版本号并写明改动 |
| DEVELOPMENT_PLAN.md（本文档） | **每完成一个子任务**勾选；遇阻塞在 §11 记录；偏离原设计的决策在 §11 写明原因 |
| README.md | M10 阶段一次性完成 |
| audit_logs（DB 表） | 所有写操作自动落表，无需手动维护 |

---

## 9. 依赖速查

```toml
# pyproject.toml 关键依赖（M0 锁定版本）
python-telegram-bot = "^21"
sqlalchemy = "^2.0"
alembic = "^1.13"
pydantic-settings = "^2"
asyncpg = "*"
aiosqlite = "*"
argon2-cffi = "*"
structlog = "*"

[tool.dev-dependencies]
pytest = "*"
pytest-asyncio = "*"
ruff = "*"
mypy = "*"
```

---

## 10. 当前下一步

**☞ M2 ✅ 完成。等待用户确认即可进入 M3（代审型路由）**

M3 启动时执行：
1. 创建特性分支 `feature/M3-delegated`
2. 按 §4 M3 任务清单逐项打勾推进（在 audit_service 中实现广播 + 行锁）
3. 完成后合并到 main，进入 M4

---

## 11. 执行日志

> 开发过程中的偏离决策、阻塞、关键判断在此追加。每条带日期。

- `2026-05-12` 文档创建，与 REQUIREMENTS v1.0 对齐，未进入开发。
- `2026-05-12` **M2 完成**。关键决策与发现：
  - **新增 audit_messages 表**：原 plan 把 message_id 计划存 applications 列上，但代审型每个管理员一行更自然，独立表从一开始就支持 M3 多审核者扩展。
  - **拒绝原因输入采用 bot_data 状态字典**：在 `awaiting_reject_reasons[reviewer_id] = app_id` 中临时记录；进程重启即丢失，可接受（reviewer 可重新点拒绝）。落 DB 在 M2 阶段被判定为过度工程。
  - **消息分发优先级**：on_material_message 头部加入 `consume_reject_reason_text` 短路逻辑，确保审核者在等待原因时不会被 wizard handler 抢消息。
  - **audit_service 容错策略**：notify_reviewers 失败不回滚 status='pending'（避免用户被卡住），仅 log；后续可由 inviter `/panel` 主动重发。
  - **TTL clamp**：invite_link_service 强制 1–168 小时（即使 settings 表配置异常也不至于生成永久或负数 TTL 链接）。
  - **FakeBot 模式**：测试隔离 Telegram API 用一个 ~80 行的 FakeBot dataclass，记录 sent_media/sent_texts/edited/created_links。比 unittest.mock 更易读，断言细节更直观。
- `2026-05-12` **M1 完成**。关键决策与发现：
  - **wizard_step 编码**：0=选邀请人，i∈[1,N]=等待第 i 项材料，N+1=预览。N 来自 inviter.required_materials 长度（每个邀请人可配不同材料组合）。
  - **服务层零 Telegram 依赖**：wizard_service 入参全部用 plain Python 类型（含 `original_message_id: int`），便于单测；handler 层负责从 PTB Update 拆解再灌进来。
  - **回退到第 1 步的语义**：清空 inviter_id + clear_materials + step=0，回到选邀请人。设计上保证用户可换邀请人。
  - **取消采用二次确认**：避免误触丢失已提交材料；不取消的 dismiss 按钮编辑回提示文案，不会让用户卡住。
  - **handler 层"基于 DB 状态分发"**：用户从陈旧消息点按钮也安全 —— 一切按 DB 当前 status/wizard_step 决策。
  - **测试种子函数的坑**：`materials or [...]` 把 `materials=[]` 短路成默认值，已用 `if materials is None` 修正。
- `2026-05-12` **M0 完成**。关键决策与发现：
  - **PTB 实际版本 22.7**（pyproject 写的 `>=21.0`，pip 解析到 22.7）。代码 API 兼容，未受影响。
  - **本地 Python 3.14.4**：所有依赖安装无障碍。
  - **修复**：部分唯一索引 `uq_one_super_admin` 的 WHERE 子句首次用字符串报错（SA 需要 SQL 表达式对象），改为 `text("role = 'super'")` 后通过；PG 与 SQLite 同语法。
  - **真实 Telegram 联调推迟**：M0 验收做了"build_application 成功 + 注入逻辑 4 路径正确"，真实 `/start` 留到拿到 BOT_TOKEN 时一次性测。
  - **初始 migration 文件**：`alembic/versions/20260511_1713_0b2e72e9d569_initial_schema.py`。

---

**文档版本：v0.4（M2 完成）**
**最后更新：2026-05-12**
