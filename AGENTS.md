# AGENTS.md

## 项目背景

GithubHot 是一个持续更新的 GitHub 热门项目数据库与文档系统，收录 star 数较高的开源项目，按语言、领域、热度等级分类，并生成中文 Markdown 文档。

## 关键文件

| 文件 | 说明 |
|---|---|
| `config.yaml` | 项目配置（热门标准、分类关键词等） |
| `data/github_hot.db` | SQLite 数据库，存储项目基本信息 |
| `src/github_hot/` | Python 核心源码 |
| `docs/` | 生成的 Markdown 文档 |
| `docs/TRANSLATION.md` | **翻译工作流说明**（中英文双语生成流程） |
| `docs/FETCH_STRATEGY.md` | **抓取策略说明**（REST/GraphQL API 穷尽抓取方案） |

## 数据库 Schema

### projects 表（核心）

```
id, github_id, full_name, owner, name, description, html_url,
language, stars, forks, watchers, open_issues,
created_at, updated_at, pushed_at, topics, license,
homepage, size, archived, fork,
stars_7d_ago, stars_30d_ago, stars_90d_ago,  -- 增速历史
hotness_score, hotness_level,
description_zh, topics_zh,  -- 中文翻译字段
first_seen_at, last_fetched_at, fetch_count, is_hot
```

### tags 表 + project_tags 表

多对多关系，支持：
- **language**：编程语言标签
- **domain**：领域标签（AI/ML、Web Dev、DevOps 等）
- **hotness**：热度等级标签（legendary、very-hot、hot、rising）
- **activity**：活跃标签（基于 `pushed_at`，daily/weekly/monthly）
- **trend**：趋势标签（基于 OpenGithubs 外部增长数据）

### trend_rankings 表（外部趋势数据）

```
id, full_name, period(daily/weekly/monthly), rank, growth, total_stars,
ranking_date, fetched_at
```

存储来自 OpenGithubs 社区的日/周/月飙升榜单数据。

## CLI 命令

```bash
# 抓取数据（REST Search API）
PYTHONPATH=src python -m github_hot.cli fetch --pages 10 --threshold 1000

# 抓取数据（GraphQL API，突破1000条限制）
PYTHONPATH=src python -m github_hot.cli fetch-graphql --query "stars:>=2000"

# 抓取外部趋势数据（OpenGithubs 日/周/月榜）
PYTHONPATH=src python -m github_hot.cli fetch-trends

# 补录趋势榜中缺失的项目
PYTHONPATH=src python -m github_hot.cli backfill-trends

# 批量翻译未翻译项目
PYTHONPATH=src python -m github_hot.cli translate

# 刷新时间相关分类（活跃度 + 趋势 + 翻译 + 生成文档）
PYTHONPATH=src python -m github_hot.cli refresh

# 每天 08:30 自动定时刷新
PYTHONPATH=src python -m github_hot.cli refresh --schedule --time 08:30

# 评分
PYTHONPATH=src python -m github_hot.cli score

# 分类
PYTHONPATH=src python -m github_hot.cli classify

# 生成文档
PYTHONPATH=src python -m github_hot.cli generate

# 一键全部
PYTHONPATH=src python -m github_hot.cli update

# 查看统计
PYTHONPATH=src python -m github_hot.cli stats

# 查看项目详情
PYTHONPATH=src python -m github_hot.cli info owner/repo
```

## 数据源

### 主数据源
- **GitHub Search API**（REST）：30次/分钟，1000条硬上限
- **GitHub GraphQL API**：5000点/小时，cursor 分页无上限

### 趋势数据源
- **OpenGithubs/github-daily-rank**：日飙升 Top10，含增长量
- **OpenGithubs/github-weekly-rank**：周飙升 Top20，含增长量
- **OpenGithubs/github-monthly-rank**：月飙升 Top30，含增长量

## 翻译工作流

项目支持中英文双语展示。翻译流程详见 `docs/TRANSLATION.md`，核心要点：

- **多后端自动翻译器**：`mlx`（本地 Hy-MT2-7B 模型）→ `google`（Google Translate）→ `googletrans`（备选端点），自动 fallback
- **本地 MLX 模型**（推荐）：基于 `mlx_lm.server` 启动的本地 API 服务，质量最高（LLM→大语言模型）、无网络/速率限制、约 1.5s/条
- **Google 翻译**：免费在线接口，约 2-3s/条，有速率限制风险
- 技术专有名词保留英文（`python`、`api`、`llm`、`mcp` 等 120+ 白名单）
- 原文已是中文的项目自动识别并保留
- CLI 一键执行：`python -m github_hot.cli translate`
