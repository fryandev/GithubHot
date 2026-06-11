# GitHub 项目穷尽抓取方案

## 双 API 架构

| API | 速率限制 | 分页方式 | 最大返回 | 适用场景 |
|-----|----------|----------|----------|----------|
| REST Search API | 30次/分钟 | 页码分页 | 1000条 | 小批量快速抓取 |
| GraphQL API | 5000点/小时 | cursor 分页 | 无上限 | 大批量穷尽抓取 |

## REST Search API 限制

- 每查询最多返回 **1000 条**
- 支持排序：`stars`, `updated`, `created`
- 支持过滤：`language`, `created`, `updated`, `topics`

之前的问题：`stars>=1000` 只抓 1000 个就停，实际该区间可能有 **数万** 个项目。

## 方案一：GraphQL API（推荐）

直接使用 `github_hot.graphql_fetcher.GraphQLFetcher`：

```python
from github_hot.graphql_fetcher import GraphQLFetcher

fetcher = GraphQLFetcher()
repos = fetcher.fetch_all(query="stars:>=2000", max_results=5000)
```

优势：
- 突破 1000 条硬限制
- 单次查询可获取 100 个仓库
- 可精确控制返回字段（topics、watchers、issues 等）
- 速率更宽松（5000点/小时）

CLI 用法：
```bash
PYTHONPATH=src python -m github_hot.cli fetch-graphql \
  --query "stars:>=2000 language:python" \
  --max-results 5000
```

## 方案二：自适应递归穷尽（REST API）

核心思想：**自顶向下，遇顶则分**。

```
fetch_exhaustive(min_stars, max_stars=∞):
    query = "stars:{min}..{max}"（或 stars>={min}）
    repos = search(query, sort="stars", desc, pages=10)
    
    if len(repos) < 1000:
        return repos                    # ← 该区间抓全了！
    
    # 触顶了，还有遗漏。看第1000条的 star 数
    lowest_star = repos[-1]["stargazers_count"]
    
    # stars > lowest_star 的一定全抓到了（排序保证）
    definite = [r for r in repos if r["stars"] > lowest_star]
    
    # 递归两部分：
    # 1. 更高星级的（确保全部抓完）
    higher = fetch_exhaustive(lowest_star + 1, ∞)
    
    # 2. 当前最低星级的（可能只抓到一部分，需要更细拆分）
    same_star = [r for r in repos if r["stars"] == lowest_star]
    # 对 same_star 用 "按语言拆分" 或 "按 updated 排序" 补抓
    
    # 3. 更低星级的区间
    lower = fetch_exhaustive(min_stars, lowest_star - 1)
    
    return merge_and_dedup(definite, higher, same_star, lower)
```

## 辅助策略（触顶时的拆分手段）

当某个区间反复触顶 1000 条时，按以下优先级拆分：

1. **按语言拆分**：`stars:1000..1999 language:python` — 主流语言各自查询
2. **按创建时间拆分**：`stars:1000..1999 created:2024` / `created:2023` 等
3. **按排序轮换**：同一查询分别按 `stars desc`、`updated desc`、`created desc` 抓，取并集

## 区间覆盖策略

不是"每一批固定区间"，而是：

| 优先级 | Star 区间 | 策略 | 目标 |
|--------|-----------|------|------|
| P0 | ≥10万 | 直接抓，通常<1000 | 抓全 |
| P1 | 5万-10万 | 直接抓 | 抓全 |
| P2 | 2万-5万 | 递归细分 | 抓全 |
| P3 | 1万-2万 | 递归+语言拆分 | 抓全 |
| P4 | 5千-1万 | 递归+语言拆分 | 抓全或接近全 |
| P5 | 2千-5千 | 语言拆分为主 | 尽量多 |
| P6 | 1千-2千 | 语言拆分+抽样 | 适量 |
| P7 | <1千 | 按兴趣抽样 | 适量 |

## 穷尽判定标准

一个区间算"抓全"当满足以下任一：
- 查询结果 < 1000 条（API 没有截断）
- 用所有拆分手段（语言×时间×排序）后，不再发现新项目

## 实施计划

1. **补全高星区（P0-P3）**：这是之前遗漏最严重的，优先补全
2. **扩展中星区（P4-P5）**：用细分策略大量抓取
3. **控制总量**：设定合理上限（如 5000/10000/20000），避免无限膨胀

## 外部趋势数据源

除 GitHub API 外，系统还整合 OpenGithubs 社区的趋势数据：

| 数据源 | 仓库 | 更新频率 | 内容 |
|--------|------|----------|------|
| 日飙升榜 | OpenGithubs/github-daily-rank | 每天 | Top10，含日增长量 |
| 周飙升榜 | OpenGithubs/github-weekly-rank | 每周 | Top20，含周增长量 |
| 月飙升榜 | OpenGithubs/github-monthly-rank | 每月 | Top30，含月增长量 |

抓取方式：
```bash
PYTHONPATH=src python -m github_hot.cli fetch-trends
```

数据存储在 `trend_rankings` 表，用于：
- 项目真实趋势分类（`trend-top-daily`/`weekly`/`monthly` 标签）
- 生成 `docs/by-trend/` 趋势文档
