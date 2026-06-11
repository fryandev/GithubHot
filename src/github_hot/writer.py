"""Markdown 文档生成模块"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from jinja2 import Template


INDEX_TEMPLATE = """# 🔥 GitHub 热门项目精选

> 最后更新：{{ update_time }}

## 📊 数据概览

| 指标 | 数值 |
|---|---|
| 收录项目总数 | {{ stats.total_projects }} |
| 热门项目数 | {{ stats.hot_projects }} |
| 涵盖语言 | {{ stats.languages|length }} 种 |
| 涵盖领域 | {{ stats.domains|length }} 个 |

## 🏷️ 热门标签

### 按语言

{% for lang in stats.languages[:15] %}- [{{ lang.name }}](by-language/{{ lang.link }}) ({{ lang.count }})
{% endfor %}
{% if stats.languages|length > 15 %}... 等共 {{ stats.languages|length }} 种语言
{% endif %}

### 按领域

{% for domain in stats.domains %}- [{{ domain.description }}](by-category/{{ domain.link }}) ({{ domain.count }})
{% endfor %}

### 按热度

{% for level in stats.levels %}- [{{ level.description }}](by-hotness/{{ level.link }}) ({{ level.count }})
{% endfor %}

### 按活跃

{% for activity in stats.activities %}- [{{ activity.description }}](by-activity/{{ activity.link }}) ({{ activity.count }})
{% endfor %}

### 按趋势

{% for trend in stats.trends %}- [{{ trend.description }}](by-trend/{{ trend.link }}) ({{ trend.count }})
{% endfor %}

## 📈 热门项目 Top 30

| 排名 | 项目 | ⭐ Stars | 🍴 Forks | 语言 | 热度 |
|---|---|---|---|---|---|
{% for p in top_projects %}{{ loop.index }} | [{{ p.full_name }}](https://github.com/{{ p.full_name }}) | {{ p.stars }} | {{ p.forks }} | {{ p.language or '-' }} | {{ p.hotness_level or '-' }} |
{% endfor %}

---

*本仓库使用 [GithubHot](https://github.com/) 自动生成与维护*
"""

CATEGORY_TEMPLATE = """# {{ title }}

> {{ description }}
> 最后更新：{{ update_time }}

{% if total_count %}共收录 **{{ total_count }}** 个项目{% endif %}
{% if page_info %}（{{ page_info }}）{% endif %}

## 项目列表

{% for p in projects %}
### {{ global_index + loop.index }}. {{ p.full_name }}

| 属性 | 信息 |
|---|---|
| 链接 | [https://github.com/{{ p.full_name }}](https://github.com/{{ p.full_name }}) |
| ⭐ Stars | {{ p.stars }} |
| 🍴 Forks | {{ p.forks }} |
| 👀 Watchers | {{ p.watchers }} |
| 📝 Open Issues | {{ p.open_issues }} |
| 💻 主语言 | {{ p.language or '未知' }} |
| 🔥 热度等级 | {{ p.hotness_level or '-' }} |
| 📅 创建时间 | {{ p.created_at[:10] if p.created_at else '-' }} |
| 🔄 最后更新 | {{ p.updated_at[:10] if p.updated_at else '-' }} |
| 📜 License | {{ p.license or '未知' }} |

**简介**：
{{ p.description or '暂无描述' }}

{% if p.description_zh and p.description_zh != p.description %}**中文简介**：
{{ p.description_zh }}
{% endif %}

**Topics**：{% if p.topics and p.topics|length > 0 %}{{ p.topics | join(', ') }}{% else %}-{% endif %}

{% if p.topics_zh and p.topics_zh != p.topics %}**中文Topics**：{{ p.topics_zh }}
{% endif %}

---
{% endfor %}

{% if prev_page or next_page %}
<div align="center">

{% if prev_page %}[← 上一页]({{ prev_page }}){% endif %}
{% if prev_page and next_page %} | {% endif %}
{% if next_page %}[下一页 →]({{ next_page }}){% endif %}

</div>
{% endif %}
"""

PARENT_INDEX_TEMPLATE = """# {{ title }}

> {{ description }}
> 最后更新：{{ update_time }}

共收录 **{{ total_count }}** 个项目，分成 **{{ page_count }}** 页

## 分页索引

{% for page in pages %}| [第 {{ page.num }} 页]({{ page.file }}) | {{ page.start }} - {{ page.end }} |
{% endfor %}

---

*本仓库使用 [GithubHot](https://github.com/) 自动生成与维护*
"""

README_TEMPLATE = """# {{ title }}

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

### 抓取数据

```bash
# 抓取热门项目
python -m github_hot.cli fetch

# 更新热门评分
python -m github_hot.cli score

# 生成分类标签
python -m github_hot.cli classify

# 生成文档
python -m github_hot.cli generate

# 一键执行全部
python -m github_hot.cli update
```

### 查询项目

```bash
# 查看热门项目 Top 20
python -m github_hot.cli list-projects --limit 20

# 按语言筛选
python -m github_hot.cli list-projects --language python

# 按领域筛选
python -m github_hot.cli list-projects --tag ai-ml

# 查看统计
python -m github_hot.cli stats
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
"""


class DocumentWriter:
    """Markdown 文档生成器"""

    PAGE_SIZE = 100  # 每页最多项目数

    def __init__(self, output_dir: str = "docs"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _normalize_project(project: Dict[str, Any]) -> Dict[str, Any]:
        """规范化项目数据，确保 topics 等字段格式正确"""
        p = dict(project)
        topics = p.get("topics")
        if isinstance(topics, str):
            try:
                p["topics"] = json.loads(topics)
            except (json.JSONDecodeError, TypeError):
                p["topics"] = []
        elif topics is None:
            p["topics"] = []
        return p

    def _write_paginated(self, out_dir: Path, base_filename: str, title: str,
                         description: str, projects: List[Dict], doc_type: str):
        """写入分页文档，超过PAGE_SIZE则拆分"""
        total = len(projects)
        normalized = [self._normalize_project(p) for p in projects]
        update_time = datetime.now().strftime("%Y-%m-%d %H:%M")

        if total <= self.PAGE_SIZE:
            # 不超页，直接写入单文件
            template = Template(CATEGORY_TEMPLATE)
            content = template.render(
                title=title,
                description=description,
                update_time=update_time,
                total_count=total,
                page_info="",
                projects=normalized,
                global_index=0,
                prev_page=None,
                next_page=None,
            )
            (out_dir / f"{base_filename}.md").write_text(content, encoding="utf-8")
            print(f"  ✅ {doc_type}文档: docs/{out_dir.name}/{base_filename}.md ({total} 个项目)")
            return base_filename + ".md"

        # 需要分页：创建子目录
        sub_dir = out_dir / base_filename
        sub_dir.mkdir(exist_ok=True)

        page_count = (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE
        pages_info = []

        for page_idx in range(page_count):
            start = page_idx * self.PAGE_SIZE
            end = min(start + self.PAGE_SIZE, total)
            page_projects = normalized[start:end]
            page_num = page_idx + 1
            page_file = f"{base_filename}-{page_num:02d}.md"

            # 上下页链接
            prev_page = f"{base_filename}-{page_num - 1:02d}.md" if page_idx > 0 else None
            next_page = f"{base_filename}-{page_num + 1:02d}.md" if page_idx < page_count - 1 else None

            template = Template(CATEGORY_TEMPLATE)
            content = template.render(
                title=f"{title} - 第 {page_num} 页",
                description=description,
                update_time=update_time,
                total_count=total,
                page_info=f"第 {page_num}/{page_count} 页",
                projects=page_projects,
                global_index=start,
                prev_page=prev_page,
                next_page=next_page,
            )
            (sub_dir / page_file).write_text(content, encoding="utf-8")

            pages_info.append({
                "num": page_num,
                "file": f"{base_filename}/{page_file}",
                "start": start + 1,
                "end": end,
            })

        # 写入父索引文档
        parent_template = Template(PARENT_INDEX_TEMPLATE)
        parent_content = parent_template.render(
            title=title,
            description=description,
            update_time=update_time,
            total_count=total,
            page_count=page_count,
            pages=pages_info,
        )
        (out_dir / f"{base_filename}.md").write_text(parent_content, encoding="utf-8")
        print(f"  ✅ {doc_type}文档: docs/{out_dir.name}/{base_filename}.md ({total} 个项目, {page_count} 页)")
        return f"{base_filename}.md"

    def write_index(self, projects: List[Dict], stats: Dict[str, Any]):
        """写入首页索引"""
        # 准备统计数据
        languages = []
        for lang in stats.get("language_distribution", []):
            name = lang["language"]
            count = lang["count"]
            # 判断是否分页
            link = f"{self._slugify(name)}.md"
            languages.append({
                "name": name,
                "count": count,
                "link": link,
            })
        languages.sort(key=lambda x: x["count"], reverse=True)

        # 从 level_distribution 动态构建热度统计
        level_counts = {lv["level"]: lv["count"] for lv in stats.get("level_distribution", [])}
        levels = [
            {"name": "legendary", "description": "⭐⭐⭐ 传奇级", "file": "legendary.md", "count": level_counts.get("legendary", 0)},
            {"name": "very-hot", "description": "⭐⭐ 非常热门", "file": "very-hot.md", "count": level_counts.get("very-hot", 0)},
            {"name": "hot", "description": "⭐ 热门", "file": "hot.md", "count": level_counts.get("hot", 0)},
            {"name": "rising", "description": "🚀 新兴热门", "file": "rising.md", "count": level_counts.get("rising", 0)},
        ]
        # 保留所有热度等级，即使 count=0 也显示链接
        for lv in levels:
            lv["link"] = lv["file"]

        # 活跃统计
        activity_dist = stats.get("activity_distribution", {})
        activity_map = {
            "daily": "🔥 最近7天活跃",
            "weekly": "📅 最近30天活跃",
            "monthly": "📆 最近90天活跃",
        }
        activities = []
        for key, desc in activity_map.items():
            count = activity_dist.get(key, 0)
            if count > 0:
                activities.append({
                    "name": key,
                    "description": desc,
                    "link": f"{key}.md",
                    "count": count,
                })

        # 趋势统计
        trend_stats = stats.get("trend_stats", {})
        trend_map = {
            "daily": "📈 日飙升榜",
            "weekly": "📊 周飙升榜",
            "monthly": "📉 月飙升榜",
        }
        trends = []
        for key, desc in trend_map.items():
            ts = trend_stats.get(key, {})
            count = ts.get("count", 0)
            if count > 0:
                trends.append({
                    "name": key,
                    "description": desc,
                    "link": f"{key}.md",
                    "count": count,
                })

        # 领域统计
        domain_distribution = stats.get("domain_distribution", [])
        domain_map = {
            "ai-ml": "🤖 AI / 机器学习",
            "web-dev": "🌐 Web 开发",
            "devops": "🔧 DevOps",
            "database": "🗄️ 数据库",
            "infrastructure": "🏗️ 基础设施",
            "security": "🔒 安全",
            "tools": "🛠️ 工具",
            "mobile": "📱 移动端",
            "data-science": "📊 数据科学",
            "blockchain": "⛓️ 区块链",
            "game-dev": "🎮 游戏开发",
            "embedded": "🔌 嵌入式 / IoT",
        }
        domains = []
        for d in domain_distribution:
            name = d.get("name", "")
            domains.append({
                "name": name,
                "description": domain_map.get(name, name),
                "link": f"{name}.md",
                "count": d.get("count", 0),
            })
        domains.sort(key=lambda x: x["count"], reverse=True)
        if not domains:
            for name, desc in domain_map.items():
                domains.append({"name": name, "description": desc, "link": f"{name}.md", "count": 0})

        template = Template(INDEX_TEMPLATE)
        content = template.render(
            update_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
            stats={
                "total_projects": stats.get("total_projects", 0),
                "hot_projects": stats.get("hot_projects", 0),
                "languages": languages,
                "domains": domains,
                "levels": levels,
                "activities": activities,
                "trends": trends,
            },
            top_projects=[self._normalize_project(p) for p in projects[:30]],
        )

        (self.output_dir / "README.md").write_text(content, encoding="utf-8")
        print(f"  ✅ 首页索引: docs/README.md")

    def write_by_language(self, language: str, projects: List[Dict]):
        """按语言写入文档"""
        out_dir = self.output_dir / "by-language"
        out_dir.mkdir(exist_ok=True)
        filename = self._slugify(language)
        self._write_paginated(
            out_dir, filename,
            f"💻 {language} 热门项目",
            f"使用 {language} 开发的热门开源项目",
            projects,
            "语言",
        )

    def write_by_category(self, category: str, description: str, projects: List[Dict]):
        """按领域写入文档"""
        out_dir = self.output_dir / "by-category"
        out_dir.mkdir(exist_ok=True)
        self._write_paginated(
            out_dir, category,
            description,
            f"{description} 相关的热门开源项目",
            projects,
            "领域",
        )

    def write_by_hotness(self, level: str, description: str, projects: List[Dict]):
        """按热度写入文档"""
        out_dir = self.output_dir / "by-hotness"
        out_dir.mkdir(exist_ok=True)
        self._write_paginated(
            out_dir, level,
            description,
            f"{description} 项目列表",
            projects,
            "热度",
        )

    def write_by_trend(self, trend_type: str, description: str, projects: List[Dict]):
        """按趋势写入文档（显示增长量）"""
        out_dir = self.output_dir / "by-trend"
        out_dir.mkdir(exist_ok=True)
        self._write_paginated(
            out_dir, trend_type,
            description,
            f"{description} 项目列表",
            projects,
            "趋势",
        )

    def write_by_activity(self, activity_type: str, description: str, projects: List[Dict]):
        """按活跃写入文档"""
        out_dir = self.output_dir / "by-activity"
        out_dir.mkdir(exist_ok=True)
        self._write_paginated(
            out_dir, activity_type,
            description,
            f"{description} 项目列表",
            projects,
            "活跃",
        )

    def write_project_readme(self, title: str = "GithubHot"):
        """写入项目根目录 README"""
        template = Template(README_TEMPLATE)
        content = template.render(title=title)
        Path("README.md").write_text(content, encoding="utf-8")
        print(f"  ✅ 项目 README: README.md")

    @staticmethod
    def _slugify(text: str) -> str:
        """将文本转为文件名友好的格式"""
        return text.lower().replace(" ", "-").replace("#", "sharp").replace("+", "plus").replace("/", "-")
