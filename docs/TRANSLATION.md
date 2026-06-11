# 🌐 翻译工作流说明

本文档说明 GithubHot 项目中英文内容（项目简介、Topics）的批量翻译流程。

当前系统使用 **多后端自动翻译器**（`deep_translator.GoogleTranslator` + `googletrans`）通过 CLI 一键执行，替代了早期的人工 Agent 分批翻译流程。

---

## 一、设计原则

1. **保留原文 + 添加译文**：英文原文和中文译文同时保留在数据库中
2. **技术专有名词不翻译**：`python`、`api`、`react`、`docker`、`kubernetes`、`llm`、`mcp` 等保持英文
3. **中文原文智能识别**：如果项目简介本身就是中文，则直接保留，不做"翻译"
4. **多线程并行**：默认 5 线程并发，充分利用免费翻译接口的吞吐量
5. **自动降级**：主译器（Google）限流或失败时，自动切换到备选译器（googletrans）

---

## 二、翻译器架构

### 2.1 多后端自动 Fallback

```
┌─────────────────────────────────────────────┐
│         MultiBackendTranslator              │
│  ┌─────────────────────────────────┐        │
│  │  MLXBackend                     │        │
│  │  (本地 Hy-MT2-7B 模型)         │───────┼──→ 首选，质量最高
│  │  1.5s/条 | LLM→大语言模型      │        │
│  └─────────────────────────────────┘        │
│  ┌─────────────────────────────────┐        │
│  │  GoogleTranslatorBackend        │        │
│  │  (deep_translator.Google)       │───────┼──→ 在线免费接口
│  │  2-3s/条 | 有速率限制风险       │        │
│  └─────────────────────────────────┘        │
│  ┌─────────────────────────────────┐        │
│  │  GoogletransBackend             │        │
│  │  (googletrans.Translator)       │───────┼──→ 备选端点
│  │  1.2s/条 | 不同内部 API        │        │
│  └─────────────────────────────────┘        │
│              ↓ fallback 自动切换             │
└─────────────────────────────────────────────┘
```

- **MLX 本地模型**（推荐）：基于 `mlx_lm.server` 启动本地 API 服务，翻译质量最佳，无网络/速率限制。需预先启动服务：`mlx_lm.server --model ~/mlx-env/models/Hy-MT2-7B-4bit --host 0.0.0.0 --port 8080`
- **线程安全**：Google 后端每次调用创建独立实例；MLX 后端使用线程锁保证单线程调用
- **字符截断**：单条文本上限约 4000 字符，超长自动截断
- **Topics 白名单**：`TECH_KEYWORDS` 集合包含 120+ 技术专有名词，命中时不翻译

### 2.2 技术名词白名单（节选）

```python
TECH_KEYWORDS = {
    "python", "javascript", "typescript", "java", "go", "rust", "c++",
    "react", "vue", "angular", "docker", "kubernetes", "k8s",
    "aws", "gcp", "azure", "git", "github", "linux", "nginx",
    "tensorflow", "pytorch", "api", "rest", "graphql", "grpc",
    "json", "xml", "yaml", "cli", "gui", "sdk", "ide",
    "ai", "ml", "llm", "nlp", "cv", "ocr", "rag",
    "blockchain", "web3", "gpu", "cpu", "wasm",
    "oauth", "jwt", "crud", "mvc", "orm",
    "ui", "ux", "webpack", "vite", "jest", "pytest",
    "prometheus", "grafana", "kafka", "rabbitmq",
    "openai", "anthropic", "claude", "gpt", "gemini",
    "huggingface", "mcp", "copilot", "cursor",
    "open-source", "oss", ...
}
```

---

## 三、CLI 翻译命令

### 3.1 一键翻译所有未翻译项目

```bash
cd /Users/ryan/Projects/GithubHot

# 启动本地 MLX 翻译服务（首次需加载模型，后续常驻后台）
mlx_lm.server --model ~/mlx-env/models/Hy-MT2-7B-4bit --host 0.0.0.0 --port 8080 &

# 执行翻译
PYTHONPATH=src python -m github_hot.cli translate
```

输出示例：
```
🔤 发现 42 个未翻译项目
   线程数: 5
  ✅ 翻译后端就绪: mlx
  ✅ 翻译后端就绪: google
  ✅ 翻译后端就绪: googletrans
翻译: 100%|██████████| 42/42 [01:05<00:00,  1.55s/it]

✅ 翻译完成: 42/42 个项目已翻译
```

### 3.2 限制翻译数量（测试/调试）

```bash
PYTHONPATH=src python -m github_hot.cli translate --limit 10
```

### 3.3 调整线程数

```bash
# 默认 5 线程，可根据网络状况调整
PYTHONPATH=src python -m github_hot.cli translate --workers 10
PYTHONPATH=src python -m github_hot.cli translate --workers 3  # 降低速率避免限流
```

---

## 四、补录场景的翻译

### 4.1 何时需要补录翻译

以下场景会产生新的未翻译项目，需要执行翻译：

| 场景 | 说明 |
|---|---|
| **Trend 补录** | `backfill-trends` 将外部趋势榜单中的新项目录入数据库 |
| **手动新增** | 通过 `fetch` 或 `fetch-graphql` 抓取了新的仓库 |
| **翻译质量修复** | 发现大量错误翻译（如 "法学硕士" → "LLM"），清空 `description_zh` 后重翻 |

### 4.2 补录后完整刷新流程

趋势榜单每日更新，补录后建议执行完整刷新：

```bash
# 单步执行（推荐）
PYTHONPATH=src python -m github_hot.cli refresh

# 该命令自动完成：
#   1. fetch-trends    → 抓取最新日/周/月榜单
#   2. backfill        → 补录库中缺失的趋势项目
#   3. classify        → 重新打标签（活跃度 + 趋势）
#   4. translate       → 翻译新增/未翻译项目
#   5. generate        → 重新生成所有文档
```

### 4.3 定时自动刷新

```bash
# 每天 08:30 自动执行完整刷新
PYTHONPATH=src python -m github_hot.cli refresh --schedule --time 08:30
```

---

## 五、未翻译项目检测规则

数据库通过以下条件识别需要翻译的项目：

```sql
SELECT * FROM projects
WHERE description_zh IS NULL
   OR description_zh = ''
   OR description_zh = description    -- 伪翻译（英文原文被直接复制）
```

**伪翻译**：早期部分项目的 `description_zh` 等于 `description`（英文原文），这种也被视为未翻译，会自动重翻。

---

## 六、常见问题修复

### 6.1 批量修复错误翻译

当发现某个术语被系统性误译时（如 "LLM" → "法学硕士"），可直接 SQL 修复：

```bash
PYTHONPATH=src python3 -c "
from github_hot.database import Database
db = Database()

# 统计受影响项目
count = db.conn.execute('''
    SELECT COUNT(*) FROM projects
    WHERE description_zh LIKE '%法学硕士%'
       OR topics_zh LIKE '%法学硕士%'
''').fetchone()[0]
print(f'受影响项目: {count}')

# 执行替换
db.conn.execute('''
    UPDATE projects
    SET description_zh = REPLACE(description_zh, '法学硕士', 'LLM'),
        topics_zh = REPLACE(topics_zh, '法学硕士', 'LLM')
    WHERE description_zh LIKE '%法学硕士%'
       OR topics_zh LIKE '%法学硕士%'
''')
db.conn.commit()

# 重新生成文档
import subprocess
subprocess.run(['PYTHONPATH=src', 'python', '-m', 'github_hot.cli', 'generate'])
"
```

### 6.2 添加新的技术名词到白名单

编辑 `src/github_hot/translator.py` 中的 `TECH_KEYWORDS` 集合，添加新名词后：

```bash
# 清空受影响项目的翻译，让下次 translate 命令自动重翻
PYTHONPATH=src python3 -c "
from github_hot.database import Database
db = Database()
db.conn.execute(\"\"
    UPDATE projects
    SET description_zh = NULL, topics_zh = NULL
    WHERE topics LIKE '%新名词%'
       OR description LIKE '%新名词%'
\"\")
db.conn.commit()
print('已清空，执行 translate 命令重新翻译')
"

PYTHONPATH=src python -m github_hot.cli translate
PYTHONPATH=src python -m github_hot.cli generate
```

---

## 七、翻译效果验证

### 7.1 检查中文原文项目是否被正确保留

```sql
SELECT full_name, description, description_zh
FROM projects
WHERE description = description_zh
  AND description != ''
ORDER BY stars DESC
LIMIT 10;
```

### 7.2 检查翻译质量抽样

```sql
SELECT full_name, description, description_zh
FROM projects
WHERE description_zh != ''
  AND description != description_zh
ORDER BY RANDOM()
LIMIT 10;
```

### 7.3 检查 Topics 翻译

```sql
SELECT full_name, topics, topics_zh
FROM projects
WHERE topics_zh != ''
  AND topics != topics_zh
ORDER BY RANDOM()
LIMIT 10;
```

---

## 八、注意事项

1. **MLX 服务启动**：首次启动需加载模型（约 10-30 秒），之后常驻后台随时可调用
2. **速率限制**：Google 免费翻译接口约 2~3 秒/条，大批量翻译（>1000 条）建议低峰时段执行；MLX 本地模型无限制
3. **线程数**：MLX 为单线程推理（内部加锁），多线程主要用于 Google 后端并发；网络不稳定时降低 `--workers`
4. **emoji 保留**：简介中的 emoji（如 🐙、🚀、📚）原样保留
5. **URL 保留**：简介中的链接地址不做翻译或修改
6. **空值行为**：空字符串不等于 `NULL`，导入时统一按空字符串处理
7. **翻译后必须 generate**：`translate` 只更新数据库，文档需要 `generate` 命令重新渲染
