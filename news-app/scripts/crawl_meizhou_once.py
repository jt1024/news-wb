"""一次性：抓取梅州两个源（跑完看 FetchLog 结果）。"""
import asyncio
import os
import sys

os.chdir("/Users/jt/Desktop/CC/news/news-app")  # DB 路径相对 cwd，必须固定到应用目录
sys.path.insert(0, "/Users/jt/Desktop/CC/news/news-app")

from app.crawler.runner import run_fetch


async def main():
    for sid in (26, 27):
        r = await run_fetch(source_id=sid)
        for x in r["results"]:
            print(f"[{x['source']}] {x['status']} 发现{x['found']} 新增{x['inserted']} "
                  f"重复{x['duplicated']} 备注: {x['error'] or '无'}")


asyncio.run(main())
