from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.episode import Episode
from app.models.podcast import Podcast
from app.models.topic import TopicCluster, EpisodeTopic
from app.services.clustering import run_clustering
from app.services.rag import ask_question

router = APIRouter(prefix="/api/insights", tags=["insights"])


@router.get("/topics")
async def list_topics(
    podcast_ids: str | None = Query(None, description="Comma-separated podcast IDs"),
    db: AsyncSession = Depends(get_db),
):
    query = select(
        TopicCluster.id, TopicCluster.label, TopicCluster.description,
        TopicCluster.source, TopicCluster.created_at,
        func.count(EpisodeTopic.episode_id).label("episode_count"),
    ).outerjoin(EpisodeTopic, EpisodeTopic.topic_id == TopicCluster.id)

    if podcast_ids:
        pid_list = podcast_ids.split(",")
        query = query.outerjoin(Episode, Episode.id == EpisodeTopic.episode_id)
        query = query.where(
            (EpisodeTopic.episode_id.is_(None)) | (Episode.podcast_id.in_(pid_list))
        ).distinct()

    query = query.group_by(TopicCluster.id).order_by(func.count(EpisodeTopic.episode_id).desc())
    result = await db.execute(query)
    rows = result.all()

    return [
        {
            "id": str(r.id),
            "label": r.label,
            "description": r.description,
            "source": r.source,
            "episode_count": r.episode_count,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("/topics/{topic_id}/episodes")
async def topic_episodes(
    topic_id: UUID,
    podcast_ids: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Episode, EpisodeTopic.score, Podcast.title.label("podcast_title"))
        .join(EpisodeTopic, EpisodeTopic.episode_id == Episode.id)
        .join(Podcast, Podcast.id == Episode.podcast_id)
        .where(EpisodeTopic.topic_id == topic_id)
    )
    if podcast_ids:
        query = query.where(Episode.podcast_id.in_(podcast_ids.split(",")))
    query = query.order_by(EpisodeTopic.score.desc()).limit(100)

    result = await db.execute(query)
    rows = result.all()

    return [
        {
            "id": str(r.Episode.id),
            "title": r.Episode.title,
            "podcast_title": r.podcast_title,
            "published_at": r.Episode.published_at.isoformat() if r.Episode.published_at else None,
            "score": round(r.score, 3),
        }
        for r in rows
    ]


@router.get("/comparison")
async def cross_series_comparison(
    podcast_ids: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    topic_query = select(TopicCluster.id, TopicCluster.label).order_by(TopicCluster.label)
    topics = (await db.execute(topic_query)).all()

    podcast_query = select(Podcast.id, Podcast.title).order_by(Podcast.title)
    if podcast_ids:
        podcast_query = podcast_query.where(Podcast.id.in_(podcast_ids.split(",")))
    podcasts = (await db.execute(podcast_query)).all()

    comparison = []
    for topic in topics:
        row = {"topic_id": str(topic.id), "topic": topic.label, "podcasts": {}}
        for p in podcasts:
            total = (
                await db.execute(
                    select(func.count(Episode.id)).where(Episode.podcast_id == p.id)
                )
            ).scalar_one() or 1
            matched = (
                await db.execute(
                    select(func.count(EpisodeTopic.episode_id))
                    .join(Episode, Episode.id == EpisodeTopic.episode_id)
                    .where(
                        EpisodeTopic.topic_id == topic.id,
                        Episode.podcast_id == p.id,
                    )
                )
            ).scalar_one() or 0
            row["podcasts"][str(p.id)] = {
                "title": p.title,
                "matched": matched,
                "total": total,
                "pct": round(matched / total * 100, 1),
            }
        comparison.append(row)

    return {
        "topics": comparison,
        "podcasts": [{"id": str(p.id), "title": p.title} for p in podcasts],
    }


@router.post("/rag")
async def rag_query(
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    question = body.get("question", "").strip()
    podcast_ids = body.get("podcast_ids")
    if not question:
        return {"error": "question is required"}

    result = await ask_question(session=db, question=question, podcast_ids=podcast_ids)
    return result


@router.post("/clusters/refresh")
async def refresh_clusters():
    await run_clustering()
    return {"status": "clustering started"}
