#!/usr/bin/env python3
"""
Open a visible browser so the user can manually pass any CAPTCHA / DataDome
challenge, then save the resulting storage state (cookies + localStorage) to
.playwright_state/<site>.json so the scraper can re-use it.

Usage:
    python init_playwright_state.py --site usaridetoday
"""
import argparse
import json
import os
import time

from playwright.sync_api import sync_playwright

from site_configs import SITE_CONFIGS

STATE_DIR = ".playwright_state"


def main():
    parser = argparse.ArgumentParser(
        description="Save Playwright browser state for a configured site."
    )
    parser.add_argument(
        "--site",
        required=True,
        help="Site key from SITE_CONFIGS (e.g. usaridetoday)",
    )
    args = parser.parse_args()

    site_config = SITE_CONFIGS.get(args.site)
    if not site_config:
        known = ", ".join(SITE_CONFIGS.keys())
        print(f"❌ Unknown site '{args.site}'. Known sites: {known}")
        return 1

    start_url = site_config.get("preflight_url") or site_config.get("listings_url")
    if not start_url:
        print(f"❌ Site '{args.site}' has no preflight_url or listings_url configured.")
        return 1

    os.makedirs(STATE_DIR, exist_ok=True)
    state_path = os.path.join(STATE_DIR, f"{args.site}.json")

    if os.path.exists(state_path):
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                saved_state = json.load(f)
            now = time.time()
            expired = [
                c["name"]
                for c in saved_state.get("cookies", [])
                if c.get("expires", -1) != -1 and c["expires"] < now
            ]
            if expired:
                os.remove(state_path)
                print(f"🗑️  Deleted stale state file (expired cookies: {', '.join(expired)})")
            else:
                print(f"ℹ️  Existing state file looks valid, will overwrite after new session.")
        except Exception as exc:
            print(f"⚠️  Could not read existing state file, will overwrite: {exc}")

    print(f"🌐  Opening browser for site:  {args.site}")
    print(f"🌐  Navigating to:             {start_url}")
    print()
    print("    If a CAPTCHA or anti-bot challenge appears, complete it now.")
    print("    When the real page is fully loaded, come back here and press ENTER.")
    print()

    ua = site_config.get("headers", {}).get(
        "User-Agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/146.0.0.0 Safari/537.36",
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            channel="chrome",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--lang=en-US,en",
            ],
        )
        context = browser.new_context(
            user_agent=ua,
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/Chicago",
        )
        page = context.new_page()

        try:
            page.goto(start_url, wait_until="domcontentloaded", timeout=60_000)
        except Exception as exc:
            print(f"⚠️  Navigation raised an exception (you can still proceed): {exc}")

        input("Press ENTER to save session state and close the browser... ")

        context.storage_state(path=state_path)
        browser.close()

    print(f"✅  Session state saved to: {state_path}")
    print("    The scraper will automatically load this state when using Playwright.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
