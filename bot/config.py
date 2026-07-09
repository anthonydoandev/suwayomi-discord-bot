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
    bulk_confirm_threshold: int = 100

    @field_validator("source_ids")
    @classmethod
    def no_local_source(cls, v: list[str]) -> list[str]:
        # id "0" is Suwayomi's Local source pseudo-source — never searchable
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
        bulk_confirm_threshold=int(os.getenv("BULK_CONFIRM_THRESHOLD", "100")),
    )
