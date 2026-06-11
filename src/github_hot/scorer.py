"""热门评分算法模块"""

import math
from typing import Dict, Any

import yaml


class HotnessScorer:
    """项目热门程度评分器"""

    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        self.hotness_config = config.get("hotness", {})
        self.weights = self.hotness_config.get("weights", {})
        self.levels = self.hotness_config.get("levels", {})
        self.min_stars = self.hotness_config.get("min_stars", 3000)
        self.min_forks = self.hotness_config.get("min_forks", 500)
        self.min_growth_7d = self.hotness_config.get("min_star_growth_7d", 50)
        self.min_growth_30d = self.hotness_config.get("min_star_growth_30d", 200)

    def calculate_score(self, project: Dict[str, Any]) -> float:
        """
        计算综合热门评分

        评分公式：
        score = stars * w1 + forks * w2 + watchers * w3 + open_issues * w4
                + growth_7d * w5 + growth_30d * w6
        """
        stars = project.get("stars", 0)
        forks = project.get("forks", 0)
        watchers = project.get("watchers", 0)
        open_issues = project.get("open_issues", 0)

        # 计算增速
        stars_7d_ago = project.get("stars_7d_ago", stars)
        stars_30d_ago = project.get("stars_30d_ago", stars)
        growth_7d = max(0, stars - stars_7d_ago)
        growth_30d = max(0, stars - stars_30d_ago)

        # 日平均增速
        daily_growth_7d = growth_7d / 7.0
        daily_growth_30d = growth_30d / 30.0

        w = self.weights
        score = (
            stars * w.get("stars", 1.0)
            + forks * w.get("forks", 2.0)
            + watchers * w.get("watchers", 0.5)
            + open_issues * w.get("open_issues", 0.1)
            + daily_growth_7d * w.get("recent_growth_7d", 10.0)
            + daily_growth_30d * w.get("recent_growth_30d", 5.0)
        )

        return round(score, 2)

    def determine_level(self, project: Dict[str, Any]) -> str:
        """判定热门等级"""
        stars = project.get("stars", 0)
        score = project.get("hotness_score", 0)
        growth_7d = project.get("stars", 0) - project.get("stars_7d_ago", project.get("stars", 0))
        growth_30d = project.get("stars", 0) - project.get("stars_30d_ago", project.get("stars", 0))

        # 传奇级
        if stars >= self.levels.get("legendary", 100000):
            return "legendary"
        # 非常热门
        if stars >= self.levels.get("very_hot", 20000):
            return "very-hot"
        # 热门
        if stars >= self.levels.get("hot", 5000):
            return "hot"
        # 新兴（增速突出但总量不高）
        if growth_7d >= self.min_growth_7d * 2 or growth_30d >= self.min_growth_30d:
            return "rising"
        # 基础热门判定
        if stars >= self.min_stars or project.get("forks", 0) >= self.min_forks:
            return "hot"
        if growth_7d >= self.min_growth_7d:
            return "rising"

        return ""

    def is_hot(self, project: Dict[str, Any]) -> bool:
        """判定是否为热门项目"""
        stars = project.get("stars", 0)
        forks = project.get("forks", 0)
        growth_7d = stars - project.get("stars_7d_ago", stars)
        growth_30d = stars - project.get("stars_30d_ago", stars)

        # 基础门槛
        if stars >= self.min_stars or forks >= self.min_forks:
            return True
        # 增速门槛
        if growth_7d >= self.min_growth_7d or growth_30d >= self.min_growth_30d:
            return True
        # 高评分
        if project.get("hotness_score", 0) >= self.levels.get("hot", 5000):
            return True

        return False

    def evaluate(self, project: Dict[str, Any]) -> Dict[str, Any]:
        """完整评估一个项目"""
        score = self.calculate_score(project)
        project["hotness_score"] = score
        project["hotness_level"] = self.determine_level({**project, "hotness_score": score})
        project["is_hot"] = self.is_hot({**project, "hotness_score": score})
        return project
