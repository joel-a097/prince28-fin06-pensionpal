# Re-export from the canonical location so existing imports continue to work.
from pensionpal.config import Settings, get_settings, settings

__all__ = ["Settings", "get_settings", "settings"]
