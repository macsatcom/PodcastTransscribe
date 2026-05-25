import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.setting import Setting
from app.services.openrouter import OpenRouterClient, get_api_key
from app.services.searcher import search_semantic

logger = logging.getLogger(__name__)

RAG_SYSTEM_PROMPT = (
    "You are answering questions about podcast transcripts. "
    "Below are relevant transcript excerpts with their sources. "
    "Answer the question using ONLY the excerpts below. "
    "Cite sources at the end as: [PodcastName, Month Year]. "
    "If the excerpts do not contain enough information, say so clearly. "
    "Do not invent facts or hallucinate sources."
)


async def ask_question(
    session: AsyncSession,
    question: str,
    podcast_ids: list[str] | None = None,
) -> dict:
    semantic_results = await search_semantic(
        session, question,
        podcast_ids=podcast_ids,
        limit=20,
    )

    if not semantic_results:
        return {
            "answer": "No relevant transcript excerpts were found for your question.",
            "sources": [],
        }

    sources = []
    chunks_text = []
    for i, r in enumerate(semantic_results):
        label = f"{r['podcast_title']}, {r.get('published_at', '')[:10]}"
        chunks_text.append(f"Excerpt {i + 1} [{label}]:\n{r['snippet']}")
        sources.append({
            "episode_id": r["episode_id"],
            "episode_title": r["episode_title"],
            "podcast_title": r["podcast_title"],
            "published_at": r.get("published_at"),
        })

    chunk_block = "\n\n".join(chunks_text)
    user_message = f"---\n{chunk_block}\n---\nQuestion: {question}"

    model_setting = await session.get(Setting, "summarization_model")
    model = model_setting.value if model_setting else "openai/gpt-4o-mini"
    api_key = await get_api_key(session)

    async with OpenRouterClient(api_key=api_key) as client:
        result = await client._post("chat/completions", {
            "model": model,
            "messages": [
                {"role": "system", "content": RAG_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        })

    choices = result.get("choices", [])
    answer = choices[0].get("message", {}).get("content", "") if choices else "Unable to generate answer."

    return {"answer": answer, "sources": sources}
