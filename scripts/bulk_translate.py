#!/usr/bin/env python3
"""大批量翻译脚本（Google 后端，断点续翻）

用法：
    cd /Users/ryan/Projects/GithubHot
    PYTHONPATH=src python scripts/bulk_translate.py

特性：
- 使用 Google + Googletrans 后端（跳过 MLX，避免本地资源瓶颈）
- 每 100 条自动保存到数据库，随时可中断再续
- 自动检测已翻译项目，避免重复工作
"""

import sys
sys.path.insert(0, "src")

from github_hot.database import Database
from github_hot.translator import MultiBackendTranslator


def main():
    db = Database()
    translator = MultiBackendTranslator(
        backend_order=["google", "googletrans"],
        max_workers=10,
    )

    # 统计未翻译项目
    total = db.conn.execute('''
        SELECT COUNT(*) FROM projects
        WHERE description_zh IS NULL OR description_zh = "" OR description_zh = description
    ''').fetchone()[0]
    print(f"🔤 共 {total} 个未翻译项目")

    if total == 0:
        print("✅ 所有项目已翻译")
        return

    batch_size = 100
    processed = 0

    while True:
        # 每次取一批未翻译的（使用修复后的方法，自动排除中文原文）
        projects = db.get_untranslated_projects(limit=batch_size)

        if not projects:
            break

        print(f"\n📦 第 {processed//batch_size + 1} 批: {len(projects)} 个项目")

        # 翻译
        results = translator.translate_projects(projects, progress=True)

        # 保存
        db.update_translations(results)
        processed += len(results)

        # 统计本批成功数
        success = sum(1 for r in results if r.get("description_zh"))
        print(f"   ✅ 本批成功: {success}/{len(results)} | 累计: {processed}/{total}")

        if len(projects) < batch_size:
            break

    print(f"\n🎉 全部完成！共翻译 {processed} 个项目")
    db.close()


if __name__ == "__main__":
    main()
