import pytest
from app.adapters import RSSSourceAdapter


SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>Test Podcast</title>
    <image><url>https://example.com/cover.jpg</url></image>
    <item>
      <title>Episode 1</title>
      <guid>ep1</guid>
      <enclosure url="https://example.com/ep1.mp3" type="audio/mpeg" length="12345"/>
      <pubDate>Mon, 01 Jan 2024 10:00:00 GMT</pubDate>
      <itunes:duration>1800</itunes:duration>
    </item>
  </channel>
</rss>
"""


@pytest.mark.asyncio
async def test_rss_adapter_discover(httpx_mock):
    httpx_mock.add_response(url="https://example.com/feed.xml", text=SAMPLE_FEED)
    adapter = RSSSourceAdapter()
    episodes = await adapter.discover_new("https://example.com/feed.xml")
    assert len(episodes) == 1
    assert episodes[0].guid == "ep1"
    assert episodes[0].title == "Episode 1"
    assert episodes[0].audio_url == "https://example.com/ep1.mp3"
    assert episodes[0].duration_seconds == 1800
    assert episodes[0].cover_url == "https://example.com/cover.jpg"


@pytest.mark.asyncio
async def test_parse_duration_seconds():
    adapter = RSSSourceAdapter()
    assert adapter._parse_duration("1800") == 1800


@pytest.mark.asyncio
async def test_parse_duration_mm_ss():
    adapter = RSSSourceAdapter()
    assert adapter._parse_duration("30:15") == 1815


@pytest.mark.asyncio
async def test_parse_duration_hh_mm_ss():
    adapter = RSSSourceAdapter()
    assert adapter._parse_duration("1:30:15") == 5415
