# 开发日志（DEVLOG）

记录竞品情报 Agent 开发过程中的问题、原因、解决方案与优化。  
**维护约定：** 每次修复 Bug、完成优化或踩坑后，在下方「日志条目」**顶部**追加一条（最新的在最上）。

---

## 条目格式

```markdown
### YYYY-MM-DD | 简短标题

- **类型：** Bug / 优化 / 踩坑 / 设计说明 / 配置
- **状态：** 已解决 / 进行中 / 待处理 / 已知限制
- **影响范围：** 模块或文件
- **现象：** 看到了什么
- **原因：** 根因分析
- **解决 / 做法：** 具体步骤或代码变更（无则写「暂无」）
- **备注：** 可选，关联 Spec、后续 TODO
```

---

## 日志条目

### 2026-05-30 | 清库后 RSS 全链路验证通过（11 条推送）

- **类型：** 踩坑 / 验证
- **状态：** 已解决（验证通过）
- **影响范围：** 采集 → 处理 → 推送
- **现象：** 清空 `data/intel.db` 后执行 `python run_once.py`，约 50s 完成；`intel_new=11`，11 次 `pushed`，飞书 webhook 生效。
- **原因：** 此前 DB 中 URL 均已入库（`url_exists`），无新 RawDoc，推送不会被触发；清库后 30 天内 RSS 条目重新进入流水线。
- **解决 / 做法：**
  1. 停止 `main.py`（若在跑）
  2. `Remove-Item data\intel.db`（可选备份 `.bak`）
  3. `python run_once.py`
- **备注：** HTTP 源仍全部失败（见下条「trafilatura Document」）。Slack 配置 rss+atom 双 Feed 产生 3 条 `pre_dedup_skipped`；2 条 `title_duplicate_skipped`（CLI 标题相似）浪费 LLM Token。

---

### 2026-05-30 | 配置 webhook 后重跑仍无推送

- **类型：** 设计说明 / 踩坑
- **状态：** 已知限制（V1 按设计）
- **影响范围：** `intel/collect.py` → `intel/push.py`
- **现象：** 在 `competitors.yaml` 填入 `feishu_webhook` 后 `run_once`，日志无 `pushed` / `push_failed`，`intel_new=0`。
- **原因：**
  1. 推送仅对**本次运行新产生**的 Intel 调用（`job_collect` 内 `process` 成功后立刻 `push`）。
  2. 历史 `pending` 或 `failed_push.txt` 中的记录 **V1 不会自动补推**。
  3. 若采集阶段无新 RawDoc（去重 / stale / HTTP 失败），则根本不会进入 push。
- **解决 / 做法：**
  - 需要新内容：清库或等竞品 RSS 更新。
  - 补推历史：手动脚本调用 `push.push(intel, webhook)`，或后续实现 failed_push 重试（Spec 未定义 V1 自动重试）。
- **备注：** `failed_push.txt` 只是失败摘要（时间|竞品|标题|错误），不是飞书消息正文；完整内容在 `intel` 表。

---

### 2026-05-30 | HTTP 采集失败：trafilatura 返回 Document 非 dict

- **类型：** Bug
- **状态：** 待处理
- **影响范围：** `intel/collect.py` → `_collect_http`
- **现象：** HTTP 200 成功，随后 `collect_failed error="'Document' object has no attribute 'get'"`。Slack / Stripe / Linear 共 5 个 HTTP 源零产出；Linear 无 RSS，完全无情报。
- **原因：** 新版 `trafilatura.bare_extraction()` 返回 `Document` 对象，代码仍使用 `doc.get("text")` / `doc.get("title")` 按 dict 访问。
- **解决 / 做法：** 暂无。建议在 `_collect_http` 中兼容 `Document`（属性访问或 `as_dict()`）与 legacy dict 返回值；补充 `tests/test_collect.py` 用例。
- **备注：** 相关代码约 `intel/collect.py` L107–110。

---

### 2026-05-30 | main.py 启动后长时间无新日志

- **类型：** 踩坑 / 设计说明
- **状态：** 已理解（非 Bug）
- **影响范围：** `main.py`、`scheduler.py`
- **现象：** `python main.py` 首轮 `job_end` 约 17s 出现后，终端长时间无输出，用户误以为卡住。
- **原因：** `main.py` 启动 APScheduler 后 `await stop.wait()` 常驻；下次采集默认 **60 分钟**（`interval_minutes`）。首轮结束即进入等待，无新日志是正常的。
- **解决 / 做法：**
  - 单次验证用 `python run_once.py`（跑完即退出）。
  - 长期运行用 `main.py`；可调小 `interval_minutes` 做测试。
- **备注：** 启动时 `next_run_time=datetime.now()`，会立即执行一次 collect。

---

### 2026-05-30 | 调大 cold_start_days 仍 intel_new=0

- **类型：** 踩坑 / 设计说明
- **状态：** 已理解
- **影响范围：** `intel/collect.py` → `_collect_rss`，`config/competitors.yaml`
- **现象：** `cold_start_days: 7 → 30` 后重跑，仍大量跳过、无新情报。
- **原因：**
  1. `cold_start_days` 只影响**未入库**且发布时间在窗口内的 RSS；已在 `intel` 表的 URL 仍被 `url_exists` 跳过（与 cold_start 无关）。
  2. 配置上限 `le=30`，超过 30 天的条目仍 `collect_stale_entry`。
  3. HTTP 源失败不受益于该参数。
- **解决 / 做法：** 要重采历史需清库或删 `intel` 对应行；要更老条目需改 Spec/代码放宽 stale 逻辑（当前最大 30 天）。

---

### 2026-05-30 | intel.db 无法在编辑器中直接阅读

- **类型：** 踩坑
- **状态：** 已解决（使用方式）
- **影响范围：** `data/intel.db`
- **现象：** 在 Cursor 中打开 `intel.db` 显示乱码。
- **原因：** SQLite 为二进制格式，非文本文件。
- **解决 / 做法：**
  - 安装 Cursor/VS Code 插件 **SQLite Viewer**，右键打开。
  - 或 `python -c "import sqlite3; ..."` / DB Browser for SQLite。
  - 常用表：`intel`（情报）、`raw_doc`（采集元数据）、`run_log`（任务记录）、`failed_push`（推送失败队列）。
- **备注：** 改库前停 `main.py` 并备份 `intel.db`。

---

### 2026-05-30 | LLM 配置极简 + .env 自动加载

- **类型：** 优化
- **状态：** 已解决
- **影响范围：** `config/env.py`、`config/settings.py`、`infra/llm/factory.py`、`bootstrap.py` / `run_once.py` / `main.py`
- **现象：** 早期 LLM 未生效或 YAML 配置冗长。
- **原因：** API Key / base_url 分散在 YAML；未自动加载 `.env`。
- **解决 / 做法：**
  - YAML 仅保留 `llm.provider` + `llm.model`。
  - `load_settings()` 首行 `load_env()`（python-dotenv）。
  - Key 从 provider preset 对应环境变量读取（如 `DASHSCOPE_API_KEY`），启动日志 `llm_config_ready`。
- **备注：** 见 SPEC-2026-050 v1.4、`.env.example`。

---

### 2026-05-30 | Slack RSS + Atom 双源重复

- **类型：** 优化（配置层）
- **状态：** 待处理（可选）
- **影响范围：** `config/competitors.yaml`
- **现象：** 同一 changelog 在日志中成对出现 `collect_pre_dedup_skipped` / 采集阶段重复 RawDoc。
- **原因：** `rss.xml` 与 `atom.xml` 内容高度重叠；`collect_all` 先采完所有源再 process，Atom 重复 URL 在 process 阶段 `pre_dedup_skipped`。
- **解决 / 做法：** 配置中只保留 RSS **或** Atom 其中一个。
- **备注：** 不影响正确性，略增网络与日志噪音。

---

### 2026-05-30 | 标题去重在 LLM 之后，重复标题浪费 Token

- **类型：** 优化（待做）
- **状态：** 待处理
- **影响范围：** `intel/process.py`
- **现象：** 日志出现 `llm_call` 紧接着 `title_duplicate_skipped`（如 Slack CLI 多条版本标题）。
- **原因：** `_is_title_duplicate` 在 LLM 提取之后执行；相似标题仍调用 LLM。
- **解决 / 做法：** 暂无。可考虑用 RawDoc.title 或 RSS title 做 Pre-LLM 轻量标题去重（需 Spec 对齐）。
- **备注：** Spec 原则「重复内容不调用 LLM」主要针对 URL；标题相似是 Post-LLM 策略。

---

## 待办汇总（从日志提炼）

| 优先级 | 项 | 状态 |
|--------|-----|------|
| P0 | 修复 HTTP `trafilatura Document` 兼容 | 待处理 |
| P2 | Slack 去掉重复 RSS/Atom 源 | 可选 |
| P2 | failed_push 补推或 CLI 工具 | 未实现 |
| P3 | Pre-LLM 标题去重减少 Token | 未实现 |

---

## 相关文档

- [README.md](../README.md) — 运行与配置
- [specs/INDEX.md](../specs/INDEX.md) — Spec 索引
- `.cursor/rules/devlog.mdc` — Agent 更新本日志的规则
