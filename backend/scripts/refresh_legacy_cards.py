"""批量重刷旧版速读卡片:background/method/result/insight -> what/why/how。

Run from the backend directory with the project venv:
    ./.venv/bin/python -m scripts.refresh_legacy_cards --limit 20

默认只挑旧结构卡片,单条失败自动跳过并继续;每条之间留 sleep 控制节奏。
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.core.db import dispose_engine, session_scope
from app.models import Item, ItemContent
from app.services.app_settings import get_llm_config
from app.services.item_enrich import is_legacy_card, regenerate_card
from app.services.llm import LLMClient


def _parse_ids(raw: str) -> list[int]:
    ids: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            ids.append(int(part))
    return ids


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="重刷旧版速读卡片")
    parser.add_argument(
        "--limit", type=int, default=20, help="最多重刷条数(默认 20,控制 token 消耗)"
    )
    parser.add_argument(
        "--ids", type=str, default="", help="只重刷指定条目 id,逗号分隔(不受 --limit 截断)"
    )
    parser.add_argument("--force", action="store_true", help="跳过旧结构筛选,强制重刷选中条目")
    parser.add_argument("--sleep", type=float, default=0.5, help="每条之间的间隔秒数(默认 0.5)")
    return parser.parse_args()


async def run(*, limit: int, ids: list[int], force: bool, sleep: float) -> int:
    async with session_scope() as session:
        llm = LLMClient.from_config(await get_llm_config(session))
        if llm is None:
            print("LLM 未配置,无法重刷卡片。请先在设置页配置 LLM。")
            return
        stmt = (
            select(Item)
            .join(ItemContent, ItemContent.item_id == Item.id)
            .where(ItemContent.card.is_not(None))
            .order_by(Item.id.desc())
        )
        if ids:
            stmt = stmt.where(Item.id.in_(ids))
        items = list((await session.scalars(stmt)).all())
        # JSONB 里存的 JSON null 也会通过 IS NOT NULL,统一按 dict 过滤。
        cards = [item for item in items if isinstance(item.content.card, dict)]
        candidates = [item for item in cards if force or is_legacy_card(item.content.card)]
        skipped = len(cards) - len(candidates)
        targets = candidates if ids else candidates[:limit]
        if not targets:
            print(f"没有需要重刷的旧版卡片(候选 {len(cards)} 条,跳过 {skipped} 条)。")
            return 0

        ok = failed = legacy_out = 0
        target_ids = [item.id for item in targets]
        for index, target_id in enumerate(target_ids, start=1):
            # rollback 会过期对象,逐条按 id 重新取,避免惰性刷新触发同步 IO。
            item = await session.get(Item, target_id)
            if item is None:
                failed += 1
                print(f"[{index}/{len(target_ids)}] item {target_id} 失败:条目已不存在")
                continue
            title = item.title
            try:
                result = await regenerate_card(session, item, llm)
                ok += 1
                if is_legacy_card(result.card):
                    legacy_out += 1
                    note = "模型仍返回旧结构"
                else:
                    note = "已升级为 what/why/how"
                print(f"[{index}/{len(target_ids)}] item {target_id} 完成:{note} | {title[:40]}")
            except Exception as exc:
                await session.rollback()
                failed += 1
                print(f"[{index}/{len(target_ids)}] item {target_id} 失败:{exc}")
            if sleep > 0 and index < len(target_ids):
                await asyncio.sleep(sleep)

        print(
            f"结果:成功 {ok} 条(其中仍旧结构 {legacy_out} 条)/ 失败 {failed} 条"
            f" / 跳过非旧卡 {skipped} 条 / 候选 {len(cards)} 条"
        )
        return failed


async def main() -> None:
    args = parse_args()
    try:
        failed = await run(
            limit=max(1, args.limit),
            ids=_parse_ids(args.ids),
            force=args.force,
            sleep=max(0.0, args.sleep),
        )
    finally:
        await dispose_engine()
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
