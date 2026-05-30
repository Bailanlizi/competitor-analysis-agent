# 竞品情报 Agent

为产品经理设计的竞品情报自动采集、处理、推送与周报汇总系统。后台定时从 RSS、静态网页等公开渠道拉取竞品信息，经 LLM 提取结构化情报后推送至飞书/钉钉，每周一自动生成 Markdown 周报。

面向单一用户、本地/自托管部署，数据存储在本地 SQLite 与文件系统中（LLM 调用除外）。

## 功能概览

| 能力 | 说明 |
|------|------|
| 定时采集 | RSS 订阅 + 静态 HTTP 页面，默认每 60 分钟执行 |
| 情报提取 | 可插拔 LLM 后端（默认 OpenAI）；无 API Key 时降级为规则匹配 |
| 实时推送 | 高置信度情报推送飞书/钉钉 webhook |
| 周报汇总 | 每周一 09:00 生成 Markdown 周报并推送 |
| 数据治理 | 去重、原始 HTML 归档、失败推送记录、日志清理 |

## 系统架构

```
触发层 (APScheduler)
    ├── collect      定时采集
    ├── weekly       周一周报
    └── cleanup_*    数据/日志清理

流水线
    Collect → Process → Push
    (采集)    (LLM)     (推送)

存储层
    SQLite (data/intel.db) + 本地文件 (storage/, reports/, logs/)
```

## 项目结构

```
competitor-analysis-agent/
├── main.py                 # 生产入口：启动调度器，长期后台运行
├── run_once.py             # 手动单次采集
├── bootstrap.py            # 冒烟测试：加载配置 + 初始化 DB
├── scheduler.py            # APScheduler 任务注册
├── config/
│   ├── competitors.yaml    # 竞品源、webhook、调度配置
│   └── settings.py         # 配置加载与校验
├── intel/
│   ├── collect.py          # 采集编排
│   ├── process.py          # LLM 情报提取
│   ├── push.py             # 飞书/钉钉推送
│   └── weekly.py           # 周报生成
├── infra/
│   ├── db.py               # SQLite 存储
│   ├── llm/                # LLM 可插拔层（Provider + 降级）
│   ├── http.py             # HTTP 客户端
│   ├── log.py              # 结构化日志
│   └── utils.py            # 工具函数
├── prompts/v1/             # Jinja2 提示词模板
├── models.py               # Pydantic 数据模型
├── tests/                  # pytest 测试套件
└── specs/                  # Spec 设计文档（见 specs/INDEX.md）
```

## 环境要求

- Python 3.11+
- 网络访问（采集目标站点 + LLM API）

### LLM 后端配置（可插拔）

**YAML 只配 provider 和 model**，密钥与 URL 写在项目根目录 `.env`，启动时自动加载（`python-dotenv`）：

```yaml
# config/competitors.yaml
llm:
  provider: qwen
  model: qwen-plus
```

```env
# .env（复制自 .env.example）
DASHSCOPE_API_KEY=sk-...
LLM_BASE_URL=          # 可选，覆盖 preset 默认端点；custom/azure 必填
LLM_API_KEY=           # 可选，preset 专用 Key 为空时的通用 fallback
```

| provider | .env 密钥变量 | 说明 |
|----------|---------------|------|
| `openai` | `OPENAI_API_KEY` | 默认 |
| `deepseek` | `DEEPSEEK_API_KEY` | DeepSeek |
| `qwen` | `DASHSCOPE_API_KEY` | 通义千问兼容模式 |
| `moonshot` | `MOONSHOT_API_KEY` | Kimi |
| `zhipu` | `ZHIPU_API_KEY` | 智谱 |
| `ollama` | （无需） | 本地端点，可用 `LLM_BASE_URL` 覆盖 |
| `custom` / `azure` | `LLM_API_KEY` 或对应 Key | 必须在 `.env` 设置 `LLM_BASE_URL` |

启动后日志会输出 `llm_config_ready`（含 `api_key_configured`、脱敏 `base_url`）。若 Key 缺失会 warning，LLM 自动降级为规则提取。

## 快速开始

### 1. 安装依赖

```bash
git clone <repo-url>
cd competitor-analysis-agent

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`（启动时自动加载），填入对应 provider 的 API Key：

```env
DASHSCOPE_API_KEY=sk-...     # llm.provider: qwen
LLM_BASE_URL=                # 可选；custom/azure 必填
SEARCH_API_KEY=...           # 关键词搜索（可选，默认关闭）
```

### 3. 配置竞品源

编辑 `config/competitors.yaml`：

- 将占位 URL 替换为真实竞品的 RSS / 更新日志 / 定价页地址
- 填入 `feishu_webhook` 或 `dingtalk_webhook`（未配置时推送写入本地失败记录）

```yaml
interval_minutes: 60
timezone: "Asia/Shanghai"
feishu_webhook: "https://open.feishu.cn/open-apis/bot/v2/hook/..."

competitors:
  - id: competitor_a
    name: "竞品 A"
    enabled: true
    sources:
      - type: rss
        url: "https://example.com/feed.xml"
      - type: http
        url: "https://example.com/changelog"
        name: "更新日志"
  # ... 共 3 个竞品
```

## 运行方式

### 冒烟测试

验证配置加载与数据库初始化：

```bash
python bootstrap.py
```

### 手动单次采集

执行一次完整的采集 → 处理 → 推送流程：

```bash
python run_once.py
```

### 长期后台运行（推荐）

启动调度器，自动定时采集并每周生成周报：

```bash
python main.py
```

按 `Ctrl+C` 优雅退出。

### 手动触发周报

```bash
python -c "import asyncio; from intel.weekly import job_weekly; asyncio.run(job_weekly())"
```

## 调度任务

| Job ID | 触发规则 | 功能 |
|--------|----------|------|
| `collect` | 每 N 分钟（默认 60），启动即执行 | 采集 + 处理 + 推送 |
| `weekly` | 每周一 09:00 | 生成并推送周报 |
| `cleanup_failed_push` | 每日 01:00 | 清理过期失败推送记录 |
| `cleanup_logs` | 每日 02:00 | 日志 gzip 压缩与删除 |
| `cleanup_raw_html` | 每日 03:00 | 清理原始 HTML 缓存 |
| `disk_check` | 每 60 分钟 | 磁盘空间告警 |

时区由 `config/competitors.yaml` 中的 `timezone` 控制，默认 `Asia/Shanghai`。

## 开发日志

开发过程中的问题、原因、解决方案与优化记录在 [`docs/DEVLOG.md`](docs/DEVLOG.md)。修复 Bug 或完成优化后请按该文件顶部格式追加条目（Cursor Agent 规则会自动提醒维护）。

## 运行产物

| 路径 | 说明 |
|------|------|
| `data/intel.db` | SQLite 数据库（情报、运行日志、失败推送） |
| `logs/YYYY-MM-DD.json` | 结构化 JSON 日志 |
| `reports/weekly/YYYY-MM-DD.md` | 周报 Markdown 归档 |
| `storage/raw/` | 原始 HTML 缓存 |
| `data/failed_push.txt` | 推送失败本地备份 |

## 测试

```bash
# 全量测试
pytest

# 按模块
pytest tests/test_weekly.py -v
pytest tests/test_scheduler.py -v
pytest tests/test_collect.py -v
pytest tests/test_pipeline.py -v
```

当前共 **74** 项测试。测试使用隔离临时目录，不会污染 `data/` 与 `logs/`。

## 开发进度

| 里程碑 | 状态 |
|--------|------|
| M4 存储 + 配置底座 | ✅ |
| M5 采集处理流水线 | ✅ |
| M6 周报与调度 | ✅ |
| M7 端到端验收 | ⏳ 待开始 |

Spec 文档与实现状态追踪见 [specs/INDEX.md](specs/INDEX.md)。

## 技术栈

| 组件 | 选型 |
|------|------|
| 语言 | Python 3.11+ |
| 数据模型 | Pydantic v2 |
| 数据库 | SQLite |
| HTTP | httpx |
| RSS | feedparser |
| 网页提取 | trafilatura |
| LLM | 可插拔 Provider（OpenAI 兼容 SDK，默认 openai/gpt-4o-mini） |
| 调度 | APScheduler |
| 日志 | structlog (JSON) |
| 测试 | pytest + pytest-asyncio |

## License

Private / internal use.
