"""Article listing and generation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_executor, session_dep
from app.models import Article
from app.schemas.config import Page
from app.schemas.content import ArticleGenerateIn, ArticleOut, JobOut

router = APIRouter(prefix="/articles", tags=["articles"])


@router.get("", response_model=Page[ArticleOut])
async def list_articles(
    page: int = 1,
    page_size: int = 10,
    session: AsyncSession = Depends(session_dep),
) -> Page[ArticleOut]:
    page = max(1, page)
    page_size = min(50, max(1, page_size))
    stmt = select(Article).order_by(Article.created_at.desc(), Article.id.desc())
    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(await session.scalars(stmt.offset((page - 1) * page_size).limit(page_size)))
    return Page(items=[ArticleOut.model_validate(row) for row in rows], total=total)


@router.post("/generate", response_model=JobOut, status_code=202)
async def generate_article(
    payload: ArticleGenerateIn,
    request: Request,
    session: AsyncSession = Depends(session_dep),
) -> JobOut:
    executor = get_executor(request)
    try:
        job = await executor.submit(session, "article", payload.model_dump(exclude_none=True))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JobOut.model_validate(job)


@router.get("/{article_id}", response_model=ArticleOut)
async def get_article(article_id: int, session: AsyncSession = Depends(session_dep)) -> ArticleOut:
    article = await session.get(Article, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="文章不存在")
    return ArticleOut.model_validate(article)


@router.delete("/{article_id}", status_code=204)
async def delete_article(article_id: int, session: AsyncSession = Depends(session_dep)) -> None:
    article = await session.get(Article, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="文章不存在")
    await session.delete(article)
    await session.commit()
