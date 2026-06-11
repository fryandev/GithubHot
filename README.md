# GithubHot

> 一个持续更新的 GitHub 热门项目数据库与文档系统

## ✨ 项目特点

- 📊 **量化热门标准**：基于 Stars、Forks、增速等多维度评分，不是凭感觉
- 🏷️ **多维度分类**：按语言、领域、热度等级分门别类
- 🔄 **可持续更新**：支持定期抓取和增量更新
- 🌐 **中文文档**：所有项目信息整理为中文，便于国内开发者查阅
- 🔍 **快速检索**：通过标签和分类快速找到感兴趣的项目

## 📁 目录结构

```
.
├── data/               # SQLite 数据库
│   └── github_hot.db
├── docs/               # 生成的文档
│   ├── README.md       # 总览
│   ├── by-language/    # 按语言分类
│   ├── by-category/    # 按领域分类
│   ├── by-hotness/     # 按热度分类
│   ├── by-activity/    # 按活跃分类
│   └── by-trend/       # 按趋势分类
├── src/                # 源代码
│   └── github_hot/
├── config.yaml         # 配置文件
└── README.md           # 本文件
```

## 🚀 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### 配置 GitHub Token（可选但推荐）

```bash
export GITHUB_TOKEN="your_github_personal_access_token"
```

### 运行命令

本项目通过 `PYTHONPATH=src` 方式运行：

```bash
# 抓取热门项目
PYTHONPATH=src python -m github_hot.cli fetch

# 更新热门评分
PYTHONPATH=src python -m github_hot.cli score

# 生成分类标签
PYTHONPATH=src python -m github_hot.cli classify

# 生成文档
PYTHONPATH=src python -m github_hot.cli generate

# 一键执行全部
PYTHONPATH=src python -m github_hot.cli update

# 日常刷新（推荐）
PYTHONPATH=src python -m github_hot.cli refresh
```

### 查询项目

```bash
# 查看热门项目 Top 20
PYTHONPATH=src python -m github_hot.cli list-projects --limit 20

# 按语言筛选
PYTHONPATH=src python -m github_hot.cli list-projects --language python

# 按领域筛选
PYTHONPATH=src python -m github_hot.cli list-projects --tag ai-ml

# 按最低 Stars 筛选
PYTHONPATH=src python -m github_hot.cli list-projects --min-stars 10000

# 查看单个项目详情
PYTHONPATH=src python -m github_hot.cli info owner/repo

# 查看统计
PYTHONPATH=src python -m github_hot.cli stats
```

## 📏 热门判定标准

| 等级 | 条件 |
|---|---|
| ⭐⭐⭐ 传奇级 | Stars >= 100,000 |
| ⭐⭐ 非常热门 | Stars >= 20,000 |
| ⭐ 热门 | Stars >= 5,000 |
| 🚀 新兴 | 7日增速 >= 100 或 30日增速 >= 500 |

综合评分公式：
```
score = stars * 1 + forks * 2 + watchers * 0.5 + open_issues * 0.1
        + 7日日均增速 * 10 + 30日日均增速 * 5
```

## 📄 文档分类

- [按语言分类](docs/by-language/)
- [按领域分类](docs/by-category/)
- [按热度分类](docs/by-hotness/)
- [按活跃分类](docs/by-activity/)
- [按趋势分类](docs/by-trend/)

## 📝 License

MIT