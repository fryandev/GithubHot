"""项目描述批量翻译模块（多后端自动 fallback）

支持多个免费翻译后端，主译器失败时自动切换到备选：
- google: deep_translator.GoogleTranslator（默认主译器）
- googletrans: googletrans.Translator（备选，速度更快）

使用 deep_translator (Google Translate 免费接口) 或 googletrans 进行批量翻译。
- 项目描述：auto → zh-CN
- Topics：保留技术专有名词（python、api、react 等不翻译），只翻译普通词
- 已经是中文的内容：直接保留
- 空内容：跳过
"""

import json
import re
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional

import requests
from tqdm import tqdm


# 技术专有名词白名单（不翻译）
TECH_KEYWORDS = {
    "python", "javascript", "typescript", "java", "go", "rust", "c++", "c#", "c",
    "ruby", "php", "swift", "kotlin", "scala", "r", "matlab", "dart", "lua",
    "html", "css", "sql", "bash", "shell", "powershell",
    "react", "vue", "angular", "svelte", "nextjs", "nuxt",
    "node", "nodejs", "deno", "bun",
    "docker", "kubernetes", "k8s", "helm",
    "aws", "gcp", "azure", "alicloud",
    "git", "github", "gitlab", "bitbucket",
    "linux", "ubuntu", "debian", "centos", "macos", "windows",
    "nginx", "apache", "redis", "mysql", "postgresql", "mongodb", "elasticsearch",
    "tensorflow", "pytorch", "keras", "scikit-learn", "pandas", "numpy",
    "api", "rest", "graphql", "grpc", "websocket", "http", "https",
    "json", "xml", "yaml", "toml", "csv", "protobuf",
    "cli", "gui", "sdk", "ide", "ci/cd", "devops", "saas", "paas", "iaas",
    "ai", "ml", "llm", "nlp", "cv", "ocr", "rag",
    "blockchain", "web3", "nft", "defi", "dao",
    "gpu", "cpu", "tpu", "cuda", "opencl",
    "wasm", "webassembly", "pwa", "spa", "ssr",
    "oauth", "jwt", "sso", "ldap", "saml",
    "crud", "mvc", "mvvm", "orm", "db", "sql", "nosql",
    "ui", "ux", "css", "sass", "less", "tailwind",
    "webpack", "vite", "rollup", "parcel", "esbuild",
    "jest", "mocha", "pytest", "unittest", "cypress", "playwright",
    "github-actions", "jenkins", "travis", "circleci",
    "prometheus", "grafana", "elk", "loki", "jaeger",
    "kafka", "rabbitmq", "nats", "mqtt",
    "openai", "anthropic", "claude", "gpt", "gemini", "llama", "mistral",
    "huggingface", "hf", "hugging-face",
    "mcp", "copilot", "codex", "cursor",
    "open-source", "oss", "foss",
}


class TranslatorBackend(ABC):
    """翻译后端抽象基类"""

    name: str = ""

    @abstractmethod
    def translate(self, text: str, source: str = "auto", target: str = "zh-CN") -> Optional[str]:
        """翻译单条文本，返回翻译结果或 None（失败）"""
        pass


class GoogleTranslatorBackend(TranslatorBackend):
    """deep_translator.GoogleTranslator 后端"""

    name = "google"

    def translate(self, text: str, source: str = "auto", target: str = "zh-CN") -> Optional[str]:
        try:
            from deep_translator import GoogleTranslator
            translator = GoogleTranslator(source=source, target=target)
            return translator.translate(text)
        except Exception:
            return None


class GoogletransBackend(TranslatorBackend):
    """googletrans 后端（备选，使用不同 Google 内部端点）"""

    name = "googletrans"

    def translate(self, text: str, source: str = "auto", target: str = "zh-CN") -> Optional[str]:
        try:
            from googletrans import Translator
            translator = Translator()
            result = translator.translate(text, dest=target)
            return result.text if result else None
        except Exception:
            return None


class MLXBackend(TranslatorBackend):
    """本地 MLX 翻译模型后端（Hy-MT2-MLX via mlx_lm.server）

    需要预先启动 API 服务：
        mlx_lm.server --model ~/mlx-env/models/Hy-MT2-7B-4bit --host 0.0.0.0 --port 8080

    优点：质量高（LLM→大语言模型）、无网络依赖、无速率限制
    缺点：需本地 GPU/Neural Engine 资源，持续高并发会导致排队延迟

    并发控制：使用 Semaphore(2) 限制同时请求数，避免服务过载。
    """

    name = "mlx"
    API_URL = "http://localhost:8080/v1/chat/completions"
    TIMEOUT = 60
    MAX_CONCURRENT = 2  # 同时最大并发请求数

    def __init__(self):
        import threading
        self._sem = threading.Semaphore(self.MAX_CONCURRENT)
        # 预热检测：尝试调用一次确认服务可用
        try:
            self._call_api("hello")
        except Exception as e:
            raise RuntimeError(f"MLX API 服务不可用: {e}")

    def _call_api(self, text: str) -> Optional[str]:
        """调用 MLX API（带并发限制）"""
        prompt = f"将以下英文翻译为中文，只输出翻译结果，不要添加任何解释：\n\n{text}"
        payload = {
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max(len(text) * 2, 64),
            "temperature": 0.1,
        }
        with self._sem:
            resp = requests.post(self.API_URL, json=payload, timeout=self.TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()

    def translate(self, text: str, source: str = "auto", target: str = "zh-CN") -> Optional[str]:
        try:
            return self._call_api(text)
        except Exception:
            return None


class MultiBackendTranslator:
    """多后端翻译器，自动 fallback"""

    BACKENDS = {
        "mlx": MLXBackend,
        "google": GoogleTranslatorBackend,
        "googletrans": GoogletransBackend,
    }

    def __init__(
        self,
        backend_order: Optional[List[str]] = None,
        max_workers: int = 5,
    ):
        self.max_workers = max_workers
        self.backend_order = backend_order or ["mlx", "google", "googletrans"]
        self._backends: List[TranslatorBackend] = []
        self._init_backends()

    def _init_backends(self):
        """初始化所有后端"""
        for name in self.backend_order:
            cls = self.BACKENDS.get(name)
            if not cls:
                continue
            try:
                backend = cls()
                self._backends.append(backend)
                print(f"  ✅ 翻译后端就绪: {name}")
            except Exception as e:
                print(f"  ⚠️ 翻译后端初始化失败: {name} - {e}")

        if not self._backends:
            raise RuntimeError("没有可用的翻译后端")

    def translate(self, text: str) -> Optional[str]:
        """使用可用后端翻译，自动 fallback"""
        for backend in self._backends:
            try:
                result = backend.translate(text)
                if result and result.strip() and result.strip().lower() != text.strip().lower():
                    return result
            except Exception:
                continue
        return None

    @staticmethod
    def _is_chinese(text: str) -> bool:
        """判断文本是否已经是中文"""
        if not text:
            return False
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        return chinese_chars / max(len(text), 1) > 0.3

    @staticmethod
    def _translate_topics(topics: List[str], translator: "MultiBackendTranslator") -> str:
        """翻译 Topics，保留技术专有名词

        优化：将多个 topics 批量拼接成一句话一次性翻译，减少 API 调用次数。
        """
        if not topics:
            return ""

        # 先过滤出需要翻译的 topics（非白名单、非中文）
        to_translate = []
        to_translate_indices = []
        results = [None] * len(topics)

        for i, topic in enumerate(topics):
            topic_lower = topic.lower().replace("-", "")
            if topic_lower in TECH_KEYWORDS or MultiBackendTranslator._is_chinese(topic):
                results[i] = topic
            else:
                to_translate.append(topic)
                to_translate_indices.append(i)

        if not to_translate:
            return ", ".join(results)

        # 批量翻译：用 " | " 分隔，一次性翻译后拆分
        batch_text = " | ".join(to_translate)
        translated_batch = translator.translate(batch_text)

        if translated_batch:
            # 按 "|" 拆分，去除多余空格
            parts = [p.strip() for p in translated_batch.split("|")]
            # 如果拆分数量和输入一致，一一对应
            if len(parts) == len(to_translate):
                for idx, part in zip(to_translate_indices, parts):
                    original = topics[idx].lower().replace("-", "")
                    if part and part.lower() != original:
                        results[idx] = part
                    else:
                        results[idx] = topics[idx]
            else:
                # 拆分不一致，逐个回退翻译
                for idx, original_topic in zip(to_translate_indices, to_translate):
                    t = translator.translate(original_topic)
                    results[idx] = t if t and t.lower() != original_topic.lower() else original_topic
        else:
            # 批量翻译失败，回退到保留原文
            for idx in to_translate_indices:
                results[idx] = topics[idx]

        return ", ".join(results)

    def translate_project(self, project: Dict[str, Any]) -> Dict[str, str]:
        """翻译单个项目，返回 {description_zh, topics_zh}"""
        result = {"description_zh": "", "topics_zh": ""}

        desc = (project.get("description") or "").strip()
        if desc:
            if self._is_chinese(desc):
                result["description_zh"] = desc
            else:
                translated = self.translate(desc)
                result["description_zh"] = translated or desc

        topics = project.get("topics", [])
        if isinstance(topics, str):
            try:
                import json
                topics = json.loads(topics)
            except Exception:
                topics = []
        if topics:
            result["topics_zh"] = self._translate_topics(topics, self)

        return result

    def translate_projects(
        self,
        projects: List[Dict[str, Any]],
        progress: bool = True,
    ) -> List[Dict[str, Any]]:
        """批量翻译项目"""
        results = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_map = {executor.submit(self.translate_project, p): p for p in projects}
            iterator = tqdm(as_completed(future_map), total=len(projects), desc="翻译") if progress else as_completed(future_map)
            for future in iterator:
                project = future_map[future]
                try:
                    translated = future.result()
                    results.append({
                        "id": project["id"],
                        **translated,
                    })
                except Exception as e:
                    print(f"  ⚠️ 翻译失败 {project.get('full_name', '?')}: {e}")
                    results.append({
                        "id": project["id"],
                        "description_zh": "",
                        "topics_zh": "",
                    })

        return results
