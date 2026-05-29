# AI 智能推广工作流 v5.0

面向制造业 B2B 企业的公众号推广文自动生成系统。输入主题 → AI 自动完成内容类型识别、行业信息采集、AB 多版本生成、评审排序，输出可直接发布的高质量推文。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API Key
cp .env.example .env
# 编辑 .env，填入 DeepSeek API Key

# 3. 启动 Web 服务
python run.py --web
```

打开 http://localhost:8080，输入主题即可。

## 功能概览

| 功能 | 说明 |
|------|------|
| 内容类型自动识别 | 关键词快速分类（技术/政策/事件）+ LLM 精确分类可选 |
| 多源信息采集 | 7 个行业网站并发抓取，SSL 安全连接，Playwright 兜底 |
| 三研究员并行 | 类型驱动研究方向（技术→原理/参数/效益，政策→背景/影响/策略，事件→意义/角色/展望），ThreadPool 并发 |
| AB 三版本生成 | 标准版 + 数据版 + 故事版，自动选最优；快速模式仅出标准版 |
| 五维评审 | 品牌合规/数据/逻辑/语言/客户价值，低于 80 分自动修订 |
| RAG 向量检索 | Embedding 余弦相似度匹配，SQLite 持久化（上限 500 条），相似主题复用历史内容 |
| 知识库检索 | 中文 bigram TF 评分，自动分块，支持热重载 |
| 效果加成 | 历史发布数据驱动评分加成，高互动类型自动加权 |
| 内容审核 | 生成 → 待审核 → 通过/驳回/重新生成，审核意见 + 操作审计日志 |
| 效果追踪 | 阅读/分享/点赞数据录入，按内容类型 + 版本风格分组统计 |
| 内容日历 | YAML 排期，Web UI 可视化增删改，自动执行今日任务 |
| 定时任务 | Cron/单次/间隔，支持 Webhook 通知（企业微信/飞书/自定义） |
| 封面图生成 | DALL-E 3 自动配图，Provider 模式可扩展 |
| SEO + 多形态 | Meta Description、SEO 关键词、SEO 标题变体、朋友圈摘要、邮件推送版 |
| 热重载 | 运行时重载知识库、Prompt 模板、分类关键词信号 |
| 质量趋势 | 每日评分趋势、类型覆盖分析、评分分布、选题缺口检测 |

## 运行模式

```bash
# Web 界面
python run.py --web

# 单次生成
python run.py --topic "低温除湿干化技术原理解析"

# 快速模式（仅标准版，省 2/3 LLM 调用）
python run.py --topic "污泥处置新标准" --fast

# LLM 精确分类（默认关键词分类）
python run.py --topic "某展会动态" --classify-llm

# 对话模式（支持反馈迭代）
python run.py --chat

# 定时任务
python run.py --topic "每周政策解读" --schedule --cron "0 9 * * 1"
python run.py --topic "月度报告" --schedule --interval 1440
python run.py --topic "一次性任务" --schedule --at "2026-06-01T09:00:00"

# 自动执行今日日历任务
python run.py --auto
```

## 流水线架构

```
输入主题
  │
  ├─ Step 1  内容类型识别（关键词/LLM）
  ├─ Step 2  RAG 向量检索（历史相似内容复用）
  ├─ Step 3  知识库检索（企业文档 TF 匹配）
  ├─ Step 4  Phase0 网页抓取（7 站并发）
  ├─ Step 5  Phase1 三研究员并行
  ├─ Step 6  Phase2 AB 三版本生成（标准/数据/故事）
  ├─ Step 7  Phase3 评审排序 + 低分自动修订 + 效果加成
  ├─ Step 8  封面图生成（DALL-E 3）
  │
  └─ 输出：标题 + 正文 + SEO 元数据 + 朋友圈摘要 + 邮件版
```

关键设计：
- **并发控制**：Semaphore(2)，最多 2 个流水线同时运行，超时 300s
- **中断支持**：Web 端可随时停止正在执行的任务
- **输出轮替**：最多保留 30 个输出文件，超量自动清理最早文件

## 项目结构

```
ai-marketing-workflow/
├── main.py / run.py              # 入口
├── config.py                     # 全局配置（.env 驱动，dataclass）
├── pipeline.py                   # 核心流水线编排
├── agents/                       # Agent 模块
│   ├── classifier.py             # 内容类型识别（LLM + 关键词）
│   ├── researcher.py             # 三研究员并行
│   ├── editor.py                 # AB 多版本生成 + SEO 输出
│   └── critic.py                 # 五维评审 + 自动修订 + 效果加成
├── infra/                        # 基础设施
│   ├── llm.py                    # LLM/Embedding 调用（OpenAI 兼容）
│   ├── prompts.py                # Prompt 模板（支持热重载）
│   ├── scraper.py                # 网页抓取（requests + Playwright fallback）
│   ├── rag.py                    # RAG 向量检索（余弦相似度，SQLite 持久化）
│   ├── memory.py                 # 记忆层：会话/审核/效果追踪/统计
│   ├── knowledge_base.py         # 知识库分块 + 中文 bigram TF 检索
│   ├── image_gen.py              # 封面图生成（Provider 模式）
│   ├── notify.py                 # Webhook 通知（企业微信/飞书/自定义）
│   └── sqlite_utils.py           # SQLite 工具（WAL checkpoint / vacuum）
├── web/
│   ├── routes.py                 # FastAPI 路由（40+ 端点）
│   └── templates/
│       ├── index.html            # Web UI
│       └── style.css
├── cli/chat.py                   # CLI 对话模式
├── scheduler/scheduler.py        # 定时调度（APScheduler）
├── tests/                        # 单元测试
├── jikang-marketing-skill/       # 企业品牌 Skill
│   ├── SKILL.md                  # 品牌策略 + 架构文档
│   ├── assets/
│   │   ├── content_calendar.yaml # 内容日历排期
│   │   └── article_template.md   # 文章模板
│   └── references/
│       ├── content_types.md      # 内容类型写作策略
│       ├── brand_guidelines.md   # 品牌调性手册
│       ├── search_strategy.md    # 搜索策略
│       └── knowledge_base_setup.md # 知识库配置
├── knowledge_base/               # 企业知识库 Markdown 文件
├── memory/                       # SQLite 数据库文件（运行时自动创建）
└── outputs/                      # 生成结果输出
```

## 配置项（.env）

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `LLM_MODEL` | 模型名称 | `deepseek-v4-flash` |
| `OPENAI_API_KEY` | API Key（兼容 OpenAI/DeepSeek） | - |
| `OPENAI_API_BASE` | API 地址 | `https://api.openai.com/v1` |
| `WEB_PORT` | Web 端口 | `8080` |
| `OUTPUT_DIR` | 输出目录 | `./outputs` |
| `OUTPUT_MAX_FILES` | 最多保留输出文件数 | `30` |
| `PERF_BOOST_WEIGHT` | 效果加成权重 | `0.15` |
| `WEBHOOK_URL` | 通知 Webhook（可选） | - |
| `WEBHOOK_TYPE` | 通知类型：`wecom` / `feishu` / `generic` | `generic` |
| `SCHEDULER_TIMEZONE` | 调度时区 | `Asia/Shanghai` |
| `LOG_LEVEL` | 日志级别 | `INFO` |

## Web API 概览

### 生成
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/generate` | POST | 提交异步生成任务，返回 task_id 轮询 |
| `/api/chat` | POST | 同步生成（支持 feedback 迭代） |
| `/api/chat/stream` | POST | SSE 流式生成，实时推送阶段进度 |
| `/api/task/{tid}` | GET | 查询任务状态和结果 |
| `/api/stop` | POST | 停止所有进行中的任务 |

### 审核
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/review/pending` | GET | 待审核列表 |
| `/api/review/approve` | POST | 通过审核 |
| `/api/review/reject` | POST | 驳回（填写原因） |
| `/api/review/regen` | POST | 根据驳回原因重新生成 |
| `/api/review/comment` | POST | 添加审核意见 |
| `/api/review/comments/{sid}` | GET | 查看审核意见 |
| `/api/review/audit/{sid}` | GET | 查看操作审计日志 |
| `/api/review/rejected` | GET | 驳回记录列表 |

### 效果追踪
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/performance` | POST | 录入阅读/分享/点赞数据 |
| `/api/performance/{sid}` | GET | 查询单篇效果 |
| `/api/performance/style` | POST | 记录实际发布版本风格 |
| `/api/performance/stats` | GET | 按类型 + 风格分组统计 |

### 统计与趋势
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/stats` | GET | 总览（总数/均分/今日/待审/token） |
| `/api/stats/tokens` | GET | Token 用量 + 月度明细 + 成本估算 |
| `/api/stats/trends` | GET | 每日评分趋势 + 类型对比 + 分布 |
| `/api/stats/coverage` | GET | 内容覆盖率 + 选题缺口分析 |

### 知识库管理
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/knowledge` | GET | 列出知识库文件（按目录分组） |
| `/api/knowledge/{path}` | GET | 读取文件内容 |
| `/api/knowledge` | POST | 创建/更新 Markdown 文件 |
| `/api/knowledge` | DELETE | 删除文件（自动清理空目录） |

### 调度与会话
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/schedule` | POST | 创建一次性定时任务 |
| `/api/schedule/cron` | POST | 创建 Cron 定时任务 |
| `/api/schedule/list` | GET | 查看定时任务列表 |
| `/api/schedule/cancel` | POST | 取消定时任务 |
| `/api/sessions` | GET | 会话列表（支持类型/日期/关键词过滤） |
| `/api/sessions/{sid}` | GET | 会话详情 |
| `/api/sessions/{sid}` | DELETE | 删除会话 |

### 其他
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/reload` | GET | 热重载知识库 + Prompt + 分类信号 |
| `/api/calendar` | GET/POST/PUT/DELETE | 内容日历 CRUD |
| `/api/export` | GET | 导出已审核文章（txt/json） |
| `/api/config/status` | GET | 配置状态检查 |
| `/api/notifications` | GET | 最近通知记录 |

## 内容日历

编辑 `jikang-marketing-skill/assets/content_calendar.yaml`，或在 Web UI 中点击「日历」按钮直接增删改：

```yaml
- date: "2026-05-25"
  type: tech
  topic: "低温除湿干化设备选型指南"
  keywords: ["设备选型", "参数对比", "热泵"]
  priority: high
```

运行 `python run.py --auto` 自动执行今日任务。

日历 Web API 支持读取未来 N 天任务，自动计算完成率和月度统计。

## 审核工作流

```
生成完成 → pending_review
              ├─ approve  → approved → 计入统计
              ├─ reject   → rejected（记录原因 + 审计日志）
              └─ regen    → 根据驳回原因重新调用流水线
```

- 审核操作全程审计日志（操作人、动作、状态变更、备注）
- 支持审核意见评论，可按阶段记录
- Web UI 侧边栏查看待审列表、预览正文

## 效果追踪与反馈闭环

1. 文章发布后，通过 Web API 录入阅读/分享/点赞数据
2. 记录实际发布时选用的版本风格（标准/数据/故事）
3. 按内容类型 + 版本风格统计效果，支撑策略优化
4. 效果加成机制：历史高互动类型自动获得评分加权（`PERF_BOOST_WEIGHT`），引导生成偏好

## 知识库

在 `knowledge_base/` 目录下放置 Markdown 文件，系统启动时自动加载分块。支持：

- 按段落 + 句子边界智能分块（500 字/块，100 字重叠）
- 中文 bigram + 英文分词混合 TF 评分检索
- 标题行自动加权
- 通过 `/api/reload` 或 Web UI 热重载，无需重启

## 依赖

- Python 3.10+
- LangGraph + LangChain（Agent 框架）
- FastAPI + uvicorn（Web 服务）
- APScheduler（定时调度）
- requests + BeautifulSoup + Playwright（网页抓取）
- numpy + scikit-learn（向量计算）
- OpenAI SDK（LLM 调用，兼容 DeepSeek）

## License

Internal use.
