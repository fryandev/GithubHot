"""GitHub GraphQL API 数据抓取模块

GraphQL API 优势：
- 速率限制更宽松（5000点/小时 vs 30次/分钟）
- 单次查询可获取100个仓库
- 支持cursor分页，突破1000条硬限制
- 可精确控制返回字段
"""

import os
import time
from typing import List, Dict, Any, Optional

import requests
import yaml


class GraphQLFetcher:
    """GitHub GraphQL API 数据抓取器"""

    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.token = self.config["github"].get("token", "")
        env_token = os.environ.get("GITHUB_TOKEN", "")
        if env_token:
            self.token = env_token

        self.endpoint = "https://api.github.com/graphql"
        self.delay = 0.5
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "User-Agent": "GithubHot/0.1.0",
        })

    def _query(self, query: str, variables: Optional[Dict] = None) -> Dict[str, Any]:
        """发送 GraphQL 查询"""
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        try:
            response = self.session.post(self.endpoint, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()

            if "errors" in data:
                raise RuntimeError(f"GraphQL 错误: {data['errors']}")

            # 检查速率限制
            rate_limit = data.get("data", {}).get("rateLimit")
            if rate_limit:
                remaining = rate_limit.get("remaining", 0)
                if remaining < 100:
                    reset_at = rate_limit.get("resetAt", "unknown")
                    print(f"⚠️  GraphQL 速率剩余 {remaining}，reset: {reset_at}")

            time.sleep(self.delay)
            return data
        except requests.exceptions.RequestException as e:
            print(f"❌ GraphQL 请求失败: {e}")
            raise

    def search_repositories(
        self,
        query: str,
        first: int = 100,
        after: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        搜索仓库，返回包含 edges/pageInfo/rateLimit 的完整结果

        Returns:
            {
                "edges": [...],
                "pageInfo": {"endCursor": "...", "hasNextPage": True/False},
                "rateLimit": {...}
            }
        """
        cursor_arg = f', after: "{after}"' if after else ""

        gql = f'''
        query {{
            search(query: "{query}", type: REPOSITORY, first: {first}{cursor_arg}) {{
                pageInfo {{
                    endCursor
                    hasNextPage
                }}
                edges {{
                    cursor
                    node {{
                        ... on Repository {{
                            name
                            owner {{ login }}
                            stargazerCount
                            forkCount
                            watchers {{ totalCount }}
                            issues(states: OPEN) {{ totalCount }}
                            pushedAt
                            createdAt
                            updatedAt
                            description
                            primaryLanguage {{ name }}
                            licenseInfo {{ spdxId name }}
                            repositoryTopics(first: 10) {{ nodes {{ topic {{ name }} }} }}
                            homepageUrl
                            isArchived
                            isFork
                            id
                        }}
                    }}
                }}
            }}
            rateLimit {{
                limit
                remaining
                resetAt
                cost
            }}
        }}
        '''

        data = self._query(gql)
        search_data = data.get("data", {}).get("search", {})
        return {
            "edges": search_data.get("edges", []),
            "pageInfo": search_data.get("pageInfo", {}),
            "rateLimit": data.get("data", {}).get("rateLimit", {}),
        }

    def fetch_all(
        self,
        query: str,
        max_results: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        抓取所有结果（自动cursor分页），突破1000条限制

        Args:
            query: GitHub 搜索查询字符串
            max_results: 最大抓取数量（None则不限制）

        Returns:
            标准化后的项目列表
        """
        all_repos = []
        cursor = None
        page = 0

        print(f"🔍 [GraphQL] 开始抓取: {query}")

        while True:
            page += 1
            batch_size = 100
            result = self.search_repositories(query, first=batch_size, after=cursor)

            edges = result.get("edges", [])
            if not edges:
                break

            for edge in edges:
                node = edge.get("node")
                if node:
                    all_repos.append(self._normalize_node(node))

            page_info = result.get("pageInfo", {})
            has_next = page_info.get("hasNextPage", False)
            cursor = page_info.get("endCursor")

            rl = result.get("rateLimit", {})
            print(f"  📄 第{page}批: +{len(edges)} 个 (累计 {len(all_repos)}) "
                  f"| 速率 {rl.get('remaining', '?')}/{rl.get('limit', '?')}")

            if not has_next or not cursor:
                break

            if max_results and len(all_repos) >= max_results:
                all_repos = all_repos[:max_results]
                break

        print(f"✅ [GraphQL] 共抓取 {len(all_repos)} 个仓库")
        return all_repos

    @staticmethod
    def _normalize_node(node: Dict[str, Any]) -> Dict[str, Any]:
        """将 GraphQL 节点数据转换为与 REST API 一致的格式"""
        owner = node.get("owner", {}) or {}
        primary_lang = node.get("primaryLanguage") or {}
        license_info = node.get("licenseInfo") or {}
        watchers = node.get("watchers") or {}
        issues = node.get("issues") or {}
        topics_data = node.get("repositoryTopics") or {}

        # 提取 topics
        topics = []
        for t_node in (topics_data.get("nodes") or []):
            topic = t_node.get("topic") or {}
            name = topic.get("name")
            if name:
                topics.append(name)

        return {
            "github_id": node.get("id", ""),
            "full_name": f"{owner.get('login', '')}/{node.get('name', '')}",
            "owner": owner.get("login", ""),
            "name": node.get("name", ""),
            "description": node.get("description") or "",
            "html_url": f"https://github.com/{owner.get('login', '')}/{node.get('name', '')}",
            "language": primary_lang.get("name") or "",
            "stars": node.get("stargazerCount", 0),
            "forks": node.get("forkCount", 0),
            "watchers": watchers.get("totalCount", 0),
            "open_issues": issues.get("totalCount", 0),
            "created_at": node.get("createdAt", ""),
            "updated_at": node.get("updatedAt", ""),
            "pushed_at": node.get("pushedAt", ""),
            "topics": topics,
            "license": license_info.get("spdxId") or license_info.get("name") or "",
            "homepage": node.get("homepageUrl") or "",
            "size": 0,
            "archived": node.get("isArchived", False),
            "fork": node.get("isFork", False),
        }
