"""Open the persistent Copart profile for a manual login."""

import asyncio

from backend.copart.browser import BrowserEngine


async def main() -> None:
    print("Opening the persistent Chrome profile for Copart.")
    print("Log in manually. Do not store Copart credentials in .env.")
    engine = BrowserEngine(headless=False)
    summary = await engine.initialize_persistent_session()
    print(
        f"Session saved in {summary['profile_dir']} "
        f"({summary['cookies_saved']} Copart cookie(s))."
    )


if __name__ == "__main__":
    asyncio.run(main())
