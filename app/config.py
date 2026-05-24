from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://podcast:podcast@localhost/podcast_transcription_search"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    audio_temp_dir: str = "/tmp/audio"
    portal_images_dir: str = "/app/portal_images"
    local_whisper_url: str = "http://whisper-cpu:9000"
    max_concurrent_processing: int = 2
    abs_url: str = ""
    abs_api_key: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

if not settings.openrouter_api_key:
    import warnings
    warnings.warn("OPENROUTER_API_KEY is not set. AI features will fail at runtime.")
