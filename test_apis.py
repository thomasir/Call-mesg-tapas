"""
TAPAS API REAL DELIVERY TESTER
───────────────────────────────
Run: python test_apis.py 9XXXXXXXXXX
Checks which APIs actually deliver real SMS / Call / WhatsApp to that number.
Watch your phone — each API fires one by one with 4s gap so you know which one worked.
"""
import asyncio
import aiohttp
import sys
import random

PHONE = sys.argv[1] if len(sys.argv) > 1 else input("Enter 10-digit phone: ").strip()

UA = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/125.0.0.0 Mobile Safari/537.36"

TEST_APIS = [

    # ════════════════════════════════════════════════════════════════
    #  📱 SMS — SIGNUP / REGISTRATION flows (send to ANY number)
    # ════════════════════════════════════════════════════════════════

    {
        "name": "Swiggy (Login OTP)",
        "kind": "sms",
        "url": "https://www.swiggy.com/dapi/auth/otp-generate",
        "method": "POST",
        "json": {"mobile": PHONE},
        "headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.swiggy.com",
            "Referer": "https://www.swiggy.com/",
        },
    },
    {
        "name": "Zomato (Login OTP)",
        "kind": "sms",
        "url": "https://api.zomato.com/api/v1/user/auth/otp_request",
        "method": "POST",
        "json": {"mobile": PHONE, "country_id": 1},
        "headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.zomato.com",
            "Referer": "https://www.zomato.com/",
        },
    },
    {
        "name": "Meesho (Signup OTP)",
        "kind": "sms",
        "url": "https://meesho.com/api/v1/users/otp",
        "method": "POST",
        "json": {"phone_number": PHONE},
        "headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.meesho.com",
            "Referer": "https://www.meesho.com/",
        },
    },
    {
        "name": "BigBasket (Login OTP)",
        "kind": "sms",
        "url": "https://www.bigbasket.com/accounts/generate-otp-login/",
        "method": "POST",
        "data": {"phone_no": PHONE, "csrfmiddlewaretoken": "dummy"},
        "headers": {
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://www.bigbasket.com",
            "Referer": "https://www.bigbasket.com/",
            "X-Requested-With": "XMLHttpRequest",
        },
    },
    {
        "name": "Blinkit / Grofers (OTP)",
        "kind": "sms",
        "url": "https://blinkit.com/v4/user/generate_otp",
        "method": "POST",
        "json": {"phone": PHONE},
        "headers": {
            "Content-Type": "application/json",
            "Origin": "https://blinkit.com",
            "Referer": "https://blinkit.com/",
            "app_client": "web",
        },
    },
    {
        "name": "Flipkart (Login OTP)",
        "kind": "sms",
        "url": "https://www.flipkart.com/api/4/user/mobilelogin/otp",
        "method": "POST",
        "json": {"mobileNumber": PHONE},
        "headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.flipkart.com",
            "Referer": "https://www.flipkart.com/",
        },
    },
    {
        "name": "Amazon India (OTP)",
        "kind": "sms",
        "url": "https://www.amazon.in/ap/signin",
        "method": "POST",
        "data": {"phoneNumber": f"+91{PHONE}", "action": "mobileSmsOtp"},
        "headers": {
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://www.amazon.in",
            "Referer": "https://www.amazon.in/",
        },
    },
    {
        "name": "Vedantu (Login OTP)",
        "kind": "sms",
        "url": "https://user.vedantu.com/user/preLoginVerification",
        "method": "POST",
        "json": {"mobile": PHONE, "countryCode": "+91", "type": "LOGIN"},
        "headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.vedantu.com",
            "Referer": "https://www.vedantu.com/",
        },
    },
    {
        "name": "CountryDelight (OTP)",
        "kind": "sms",
        "url": "https://api.countrydelight.in/api/auth/new_request_otp/?format=json",
        "method": "POST",
        "json": {"phone": PHONE},
        "headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.countrydelight.in",
            "Referer": "https://www.countrydelight.in/",
        },
    },
    {
        "name": "Urban Company (OTP)",
        "kind": "sms",
        "url": "https://www.urbancompany.com/v7/consumer/send_otp/",
        "method": "POST",
        "json": {"phone": PHONE, "dial_code": "+91"},
        "headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.urbancompany.com",
            "Referer": "https://www.urbancompany.com/",
        },
    },
    {
        "name": "Dunzo (OTP)",
        "kind": "sms",
        "url": "https://api.dunzo.com/api/auth/otp/",
        "method": "POST",
        "json": {"phone_number": f"+91{PHONE}"},
        "headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.dunzo.com",
            "Referer": "https://www.dunzo.com/",
        },
    },
    {
        "name": "Practo (OTP)",
        "kind": "sms",
        "url": "https://www.practo.com/api/v1/profiles/otp",
        "method": "POST",
        "json": {"phone_number": PHONE, "country_code": "+91"},
        "headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.practo.com",
            "Referer": "https://www.practo.com/",
        },
    },
    {
        "name": "PharmEasy (OTP)",
        "kind": "sms",
        "url": "https://pharmeasy.in/api/auth/v4/sendOtp",
        "method": "POST",
        "json": {"phone": PHONE},
        "headers": {
            "Content-Type": "application/json",
            "Origin": "https://pharmeasy.in",
            "Referer": "https://pharmeasy.in/",
        },
    },
    {
        "name": "1mg (OTP)",
        "kind": "sms",
        "url": "https://www.1mg.com/auth/send_otp",
        "method": "POST",
        "json": {"mobile": PHONE},
        "headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.1mg.com",
            "Referer": "https://www.1mg.com/",
        },
    },
    {
        "name": "Nykaa (OTP)",
        "kind": "sms",
        "url": "https://www.nykaa.com/api/auth/mobile/sendOTP",
        "method": "POST",
        "json": {"mobileNo": PHONE},
        "headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.nykaa.com",
            "Referer": "https://www.nykaa.com/",
        },
    },
    {
        "name": "JioMart (OTP)",
        "kind": "sms",
        "url": "https://www.jiomart.com/api/customer/v2/mobile/otp",
        "method": "POST",
        "json": {"mobileNumber": PHONE},
        "headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.jiomart.com",
            "Referer": "https://www.jiomart.com/",
        },
    },
    {
        "name": "Zepto (OTP)",
        "kind": "sms",
        "url": "https://node-api.zepto.co.in/v1/user/otp/send",
        "method": "POST",
        "json": {"phone": PHONE, "type": "LOGIN"},
        "headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.zepto.co.in",
            "Referer": "https://www.zepto.co.in/",
        },
    },
    {
        "name": "Cars24 (OTP)",
        "kind": "sms",
        "url": "https://api.cars24.com/partner/v2/users/login",
        "method": "POST",
        "json": {"phone": PHONE, "country_code": "+91"},
        "headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.cars24.com",
            "Referer": "https://www.cars24.com/",
        },
    },
    {
        "name": "Spinny (OTP)",
        "kind": "sms",
        "url": "https://www.spinny.com/api/v1/auth/generate_otp/",
        "method": "POST",
        "json": {"phone_number": PHONE, "country_code": "+91"},
        "headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.spinny.com",
            "Referer": "https://www.spinny.com/",
        },
    },
    {
        "name": "Rapido (OTP)",
        "kind": "sms",
        "url": "https://rapido.bike/api/auth/otp",
        "method": "POST",
        "json": {"phone": f"+91{PHONE}"},
        "headers": {
            "Content-Type": "application/json",
            "Origin": "https://rapido.bike",
            "Referer": "https://rapido.bike/",
        },
    },
    {
        "name": "OYO (OTP)",
        "kind": "sms",
        "url": "https://www.oyorooms.com/api/v3/login/otp",
        "method": "POST",
        "json": {"mobile": PHONE, "countryCode": "91"},
        "headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.oyorooms.com",
            "Referer": "https://www.oyorooms.com/",
        },
    },
    {
        "name": "MakeMyTrip (OTP)",
        "kind": "sms",
        "url": "https://www.makemytrip.com/api/auth/sendOtp",
        "method": "POST",
        "json": {"phone": PHONE, "cc": "91"},
        "headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.makemytrip.com",
            "Referer": "https://www.makemytrip.com/",
        },
    },
    {
        "name": "Goibibo (OTP)",
        "kind": "sms",
        "url": "https://www.goibibo.com/api/gommt/gologin/v1/sendOTP",
        "method": "POST",
        "json": {"mobileNo": PHONE, "countryCode": "+91"},
        "headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.goibibo.com",
            "Referer": "https://www.goibibo.com/",
        },
    },
    {
        "name": "Ixigo (OTP)",
        "kind": "sms",
        "url": "https://www.ixigo.com/api/v4/user/otp/request",
        "method": "POST",
        "json": {"mobile": PHONE, "country_code": "91"},
        "headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.ixigo.com",
            "Referer": "https://www.ixigo.com/",
        },
    },
    {
        "name": "Lenskart (OTP)",
        "kind": "sms",
        "url": "https://www.lenskart.com/api/v6/user/login",
        "method": "POST",
        "json": {"mobile": PHONE},
        "headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.lenskart.com",
            "Referer": "https://www.lenskart.com/",
        },
    },

    # ════════════════════════════════════════════════════════════════
    #  💬 WHATSAPP
    # ════════════════════════════════════════════════════════════════

    {
        "name": "Swiggy WhatsApp OTP",
        "kind": "whatsapp",
        "url": "https://www.swiggy.com/dapi/auth/otp-generate",
        "method": "POST",
        "json": {"mobile": PHONE, "type": "whatsapp"},
        "headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.swiggy.com",
            "Referer": "https://www.swiggy.com/",
        },
    },

    # ════════════════════════════════════════════════════════════════
    #  📞 CALL
    # ════════════════════════════════════════════════════════════════

    {
        "name": "Swiggy Voice Call OTP",
        "kind": "call",
        "url": "https://www.swiggy.com/dapi/auth/otp-generate",
        "method": "POST",
        "json": {"mobile": PHONE, "type": "voice_call"},
        "headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.swiggy.com",
            "Referer": "https://www.swiggy.com/",
        },
    },
    {
        "name": "Vedantu Voice Call OTP",
        "kind": "call",
        "url": "https://user.vedantu.com/user/preLoginVerification",
        "method": "POST",
        "json": {"mobile": PHONE, "countryCode": "+91", "type": "VOICE"},
        "headers": {
            "Content-Type": "application/json",
            "Origin": "https://www.vedantu.com",
            "Referer": "https://www.vedantu.com/",
        },
    },
]


async def test_one(session: aiohttp.ClientSession, api: dict, idx: int, total: int):
    name = api["name"]
    kind = api.get("kind", "sms")
    icon = {"sms": "📱", "whatsapp": "💬", "call": "📞"}.get(kind, "📡")
    print(f"\n[{idx}/{total}] {icon} {name}")
    print(f"  URL : {api['url']}")

    kw = dict(
        headers={**api.get("headers", {}), "User-Agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/125.0.0.0 Mobile Safari/537.36"},
        timeout=aiohttp.ClientTimeout(total=12, connect=5),
        allow_redirects=True,
        ssl=False,
    )
    if "json" in api:
        kw["json"] = api["json"]
    if "data" in api:
        kw["data"] = api["data"]
    if "params" in api:
        kw["params"] = api["params"]

    try:
        method = api["method"].lower()
        async with getattr(session, method)(api["url"], **kw) as resp:
            status = resp.status
            try:
                raw = await asyncio.wait_for(resp.read(), timeout=5)
                body = raw.decode("utf-8", errors="replace")[:500]
            except Exception:
                body = "(no body / timeout)"

        if status == 202 and not body.strip():
            verdict = "✅ HTTP 202 ACCEPTED — OTP should arrive on phone"
        elif status in (200, 201) and body.strip():
            verdict = f"✅ HTTP {status} — Check phone"
        elif status == 429:
            verdict = "🚦 RATE LIMITED — too many requests"
        elif status in (401, 403):
            verdict = "🔒 AUTH REQUIRED — needs session/CSRF"
        elif status == 404:
            verdict = "💀 DEAD — endpoint not found"
        else:
            verdict = f"❓ HTTP {status}"

        print(f"  Status : {status}")
        print(f"  Body   : {body[:200]}")
        print(f"  ►  {verdict}")
        return (name, kind, status, verdict, body[:100])

    except asyncio.TimeoutError:
        print(f"  ►  ⏱ TIMEOUT — server didn't respond")
        return (name, kind, 0, "TIMEOUT", "")
    except Exception as e:
        print(f"  ►  💥 ERROR — {e}")
        return (name, kind, -1, f"ERROR: {e}", "")


async def main():
    print("=" * 60)
    print(f"  TAPAS API REAL DELIVERY TEST")
    print(f"  Phone : +91{PHONE}")
    print(f"  APIs  : {len(TEST_APIS)}")
    print("=" * 60)
    print("  👀 Keep your phone OPEN — check after each test!")
    print("=" * 60)

    connector = aiohttp.TCPConnector(ssl=False, limit=5)
    results = []

    async with aiohttp.ClientSession(connector=connector) as session:
        for i, api in enumerate(TEST_APIS, 1):
            r = await test_one(session, api, i, len(TEST_APIS))
            results.append(r)
            # 3 second gap between each — so you know exactly which one delivered
            if i < len(TEST_APIS):
                print("  (waiting 3s...)")
                await asyncio.sleep(3)

    # Summary
    print("\n" + "=" * 60)
    print("  RESULTS SUMMARY")
    print("=" * 60)
    working = []
    for name, kind, status, verdict, body in results:
        icon = {"sms": "📱", "whatsapp": "💬", "call": "📞"}.get(kind, "📡")
        mark = "✅" if "✅" in verdict else ("🚦" if "RATE" in verdict else "❌")
        print(f"  {mark} {icon} {name:<30} → {verdict[:40]}")
        if "✅" in verdict:
            working.append((icon, name, kind))

    print("\n" + "=" * 60)
    print(f"  CONFIRMED WORKING ({len(working)}):")
    for icon, name, kind in working:
        print(f"    {icon} {name} ({kind})")
    print("=" * 60)
    print("\n  ⚠️  Cross-check with your phone:")
    print("    📱 Got SMS?      → those APIs work for real")
    print("    💬 Got WhatsApp? → those work")
    print("    📞 Got a call?   → those work")
    print("  Add only REAL delivery ones to tapas.py\n")


asyncio.run(main())
