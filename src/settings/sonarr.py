from pydantic import BaseModel


class Sonarr(BaseModel):
    """Optional Sonarr connection: enables the /addshow command and the Add show button."""
    url: str                                  # e.g. http://sonarr:8989
    api_key: str
    root_folder: str = "/downloads/Shows"     # path as Sonarr sees it
    quality_profile: str = "HD-1080p"         # profile name; the first profile is used if it does not exist
