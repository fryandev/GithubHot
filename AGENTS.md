# AGENTS.md

> 本文件面向 AI 编程助手。读者应被假设对本项目一无所知。

## 项目概述

**GithubHot** 是一个持续更新的 GitHub 热门项目数据库与中文文档系统。

核心工作流：
1. **抓取** — 通过 GitHub REST / GraphQL API 获取高星开源项目元数据
2. **评分** — 基于 Stars、Forks、Watchers、Issues、7日/30日增速计算综合热度分
3. **分类** — 自动打上语言、领域、热度等级、活跃度、趋势五类标签
4. **翻译** — 将项目描述和 Topics 翻译成中文（保留技术专有名词）
5. **生成文档** — 输出按语言/领域/热度/活跃/趋势分类的 Markdown 文档到 `docs/`

项目主要使用中文注释和文档。代码位于 `src/github_hot/`，数据库为 `data/github_hot.db`（SQLite）。

---

## 技术栈与依赖

| 层级 | 技术 |
|---|---|
| 语言 | Python 3.11+ |
| 数据库 | SQLite3（标准库） |
| CLI 框架 | Click |
| HTTP 请求 | requests |
| 模板引擎 | Jinja2（用于生成 Markdown） |
| 配置格式 | YAML |
| 进度条 | tqdm |
| 定时调度 | schedule（`refresh --schedule` 使用） |
| 可选翻译 | deep_translator、googletrans、mlx_lm（本地模型） |

依赖清单见 `requirements.txt`：
```
requests>=2.31.0
pyyaml>=6.0.1
click>=8.1.7
tqdm>=4.66.1
jinja2>=3.1.2
schedule>=1.2.0
```

> 注意：项目没有 `setup.py`、`pyproject.toml` 或 `package.json`，是纯脚本型 Python 项目，通过 `PYTHONPATH=src` 运行。

---

## 目录结构

```
.
├── config.yaml              # 核心配置文件（API、评分权重、分类关键词）
├── requirements.txt         # Python 依赖
├── data/
│   └── github_hot.db        # SQLite 数据库（项目数据 + 标签 + 趋势排名 + 抓取历史）
├── src/github_hot/          # 主源码包
│   ├── __init__.py
│   ├── __main__.py          # python -m github_hot 入口
│   ├── cli.py               # Click CLI（所有命令入口）
│   ├── database.py          # SQLite 封装：Schema、CRUD、统计、增速计算
│   ├── fetcher.py           # GitHub REST API 抓取器
│   ├── graphql_fetcher.py   # GitHub GraphQL API 抓取器（突破1000条限制）
│   ├── trend_fetcher.py     # OpenGithubs 日/周/月飙升榜抓取器
│   ├── scorer.py            # 热门评分算法
│   ├── classifier.py        # 项目自动分类器（语言/领域/热度/活跃/趋势）
│   ├── translator.py        # 多后端批量翻译器（MLX → Google → googletrans）
│   └── writer.py            # Markdown 文档生成器（Jinja2 模板）
├── scripts/
│   └── bulk_translate.py    # 独立大批量翻译脚本（断点续翻、每100条保存）
├── docs/                    # 生成的 Markdown 文档
│   ├── README.md            # 总览首页
│   ├── by-language/         # 按编程语言分类
│   ├── by-category/         # 按领域分类
│   ├── by-hotness/          # 按热度等级分类
│   ├── by-activity/         # 按最近活跃时间分类
│   ├── by-trend/            # 按 OpenGithubs 趋势榜分类
│   ├── TRANSLATION.md       # 翻译工作流详细说明
│   ├── FETCH_STRATEGY.md    # 抓取策略详细说明（REST vs GraphQL、穷尽方案）
│   └── TRANSLATION-legacy.md
└── README.md                # 项目根 README（由 writer.py 自动生成）
```

---

## 运行方式

所有命令均需将 `src` 加入 Python 路径：

```bash
# 通用前缀
PYTHONPATH=src python -m github_hot.cli <command>
```

### 核心命令

```bash
# 一键完整更新（fetch → fetch-trends → score → classify → generate）
PYTHONPATH=src python -m github_hot.cli update

# 分步执行
PYTHONPATH=src python -m github_hot.cli fetch --pages 10 --threshold 1000
PYTHONPATH=src python -m github_hot.cli fetch-graphql --query "stars:>=2000" --max-results 5000
PYTHONPATH=src python -m github_hot.cli fetch-trends
PYTHONPATH=src python -m github_hot.cli backfill-trends
PYTHONPATH=src python -m github_hot.cli score
PYTHONPATH=src python -m github_hot.cli classify
PYTHONPATH=src python -m github_hot.cli translate
PYTHONPATH=src python -m github_hot.cli generate

# 日常刷新（活跃度/趋势/翻译/文档会随时间自然变化）
PYTHONPATH=src python -m github_hot.cli refresh

# 定时自动刷新（每天 08:30）
PYTHONPATH=src python -m github_hot.cli refresh --schedule --time 08:30

# 查询类命令
PYTHONPATH=src python -m github_hot.cli list-projects --limit 20
PYTHONPATH=src python -m github_hot.cli list-projects --language python
PYTHONPATH=src python -m github_hot.cli list-projects --tag ai-ml
PYTHONPATH=src python -m github_hot.cli stats
PYTHONPATH=src python -m github_hot.cli info owner/repo
```

### 环境变量

| 变量 | 说明 |
|---|---|
| `GITHUB_TOKEN` | **强烈建议设置**。GitHub Personal Access Token，用于提高 API 速率限制。REST API 无 Token 为 60次/小时，有 Token 为 5000次/小时；GraphQL 为 5000点/小时。 |

---

## 数据库 Schema

数据库文件：`data/github_hot.db`

### `projects` 表（核心）

```
id, github_id, full_name, owner, name, description, html_url,
language, stars, forks, watchers, open_issues,
created_at, updated_at, pushed_at, topics(JSON), license,
homepage, size, archived, fork,
stars_7d_ago, stars_30d_ago, stars_90d_ago,
hotness_score, hotness_level,
description_zh, topics_zh,
first_seen_at, last_fetched_at, fetch_count, is_hot
```

### `tags` 表 + `project_tags` 表

多对多关系。标签分类：
- `language`：编程语言标签
- `domain`：领域标签（ai-ml、web-dev、devops、database 等）
- `hotness`：热度等级（legendary、very-hot、hot、rising、trending-weekly 等）
- `activity`：活跃标签（activity-daily、activity-weekly、activity-monthly，基于 `pushed_at`）
- `trend`：趋势标签（trend-top-daily、weekly、monthly，基于外部 OpenGithubs 数据）

### `fetch_history` 表

记录每次抓取的 stars/forks/open_issues，用于计算增速。

### `trend_rankings` 表

存储 OpenGithubs 社区日/周/月飙升榜单的外部数据：
```
id, full_name, period(daily/weekly/monthly), rank, growth, total_stars,
ranking_date, fetched_at
```

---

## 代码组织与模块职责

### `cli.py`
- Click 命令组入口，定义所有子命令
- 负责命令编排（如 `update` 依次调用 fetch → fetch-trends → score → classify → generate）
- `refresh` 命令内部定义 `_refresh_job()`，使用 `schedule` 库做定时任务
- 注意：模块顶部有 `sys.path.insert(0, str(Path(__file__).parent.parent))` 以确保能找到 `src`

### `database.py`
- `Database` 类封装所有 SQLite 操作
- 在 `__init__` 中自动执行 `SCHEMA` 创建表和索引
- 自动初始化 `DEFAULT_TAGS`（硬编码的默认标签列表）
- `upsert_project` 实现插入或更新，首次插入时将 `stars_7d_ago` / `stars_30d_ago` 设为当前 stars
- `get_untranslated_projects` 会排除中文字符占比 >30% 的项目（避免翻译中文原文）
- topics 字段在数据库中存储为 JSON 字符串，读写时通过 `_normalize_topics` 转换

### `fetcher.py`
- `GitHubFetcher`：REST API 封装
- 支持 `search_repositories`（页码分页，硬上限1000条）和 `get_repository`（单仓库补录）
- `normalize_repo` 将 GitHub API 原始响应转为项目内部字典格式
- 速率限制检查：读取响应头 `X-RateLimit-Remaining`，低于5时自动 sleep 到 reset 时间

### `graphql_fetcher.py`
- `GraphQLFetcher`：GraphQL API 封装
- 使用 cursor 分页，突破 REST Search API 的 1000 条硬限制
- 单次查询获取 100 个仓库，包含 topics、watchers、issues、license 等完整字段
- `_normalize_node` 将 GraphQL 节点格式转为与 REST API 一致的内部字典

### `trend_fetcher.py`
- `TrendFetcher`：从 OpenGithubs 抓取日/周/月飙升榜
- 自动发现最新文件路径（按年份/月份目录结构遍历 GitHub API 目录树）
- 解析 Markdown 表格/列表格式，提取排名、项目名、总星数、增长量
- 支持 `36.2k` 等 star 文本解析和 `🔺3177` 等增长量文本解析

### `scorer.py`
- `HotnessScorer`：热门评分算法
- 评分公式：`score = stars*1 + forks*2 + watchers*0.5 + open_issues*0.1 + 7日日均增速*10 + 30日日均增速*5`
- 等级判定：legendary(≥100k)、very-hot(≥20k)、hot(≥5k)、rising(增速突出)
- 配置读取自 `config.yaml` 的 `hotness.weights` 和 `hotness.levels`

### `classifier.py`
- `ProjectClassifier`：自动分类器
- `classify()` 返回 `[(tag_name, category, confidence), ...]`
- 语言分类：基于 `project["language"]`，使用 `language_aliases` 映射（如 C++ → cpp）
- 领域分类：基于 `config.yaml` 中的 `domain_keywords`，匹配 description + topics + name，置信度 = min(匹配数 / (总关键词数 * 0.3), 1.0)
- 活跃分类：基于 `pushed_at` 距今天数，分为 7天/30天/90天三档
- 趋势分类：基于 `project["trend_data"]`（由 CLI 的 classify 命令从数据库加载后注入）

### `translator.py`
- `MultiBackendTranslator`：多后端自动 fallback 翻译器
- 默认后端顺序：`mlx` → `google` → `googletrans`
- `MLXBackend`：调用本地 `http://localhost:8080/v1/chat/completions`（需预先启动 `mlx_lm.server`），带 Semaphore(2) 并发限制
- `GoogleTranslatorBackend`：基于 `deep_translator.GoogleTranslator`
- `GoogletransBackend`：基于 `googletrans.Translator`（不同内部端点）
- 技术专有名词白名单 `TECH_KEYWORDS`（120+ 词汇）不翻译
- Topics 翻译采用批量拼接策略：用 `" | "` 将多个 topic 拼成一句一次性翻译，再拆分，减少 API 调用
- 中文原文智能识别：中文字符占比 >30% 则直接保留

### `writer.py`
- `DocumentWriter`：Markdown 文档生成器
- 使用内嵌的 Jinja2 字符串模板（`INDEX_TEMPLATE`、`CATEGORY_TEMPLATE`、`PARENT_INDEX_TEMPLATE`、`README_TEMPLATE`）
- `_write_paginated`：单类项目超过 `PAGE_SIZE=100` 时自动拆分为多页，并生成上下页链接和父索引页
- 输出目录结构：`docs/by-language/`、`docs/by-category/`、`docs/by-hotness/`、`docs/by-activity/`、`docs/by-trend/`

---

## 配置文件 (`config.yaml`)

```yaml
github:
  token: ""              # 优先从 GITHUB_TOKEN 环境变量读取
  base_url: "https://api.github.com"
  per_page: 100
  request_delay: 1.5       # REST API 请求间隔（秒）

hotness:
  min_stars: 3000
  min_forks: 500
  min_star_growth_7d: 50
  min_star_growth_30d: 200
  weights:                 # 评分权重
    stars: 1.0
    forks: 2.0
    watchers: 0.5
    open_issues: 0.1
    recent_growth_7d: 10.0
    recent_growth_30d: 5.0
  levels:
    legendary: 100000
    very_hot: 20000
    hot: 5000
    rising: 1000

search:
  default_star_threshold: 1000
  max_pages: 5
  sort: "stars"
  order: "desc"

categories:
  language_aliases:        # 语言别名映射
    "C++": "cpp"
    "C#": "csharp"
    ...
  domain_keywords:         # 领域关键词映射（ai-ml、web-dev、devops 等）
    ai-ml:
      - "machine learning"
      - "deep learning"
      - "llm"
      - "大模型"
      ...

docs:
  output_dir: "docs"
  projects_per_page: 50
  generate_trends: true
```

---

## 开发规范与约定

### 语言与注释
- **所有代码注释、文档字符串、CLI 输出、生成的 Markdown 均使用中文**。
- 变量名、函数名、类名使用英文（Python 惯例）。
- 数据库字段名使用英文小写 + 下划线。

### 代码风格
- 无强制格式化工具（未配置 black/ruff），遵循基本 PEP 8
- 类型提示：部分模块有 `from typing import ...` 导入，但函数签名中类型提示使用不完整，以运行时 duck typing 为主
- 字符串格式化：混合使用 f-string 和传统 `%` / `.format()`，f-string 占主导
- 错误处理：API 请求使用 `try/except` 捕获并打印中文错误信息，通常不抛出而是打印警告后继续

### 模块间数据契约
- 项目数据在模块间以 `Dict[str, Any]` 传递，标准字段由 `fetcher.normalize_repo` 和 `graphql_fetcher._normalize_node` 定义
- `topics` 字段在内存中为 `List[str]`，在数据库中序列化为 JSON 字符串
- `archived` / `fork` 在内存中为 `bool`，在数据库中存储为 `INTEGER`（0/1）

### 路径处理
- `database.py` 和 `writer.py` 使用 `pathlib.Path`
- 数据库路径默认相对于工作目录：`data/github_hot.db`
- 文档输出默认相对于工作目录：`docs/`

---

## 测试策略

**当前项目没有自动化测试套件**（无 `tests/` 目录、无 pytest 配置）。

验证方式以手动 CLI 命令和数据库查询为主：

```bash
# 验证抓取
PYTHONPATH=src python -m github_hot.cli stats

# 验证翻译质量
PYTHONPATH=src python3 -c "
from github_hot.database import Database
db = Database()
rows = db.conn.execute('SELECT full_name, description, description_zh FROM projects WHERE description_zh != \"\" LIMIT 5').fetchall()
for r in rows:
    print(r['full_name'], '|', r['description_zh'])
"

# 验证文档生成
ls -la docs/by-language/ docs/by-category/
```

---

## 安全与敏感信息

### GitHub Token
- **绝不能将含有效 Token 的 `config.yaml` 提交到仓库**。`config.yaml` 中的 `github.token` 字段留空，优先从 `GITHUB_TOKEN` 环境变量读取。
- REST API 未认证时限速 60次/小时，认证后 5000次/小时；GraphQL 为 5000点/小时。
- Token 在 HTTP Header 中以 `Authorization: token <TOKEN>`（REST）或 `Authorization: Bearer <TOKEN>`（GraphQL）发送。

### 数据安全
- `data/github_hot.db` 包含公开 GitHub 项目元数据，无敏感个人信息。
- `.gitignore` 中默认**不忽略** `data/github_hot.db`（注释掉了），即数据库通常会被提交。若数据库体积膨胀到不宜提交，可取消注释该行。

### 外部 API 风险
- `translator.py` 中的 Google 翻译后端调用第三方免费接口，存在速率限制和服务不稳定风险，已通过多后端 fallback 缓解。
- `mlx_lm.server` 为本地服务，无外泄风险，但需确保端口 8080 不被未授权访问。

---

## 常见问题与修复模式

### 1. 发现系统性翻译错误（如 "LLM" → "法学硕士"）
```bash
PYTHONPATH=src python3 -c "
from github_hot.database import Database
db = Database()
db.conn.execute(\"UPDATE projects SET description_zh = REPLACE(description_zh, '法学硕士', 'LLM'), topics_zh = REPLACE(topics_zh, '法学硕士', 'LLM') WHERE description_zh LIKE '%法学硕士%' OR topics_zh LIKE '%法学硕士%'\")
db.conn.commit()
"
PYTHONPATH=src python -m github_hot.cli generate
```

### 2. 新增技术名词到白名单
编辑 `src/github_hot/translator.py` 中的 `TECH_KEYWORDS`，然后清空受影响项目的翻译并重新执行 `translate`。

### 3. GraphQL 抓取大量数据
```bash
PYTHONPATH=src python -m github_hot.cli fetch-graphql --query "stars:>=2000" --max-results 5000
```

### 4. 定时任务部署
```bash
PYTHONPATH=src python -m github_hot.cli refresh --schedule --time 08:30
```
该命令会阻塞当前终端，适合用 `screen`/`tmux` 或 systemd 托管。

---

## 关键参考文档

| 文档 | 内容 |
|---|---|
| `docs/TRANSLATION.md` | 翻译工作流完整说明（架构、CLI、批量修复、质量验证） |
| `docs/FETCH_STRATEGY.md` | 抓取策略（REST 1000条限制、GraphQL cursor 分页、自适应递归穷尽方案） |
| `docs/TRANSLATION-legacy.md` | 早期人工翻译流程（已废弃，仅供参考） |
