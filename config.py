import os

BOT_TOKEN        = os.environ.get("BOT_TOKEN", "")
OWNER_ID         = int(os.environ.get("OWNER_ID", "0"))
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "")   # set via env var — empty = no channel gate
CHANNEL_LINK     = os.environ.get("CHANNEL_LINK", "")
GITHUB_REPO      = os.environ.get("GITHUB_REPO", "")
GITHUB_TOKEN     = os.environ.get("GITHUB_TOKEN", "")
DB_NAME          = os.environ.get("DB_NAME", "bot_data.db")
LOG_CHANNEL_ID   = int(os.environ.get("LOG_CHANNEL_ID", "-1004281892706"))

# ─── Proxy config (set in env vars for Indian IP routing) ────────────────────
# PROXY_URL  → single proxy  e.g. http://user:pass@1.2.3.4:8080
# PROXY_LIST → comma-separated list for rotation
#              e.g. http://u:p@1.1.1.1:8080,http://u:p@2.2.2.2:8080
PROXY_URL  = os.environ.get("PROXY_URL", "").strip()
PROXY_LIST = [p.strip() for p in os.environ.get("PROXY_LIST", "").split(",") if p.strip()]
