import logging
from app.models.setting import Setting
from app.services.openrouter import OpenRouterClient, get_api_key

logger = logging.getLogger(__name__)

EMBEDDING_MODEL_KEY = "embedding_model"
DEFAULT_EMBEDDING_MODEL = "openai/text-embedding-3-small"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))
        start += chunk_size - overlap
    return chunks


async def embed_chunks(session, chunks: list[str]) -> list[list[float]]:
    setting = await session.get(Setting, EMBEDDING_MODEL_KEY)
    model = setting.value if setting else DEFAULT_EMBEDDING_MODEL
    api_key = await get_api_key(session)

    async with OpenRouterClient(api_key=api_key) as client:
        embeddings = []
        for chunk in chunks:
            embedding = await client.embed(model, chunk)
            embeddings.append(embedding)
        return embeddings
