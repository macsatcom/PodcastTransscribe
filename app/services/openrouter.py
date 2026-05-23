import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings


async def get_api_key(session: AsyncSession | None = None) -> str:
    if session is not None:
        from app.models.setting import Setting
        setting = await session.get(Setting, "openrouter_api_key")
        if setting and setting.value:
            return setting.value
    return settings.openrouter_api_key


class OpenRouterClient:
    def __init__(self, api_key: str | None = None):
        self.base_url = settings.openrouter_base_url
        self.api_key = api_key or settings.openrouter_api_key
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY is not set")
        self._http = httpx.AsyncClient(timeout=600)

    async def close(self):
        await self._http.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def _post(self, path: str, json: dict) -> dict:
        response = await self._http.post(
            f"{self.base_url}/{path}",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=json,
        )
        response.raise_for_status()
        return response.json()

    def _is_whisper_model(self, model: str) -> bool:
        ml = model.lower()
        return any(kw in ml for kw in ["whisper", "transcribe", "chirp"])

    async def transcribe_with_timestamps(self, model: str, audio_data: bytes) -> dict:
        if self._is_whisper_model(model):
            return await self._whisper_transcribe(model, audio_data)
        return await self._chat_transcribe(model, audio_data)

    async def _whisper_transcribe(self, model: str, audio_data: bytes) -> dict:
        import subprocess, tempfile, os, math, base64

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(audio_data)
            src_path = f.name

        try:
            wav_path = src_path + ".wav"
            subprocess.run(
                ["ffmpeg", "-y", "-i", src_path,
                 "-vn", "-ar", "16000", "-ac", "1", "-f", "wav", wav_path],
                capture_output=True, timeout=120,
            )

            dur = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", wav_path],
                capture_output=True, text=True, timeout=30,
            )
            total_secs = math.ceil(float(dur.stdout.strip()))

            CHUNK_SECS = 60
            texts = []

            for start in range(0, total_secs, CHUNK_SECS):
                end = min(start + CHUNK_SECS, total_secs)
                chunk_path = src_path + f"_{start}.wav"
                try:
                    subprocess.run(
                        ["ffmpeg", "-y", "-ss", str(start), "-to", str(end),
                         "-i", wav_path,
                         "-vn", "-ar", "16000", "-ac", "1",
                         "-f", "wav", chunk_path],
                        capture_output=True, timeout=120,
                    )
                    with open(chunk_path, "rb") as f:
                        chunk_data = f.read()
                except Exception:
                    continue
                finally:
                    if os.path.exists(chunk_path):
                        os.unlink(chunk_path)

                b64 = base64.b64encode(chunk_data).decode()
                try:
                    result = await self._post("audio/transcriptions", {
                        "model": model,
                        "input_audio": {"data": b64, "format": "wav"},
                    })
                    texts.append(result.get("text", ""))
                except Exception:
                    continue
        finally:
            os.unlink(src_path)
            if os.path.exists(wav_path):
                os.unlink(wav_path)

        raw_text = " ".join(texts)
        text = raw_text

        if raw_text:
            try:
                formatted = await self._post("chat/completions", {
                    "model": "openai/gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": "You format raw speech transcripts into readable paragraphs. Only insert blank lines between paragraphs at natural breaks — never change, add, or remove any words or punctuation."},
                        {"role": "user", "content": f"Insert blank lines between paragraphs in this transcript at natural topic shifts or speaker changes. Do NOT change any words:\n\n{raw_text}"},
                    ],
                })
                choices = formatted.get("choices", [])
                if choices:
                    text = choices[0].get("message", {}).get("content", raw_text)
            except Exception:
                text = raw_text

        return {"text": text, "segments": None}

    async def _chat_transcribe(self, model: str, audio_data: bytes) -> dict:
        import base64, subprocess, tempfile, os

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(audio_data)
            mp3_path = f.name

        try:
            out_path = mp3_path + "_compressed.mp3"
            subprocess.run(
                ["ffmpeg", "-y", "-i", mp3_path,
                 "-vn", "-ar", "16000", "-ac", "1", "-b:a", "24k",
                 "-f", "mp3", out_path],
                capture_output=True, timeout=120,
            )
            with open(out_path, "rb") as f:
                compressed = f.read()
        finally:
            os.unlink(mp3_path)
            if os.path.exists(out_path):
                os.unlink(out_path)

        b64 = base64.b64encode(compressed).decode()

        result = await self._post("chat/completions", {
            "model": model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Transcribe this audio exactly as spoken. Format the output into paragraphs based on natural topic shifts or speaker changes — insert blank lines between paragraphs. Return ONLY the transcribed text, no introduction or commentary."},
                    {"type": "input_audio", "input_audio": {"data": b64, "format": "mp3"}},
                ],
            }],
        })
        choices = result.get("choices", [])
        if not choices:
            raise ValueError("OpenRouter returned no choices")
        return {"text": choices[0].get("message", {}).get("content", ""), "segments": None}

    async def summarize(self, model: str, transcript: str, language: str) -> str:
        prompt = (
            f"Summarize this podcast episode in {language or 'the same language as the transcript'} "
            f"in 3-5 paragraphs:\n\n{transcript}"
        )
        result = await self._post("chat/completions", {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a helpful assistant that summarizes podcast episodes."},
                {"role": "user", "content": prompt},
            ],
        })
        choices = result.get("choices", [])
        if not choices:
            raise ValueError("OpenRouter returned no choices")
        return choices[0].get("message", {}).get("content", "")

    async def embed(self, model: str, text: str) -> list[float]:
        result = await self._post("embeddings", {
            "model": model,
            "input": text,
        })
        data = result.get("data", [])
        if not data:
            raise ValueError("OpenRouter returned no embedding data")
        return data[0].get("embedding", [])
