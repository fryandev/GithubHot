"""GitHub API 数据抓取模块"""

import time
import os
from typing import List, Dict, Optional, Any
from urllib.parse import urlencode

import requests
import yaml


class GitHubFetcher:
    """GitHub API 数据抓取器"""

    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.token = self.config["github"].get("token", "")
        # 优先从环境变量读取 token
        env_token = os.environ.get("GITHUB_TOKEN", "")
        if env_token:
            self.token = env_token

        self.base_url = self.config["github"].get("base_url", "https://api.github.com")
        self.per_page = self.config["github"].get("per_page", 100)
        self.delay = self.config["github"].get("request_delay", 1.5)
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "GithubHot/0.1.0",
        })
        if self.token:
            self.session.headers["Authorization"] = f"token {self.token}"

    def _request(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """发送 API 请求"""
        url = f"{self.base_url}{endpoint}"
        try:
            response = self.session.get(url, params=params or {}, timeout=30)
            # 速率限制检查
            remaining = int(response.headers.get("X-RateLimit-Remaining", 1))
            reset_time = int(response.headers.get("X-RateLimit-Reset", 0))
            if remaining < 5:
                wait = max(reset_time - int(time.time()), 60)
                print(f"⚠️  API 速率限制即将耗尽，等待 {wait} 秒...")
                time.sleep(wait)

            response.raise_for_status()
            time.sleep(self.delay)
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ 请求失败: {url} - {e}")
            raise

    def search_repositories(
        self,
        query: str,
        sort: str = "stars",
        order: str = "desc",
        per_page: Optional[int] = None,
        page: int = 1,
    ) -> List[Dict[str, Any]]:
        """搜索仓库"""
        params = {
            "q": query,
            "sort": sort,
            "order": order,
            "per_page": per_page or self.per_page,
            "page": page,
        }
        data = self._request("/search/repositories", params)
        return data.get("items", [])

    def get_repository(self, owner: str, repo: str) -> Dict[str, Any]:
        """获取单个仓库详情"""
        return self._request(f"/repos/{owner}/{repo}")

    def get_repo_languages(self, owner: str, repo: str) -> Dict[str, int]:
        """获取仓库语言占比"""
        return self._request(f"/repos/{owner}/{repo}/languages")

    def get_repo_readme(self, owner: str, repo: str) -> str:
        """获取仓库 README 内容"""
        try:
            data = self._request(f"/repos/{owner}/{repo}/readme")
            import base64
            content = data.get("content", "")
            if content:
                return base64.b64decode(content.replace("\n", "")).decode("utf-8", errors="replace")
            return ""
        except Exception as e:
            print(f"⚠️ 获取 README 失败 {owner}/{repo}: {e}")
            return ""

    def fetch_hot_repositories(
        self,
        star_threshold: Optional[int] = None,
        max_pages: Optional[int] = None,
        language: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        抓取热门仓库

        Args:
            star_threshold: 最低 star 数
            max_pages: 最大抓取页数
            language: 限定语言
        """
        threshold = star_threshold or self.config["search"].get("default_star_threshold", 1000)
        pages = max_pages or self.config["search"].get("max_pages", 5)
        sort = self.config["search"].get("sort", "stars")
        order = self.config["search"].get("order", "desc")

        query = f"stars:>={threshold}"
        if language:
            query += f" language:{language}"

        all_repos = []
        print(f"🔍 开始抓取: {query} (最多 {pages} 页)")

        for page in range(1, pages + 1):
            print(f"  📄 第 {page}/{pages} 页...")
            try:
                repos = self.search_repositories(query, sort, order, page=page)
                if not repos:
                    break
                all_repos.extend(repos)
            except Exception as e:
                print(f"  ⚠️ 第 {page} 页抓取失败: {e}")
                break

        print(f"✅ 共抓取 {len(all_repos)} 个仓库")
        return all_repos

    def fetch_trending_repositories(self, since: str = "weekly") -> List[Dict[str, Any]]:
        """
        获取趋势仓库（基于最近创建或更新）

        Args:
            since: daily, weekly, monthly
        """
        date_map = {
            "daily": "1",
            "weekly": "7",
            "monthly": "30",
        }
        days = date_map.get(since, "7")
        query = f"created:>={self._date_n_days_ago(int(days))} stars:>100"

        print(f"🔥 抓取 {since} 趋势仓库...")
        return self.search_repositories(query, sort="stars", order="desc", per_page=100)

    @staticmethod
    def _date_n_days_ago(n: int) -> str:
        """返回 n 天前的日期字符串 (YYYY-MM-DD)"""
        from datetime import datetime, timedelta
        return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")

    @staticmethod
    def normalize_repo(raw: Dict[str, Any]) -> Dict[str, Any]:
        """将 GitHub API 返回的原始数据标准化"""
        license_info = raw.get("license") or {}
        return {
            "github_id": raw["id"],
            "full_name": raw["full_name"],
            "owner": raw["owner"]["login"],
            "name": raw["name"],
            "description": raw.get("description") or "",
            "html_url": raw["html_url"],
            "language": raw.get("language") or "",
            "stars": raw.get("stargazers_count", 0),
            "forks": raw.get("forks_count", 0),
            "watchers": raw.get("watchers_count", 0),
            "open_issues": raw.get("open_issues_count", 0),
            "created_at": raw.get("created_at", ""),
            "updated_at": raw.get("updated_at", ""),
            "pushed_at": raw.get("pushed_at", ""),
            "topics": raw.get("topics", []),
            "license": license_info.get("spdx_id") or license_info.get("name") or "",
            "homepage": raw.get("homepage") or "",
            "size": raw.get("size", 0),
            "archived": raw.get("archived", False),
            "fork": raw.get("fork", False),
        }
