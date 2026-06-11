"""数据库操作模块"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any


SCHEMA = """
-- 项目基本信息表
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    github_id INTEGER UNIQUE NOT NULL,
    full_name TEXT UNIQUE NOT NULL,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    html_url TEXT NOT NULL,
    language TEXT,
    stars INTEGER DEFAULT 0,
    forks INTEGER DEFAULT 0,
    watchers INTEGER DEFAULT 0,
    open_issues INTEGER DEFAULT 0,
    created_at TEXT,
    updated_at TEXT,
    pushed_at TEXT,
    topics TEXT,  -- JSON数组
    license TEXT,
    homepage TEXT,
    size INTEGER DEFAULT 0,
    archived INTEGER DEFAULT 0,
    fork INTEGER DEFAULT 0,
    description_zh TEXT,
    topics_zh TEXT,
    -- 增速数据
    stars_7d_ago INTEGER DEFAULT 0,
    stars_30d_ago INTEGER DEFAULT 0,
    stars_90d_ago INTEGER DEFAULT 0,
    -- 评分
    hotness_score REAL DEFAULT 0,
    hotness_level TEXT DEFAULT '',
    -- 元数据
    first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
    fetch_count INTEGER DEFAULT 1,
    is_hot INTEGER DEFAULT 1
);

-- 标签定义表
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    category TEXT NOT NULL,  -- language, domain, hotness
    description TEXT,
    color TEXT DEFAULT '#666666',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 项目-标签关联表
CREATE TABLE IF NOT EXISTS project_tags (
    project_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    confidence REAL DEFAULT 1.0,  -- 分类置信度
    PRIMARY KEY (project_id, tag_id),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);

-- 抓取历史表（用于计算增速）
CREATE TABLE IF NOT EXISTS fetch_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    stars INTEGER DEFAULT 0,
    forks INTEGER DEFAULT 0,
    open_issues INTEGER DEFAULT 0,
    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 外部趋势排名表（来自 OpenGithubs 等数据源）
CREATE TABLE IF NOT EXISTS trend_rankings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    period TEXT NOT NULL,  -- daily, weekly, monthly
    rank INTEGER NOT NULL,
    growth INTEGER DEFAULT 0,
    total_stars INTEGER DEFAULT 0,
    ranking_date TEXT NOT NULL,
    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(full_name, period, ranking_date)
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_projects_stars ON projects(stars DESC);
CREATE INDEX IF NOT EXISTS idx_projects_hotness ON projects(hotness_score DESC);
CREATE INDEX IF NOT EXISTS idx_projects_language ON projects(language);
CREATE INDEX IF NOT EXISTS idx_projects_level ON projects(hotness_level);
CREATE INDEX IF NOT EXISTS idx_fetch_history_name ON fetch_history(full_name, fetched_at);
CREATE INDEX IF NOT EXISTS idx_tags_category ON tags(category);
CREATE INDEX IF NOT EXISTS idx_project_tags_project ON project_tags(project_id);
CREATE INDEX IF NOT EXISTS idx_project_tags_tag ON project_tags(tag_id);
"""

DEFAULT_TAGS = [
    # 热度标签
    ("legendary", "hotness", "⭐⭐⭐ 传奇级 (100k+ stars)", "#ff4757"),
    ("very-hot", "hotness", "⭐⭐ 非常热门 (20k+ stars)", "#ff6348"),
    ("hot", "hotness", "⭐ 热门 (5k+ stars)", "#ffa502"),
    ("rising", "hotness", "🚀 新兴热门 (增速突出)", "#2ed573"),
    ("trending-weekly", "hotness", "📈 本周趋势", "#1e90ff"),
    ("trending-monthly", "hotness", "📊 本月趋势", "#3742fa"),
    # 活跃分类标签（基于 pushed_at）
    ("activity-daily", "activity", "🔥 最近7天活跃", "#ff4757"),
    ("activity-weekly", "activity", "📅 最近30天活跃", "#ffa502"),
    ("activity-monthly", "activity", "📆 最近90天活跃", "#2ed573"),
    # 领域标签
    ("ai-ml", "domain", "AI / 机器学习", "#a29bfe"),
    ("web-dev", "domain", "Web 开发", "#fd79a8"),
    ("devops", "domain", "DevOps / 运维", "#00b894"),
    ("database", "domain", "数据库", "#e17055"),
    ("infrastructure", "domain", "基础设施", "#636e72"),
    ("security", "domain", "安全", "#d63031"),
    ("mobile", "domain", "移动端", "#0984e3"),
    ("tools", "domain", "工具", "#6c5ce7"),
    ("data-science", "domain", "数据科学", "#e84393"),
    ("blockchain", "domain", "区块链", "#f39c12"),
    ("game-dev", "domain", "游戏开发", "#8e44ad"),
    ("embedded", "domain", "嵌入式 / IoT", "#27ae60"),
]


class Database:
    """SQLite 数据库管理器"""

    def __init__(self, db_path: str = "data/github_hot.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        """初始化数据库表结构"""
        self.conn.executescript(SCHEMA)
        self._init_default_tags()
        self.conn.commit()

    def _init_default_tags(self):
        """初始化默认标签"""
        cursor = self.conn.cursor()
        for name, category, description, color in DEFAULT_TAGS:
            cursor.execute(
                """INSERT OR IGNORE INTO tags (name, category, description, color)
                   VALUES (?, ?, ?, ?)""",
                (name, category, description, color),
            )
        self.conn.commit()

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # ------------------------------------------------------------------
    # 项目 CRUD
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_topics(topics) -> list:
        """确保 topics 是列表类型"""
        if isinstance(topics, list):
            return topics
        if isinstance(topics, str):
            try:
                parsed = json.loads(topics)
                if isinstance(parsed, list):
                    return parsed
                if isinstance(parsed, str):
                    # 双重编码的情况
                    return json.loads(parsed)
            except (json.JSONDecodeError, TypeError):
                pass
        return []

    def upsert_project(self, project: Dict[str, Any]) -> int:
        """插入或更新项目，返回项目 id"""
        cursor = self.conn.cursor()

        # 检查项目是否存在
        cursor.execute(
            "SELECT id, stars, stars_7d_ago, stars_30d_ago, fetch_count FROM projects WHERE full_name = ?",
            (project["full_name"],),
        )
        existing = cursor.fetchone()

        now = datetime.now().isoformat()

        if existing:
            # 更新已有项目，保留历史增速数据
            project_id = existing["id"]
            old_stars = existing["stars"]
            old_fetch_count = existing["fetch_count"] or 1

            # 更新历史数据（首次保留，之后按需更新）
            stars_7d = existing["stars_7d_ago"] or old_stars
            stars_30d = existing["stars_30d_ago"] or old_stars

            topics_list = self._normalize_topics(project.get("topics"))
            cursor.execute(
                """UPDATE projects SET
                    description = ?,
                    language = ?,
                    stars = ?,
                    forks = ?,
                    watchers = ?,
                    open_issues = ?,
                    updated_at = ?,
                    pushed_at = ?,
                    topics = ?,
                    license = ?,
                    homepage = ?,
                    size = ?,
                    archived = ?,
                    fork = ?,
                    stars_7d_ago = ?,
                    stars_30d_ago = ?,
                    hotness_score = ?,
                    hotness_level = ?,
                    last_fetched_at = ?,
                    fetch_count = ?,
                    is_hot = ?
                WHERE id = ?""",
                (
                    project.get("description", ""),
                    project.get("language", ""),
                    project.get("stars", 0),
                    project.get("forks", 0),
                    project.get("watchers", 0),
                    project.get("open_issues", 0),
                    project.get("updated_at", ""),
                    project.get("pushed_at", ""),
                    json.dumps(topics_list, ensure_ascii=False),
                    project.get("license", ""),
                    project.get("homepage", ""),
                    project.get("size", 0),
                    1 if project.get("archived") else 0,
                    1 if project.get("fork") else 0,
                    stars_7d,
                    stars_30d,
                    project.get("hotness_score", 0),
                    project.get("hotness_level", ""),
                    now,
                    old_fetch_count + 1,
                    1 if project.get("is_hot", True) else 0,
                    project_id,
                ),
            )
        else:
            # 插入新项目
            topics_list = self._normalize_topics(project.get("topics"))
            cursor.execute(
                """INSERT INTO projects
                (github_id, full_name, owner, name, description, html_url,
                 language, stars, forks, watchers, open_issues,
                 created_at, updated_at, pushed_at, topics, license,
                 homepage, size, archived, fork,
                 stars_7d_ago, stars_30d_ago,
                 hotness_score, hotness_level, first_seen_at, last_fetched_at, is_hot)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    project["github_id"],
                    project["full_name"],
                    project["owner"],
                    project["name"],
                    project.get("description", ""),
                    project["html_url"],
                    project.get("language", ""),
                    project.get("stars", 0),
                    project.get("forks", 0),
                    project.get("watchers", 0),
                    project.get("open_issues", 0),
                    project.get("created_at", ""),
                    project.get("updated_at", ""),
                    project.get("pushed_at", ""),
                    json.dumps(topics_list, ensure_ascii=False),
                    project.get("license", ""),
                    project.get("homepage", ""),
                    project.get("size", 0),
                    1 if project.get("archived") else 0,
                    1 if project.get("fork") else 0,
                    project.get("stars", 0),  # 首次抓取，历史值设为当前值
                    project.get("stars", 0),
                    project.get("hotness_score", 0),
                    project.get("hotness_level", ""),
                    now,
                    now,
                    1 if project.get("is_hot", True) else 0,
                ),
            )
            project_id = cursor.lastrowid

        self.conn.commit()
        return project_id

    def record_fetch_history(self, full_name: str, stars: int, forks: int, open_issues: int):
        """记录抓取历史"""
        self.conn.execute(
            "INSERT INTO fetch_history (full_name, stars, forks, open_issues) VALUES (?, ?, ?, ?)",
            (full_name, stars, forks, open_issues),
        )
        self.conn.commit()

    def get_project_by_name(self, full_name: str) -> Optional[Dict]:
        """根据 full_name 获取项目"""
        cursor = self.conn.execute("SELECT * FROM projects WHERE full_name = ?", (full_name,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_all_projects(
        self,
        limit: Optional[int] = None,
        order_by: str = "hotness_score DESC",
        where: str = "",
        params: tuple = (),
    ) -> List[Dict]:
        """获取项目列表"""
        sql = f"SELECT * FROM projects"
        if where:
            sql += f" WHERE {where}"
        sql += f" ORDER BY {order_by}"
        if limit:
            sql += f" LIMIT {limit}"
        cursor = self.conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    def get_projects_by_tag(self, tag_name: str, limit: Optional[int] = None) -> List[Dict]:
        """根据标签获取项目"""
        sql = """
            SELECT p.* FROM projects p
            JOIN project_tags pt ON p.id = pt.project_id
            JOIN tags t ON pt.tag_id = t.id
            WHERE t.name = ?
            ORDER BY p.hotness_score DESC
        """
        if limit:
            sql += f" LIMIT {limit}"
        cursor = self.conn.execute(sql, (tag_name,))
        return [dict(row) for row in cursor.fetchall()]

    def get_project_count(self, where: str = "", params: tuple = ()) -> int:
        """获取项目数量"""
        sql = "SELECT COUNT(*) FROM projects"
        if where:
            sql += f" WHERE {where}"
        cursor = self.conn.execute(sql, params)
        return cursor.fetchone()[0]

    # ------------------------------------------------------------------
    # 标签操作
    # ------------------------------------------------------------------

    def get_or_create_tag(self, name: str, category: str, description: str = "", color: str = "#666666") -> int:
        """获取或创建标签，返回 tag_id"""
        cursor = self.conn.execute("SELECT id FROM tags WHERE name = ?", (name,))
        row = cursor.fetchone()
        if row:
            return row[0]
        cursor = self.conn.execute(
            "INSERT INTO tags (name, category, description, color) VALUES (?, ?, ?, ?)",
            (name, category, description, color),
        )
        self.conn.commit()
        return cursor.lastrowid

    def add_project_tag(self, project_id: int, tag_id: int, confidence: float = 1.0):
        """为项目添加标签"""
        self.conn.execute(
            "INSERT OR IGNORE INTO project_tags (project_id, tag_id, confidence) VALUES (?, ?, ?)",
            (project_id, tag_id, confidence),
        )
        self.conn.commit()

    def clear_project_tags(self, project_id: int, category: Optional[str] = None):
        """清除项目的标签"""
        if category:
            self.conn.execute(
                """DELETE FROM project_tags
                WHERE project_id = ? AND tag_id IN (
                    SELECT id FROM tags WHERE category = ?
                )""",
                (project_id, category),
            )
        else:
            self.conn.execute("DELETE FROM project_tags WHERE project_id = ?", (project_id,))
        self.conn.commit()

    def get_tags(self, category: Optional[str] = None) -> List[Dict]:
        """获取标签列表"""
        if category:
            cursor = self.conn.execute("SELECT * FROM tags WHERE category = ? ORDER BY name", (category,))
        else:
            cursor = self.conn.execute("SELECT * FROM tags ORDER BY category, name")
        return [dict(row) for row in cursor.fetchall()]

    def get_project_tags(self, project_id: int) -> List[Dict]:
        """获取项目的所有标签"""
        cursor = self.conn.execute(
            """SELECT t.*, pt.confidence FROM tags t
            JOIN project_tags pt ON t.id = pt.tag_id
            WHERE pt.project_id = ? ORDER BY t.category, t.name""",
            (project_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    # ------------------------------------------------------------------
    # 统计与增速
    # ------------------------------------------------------------------

    def get_growth_rate(self, full_name: str, days: int = 7) -> Dict:
        """计算项目指定天数内的增速"""
        cursor = self.conn.execute(
            """SELECT stars, fetched_at FROM fetch_history
            WHERE full_name = ? AND fetched_at >= datetime('now', '-{} days')
            ORDER BY fetched_at ASC LIMIT 1""".format(days),
            (full_name,),
        )
        old = cursor.fetchone()

        cursor = self.conn.execute(
            """SELECT stars FROM fetch_history
            WHERE full_name = ? ORDER BY fetched_at DESC LIMIT 1""",
            (full_name,),
        )
        latest = cursor.fetchone()

        if not old or not latest:
            return {"growth": 0, "rate": 0.0}

        growth = latest["stars"] - old["stars"]
        rate = growth / days
        return {"growth": growth, "rate": round(rate, 2)}

    def get_stats(self) -> Dict:
        """获取数据库统计信息"""
        total = self.conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        hot = self.conn.execute("SELECT COUNT(*) FROM projects WHERE is_hot = 1").fetchone()[0]
        languages = self.conn.execute(
            "SELECT language, COUNT(*) as cnt FROM projects WHERE language != '' GROUP BY language ORDER BY cnt DESC"
        ).fetchall()
        levels = self.conn.execute(
            "SELECT hotness_level, COUNT(*) as cnt FROM projects WHERE hotness_level != '' GROUP BY hotness_level"
        ).fetchall()
        # 领域分布
        domains = self.conn.execute(
            """SELECT t.name, COUNT(*) as cnt 
               FROM tags t 
               JOIN project_tags pt ON t.id = pt.tag_id 
               WHERE t.category = 'domain' 
               GROUP BY t.name 
               ORDER BY cnt DESC"""
        ).fetchall()
        # 活跃分布（基于 pushed_at，不按标签查询，更直接）
        from datetime import datetime, timedelta
        now = datetime.now()
        daily_cutoff = (now - timedelta(days=7)).isoformat()
        weekly_cutoff = (now - timedelta(days=30)).isoformat()
        monthly_cutoff = (now - timedelta(days=90)).isoformat()
        activity_daily = self.conn.execute(
            "SELECT COUNT(*) FROM projects WHERE pushed_at >= ?", (daily_cutoff,)
        ).fetchone()[0]
        activity_weekly = self.conn.execute(
            "SELECT COUNT(*) FROM projects WHERE pushed_at >= ? AND pushed_at < ?",
            (weekly_cutoff, daily_cutoff)
        ).fetchone()[0]
        activity_monthly = self.conn.execute(
            "SELECT COUNT(*) FROM projects WHERE pushed_at >= ? AND pushed_at < ?",
            (monthly_cutoff, weekly_cutoff)
        ).fetchone()[0]
        return {
            "total_projects": total,
            "hot_projects": hot,
            "language_distribution": [{"language": r["language"], "count": r["cnt"]} for r in languages],
            "level_distribution": [{"level": r["hotness_level"], "count": r["cnt"]} for r in levels],
            "domain_distribution": [{"name": r["name"], "count": r["cnt"]} for r in domains],
            "activity_distribution": {
                "daily": activity_daily,
                "weekly": activity_weekly,
                "monthly": activity_monthly,
            },
        }

    def save_trend_rankings(self, rankings: List[Dict[str, Any]]):
        """保存外部趋势排名数据"""
        cursor = self.conn.cursor()
        for r in rankings:
            cursor.execute(
                """INSERT OR REPLACE INTO trend_rankings
                (full_name, period, rank, growth, total_stars, ranking_date)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    r["full_name"],
                    r["period"],
                    r["rank"],
                    r.get("growth", 0),
                    r.get("total_stars", 0),
                    r.get("ranking_date", ""),
                ),
            )
        self.conn.commit()
        print(f"💾 已保存 {len(rankings)} 条趋势数据")

    def get_trend_rankings(self, period: str) -> List[Dict]:
        """获取指定周期的趋势排名"""
        cursor = self.conn.execute(
            """SELECT * FROM trend_rankings
            WHERE period = ?
            ORDER BY rank ASC""",
            (period,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_trend_stats(self) -> Dict[str, Any]:
        """获取趋势统计（各周期最新一期）"""
        stats = {}
        for period in ["daily", "weekly", "monthly"]:
            cursor = self.conn.execute(
                """SELECT ranking_date, COUNT(*) as cnt,
                   MAX(growth) as max_growth, AVG(growth) as avg_growth
                FROM trend_rankings
                WHERE period = ?
                GROUP BY ranking_date
                ORDER BY ranking_date DESC LIMIT 1""",
                (period,),
            )
            row = cursor.fetchone()
            if row:
                stats[period] = {
                    "date": row["ranking_date"],
                    "count": row["cnt"],
                    "max_growth": row["max_growth"],
                    "avg_growth": round(row["avg_growth"] or 0, 1),
                }
            else:
                stats[period] = {"date": "", "count": 0, "max_growth": 0, "avg_growth": 0}
        return stats

    def get_projects_with_trend(self, period: str) -> List[Dict]:
        """获取带有趋势数据的项目（关联 projects 表）"""
        cursor = self.conn.execute(
            """SELECT p.*, tr.rank, tr.growth, tr.total_stars, tr.ranking_date
            FROM projects p
            JOIN trend_rankings tr ON p.full_name = tr.full_name
            WHERE tr.period = ?
            ORDER BY tr.rank ASC""",
            (period,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_untranslated_projects(self, limit: Optional[int] = None) -> List[Dict]:
        """获取未翻译的项目列表（description_zh 为空/与原文相同，且 description 不为空、非中文）"""
        import re
        sql = """
            SELECT id, full_name, description, topics
            FROM projects
            WHERE (description_zh IS NULL OR description_zh = '' OR description_zh = description)
              AND (description IS NOT NULL AND description != '')
            ORDER BY stars DESC
        """
        cursor = self.conn.execute(sql)
        results = []
        for row in cursor.fetchall():
            p = dict(row)
            desc = (p.get("description") or "").strip()
            # 排除中文原文（中文字符占比 > 30%）
            chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", desc))
            if chinese_chars / max(len(desc), 1) > 0.3:
                continue
            results.append(p)
        if limit:
            results = results[:limit]
        return results

    def update_translations(self, translations: List[Dict[str, Any]]):
        """批量更新翻译结果"""
        cursor = self.conn.cursor()
        for t in translations:
            cursor.execute(
                "UPDATE projects SET description_zh = ?, topics_zh = ? WHERE id = ?",
                (t.get("description_zh", ""), t.get("topics_zh", ""), t["id"]),
            )
        self.conn.commit()
        print(f"💾 已更新 {len(translations)} 个项目的翻译")

    def get_missing_trend_projects(self) -> List[Dict]:
        """获取趋势榜中缺失的项目列表（去重）"""
        cursor = self.conn.execute(
            """SELECT DISTINCT tr.full_name, MAX(tr.total_stars) as stars
            FROM trend_rankings tr
            LEFT JOIN projects p ON tr.full_name = p.full_name
            WHERE p.id IS NULL
            GROUP BY tr.full_name
            ORDER BY stars DESC"""
        )
        return [dict(row) for row in cursor.fetchall()]

    def clear_trend_rankings(self, period: Optional[str] = None):
        """清空趋势数据"""
        if period:
            self.conn.execute("DELETE FROM trend_rankings WHERE period = ?", (period,))
        else:
            self.conn.execute("DELETE FROM trend_rankings")
        self.conn.commit()

    def update_growth_data(self):
        """更新所有项目的增速数据（基于 fetch_history）"""
        # 获取 7 天前的数据
        cursor = self.conn.execute(
            """SELECT full_name, stars FROM fetch_history
            WHERE fetched_at >= datetime('now', '-7 days')
            GROUP BY full_name HAVING MIN(fetched_at)"""
        )
        stars_7d = {r["full_name"]: r["stars"] for r in cursor.fetchall()}

        # 获取 30 天前的数据
        cursor = self.conn.execute(
            """SELECT full_name, stars FROM fetch_history
            WHERE fetched_at >= datetime('now', '-30 days')
            GROUP BY full_name HAVING MIN(fetched_at)"""
        )
        stars_30d = {r["full_name"]: r["stars"] for r in cursor.fetchall()}

        # 更新项目表
        for full_name, stars in stars_7d.items():
            self.conn.execute(
                "UPDATE projects SET stars_7d_ago = ? WHERE full_name = ?",
                (stars, full_name),
            )
        for full_name, stars in stars_30d.items():
            self.conn.execute(
                "UPDATE projects SET stars_30d_ago = ? WHERE full_name = ?",
                (stars, full_name),
            )
        self.conn.commit()
