from unittest.mock import Mock, patch, AsyncMock

import pytest

from app.config import settings
from app.services.openrouter import OpenRouterClient


@pytest.fixture(autouse=True)
def set_api_key():
    settings.openrouter_api_key = "test-key"


@pytest.mark.asyncio
async def test_summarize():
    client = OpenRouterClient()
    mock_response = {
        "choices": [{"message": {"content": "This is a summary."}}]
    }
    with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
        mock_response_instance = AsyncMock()
        mock_response_instance.status_code = 200
        mock_response_instance.json = Mock(return_value=mock_response)
        mock_post.return_value = mock_response_instance
        result = await client.summarize("test-model", "Some transcript text", "danish")
        assert result[0] == "This is a summary."
    await client.close()


@pytest.mark.asyncio
async def test_embed():
    client = OpenRouterClient()
    mock_response = {
        "data": [{"embedding": [0.1, 0.2, 0.3]}]
    }
    with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
        mock_response_instance = AsyncMock()
        mock_response_instance.status_code = 200
        mock_response_instance.json = Mock(return_value=mock_response)
        mock_post.return_value = mock_response_instance
        result = await client.embed("test-model", "test text")
        assert result == [0.1, 0.2, 0.3]
    await client.close()
