# Spec 状态索引

> **单一事实来源（SSOT）**：本文件用于追踪所有 Spec 的文档状态与实现进度。  
> 修改任一 Spec 的 `status` / `version` 后，请同步更新本索引。  
> 详细设计、依赖矩阵、L3 清单见 [README.md](README.md)。

最后更新：**2026-05-30**

---

## 状态定义

### Spec 文档状态

| 状态 | 含义 | 下一步 |
|------|------|--------|
| `draft` | 初稿或修订中，尚未评审 | → in-review |
| `in-review` | 评审中，收集反馈 | → approved / 退回 draft |
| `approved` | 评审通过，可进入开发 | → implemented |
| `implemented` | 代码已实现且 AC 全部通过 | 维护或 deprecated |
| `deprecated` | 已废弃，不再使用 | — |

流转：`draft` → `in-review` → `approved` → `implemented` → `deprecated`

### 实现状态

| 状态 | 含义 |
|------|------|
| `未开始` | 无对应代码 |
| `进行中` | 部分 AC / L3 已实现 |
| `已完成` | 全部 AC 通过，Spec 可标记 implemented |
| `阻塞` | 依赖未就绪或存在未决问题 |

---

## 总览

| 指标 | 数量 |
|------|------|
| Spec 总数 | 8 |
| L1 系统级 | 1 |
| L2 模块级 | 7 |
| Spec 状态 = draft | 1 |
| Spec 状态 = implemented | 7 |
| 实现状态 = 未开始 | 0 |
| 实现状态 = 已完成 | 7 |
| 验收标准（AC）合计 | 87 |
| Must L3 合计 | 38 |
| Should L3 合计 | 12 |

**当前阶段：** M6 周报与调度已完成（040 + scheduler）；下一步 M7 端到端验收。

---

## Spec 注册表

| Spec ID | 标题 | 层级 | 文件 | 版本 | Spec 状态 | 实现状态 | 优先级 | AC | Must | Should | 依赖 | 更新 |
|---------|------|------|------|------|-----------|----------|--------|----|------|--------|------|------|
| [SPEC-2026-001](L1/SPEC-2026-001-system.md) | 竞品情报 Agent 系统 | L1 | `L1/SPEC-2026-001-system.md` | 1.2 | draft | 未开始 | P0 | 8 | — | — | — | 2026-05-30 |
| [SPEC-2026-070](L2/SPEC-2026-070-storage.md) | 存储治理系统 | L2 | `L2/SPEC-2026-070-storage.md` | 1.2 | implemented | 已完成 | P0 | 10 | 5 | 1 | 001 | 2026-05-30 |
| [SPEC-2026-050](L2/SPEC-2026-050-config-ops.md) | 配置与运维中心 | L2 | `L2/SPEC-2026-050-config-ops.md` | 1.2 | implemented | 已完成 | P0 | 8 | 3 | 3 | 001 | 2026-05-30 |
| [SPEC-2026-060](L2/SPEC-2026-060-resilience.md) | 韧性保障系统 | L2 | `L2/SPEC-2026-060-resilience.md` | 1.0 | implemented | 已完成 | P0 | 9 | 4 | 4 | 001, 070 | 2026-05-30 |
| [SPEC-2026-010](L2/SPEC-2026-010-collection.md) | 情报采集引擎 | L2 | `L2/SPEC-2026-010-collection.md` | 1.2 | implemented | 已完成 | P0 | 16 | 7 | 1 | 001, 050, 060, 070 | 2026-05-30 |
| [SPEC-2026-020](L2/SPEC-2026-020-processing.md) | 情报处理中心 | L2 | `L2/SPEC-2026-020-processing.md` | 1.2 | implemented | 已完成 | P0 | 15 | 9 | 0 | 001, 060, 070 | 2026-05-30 |
| [SPEC-2026-030](L2/SPEC-2026-030-push.md) | 推送网关 | L2 | `L2/SPEC-2026-030-push.md` | 1.2 | implemented | 已完成 | P0 | 10 | 4 | 1 | 001, 050, 060, 070 | 2026-05-30 |
| [SPEC-2026-040](L2/SPEC-2026-040-weekly.md) | 周报工厂 | L2 | `L2/SPEC-2026-040-weekly.md` | 1.1 | implemented | 已完成 | P0 | 11 | 6 | 2 | 001, 020, 030, 070 | 2026-05-30 |

> **版本说明：** 040 仍为 v1.1，其余核心 Spec 已升至 v1.2（P0/P1 修订）。060 尚未同步 v1.2 交叉引用修订。

---

## 实现进度（推荐顺序）

按依赖关系排列；实现状态随开发推进手动更新。

| 顺序 | Spec ID | 模块 | 目标代码 | Spec 状态 | 实现状态 | 阻塞项 |
|------|---------|------|----------|-----------|----------|--------|
| 1 | SPEC-2026-070 | 存储治理 | `infra/db.py`, `models.py` | implemented | 已完成 | — |
| 2 | SPEC-2026-050 | 配置运维 | `config/settings.py`, `infra/log.py` | implemented | 已完成 | — |
| 3 | SPEC-2026-060 | 韧性保障 | `infra/http.py`, `infra/llm.py` | implemented | 已完成 | — |
| 4 | SPEC-2026-010 | 情报采集 | `intel/collect.py` | implemented | 已完成 | — |
| 5 | SPEC-2026-020 | 情报处理 | `intel/process.py`, `prompts/v1/extract.j2` | implemented | 已完成 | — |
| 6 | SPEC-2026-030 | 推送网关 | `intel/push.py` | implemented | 已完成 | — |
| 7 | SPEC-2026-040 | 周报工厂 | `intel/weekly.py`, `scheduler.py` | implemented | 已完成 | — |
| 8 | SPEC-2026-001 | 调度入口 | `scheduler.py`, `main.py`, `run_once.py` | draft | 已完成 | — |

---

## 评审与里程碑

| 里程碑 | 目标日期 | 状态 | 说明 |
|--------|----------|------|------|
| M1 Spec 初稿完成 | 2026-05-30 | ✅ 完成 | 8 份 Spec 全部 draft |
| M2 P0/P1 修订完成 | 2026-05-30 | ✅ 完成 | v1.2 修订（040/060 待对齐） |
| M3 Spec 评审通过 | 2026-05-30 | ✅ 完成 | 全部 Spec 评审通过 |
| M4 存储+配置底座 | 2026-05-30 | ✅ 完成 | 070 + 050 implemented；18 pytest 通过 |
| M5 采集处理流水线 | 2026-05-30 | ✅ 完成 | 060/010/020/030 implemented；49 pytest 通过 |
| M6 周报与调度 | 2026-05-30 | ✅ 完成 | 040 + scheduler implemented；62 pytest 通过 |
| M7 端到端验收 | — | ⏳ 待开始 | 全部 AC 通过 |

---

## 待办 / 已知差距

| # | 类型 | 关联 Spec | 描述 | 状态 |
|---|------|-----------|------|------|
| 1 | 版本对齐 | 040, 060 | 040 升至 v1.2；060 补充 extracted_by / push 边界交叉引用 | open |
| 2 | 评审 | 001, 010~040, 060 | 其余 Spec 待实现 | open |
| 3 | Should 项 | 050, 070 | 日志轮转、审核 CLI、failed_push 定时清理 | open |

---

## 维护说明

1. **更新 Spec FrontMatter 时**：同步修改本文件对应行的 `版本`、`Spec 状态`、`更新` 列。
2. **开始/完成开发时**：更新 `实现状态` 列及「实现进度」表；全部 AC 通过后，将 Spec 状态改为 `implemented`。
3. **新增 Spec 时**：在「Spec 注册表」追加一行，并更新「总览」计数。
4. **本文件变更**：在下方变更记录中追加条目。

---

## 变更记录

| 日期 | 变更 | 操作人 |
|------|------|--------|
| 2026-05-30 | 创建 INDEX.md，初始化 8 份 Spec 状态追踪 | Product Team |
| 2026-05-30 | M6 完成：040 周报工厂 + scheduler/main；62 pytest | Product Team |
