import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.services.pipeline import process_episode


@pytest.mark.asyncio
async def test_process_episode_full_flow():
    mock_transcript_text = "This is a test transcript with several words for testing."
    mock_segments = [{"start": 0.0, "end": 5.0, "text": "This is a test transcript"}]
    mock_summary = "Test summary."
    mock_embedding = [0.1] * 1536

    with (
        patch("app.services.pipeline.async_session") as mock_session_factory,
        patch("app.services.pipeline.RSSSourceAdapter") as mock_adapter_cls,
        patch("app.services.pipeline.transcribe_audio", new_callable=AsyncMock) as mock_transcribe,
        patch("app.services.pipeline.generate_summary", new_callable=AsyncMock) as mock_summarize,
        patch("app.services.pipeline.embed_chunks", new_callable=AsyncMock) as mock_embed,
    ):
        mock_session = AsyncMock()
        mock_session_factory.return_value.__aenter__.return_value = mock_session

        mock_episode = MagicMock()
        mock_episode.status = "new"
        mock_session.get.return_value = mock_episode

        mock_audio_bytes = MagicMock()
        mock_audio_bytes.read.return_value = b"fake audio data"
        mock_adapter = AsyncMock()
        mock_adapter.fetch_audio.return_value = mock_audio_bytes
        mock_adapter_cls.return_value = mock_adapter

        mock_transcribe.return_value = (mock_transcript_text, mock_segments)
        mock_summarize.return_value = mock_summary
        mock_embed.return_value = [mock_embedding]

        await process_episode("test-id")

        assert mock_episode.status == "ready"
