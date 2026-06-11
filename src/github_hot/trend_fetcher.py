"""外部趋势数据抓取模块

从 OpenGithubs 社区抓取日/周/月飙升榜单数据：
- github-daily-rank: 每天 Top10，含日增长量
- github-weekly-rank: 每周 Top20，含周增长量
- github-monthly-rank: 每月 Top30，含月增长量

数据存储到 trend_rankings 表，用于项目趋势分类和文档生成。
"""

import re
from typing import List, Dict, Any, Optional

import requests


REPOS = {
    "daily": {
        "repo": "OpenGithubs/github-daily-rank",
        "branch": "main",
        "period": "daily",
        "top_n": 10,
        "growth_label": "日增长",
    },
    "weekly": {
        "repo": "OpenGithubs/github-weekly-rank",
        "branch": "main",
        "period": "weekly",
        "top_n": 20,
        "growth_label": "周增长",
    },
    "monthly": {
        "repo": "OpenGithubs/github-monthly-rank",
        "branch": "main",
        "period": "monthly",
        "top_n": 30,
        "growth_label": "月增长",
    },
}

API_BASE = "https://api.github.com/repos"
RAW_BASE = "https://raw.githubusercontent.com"


class TrendFetcher:
    """OpenGithubs 趋势数据抓取器"""

    def __init__(self, token: str = ""):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "GithubHot/0.1.0",
            "Accept": "application/vnd.github+json",
        })
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def _api_get(self, path: str) -> Any:
        """发送 GitHub API 请求"""
        url = f"{API_BASE}/{path}"
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"  ⚠️ API 请求失败: {url} - {e}")
            return None

    def _raw_get(self, repo: str, branch: str, path: str) -> str:
        """获取 raw 文件内容"""
        url = f"{RAW_BASE}/{repo}/{branch}/{path}"
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            print(f"  ⚠️ Raw 请求失败: {url} - {e}")
            return ""

    def _find_latest_file(self, repo: str, branch: str) -> Optional[str]:
        """
        自动发现最新文件路径

        文件结构:
        - daily: YYYY/MM/YYYYMMDD.md
        - weekly: YYYY/MM/YYYYMMDD.md
        - monthly: YYYY/MM.md
        """
        # 1. 获取根目录列表
        contents = self._api_get(f"{repo}/contents/")
        if not contents:
            return None

        # 筛选年份目录（纯数字的目录名）
        year_dirs = [d for d in contents if d.get("type") == "dir" and d["name"].isdigit()]
        if not year_dirs:
            return None

        # 找最大年份
        year_dirs.sort(key=lambda d: d["name"], reverse=True)
        latest_year = year_dirs[0]["name"]

        # 2. 获取年份目录内容
        year_contents = self._api_get(f"{repo}/contents/{latest_year}")
        if not year_contents:
            return None

        # 区分：monthly 直接是 MM.md 文件，daily/weekly 是月份子目录
        month_files = [f for f in year_contents if f.get("type") == "file" and f["name"].endswith(".md")]
        if month_files:
            # monthly 格式: YYYY/MM.md
            month_files.sort(key=lambda f: f["name"], reverse=True)
            return f"{latest_year}/{month_files[0]['name']}"

        # daily/weekly 格式: YYYY/MM/YYYYMMDD.md
        month_dirs = [d for d in year_contents if d.get("type") == "dir" and d["name"].isdigit()]
        if not month_dirs:
            return None

        month_dirs.sort(key=lambda d: d["name"], reverse=True)
        latest_month = month_dirs[0]["name"]

        # 3. 获取月份目录内容
        month_contents = self._api_get(f"{repo}/contents/{latest_year}/{latest_month}")
        if not month_contents:
            return None

        md_files = [f for f in month_contents if f.get("type") == "file" and f["name"].endswith(".md")]
        if not md_files:
            return None

        md_files.sort(key=lambda f: f["name"], reverse=True)
        return f"{latest_year}/{latest_month}/{md_files[0]['name']}"

    @staticmethod
    def _parse_stars(text: str) -> int:
        """解析 stars 文本（如 '36.2k', '58.2k', '36219'）"""
        text = text.strip().replace(",", "").lower()
        if text.endswith("k"):
            try:
                return int(float(text[:-1]) * 1000)
            except ValueError:
                return 0
        try:
            return int(text)
        except ValueError:
            return 0

    @staticmethod
    def _parse_growth(text: str) -> int:
        """解析增长量文本（如 '🔺3177', '🔺34149', '+3177'）"""
        text = text.strip()
        # 去掉 emoji 和符号
        text = re.sub(r"[🔺🔻+\s⭐]", "", text)
        try:
            return int(text)
        except ValueError:
            return 0

    def _parse_markdown(self, markdown: str, period: str) -> List[Dict[str, Any]]:
        """解析 Markdown 内容，提取趋势数据"""
        results = []

        # 尝试从文件名或内容中提取日期
        date_match = re.search(r"(\d{4})[.-]?(\d{2})[.-]?(\d{2})", markdown[:500])
        ranking_date = ""
        if date_match:
            ranking_date = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"

        # 格式1: 表格格式（较新的格式）
        # | 排名 | 项目名 | Star⭐ | 增长量 |
        # | 1 | [owner/repo](url) | 36.2k | 🔺34149 |
        table_pattern = re.compile(
            r"\|\s*(\d+)\s*\|\s*\[([^\]]+)\]\([^)]+\)\s*\|\s*([^|]+)\|\s*([^|]+)\|"
        )
        for match in table_pattern.finditer(markdown):
            rank = int(match.group(1))
            full_name = match.group(2).strip()
            total_stars = self._parse_stars(match.group(3))
            growth = self._parse_growth(match.group(4))

            # 清理 full_name（可能包含额外文本）
            full_name = re.sub(r"\s+", "", full_name)
            if "/" not in full_name:
                continue

            results.append({
                "full_name": full_name,
                "period": period,
                "rank": rank,
                "growth": growth,
                "total_stars": total_stars,
                "ranking_date": ranking_date,
            })

        # 格式2: 列表格式（较旧的格式，用于 monthly 等）
        if not results:
            list_pattern = re.compile(
                r"[-*]\s*\*\*[^\d]*(\d+)[^:]*:\s*([^\*]+)\*\*"
                r".*?开源地址[:：]\s*https?://github\.com/([^\s\n]+)"
                r".*?总星标数量[:：]\s*([^\n]+)"
                r".*?[日月周]Star增长量[:：]\s*([^\n]+)",
                re.DOTALL,
            )
            for match in list_pattern.finditer(markdown):
                rank = int(match.group(1))
                full_name = match.group(3).strip()
                total_stars = self._parse_stars(match.group(4))
                growth = self._parse_growth(match.group(5))

                results.append({
                    "full_name": full_name,
                    "period": period,
                    "rank": rank,
                    "growth": growth,
                    "total_stars": total_stars,
                    "ranking_date": ranking_date,
                })

        return results

    def fetch_latest(self, period: str) -> List[Dict[str, Any]]:
        """抓取指定周期的最新榜单"""
        config = REPOS.get(period)
        if not config:
            raise ValueError(f"未知周期: {period}，可选: {list(REPOS.keys())}")

        print(f"🔍 [{period}] 发现最新文件...")
        file_path = self._find_latest_file(config["repo"], config["branch"])
        if not file_path:
            print(f"  ❌ 未找到 {period} 的最新文件")
            return []

        print(f"  📄 最新文件: {file_path}")
        markdown = self._raw_get(config["repo"], config["branch"], file_path)
        if not markdown:
            return []

        results = self._parse_markdown(markdown, period)
        print(f"  ✅ 解析到 {len(results)} 条趋势数据")
        return results

    def fetch_all(self) -> Dict[str, List[Dict[str, Any]]]:
        """抓取所有周期的最新榜单"""
        return {
            "daily": self.fetch_latest("daily"),
            "weekly": self.fetch_latest("weekly"),
            "monthly": self.fetch_latest("monthly"),
        }
