"""Environment-driven configuration. Fail fast on missing values."""
import os

from dotenv import load_dotenv
from pydantic import BaseModel, field_validator

load_dotenv()


class Settings(BaseModel):
    discord_token: str
    guild_id: int
    admin_user_id: int
    suwayomi_url: str
    source_ids: list[str]
    komga_url: str
    komga_api_key: str
    komga_library_id: str
    requests_channel_id: int
    admin_requests_channel_id: int
    request_updates_channel_id: int
    manga_added_channel_id: int
    bulk_confirm_threshold: int = 100
    force_approval: bool = False

    @field_validator("source_ids")
    @classmethod
    def no_local_source(cls, v: list[str]) -> list[str]:
        return [s for s in v if s and s != "0"]


def load_settings() -> Settings:
    return Settings(
        discord_token=os.environ["DISCORD_TOKEN"],
        guild_id=int(os.environ["GUILD_ID"]),
        admin_user_id=int(os.environ["ADMIN_USER_ID"]),
        suwayomi_url=os.environ["SUWAYOMI_URL"],
        source_ids=os.environ["SUWAYOMI_SOURCE_IDS"].split(","),
        komga_url=os.environ["KOMGA_URL"],
        komga_api_key=os.environ["KOMGA_API_KEY"],
        komga_library_id=os.environ["KOMGA_LIBRARY_ID"],
        requests_channel_id=int(os.environ["REQUESTS_CHANNEL_ID"]),
        admin_requests_channel_id=int(os.environ["ADMIN_REQUESTS_CHANNEL_ID"]),
        request_updates_channel_id=int(os.environ["REQUEST_UPDATES_CHANNEL_ID"]),
        manga_added_channel_id=int(os.environ["MANGA_ADDED_CHANNEL_ID"]),
        bulk_confirm_threshold=int(os.getenv("BULK_CONFIRM_THRESHOLD", "100")),
        force_approval=os.getenv("FORCE_APPROVAL", "0") == "1",
    )
