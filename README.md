# AI 智能推广工作流 v5.0

面向制造业 B2B 企业的公众号推广文自动生成系统。输入主题 → AI 自动完成内容类型识别、行业信息采集、AB多版本生成、评审排序，输出可直接发布的高质量推文。

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
| 内容类型自动识别 | 根据主题关键词自动判断技术/政策/事件类型 |
| 多源信息采集 | 7 个行业网站并发抓取，SSL 安全连接 |
| 三研究员并行 | 类型驱动研究方向，ThreadPool 并发 |
| AB 三版本生成 | 标准版 + 数据版 + 故事版，自动选最优 |
| 五维评审 | 品牌合规/数据/逻辑/语言/客户价值，低于 80 分自动修订 |
| RAG 历史利用 | Embedding 向量持久化，相似主题复用历史内容 |
| 内容审核 | 生成 → 待审核 → 通过/驳回/重新生成 |
| 效果追踪 | 阅读/分享/点赞数据录入 + 类型效果对比 |
| 内容日历 | 可视化排期，Web 端直接编辑 |
| 定时任务 | Cron/单次/间隔，支持 Webhook 通知 |
| 封面图生成 | DALL-E 3 自动配图 |

## 运行模式

```bash
# 单次生成
python run.py --topic "低温除湿干化技术原理解析"

# 快速模式（仅标准版，省 2/3 LLM 调用）
python run.py --topic "污泥处置新标准" --fast

# 对话模式（支持反馈迭代）
python run.py --chat

# 定时任务
python run.py --topic "每周政策解读" --schedule --cron "0 9 * * 1"

# 自动执行今日日历任务
python run.py --auto
```

## 项目结构

```
ai-marketing-workflow/
├── main.py / run.py          # 入口
├── config.py                 # 全局配置（.env 驱动）
├── pipeline.py               # 核心流水线编排
├── agents/                   # Agent 模块
│   ├── classifier.py         # 内容类型识别（LLM + 关键词）
│   ├── researcher.py         # 三研究员并行
│   ├── editor.py             # AB 多版本生成
│   └── critic.py             # 评审排序 + 效果加成
├── infra/                    # 基础设施
│   ├── llm.py                # LLM/Embedding 调用
│   ├── prompts.py            # Prompt 模板（支持热重载）
│   ├── scraper.py            # 网页抓取（Playwright fallback）
│   ├── rag.py                # RAG 向量检索（SQLite 持久化）
│   ├── memory.py             # 记忆层（审核 + 效果追踪）
│   ├── knowledge_base.py     # 知识库分块检索
│   ├── image_gen.py          # 封面图生成
│   ├── notify.py             # Webhook 通知
│   └── sqlite_utils.py       # SQLite 工具
├── web/
│   ├── routes.py             # FastAPI 路由
│   └── templates/
│       ├── index.html        # Web UI（白色主题）
│       └── style.css
├── cli/chat.py               # CLI 对话模式
├── scheduler/scheduler.py    # 定时调度
├── tests/                    # 单元测试
├── jikang-marketing-skill/   # 企业品牌 Skill
└── memory/                   # SQLite 数据库
```

## 配置项（.env）

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key | - |
| `DEEPSEEK_API_BASE` | API 地址 | `https://api.deepseek.com/v1` |
| `LLM_MODEL` | 模型名称 | `deepseek-v4-flash` |
| `WEB_PORT` | Web 端口 | `8080` |
| `OUTPUT_DIR` | 输出目录 | `./outputs` |
| `OUTPUT_MAX_FILES` | 最多保留输出文件数 | `30` |
| `WEBHOOK_URL` | 通知 Webhook（可选） | - |
| `WEBHOOK_TYPE` | 通知类型：wecom/feishu/generic | `generic` |
| `PERF_BOOST_WEIGHT` | 效果加成权重 | `0.15` |

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

## 审核工作流

1. 生成后文章进入「待审核」状态
2. 审核人可在 Web UI 侧边栏查看、预览正文
3. 通过 → 标记 approved，计入统计
4. 驳回 → 填写原因，标记 rejected
5. 重新生成 → 根据驳回原因重新调用流水线
