"""命令行入口"""

import os
import sys
from pathlib import Path

# 确保能找到 src 目录
sys.path.insert(0, str(Path(__file__).parent.parent))

import click
from tqdm import tqdm

from github_hot.database import Database
from github_hot.fetcher import GitHubFetcher
from github_hot.graphql_fetcher import GraphQLFetcher
from github_hot.trend_fetcher import TrendFetcher
from github_hot.translator import MultiBackendTranslator
from github_hot.scorer import HotnessScorer
from github_hot.classifier import ProjectClassifier
from github_hot.writer import DocumentWriter


@click.group()
@click.option("--db", default="data/github_hot.db", help="数据库路径")
@click.pass_context
def cli(ctx, db):
    """GitHub Hot - 热门项目数据库与文档系统"""
    ctx.ensure_object(dict)
    ctx.obj["db_path"] = db


@cli.command()
@click.option("--threshold", "-t", default=None, type=int, help="最低 star 数")
@click.option("--pages", "-p", default=None, type=int, help="抓取页数")
@click.option("--language", "-l", default=None, help="限定语言")
@click.pass_context
def fetch(ctx, threshold, pages, language):
    """从 GitHub 抓取热门项目"""
    db = Database(ctx.obj["db_path"])
    fetcher = GitHubFetcher()

    try:
        repos = fetcher.fetch_hot_repositories(
            star_threshold=threshold,
            max_pages=pages,
            language=language,
        )

        print(f"\n💾 开始保存到数据库...")
        for raw in tqdm(repos, desc="保存项目"):
            project = fetcher.normalize_repo(raw)
            project_id = db.upsert_project(project)
            db.record_fetch_history(
                project["full_name"],
                project["stars"],
                project["forks"],
                project["open_issues"],
            )

        print(f"✅ 成功保存/更新 {len(repos)} 个项目")
    finally:
        db.close()


@cli.command()
@click.option("--all", "-a", is_flag=True, help="重新评分所有项目")
@click.pass_context
def score(ctx, all):
    """计算热门评分"""
    db = Database(ctx.obj["db_path"])
    scorer = HotnessScorer()

    try:
        # 更新增速数据
        print("📊 更新增速数据...")
        db.update_growth_data()

        # 获取项目
        if all:
            projects = db.get_all_projects()
        else:
            projects = db.get_all_projects(where="hotness_score = 0 OR hotness_level = ''")

        print(f"\n🔥 开始评分 ({len(projects)} 个项目)...")
        for project in tqdm(projects, desc="评分"):
            project = scorer.evaluate(project)
            db.upsert_project(project)

        # 统计
        stats = db.get_stats()
        print(f"\n📈 评分完成:")
        print(f"   项目总数: {stats['total_projects']}")
        print(f"   热门项目: {stats['hot_projects']}")
    finally:
        db.close()


@cli.command()
@click.pass_context
def classify(ctx):
    """为项目自动分类并打标签"""
    db = Database(ctx.obj["db_path"])
    classifier = ProjectClassifier()

    try:
        projects = db.get_all_projects(where="is_hot = 1")
        print(f"\n🏷️ 开始分类 ({len(projects)} 个热门项目)...")

        # 获取趋势数据（用于真实趋势分类）
        print("📊 加载趋势数据...")
        trend_data_map = {}
        for period in ["daily", "weekly", "monthly"]:
            rankings = db.get_trend_rankings(period)
            for r in rankings:
                fn = r["full_name"]
                if fn not in trend_data_map:
                    trend_data_map[fn] = {}
                trend_data_map[fn][period] = r

        for project in tqdm(projects, desc="分类"):
            # 清除旧标签（保留热度标签）
            db.clear_project_tags(project["id"], category="language")
            db.clear_project_tags(project["id"], category="domain")
            db.clear_project_tags(project["id"], category="activity")
            db.clear_project_tags(project["id"], category="trend")

            # 附加趋势数据
            project["trend_data"] = trend_data_map.get(project["full_name"], {})

            tags = classifier.classify(project)
            for tag_name, category, confidence in tags:
                # 获取或创建标签
                tag_id = db.get_or_create_tag(tag_name, category)
                db.add_project_tag(project["id"], tag_id, confidence)

        print(f"✅ 分类完成")

        # 显示标签统计
        all_tags = db.get_tags()
        print(f"\n📋 标签统计:")
        for category in ["language", "domain", "hotness", "activity", "trend"]:
            tags = [t for t in all_tags if t["category"] == category]
            print(f"   {category}: {len(tags)} 个标签")
    finally:
        db.close()


@cli.command()
@click.pass_context
def generate(ctx):
    """生成 Markdown 文档"""
    db = Database(ctx.obj["db_path"])
    writer = DocumentWriter()

    try:
        print("\n📝 开始生成文档...")

        # 1. 首页索引
        stats = db.get_stats()
        stats["trend_stats"] = db.get_trend_stats()
        top_projects = db.get_all_projects(limit=100, order_by="hotness_score DESC")
        writer.write_index(top_projects, stats)

        # 2. 按语言分类
        languages = set()
        for p in db.get_all_projects():
            lang = p.get("language", "")
            if lang:
                languages.add(lang)

        for lang in sorted(languages):
            projects = db.get_all_projects(
                where="language = ? AND is_hot = 1",
                params=(lang,),
                order_by="hotness_score DESC",
            )
            if projects:
                writer.write_by_language(lang, projects)

        # 3. 按领域分类
        domain_tags = [t for t in db.get_tags("domain")]
        for tag in domain_tags:
            projects = db.get_projects_by_tag(tag["name"])
            if projects:
                writer.write_by_category(
                    tag["name"],
                    tag.get("description") or tag["name"],
                    projects,
                )

        # 4. 按热度分类
        level_map = {
            "legendary": "⭐⭐⭐ 传奇级",
            "very-hot": "⭐⭐ 非常热门",
            "hot": "⭐ 热门",
            "rising": "🚀 新兴热门",
        }
        for level, desc in level_map.items():
            projects = db.get_all_projects(
                where="hotness_level = ?",
                params=(level,),
                order_by="hotness_score DESC",
            )
            writer.write_by_hotness(level, desc, projects)

        # 5. 按活跃分类（基于 pushed_at）
        from datetime import datetime, timedelta
        now = datetime.now()
        daily_cutoff = (now - timedelta(days=7)).isoformat()
        weekly_cutoff = (now - timedelta(days=30)).isoformat()
        monthly_cutoff = (now - timedelta(days=90)).isoformat()

        activity_map = [
            ("daily", "🔥 最近7天活跃", f"pushed_at >= '{daily_cutoff}'"),
            ("weekly", "📅 最近30天活跃",
             f"pushed_at >= '{weekly_cutoff}' AND pushed_at < '{daily_cutoff}'"),
            ("monthly", "📆 最近90天活跃",
             f"pushed_at >= '{monthly_cutoff}' AND pushed_at < '{weekly_cutoff}'"),
        ]
        for activity_type, desc, where_clause in activity_map:
            projects = db.get_all_projects(
                where=where_clause,
                order_by="hotness_score DESC",
            )
            if projects:
                writer.write_by_activity(activity_type, desc, projects)

        # 6. 按趋势分类（基于外部增长量数据）
        for period, desc in [("daily", "📈 日飙升榜"), ("weekly", "📊 周飙升榜"), ("monthly", "📉 月飙升榜")]:
            projects = db.get_projects_with_trend(period)
            if projects:
                writer.write_by_trend(period, desc, projects)

        # 7. 项目 README
        writer.write_project_readme()

        print(f"\n✅ 文档生成完成！")
        print(f"   输出目录: docs/")
    finally:
        db.close()


@cli.command()
@click.pass_context
def update(ctx):
    """一键更新：抓取 + 评分 + 分类 + 生成文档"""
    print("=" * 50)
    print("🚀 开始一键更新")
    print("=" * 50)

    # 检查 token
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("\n⚠️ 未设置 GITHUB_TOKEN 环境变量，API 限制为每小时 60 次")
        print("   建议设置: export GITHUB_TOKEN='your_token'")
        print("   继续执行...\n")

    ctx.invoke(fetch)
    print()
    ctx.invoke(fetch_trends)
    print()
    ctx.invoke(score)
    print()
    ctx.invoke(classify)
    print()
    ctx.invoke(generate)

    print("\n" + "=" * 50)
    print("✅ 一键更新完成！")
    print("=" * 50)


@cli.command()
@click.option("--limit", "-n", default=20, help="显示数量")
@click.option("--language", "-l", default=None, help="按语言筛选")
@click.option("--tag", "-t", default=None, help="按标签筛选")
@click.option("--min-stars", default=0, help="最低 stars")
@click.pass_context
def list_projects(ctx, limit, language, tag, min_stars):
    """列出项目"""
    db = Database(ctx.obj["db_path"])

    try:
        if tag:
            projects = db.get_projects_by_tag(tag, limit=limit)
        elif language:
            projects = db.get_all_projects(
                where="language = ? AND stars >= ?",
                params=(language, min_stars),
                limit=limit,
                order_by="hotness_score DESC",
            )
        else:
            where = f"stars >= {min_stars}"
            projects = db.get_all_projects(
                where=where,
                limit=limit,
                order_by="hotness_score DESC",
            )

        if not projects:
            print("未找到项目")
            return

        print(f"\n{'排名':<4} {'项目':<40} {'⭐':<8} {'🍴':<8} {'语言':<12} {'热度'}")
        print("-" * 90)
        for i, p in enumerate(projects, 1):
            name = p["full_name"][:38]
            lang = (p["language"] or "-")[:10]
            level = p.get("hotness_level", "") or "-"
            print(f"{i:<4} {name:<40} {p['stars']:<8} {p['forks']:<8} {lang:<12} {level}")
    finally:
        db.close()


@cli.command()
@click.pass_context
def stats(ctx):
    """查看统计信息"""
    db = Database(ctx.obj["db_path"])

    try:
        s = db.get_stats()
        print("\n📊 数据库统计")
        print(f"  项目总数: {s['total_projects']}")
        print(f"  热门项目: {s['hot_projects']}")
        print(f"\n  语言分布:")
        for lang in s["language_distribution"][:15]:
            print(f"    {lang['language']}: {lang['count']}")
        print(f"\n  热度分布:")
        for lv in s["level_distribution"]:
            print(f"    {lv['level']}: {lv['count']}")
    finally:
        db.close()


@cli.command()
@click.argument("full_name")
@click.pass_context
def info(ctx, full_name):
    """查看项目详情"""
    db = Database(ctx.obj["db_path"])

    try:
        project = db.get_project_by_name(full_name)
        if not project:
            print(f"❌ 未找到项目: {full_name}")
            return

        print(f"\n📦 {project['full_name']}")
        print(f"  链接: {project['html_url']}")
        print(f"  描述: {project['description'] or '无'}")
        print(f"  ⭐ Stars: {project['stars']}")
        print(f"  🍴 Forks: {project['forks']}")
        print(f"  👀 Watchers: {project['watchers']}")
        print(f"  📝 Open Issues: {project['open_issues']}")
        print(f"  💻 语言: {project['language'] or '未知'}")
        print(f"  🔥 热度分: {project['hotness_score']}")
        print(f"  📊 等级: {project['hotness_level'] or '-'}")
        print(f"  📅 创建: {project['created_at'][:10] if project['created_at'] else '-'}")

        tags = db.get_project_tags(project["id"])
        if tags:
            print(f"  🏷️ 标签: {', '.join(t['name'] for t in tags)}")
    finally:
        db.close()


@cli.command(name="fetch-trends")
@click.pass_context
def fetch_trends(ctx):
    """抓取外部趋势数据（OpenGithubs 日/周/月榜）"""
    db = Database(ctx.obj["db_path"])
    fetcher = TrendFetcher()

    try:
        print("\n📈 开始抓取趋势数据...")
        all_data = fetcher.fetch_all()

        total = 0
        for period, rankings in all_data.items():
            if rankings:
                db.clear_trend_rankings(period)
                db.save_trend_rankings(rankings)
                total += len(rankings)

        print(f"\n✅ 共抓取 {total} 条趋势数据")

        # 显示统计
        stats = db.get_trend_stats()
        print("\n📊 趋势统计:")
        for period, s in stats.items():
            if s["count"] > 0:
                print(f"   {period}: {s['count']} 个项目 (日期: {s['date']}, 最大增长: +{s['max_growth']}⭐)")
    finally:
        db.close()


@cli.command(name="fetch-graphql")
@click.option("--query", "-q", default="stars:>=2000", help="GraphQL 搜索查询")
@click.option("--max-results", "-n", default=None, type=int, help="最大抓取数量")
@click.option("--db-path", "-d", default="data/github_hot.db", help="数据库路径")
@click.pass_context
def fetch_graphql(ctx, query, max_results, db_path):
    """使用 GraphQL API 抓取项目（突破1000限制）"""
    db = Database(db_path)
    fetcher = GraphQLFetcher()

    try:
        repos = fetcher.fetch_all(query=query, max_results=max_results)

        print(f"\n💾 开始保存到数据库...")
        for raw in tqdm(repos, desc="保存项目"):
            project_id = db.upsert_project(raw)
            db.record_fetch_history(
                raw["full_name"],
                raw["stars"],
                raw["forks"],
                raw["open_issues"],
            )

        print(f"✅ 成功保存/更新 {len(repos)} 个项目")
    finally:
        db.close()


@cli.command(name="backfill-trends")
@click.pass_context
def backfill_trends(ctx):
    """补录趋势榜中缺失的项目"""
    db = Database(ctx.obj["db_path"])
    fetcher = GitHubFetcher()

    try:
        missing = db.get_missing_trend_projects()
        if not missing:
            print("✅ 趋势榜项目已全部在库中，无需补录")
            return

        print(f"🔍 发现 {len(missing)} 个缺失的趋势项目:\n")
        for p in missing:
            print(f"  • {p['full_name']} ({p['stars']}⭐)")

        print(f"\n🚀 开始补录...")
        saved = 0
        failed = 0

        for p in tqdm(missing, desc="补录"):
            parts = p["full_name"].split("/")
            if len(parts) != 2:
                print(f"  ⚠️ 非法格式: {p['full_name']}")
                failed += 1
                continue

            owner, repo = parts
            try:
                raw = fetcher.get_repository(owner, repo)
                project = GitHubFetcher.normalize_repo(raw)
                project_id = db.upsert_project(project)
                db.record_fetch_history(
                    project["full_name"],
                    project["stars"],
                    project["forks"],
                    project["open_issues"],
                )
                saved += 1
            except Exception as e:
                print(f"  ❌ {p['full_name']}: {e}")
                failed += 1

        print(f"\n✅ 补录完成: {saved} 个成功, {failed} 个失败")
    finally:
        db.close()


@cli.command(name="translate")
@click.option("--limit", "-n", default=None, type=int, help="最大翻译数量")
@click.option("--workers", "-w", default=5, type=int, help="翻译线程数")
@click.pass_context
def translate_cmd(ctx, limit, workers):
    """批量翻译未翻译的项目描述和 Topics

    使用 deep_translator (Google Translate 免费接口)，自动识别中文原文并保留。
    技术专有名词（python、api、react 等）不翻译。
    """
    db = Database(ctx.obj["db_path"])
    translator = MultiBackendTranslator(max_workers=workers)

    try:
        projects = db.get_untranslated_projects(limit=limit)
        if not projects:
            print("✅ 所有项目已翻译，无需处理")
            return

        print(f"🔤 发现 {len(projects)} 个未翻译项目")
        print(f"   线程数: {workers} | 每批处理")

        results = translator.translate_projects(projects, progress=True)
        db.update_translations(results)

        # 统计
        with_zh = sum(1 for r in results if r.get("description_zh"))
        print(f"\n✅ 翻译完成: {with_zh}/{len(results)} 个项目已翻译")
    finally:
        db.close()


@cli.command(name="refresh")
@click.option("--schedule", "-s", is_flag=True, help="启动定时调度模式")
@click.option("--time", "-t", default="08:30", help="每日定时运行时间 (HH:MM)")
@click.pass_context
def refresh(ctx, schedule, time):
    """刷新时间相关分类（活跃度 + 趋势）

    活跃度基于 pushed_at 随时间自然变化，趋势基于外部榜单每日更新。
    该命令自动完成：fetch-trends → backfill → classify → translate → generate。

    示例：
        # 立即刷新一次
        python -m github_hot.cli refresh

        # 每天 08:30 自动刷新
        python -m github_hot.cli refresh --schedule --time 08:30
    """
    def _refresh_job():
        import time as time_mod
        print(f"\n{'='*50}")
        print(f"⏰ {time_mod.strftime('%Y-%m-%d %H:%M')} 刷新开始")
        print(f"{'='*50}")

        # 1-2. fetch-trends + backfill
        _do_refresh(ctx.obj["db_path"])

        # 3. classify
        print("\n🏷️ [3/5] 重新分类...")
        ctx.invoke(classify)
        print("   ✅ 分类完成")

        # 4. translate
        print("\n🔤 [4/5] 翻译未翻译项目...")
        ctx.invoke(translate_cmd)
        print("   ✅ 翻译完成")

        # 5. generate
        print("\n📝 [5/5] 生成文档...")
        ctx.invoke(generate)
        print("   ✅ 文档生成完成")

        print(f"\n{'='*50}")
        print("🎉 刷新全部完成！")
        print(f"{'='*50}")

    if schedule:
        import schedule as sched_lib
        import time as time_mod

        sched_lib.every().day.at(time).do(_refresh_job)
        print(f"📅 定时刷新已启动，每天 {time} 执行")
        print("   按 Ctrl+C 停止")

        # 立即执行一次
        _refresh_job()

        while True:
            sched_lib.run_pending()
            time_mod.sleep(60)
    else:
        _refresh_job()


def _do_refresh(db_path: str):
    """执行 fetch-trends + backfill-trends"""
    db = Database(db_path)
    try:
        # 1. 抓取最新趋势数据
        print("\n📈 [1/2] 抓取外部趋势数据...")
        trend_fetcher = TrendFetcher()
        all_data = trend_fetcher.fetch_all()
        total = 0
        for period, rankings in all_data.items():
            if rankings:
                db.clear_trend_rankings(period)
                db.save_trend_rankings(rankings)
                total += len(rankings)
        print(f"   ✅ 共抓取 {total} 条趋势数据")

        # 2. 补录缺失项目
        print("\n🩹 [2/2] 补录缺失趋势项目...")
        missing = db.get_missing_trend_projects()
        if missing:
            fetcher = GitHubFetcher()
            saved = 0
            for p in tqdm(missing, desc="补录"):
                parts = p["full_name"].split("/")
                if len(parts) == 2:
                    try:
                        raw = fetcher.get_repository(parts[0], parts[1])
                        project = GitHubFetcher.normalize_repo(raw)
                        db.upsert_project(project)
                        db.record_fetch_history(
                            project["full_name"],
                            project["stars"],
                            project["forks"],
                            project["open_issues"],
                        )
                        saved += 1
                    except Exception:
                        pass
            print(f"   ✅ 补录 {saved} 个项目")
        else:
            print("   ✅ 无需补录")
    finally:
        db.close()


if __name__ == "__main__":
    cli()
