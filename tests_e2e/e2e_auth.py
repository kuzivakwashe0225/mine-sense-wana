"""End-to-end: sign-up by email link, sign-in, refresh, idle warning, expiry with state restore, profile, admin.

Needs the full stack (docker compose) with short session timings in .env, e.g.
WANA_IDLE_SECONDS=80 WANA_WARN_SECONDS=60 WANA_READING_SECONDS=30, and the Mailpit UI password in MAILPIT_UI_PASSWORD.
    python tests_e2e/e2e_auth.py
"""
import asyncio
import base64
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
ENV = dict(line.split("=", 1) for line in (ROOT / ".env").read_text().splitlines() if "=" in line and not line.startswith("#"))
B = ENV.get("WANA_PUBLIC_URL", "http://localhost:8095")
MAILPIT = "http://localhost:" + ENV.get("MAILPIT_UI_PORT", "8026")
IDLE, WARN, READ = int(ENV["WANA_IDLE_SECONDS"]), int(ENV["WANA_WARN_SECONDS"]), int(ENV["WANA_READING_SECONDS"])
OUT = ROOT / "e2e-out"
OUT.mkdir(exist_ok=True)
EMAIL = f"rudo.{int(time.time())}@example.org"
PASSWORD = "Chrome-pods-2026!"
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  ' + str(detail)) if detail else ''}", flush=True)


def mailpit(path):
    req = urllib.request.Request(MAILPIT + path)
    req.add_header("Authorization", "Basic " + base64.b64encode(f"admin:{ENV['MAILPIT_UI_PASSWORD']}".encode()).decode())
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


def latest_email(to, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        found = mailpit(f"/api/v1/search?query=to:{to}")["messages"]
        if found:
            return mailpit(f"/api/v1/message/{found[0]['ID']}")
        time.sleep(1)
    raise AssertionError(f"no email to {to}")


async def keycloak_login(pg, email, password):
    await pg.wait_for_selector("#username", timeout=20000)
    await pg.fill("#username", email)
    await pg.fill("#password", password)
    await pg.click("#kc-login")


async def set_password_from_link(pg, link, password, shot=None, timeout=30000):
    await pg.goto(link)
    for _ in range(4):   # Keycloak may show a "Continue" page before the form
        if await pg.locator("#password-new").count():
            break
        cont = pg.locator("a:has-text('Continue')")
        if await cont.count():
            await cont.first.click()
        await pg.wait_for_timeout(800)
    if shot:
        await pg.screenshot(path=str(OUT / shot))
    await pg.fill("#password-new", password, timeout=timeout)
    await pg.fill("#password-confirm", password)
    await pg.click("input[type=submit]")


def reset_rate_limits():
    """Repeated local runs trip the sign-up limit (5 per hour per address); clear the counters first."""
    import subprocess
    project = os.environ.get("WANA_COMPOSE_PROJECT", "wana-local")
    subprocess.run(["docker", "compose", "-p", project, "exec", "-T", "redis", "sh", "-c",
                    'redis-cli -a "$REDIS_PASSWORD" --no-auth-warning --scan --pattern "rl:*" | xargs -r redis-cli -a "$REDIS_PASSWORD" --no-auth-warning del'],
                   cwd=ROOT, check=False, capture_output=True)


async def main():
    reset_rate_limits()
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(viewport={"width": 1440, "height": 950})
        pg = await ctx.new_page()
        errors, console = [], []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("console", lambda m: console.append(f"{m.type}: {m.text[:200]}"))
        try:
            await flow(browser, ctx, pg, errors)
        except Exception:
            await pg.screenshot(path=str(OUT / "fail.png"))
            print("URL at failure:", pg.url)
            print(*console[-15:], sep="\n")
            raise
        await browser.close()
    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)


async def flow(browser, ctx, pg, errors):
    if True:

        # 1. visitor: the map is free to view
        await pg.goto(B + "/")
        await pg.wait_for_selector(".card-head", timeout=30000)
        check("visitor sees the map without signing in", await pg.locator(".nav-item:has-text('Wana Map')").count() == 1)
        await pg.screenshot(path=str(OUT / "a1-visitor-map.png"))

        # 2. sign-up page: name + email only
        await pg.click("text=Create account")
        await pg.wait_for_selector("#su-email")
        await pg.screenshot(path=str(OUT / "a2-signup.png"))
        await pg.fill("#su-name", "Rudo Moyo")
        await pg.fill("#su-email", EMAIL)
        await pg.fill("#su-org", "Tongogara Miners Co-op")
        await pg.check(".check input")
        await pg.click("text=Send me the link")
        await pg.wait_for_selector("text=Check your email")
        check("sign-up confirms the email was sent", True)

        # 3. the email: branded, with a set-password link
        mail = latest_email(EMAIL)
        check("sign-up email arrives", "choose your password" in mail["Subject"].lower(), mail["Subject"])
        html = mail["HTML"]
        link = re.search(r'href="(http[^"]+)"', html).group(1).replace("&amp;", "&")
        mp = await ctx.new_page()
        await mp.set_content(html)
        await mp.screenshot(path=str(OUT / "a3-email.png"), full_page=True)
        await mp.close()

        # 4. follow the link, choose a password (the Wana-themed Keycloak page)
        await set_password_from_link(pg, link, PASSWORD, shot="a4-choose-password.png")
        back = pg.locator("a:has-text('Back to Wana')")
        await back.first.wait_for(timeout=20000)
        await pg.screenshot(path=str(OUT / "a5-account-ready.png"))
        await back.first.click()
        await pg.wait_for_selector(".card-head", timeout=30000)

        # 5. sign in on the Wana-themed page
        if not await pg.locator(".user-btn").count():
            await pg.click("button:has-text('Sign in') >> nth=0")
            await pg.wait_for_selector("#username", timeout=20000)
            await pg.screenshot(path=str(OUT / "a6-login.png"))
            await keycloak_login(pg, EMAIL, PASSWORD)
        await pg.wait_for_selector(".user-btn", timeout=30000)
        check("signed in after setting the password", "RUDO MOYO" in (await pg.locator(".user-btn").inner_text()).upper())

        # 6. refresh keeps the person signed in
        await pg.reload()
        await pg.wait_for_selector(".user-btn", timeout=30000)
        check("refresh keeps the user signed in", True)

        # 7. avatar menu + profile page
        await pg.click(".user-btn")
        await pg.screenshot(path=str(OUT / "a7-menu.png"))
        await pg.click(".menu >> text=Account")
        await pg.wait_for_selector(".profile-hero")
        await pg.wait_for_timeout(800)
        check("profile shows organisation", "Tongogara" in await pg.locator(".profile").inner_text())
        await pg.screenshot(path=str(OUT / "a8-profile.png"), full_page=True)

        # 8. mouse movement is not activity: only moving the mouse, the warning still appears
        await pg.click("nav >> text=Wana Field")      # field page: no reading surface on screen
        await pg.wait_for_selector("#ftarget")
        await pg.fill("#fnotes", "float on ridge, 2 m wide")   # a draft that must survive
        t0 = time.time()
        while not await pg.locator("[role=alertdialog]").count():
            await pg.mouse.move(200 + (time.time() % 7) * 40, 300 + (time.time() % 5) * 30)
            await pg.wait_for_timeout(500)
            if time.time() - t0 > IDLE:
                break
        waited = time.time() - t0
        check("mouse movement does not keep the session alive", await pg.locator("[role=alertdialog]").count() == 1, f"warning after {waited:.0f}s")
        txt = await pg.locator("[role=alertdialog]").inner_text()
        check("warning says the session expires in about 60 seconds", re.search(r"expires in (5\d|60) seconds", txt), txt.split("\n")[1][:60])
        await pg.screenshot(path=str(OUT / "a9-warning.png"))
        await pg.click("text=Stay signed in")
        await pg.wait_for_timeout(500)
        check("'Stay signed in' keeps the session", await pg.locator("[role=alertdialog]").count() == 0)

        # 9. reading counts as activity: with a card on screen the warning comes later
        await pg.click("nav >> text=Wana Map")
        await pg.wait_for_selector(".card-head")
        await pg.click(".trow >> nth=2")                 # select target rank 3
        await pg.wait_for_timeout(600)
        chosen = (await pg.locator(".card-head h2").inner_text()).strip()
        t1 = time.time()
        await pg.locator("[role=alertdialog]").wait_for(timeout=(IDLE + READ + 30) * 1000)
        reading_wait = time.time() - t1
        check("reading a card extends the session (reading exception)", reading_wait > (IDLE - WARN) + READ * 0.6,
              f"warning after {reading_wait:.0f}s (no reading: {IDLE - WARN}s)")

        # 10. let it expire: signed out, then back exactly where they were
        await pg.wait_for_url(re.compile(r"expired=1"), timeout=(WARN + 30) * 1000)
        await pg.wait_for_selector("text=You were signed out", timeout=30000)
        await pg.screenshot(path=str(OUT / "a10-expired.png"))
        check("idle session ends with an explanation", True)
        await pg.click(".callout button:has-text('Sign in')")
        await keycloak_login(pg, EMAIL, PASSWORD)
        await pg.wait_for_selector(".user-btn", timeout=30000)
        await pg.wait_for_selector(".card-head", timeout=30000)
        await pg.wait_for_timeout(1000)
        back_to = (await pg.locator(".card-head h2").inner_text()).strip()
        check("after re-sign-in the user is back on the same target", back_to == chosen, f"{chosen} -> {back_to}")
        check("welcome-back notice shown", await pg.locator("text=You are where you left off").count() == 1)
        await pg.screenshot(path=str(OUT / "a11-resumed.png"))
        await pg.click("nav >> text=Wana Field")
        await pg.wait_for_selector("#fnotes")
        await pg.wait_for_timeout(800)
        check("unsent field form survived the expiry", await pg.input_value("#fnotes") == "float on ridge, 2 m wide")

        # 11. explicit log out: refresh does not sign back in
        await pg.click(".user-btn")
        await pg.click(".menu >> text=Log out")
        await pg.wait_for_selector("button:has-text('Sign in')", timeout=30000)
        await pg.reload()
        await pg.wait_for_selector(".nav-item", timeout=30000)
        await pg.wait_for_timeout(2500)
        check("after Log out, a refresh stays signed out", await pg.locator(".user-btn").count() == 0)

        # 12. administrator: set the admin password from the bootstrap email, grant geologist to the new user
        admin_mail = latest_email(ENV["WANA_ADMIN_EMAIL"])
        admin_link = re.search(r'href="(http[^"]+)"', admin_mail["HTML"]).group(1).replace("&amp;", "&")
        actx = await browser.new_context(viewport={"width": 1440, "height": 950})
        ap = await actx.new_page()
        try:   # one-time link: an earlier run may already have used it
            await set_password_from_link(ap, admin_link, "Admin-Wana-2026!", timeout=8000)
            await ap.locator("a:has-text('Back to Wana')").first.click()
        except Exception:
            await ap.goto(B + "/")
        await ap.wait_for_selector(".nav-item", timeout=30000)
        if not await ap.locator(".user-btn").count():
            await ap.click("button:has-text('Sign in') >> nth=0")
            await keycloak_login(ap, ENV["WANA_ADMIN_EMAIL"], "Admin-Wana-2026!")
        await ap.wait_for_selector(".user-btn", timeout=30000)
        await ap.click("nav >> text=Admin · users")
        await ap.wait_for_selector(f"text={EMAIL}")
        await ap.check(f"input[aria-label='Geologist: {EMAIL}']")
        await ap.wait_for_timeout(1500)
        await ap.screenshot(path=str(OUT / "a12-admin-users.png"), full_page=True)
        check("admin granted geologist (optimistic toggle kept after the server answered)",
              await ap.is_checked(f"input[aria-label='Geologist: {EMAIL}']"))

        # 13. geologist workflow: the new geologist signs in, sends a record, reviews it, updates the map
        await pg.click("button:has-text('Sign in') >> nth=0")
        await keycloak_login(pg, EMAIL, PASSWORD)
        await pg.wait_for_selector(".user-btn", timeout=30000)
        check("new role shows after signing in again", await pg.locator(".nav-item:has-text('Review queue')").count() == 1)
        await pg.click("nav >> text=Wana Field")
        await pg.wait_for_selector("#mlat")
        await pg.fill("#mlat", "-19.664"); await pg.fill("#mlon", "30.012")
        await pg.click(".tile >> nth=0"); await pg.click(".tile >> nth=1")
        await pg.set_input_files("input[type=file]", str(ROOT / "tests_e2e" / "rock.jpg"))
        await pg.wait_for_timeout(500)
        await pg.click("text=Save record")
        await pg.wait_for_selector(".outbox .st.sent", timeout=20000)
        check("signed-in field record is sent", True)
        await pg.click("nav >> text=Review queue")
        await pg.wait_for_selector("table tbody tr td.mono", timeout=20000)
        badge = await pg.locator(".nav-item:has-text('Review queue') .badge").inner_text()
        check("review badge counts pending records", int(badge) >= 1, badge)
        await pg.fill("td input[type=number] >> nth=0", "38.5")
        await pg.click("tbody button:has-text('Chrome') >> nth=0")
        check("endorse shows at once (optimistic)", await pg.locator("tbody tr >> nth=0 >> .st.endorsed").count() == 1)
        await pg.wait_for_timeout(800)
        stages = []
        await pg.click("button:has-text('Update map')")
        for _ in range(120):
            if await pg.locator(".progress").count():
                stages.append(await pg.locator(".progress .small").inner_text())
            if await pg.locator(r"text=/Model vd+:/").count():
                break
            await pg.wait_for_timeout(100)
        await pg.screenshot(path=str(OUT / "a13-review.png"), full_page=True)
        check("map update streams its progress", len(set(stages)) >= 2, sorted(set(stages))[:3])
        check("map update finished with a new version", await pg.locator(r"text=/Model vd+:/").count() == 1)
        await pg.click("nav >> text=Account")
        await pg.wait_for_selector(".rec-list li", timeout=20000)
        check("my records show the geologist's decision", await pg.locator(".rec-list .st.endorsed").count() >= 1)

        # 14. mobile layout: drawer navigation, no sideways scrolling
        m = await browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True)
        await m.goto(B + "/#signup")
        await m.wait_for_selector("#su-email")
        await m.screenshot(path=str(OUT / "a13-mobile-signup.png"), full_page=True)
        await m.click("text=Back to the map")
        await m.wait_for_selector(".card-head", timeout=30000)
        await m.click("[aria-label='Open menu']")
        await m.wait_for_timeout(400)
        await m.screenshot(path=str(OUT / "a14-mobile-menu.png"))
        check("no sideways scrolling on a phone", not await m.evaluate("document.documentElement.scrollWidth > innerWidth"))

        check("no JavaScript errors", not errors, errors[:3])
        await browser.close()
    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    sys.exit(1 if failed else 0)


asyncio.run(main())
