# 🌐 翻译工作流说明（历史版本 - Agent 批量翻译）

> ⚠️ 本文档为历史版本备份，记录早期通过 **子 Agent 并行翻译** 的流程。
> 当前项目已迁移至 **多后端自动翻译器**（MLX 本地模型 + Google Translate），
> 详见 [`TRANSLATION.md`](TRANSLATION.md)。

---

## 一、设计原则

1. **保留原文 + 添加译文**：不做替换，英文原文和中文译文同时保留在数据库中
2. **技术专有名词不翻译**：`python`、`api`、`react`、`docker`、`kubernetes` 等保持英文
3. **中文原文智能识别**：如果项目简介本身就是中文，则直接保留，不做"翻译"
4. **Agent 批量处理**：将数据拆分为每批 100 条，通过子 Agent 并行翻译，避免上下文溢出

---

## 二、Agent 翻译 Prompt

### 2.1 提示词模板

```text
请翻译以下 GitHub 项目数据为中文。

任务：
1. 读取 /tmp/translate_batch_XX 文件
2. 对每一行（制表符分隔的 4 列：ID、项目名、英文简介、英文 Topics），
   保持前 4 列完全不变，在后面添加第 5 列（中文简介）和第 6 列（中文 Topics）
3. 将结果写入 /tmp/translate_result_XX

输出格式必须是制表符分隔的 6 列，示例：
ID\t项目名\t英文简介\t中文简介\t英文 Topics\t中文 Topics
1\towner/repo\tEnglish description here.\t中文简介在这里。\ttopic1, topic2\t主题1, 主题2

翻译规则：
- 简介翻译自然流畅，符合中文技术文档习惯
- Topics 翻译：保留技术专有名词英文（如 python、api、react、nodejs 等不翻译），只翻译普通词
- 空值保持空
- 不要省略任何行
- 不要添加额外解释文字，直接输出 TSV
```

### 2.2 关键要求

| 要求 | 说明 |
|---|---|
| **输入格式** | 制表符分隔的 4 列：ID、项目名、英文简介、英文 Topics |
| **输出格式** | 制表符分隔的 **6 列**：ID、项目名、英文简介、**中文简介**、英文 Topics、**中文 Topics** |
| **保留原文** | 第 1~4 列与输入完全一致，不得修改 |
| **技术名词** | Topics 中的技术专有名词全部保留英文，不翻译 |
| **空值处理** | 英文简介/Topics 为空时，中文对应列也为空 |
| **中文原文** | 如果英文简介本身就是中文，第 5 列直接复制第 3 列 |
| **无遗漏** | 必须输出所有行，一行都不能少 |

---

## 三、数据准备脚本

### 3.1 从数据库导出待翻译数据

```bash
cd /Users/ryan/Projects/GithubHot

python3 -c "
import sqlite3, json
conn = sqlite3.connect('data/github_hot.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute('SELECT id, full_name, description, topics FROM projects ORDER BY stars DESC')
rows = c.fetchall()

lines = []
for row in rows:
    desc = (row['description'] or '').strip()
    topics = row['topics']
    try:
        topics_list = json.loads(topics) if topics else []
    except:
        topics_list = []
    topics_str = ', '.join(topics_list)
    lines.append(f\"{row['id']}\t{row['full_name']}\t{desc}\t{topics_str}\")

with open('/tmp/translate_input.txt', 'w', encoding='utf-8') as f:
    f.write('ID\t项目名\t英文简介\t英文Topics\n')
    f.write('\n'.join(lines))

print(f'共 {len(lines)} 条')
"
```

### 3.2 拆分为批次文件（每批 100 条）

```bash
cd /tmp
tail -n +2 translate_input.txt > translate_input_noheader.txt
split -l 100 -d translate_input_noheader.txt translate_batch_

# 为每批添加表头
for f in translate_batch_*; do
    echo -e "ID\t项目名\t英文简介\t英文Topics" > "${f}.txt"
    cat "$f" >> "${f}.txt"
    mv "${f}.txt" "$f"
done

rm translate_input_noheader.txt
```

---

## 四、并行翻译执行

### 4.1 启动 Agent 翻译

每批数据启动一个子 Agent，最多可同时运行 **4 个** Agent（系统配额限制）：

```
Agent 1 → /tmp/translate_batch_00 → /tmp/translate_result_00
Agent 2 → /tmp/translate_batch_01 → /tmp/translate_result_01
Agent 3 → /tmp/translate_batch_02 → /tmp/translate_result_02
Agent 4 → /tmp/translate_batch_03 → /tmp/translate_result_03
...
```

### 4.2 合并结果

```bash
cd /tmp
echo -e "ID\t项目名\t英文简介\t中文简介\t英文Topics\t中文Topics" > translate_merged.tsv
for i in 00 01 02 03 04 05 06 07 08 09; do
    tail -n +2 "translate_result_$i" >> translate_merged.tsv
done
```

---

## 五、导入数据库

```bash
cd /Users/ryan/Projects/GithubHot

python3 -c "
import sqlite3, csv

conn = sqlite3.connect('data/github_hot.db')
c = conn.cursor()

with open('/tmp/translate_merged.tsv', 'r', encoding='utf-8') as f:
    reader = csv.reader(f, delimiter='\t')
    next(reader)  # skip header
    updated = 0
    for row in reader:
        if len(row) < 6:
            continue
        project_id = row[0]
        desc_zh = row[3]
        topics_zh = row[5]
        c.execute(
            'UPDATE projects SET description_zh = ?, topics_zh = ? WHERE id = ?',
            (desc_zh, topics_zh, project_id)
        )
        updated += 1

conn.commit()
print(f'Updated {updated} projects')
"
```

---

## 六、翻译效果验证

### 6.1 检查中文原文项目是否被正确保留

```sql
SELECT full_name, description, description_zh
FROM projects
WHERE description = description_zh
  AND description != ''
ORDER BY stars DESC;
```

### 6.2 检查翻译质量抽样

```sql
SELECT full_name, description, description_zh
FROM projects
WHERE description_zh != ''
  AND description != description_zh
ORDER BY RANDOM()
LIMIT 10;
```

---

## 七、注意事项

1. **Agent 超时**：单批 100 条约需 5~10 分钟，超时则重新启动该批次
2. **格式校验**：每个 Agent 输出后需用 `awk -F'\t' '{print NF}'` 验证每行均为 6 列
3. **emoji 保留**：简介中的 emoji（如 🐙、🚀、📚）原样保留
4. **URL 保留**：简介中的链接地址不做翻译或修改
5. **空值行为**：空字符串不等于 `NULL`，导入时统一按空字符串处理
