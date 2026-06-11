"""项目自动分类模块"""

import re
from typing import List, Dict, Any, Tuple

import yaml


class ProjectClassifier:
    """基于项目信息自动分类"""

    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        self.domain_keywords = config.get("categories", {}).get("domain_keywords", {})
        self.language_aliases = config.get("categories", {}).get("language_aliases", {})

    def classify(self, project: Dict[str, Any]) -> List[Tuple[str, str, float]]:
        """
        对项目进行分类，返回 [(tag_name, category, confidence), ...]
        """
        results = []

        # 1. 语言分类
        lang_tags = self._classify_language(project)
        results.extend(lang_tags)

        # 2. 领域分类
        domain_tags = self._classify_domain(project)
        results.extend(domain_tags)

        # 3. 热度分类
        hotness_tags = self._classify_hotness(project)
        results.extend(hotness_tags)

        # 4. 活跃分类（基于最近更新时间）
        activity_tags = self._classify_activity(project)
        results.extend(activity_tags)

        # 5. 真实趋势分类（基于外部增长数据）
        trend_tags = self._classify_trend(project)
        results.extend(trend_tags)

        return results

    def _classify_language(self, project: Dict[str, Any]) -> List[Tuple[str, str, float]]:
        """语言分类"""
        results = []
        language = project.get("language", "")
        if not language:
            return results

        # 映射别名
        tag_name = self.language_aliases.get(language, language.lower().replace(" ", "-").replace("#", "sharp"))
        results.append((tag_name, "language", 1.0))
        return results

    def _classify_domain(self, project: Dict[str, Any]) -> List[Tuple[str, str, float]]:
        """领域分类（基于关键词匹配）"""
        results = []

        # 构建待匹配的文本
        texts = []
        description = (project.get("description") or "").lower()
        texts.append(description)
        texts.extend((t or "").lower() for t in project.get("topics", []))
        name = (project.get("name") or "").lower()
        texts.append(name)
        full_text = " ".join(texts)

        for domain, keywords in self.domain_keywords.items():
            matched = 0
            for kw in keywords:
                # 支持中英文关键词
                if kw.lower() in full_text:
                    matched += 1

            if matched > 0:
                # 置信度 = 匹配关键词数 / 总关键词数，最高 1.0
                confidence = min(matched / max(len(keywords) * 0.3, 1), 1.0)
                if confidence >= 0.15:  # 最低阈值
                    results.append((domain, "domain", round(confidence, 2)))

        return results

    def _classify_hotness(self, project: Dict[str, Any]) -> List[Tuple[str, str, float]]:
        """热度分类"""
        results = []
        stars = project.get("stars", 0)
        level = project.get("hotness_level", "")
        score = project.get("hotness_score", 0)

        if level:
            results.append((level, "hotness", 1.0))

        # 增速趋势
        growth_7d = stars - project.get("stars_7d_ago", stars)
        growth_30d = stars - project.get("stars_30d_ago", stars)

        if growth_7d >= 50:
            results.append(("trending-weekly", "hotness", min(growth_7d / 500, 1.0)))
        if growth_30d >= 200:
            results.append(("trending-monthly", "hotness", min(growth_30d / 2000, 1.0)))

        return results

    def _classify_activity(self, project: Dict[str, Any]) -> List[Tuple[str, str, float]]:
        """活跃分类（基于 pushed_at 最近更新时间）

        - activity-daily: 7天内更新过
        - activity-weekly: 30天内更新过（但不满足 daily）
        - activity-monthly: 90天内更新过（但不满足 weekly）
        """
        results = []
        pushed_at = project.get("pushed_at", "")
        if not pushed_at:
            return results

        from datetime import datetime
        try:
            pushed = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
            now = datetime.now(pushed.tzinfo) if pushed.tzinfo else datetime.now()
            days_since = (now - pushed).days

            if days_since <= 7:
                results.append(("activity-daily", "activity", 1.0))
            elif days_since <= 30:
                results.append(("activity-weekly", "activity", 1.0))
            elif days_since <= 90:
                results.append(("activity-monthly", "activity", 1.0))
        except (ValueError, TypeError):
            pass

        return results

    def _classify_trend(self, project: Dict[str, Any]) -> List[Tuple[str, str, float]]:
        """真实趋势分类（基于外部趋势数据）

        从 trend_rankings 表获取项目的增长数据，打趋势标签。
        排名越靠前置信度越高。
        """
        results = []
        # 这个分类依赖于外部数据，由 CLI 在 fetch-trends 后调用
        # 分类器本身不直接查询数据库，而是通过 project 字典中的 trend 字段
        trend_data = project.get("trend_data", {})
        if not trend_data:
            return results

        for period, data in trend_data.items():
            rank = data.get("rank", 999)
            growth = data.get("growth", 0)
            confidence = max(1.0 - (rank - 1) * 0.05, 0.3)  # 排名1→1.0, 排名10→0.55

            if period == "daily":
                results.append(("trend-top-daily", "trend", round(confidence, 2)))
            elif period == "weekly":
                results.append(("trend-top-weekly", "trend", round(confidence, 2)))
            elif period == "monthly":
                results.append(("trend-top-monthly", "trend", round(confidence, 2)))

        return results

    def get_all_languages(self, projects: List[Dict[str, Any]]) -> List[str]:
        """从项目列表中提取所有语言"""
        languages = set()
        for p in projects:
            lang = p.get("language", "")
            if lang:
                languages.add(lang)
        return sorted(languages)
