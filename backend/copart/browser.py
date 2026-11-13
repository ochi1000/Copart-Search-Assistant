import asyncio
import os
import re
import time
import uuid
from typing import Callable, Optional
from urllib.parse import quote, urlencode, urlparse
from playwright.async_api import async_playwright
from dotenv import load_dotenv

from backend.core.paths import PROJECT_ROOT
from backend.core.runtime import emit_runtime_event
from backend.copart.catalog import FACET_FIELDS
from backend.copart.models import US_STATE_CODES, US_STATE_MAP, VehicleFilterConstraints

load_dotenv()

class BrowserEngine:
    def __init__(
        self,
        headless: bool = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ):
        if headless is None:
            self.headless = os.getenv("HEADLESS", "True").lower() == "true"
        else:
            self.headless = headless

        self.provider = os.getenv("BROWSER_PROVIDER", "local").strip().lower()
        if self.provider not in {"local", "browserless"}:
            raise RuntimeError(
                "BROWSER_PROVIDER must be either 'local' or 'browserless'"
            )

        self.browserless_token = os.getenv("BROWSERLESS_TOKEN", "").strip()
        self.browserless_endpoint = os.getenv(
            "BROWSERLESS_ENDPOINT",
            "wss://production-sfo.browserless.io",
        ).strip().rstrip("/")
        self.browserless_profile = os.getenv(
            "BROWSERLESS_PROFILE",
            "",
        ).strip()
        self.browserless_session_timeout_ms = max(
            30000,
            int(os.getenv("BROWSERLESS_SESSION_TIMEOUT_MS", "120000")),
        )
        self.browserless_live_timeout_ms = max(
            30000,
            min(
                int(os.getenv("BROWSERLESS_LIVE_TIMEOUT_MS", "90000")),
                self.browserless_session_timeout_ms,
            ),
        )
        if self.provider == "browserless" and not self.browserless_token:
            raise RuntimeError(
                "BROWSERLESS_TOKEN is required when BROWSER_PROVIDER=browserless"
            )

        # MCP owns stdout and may not provide a usable stderr descriptor on
        # every platform, so browser diagnostics use the server's file logger.
        self._log_callback = log_callback

        self.chrome_path = os.getenv(
            "CHROME_PATH", 
            r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        )
        self.persistent_session = (
            os.getenv("COPART_PERSISTENT_SESSION", "True").lower() == "true"
        )
        configured_profile = os.getenv("COPART_PROFILE_DIR", ".copart-profile")
        if os.path.isabs(configured_profile):
            self.profile_dir = configured_profile
        else:
            self.profile_dir = str((PROJECT_ROOT / configured_profile).resolve())

    def _log(self, message: str) -> None:
        if self._log_callback:
            try:
                self._log_callback(f"[BrowserEngine] {message}")
            except Exception:
                pass

    @staticmethod
    def _filter_items(items: list[dict], constraints: VehicleFilterConstraints) -> list[dict]:
        """Apply constraints that Copart's free-text search does not guarantee."""
        filtered = []
        state_prefix = f"{constraints.state.upper()} -" if constraints.state else None
        requested_locations = [
            BrowserEngine._normalize_location_term(location)
            for location in constraints.locations
            if location and location.strip()
        ]

        for item in items:
            item_title = item.get("title", "") or ""
            searchable_text = " ".join(
                str(value)
                for key, value in item.items()
                if key not in {"image_url", "link"} and value is not None
            ).lower()
            if constraints.include_terms and not any(
                term.lower() in searchable_text for term in constraints.include_terms
            ):
                continue
            if constraints.exclude_terms and any(
                term.lower() in searchable_text for term in constraints.exclude_terms
            ):
                continue

            normalized_title = re.sub(r"[^a-z0-9]+", " ", item_title.lower()).strip()
            padded_title = f" {normalized_title} "
            compact_title = re.sub(r"[^a-z0-9]+", "", item_title.lower())

            def title_matches(value: str) -> bool:
                normalized_value = re.sub(
                    r"[^a-z0-9]+", " ", value.lower()
                ).strip()
                compact_value = re.sub(r"[^a-z0-9]+", "", value.lower())
                return (
                    f" {normalized_value} " in padded_title
                    or (
                        len(compact_value) >= 4
                        and compact_value in compact_title
                    )
                )

            if constraints.makes and not any(
                title_matches(make) for make in constraints.makes
            ):
                continue
            if constraints.models and not any(
                title_matches(model) for model in constraints.models
            ):
                continue

            if constraints.min_year or constraints.max_year:
                year_match = re.search(r"\b(19\d\d|20\d\d)\b", item_title)
                if not year_match:
                    continue
                year = int(year_match.group(1))
                if constraints.min_year and year < constraints.min_year:
                    continue
                if constraints.max_year and year > constraints.max_year:
                    continue

            if state_prefix and not item.get("yard_location", "").upper().startswith(state_prefix):
                continue

            if requested_locations:
                yard = item.get("yard_location", "") or ""
                if not any(
                    BrowserEngine._yard_matches_location(yard, location)
                    for location in requested_locations
                ):
                    continue

            if constraints.min_odometer is not None:
                odometer = item.get("odometer_miles")
                if odometer is None or odometer < constraints.min_odometer:
                    continue

            if constraints.max_odometer is not None:
                odometer = item.get("odometer_miles")
                if odometer is None or odometer > constraints.max_odometer:
                    continue

            requested_titles = constraints.title_types
            if requested_titles:
                title_text = re.sub(
                    r"[^a-z0-9]+", " ", item.get("title_status", "").lower()
                )
                if not any(
                    re.sub(r"[^a-z0-9]+", " ", value.lower()).strip() in title_text
                    for value in requested_titles
                ):
                    continue

            if constraints.damage:
                requested_damage = re.sub(
                    r"[^a-z0-9]+", " ", constraints.damage.lower()
                ).strip()
                actual_damage = re.sub(
                    r"[^a-z0-9]+", " ", item.get("damage", "").lower()
                ).strip()
                if requested_damage not in actual_damage:
                    continue

            filtered.append(item)

        return filtered

    @staticmethod
    def _normalize_location_term(location: str) -> str:
        cleaned = " ".join(location.strip().split())
        lowered = cleaned.lower()
        if lowered in US_STATE_MAP:
            return US_STATE_MAP[lowered]
        uppered = cleaned.upper()
        if uppered in US_STATE_CODES:
            return uppered
        return cleaned

    @staticmethod
    def _yard_matches_location(yard: str, location: str) -> bool:
        yard_upper = yard.upper()
        location_upper = location.upper()
        if location_upper in US_STATE_CODES:
            return yard_upper.startswith(f"{location_upper} -")
        yard_tokens = set(re.findall(r"[A-Z0-9]+", yard_upper))
        location_tokens = set(re.findall(r"[A-Z0-9]+", location_upper))
        return bool(location_tokens) and location_tokens.issubset(yard_tokens)

    @staticmethod
    def _build_search_query(constraints: VehicleFilterConstraints) -> str:
        """Build Copart free text with every requested state or location."""
        query = " ".join(constraints.query.split())
        location_terms = []
        if constraints.state:
            location_terms.append(constraints.state.upper())
        location_terms.extend(
            BrowserEngine._normalize_location_term(location)
            for location in constraints.locations
            if location and location.strip()
        )

        query_normalized = " ".join(re.findall(r"[A-Z0-9]+", query.upper()))
        appended = []
        for term in location_terms:
            normalized_term = " ".join(re.findall(r"[A-Z0-9]+", term.upper()))
            if not normalized_term:
                continue
            padded_query = f" {query_normalized} "
            if f" {normalized_term} " not in padded_query and normalized_term not in appended:
                appended.append(normalized_term)
        return " ".join([query, *appended])

    def _get_launch_config(self, headless: Optional[bool] = None):
        """Construct Chrome launch arguments for headless or headed operation."""
        use_headless = self.headless if headless is None else headless
        args = ["--window-size=1200,850"]

        return args

    def _browserless_ws_url(self) -> str:
        """Build the private Browserless CDP endpoint without logging secrets."""
        parameters = {
            "token": self.browserless_token,
            "timeout": str(self.browserless_session_timeout_ms),
        }
        if self.browserless_profile:
            parameters["profile"] = self.browserless_profile
        separator = "&" if "?" in self.browserless_endpoint else "?"
        return f"{self.browserless_endpoint}{separator}{urlencode(parameters)}"

    async def _set_browser_window(self, page, state: str) -> None:
        """Minimize routine work and restore the real window for verification."""
        if self.provider == "browserless" or self.headless:
            return
        session = None
        try:
            session = await page.context.new_cdp_session(page)
            window = await session.send("Browser.getWindowForTarget")
            window_id = window["windowId"]
            if state == "normal":
                await session.send(
                    "Browser.setWindowBounds",
                    {"windowId": window_id, "bounds": {"windowState": "normal"}},
                )
                await session.send(
                    "Browser.setWindowBounds",
                    {
                        "windowId": window_id,
                        "bounds": {
                            "left": 80,
                            "top": 60,
                            "width": 1200,
                            "height": 850,
                        },
                    },
                )
                await page.bring_to_front()
            else:
                await session.send(
                    "Browser.setWindowBounds",
                    {"windowId": window_id, "bounds": {"windowState": "minimized"}},
                )
            self._log(f"Chrome window state changed to {state}")
        except Exception as exc:
            self._log(f"Could not change Chrome window state to {state}: {exc}")
        finally:
            if session is not None:
                try:
                    await session.detach()
                except Exception:
                    pass

    @staticmethod
    def _user_agent_for(browser) -> str:
        """Build a normal Chrome UA that matches the installed executable."""
        version = browser.version
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{version} Safari/537.36"
        )

    def _common_context_options(self) -> dict:
        return {
            "locale": "en-US",
            "timezone_id": "America/Chicago",
            "viewport": {"width": 1920, "height": 1080},
            "permissions": ["geolocation"],
            "extra_http_headers": {
                "Accept-Language": "en-US,en;q=0.9",
            },
        }

    async def _launch_browser_context(
        self,
        playwright,
        *,
        headless: Optional[bool] = None,
        force_persistent: bool = False,
    ):
        """Launch Chrome and optionally reuse a dedicated on-disk profile."""
        if self.provider == "browserless":
            browser = await playwright.chromium.connect_over_cdp(
                self._browserless_ws_url(),
                timeout=30000,
            )
            if not browser.contexts:
                await browser.close()
                raise RuntimeError(
                    "Browserless connected without a default browser context"
                )
            context = browser.contexts[0]
            self._log("Connected to Browserless remote Chrome")
            return browser, context

        use_headless = self.headless if headless is None else headless
        use_persistent = self.persistent_session or force_persistent

        if use_persistent:
            os.makedirs(self.profile_dir, exist_ok=True)
            try:
                context = await playwright.chromium.launch_persistent_context(
                    user_data_dir=self.profile_dir,
                    executable_path=self.chrome_path,
                    headless=use_headless,
                    args=self._get_launch_config(use_headless),
                    **self._common_context_options(),
                )
            except Exception as exc:
                message = str(exc).lower()
                if "user data directory" in message or "processsingleton" in message:
                    raise RuntimeError(
                        "The Copart browser profile is already open. Close the setup browser "
                        "or other client process and try again."
                    ) from exc
                raise
            self._log(f"Using persistent Copart profile: {self.profile_dir}")
            return context.browser, context

        browser = await playwright.chromium.launch(
            executable_path=self.chrome_path,
            headless=use_headless,
            args=self._get_launch_config(use_headless),
        )
        context_options = self._common_context_options()
        context_options["user_agent"] = self._user_agent_for(browser)
        context = await browser.new_context(**context_options)
        return browser, context

    async def _close_browser_context(self, browser, context) -> None:
        if self.provider == "browserless":
            if browser and browser.is_connected():
                await browser.close()
            return
        try:
            await context.close()
        finally:
            if browser and browser.is_connected():
                await browser.close()

    @staticmethod
    async def _page_for_context(context):
        for page in context.pages:
            if page.url == "about:blank":
                return page
        return await context.new_page()

    @staticmethod
    async def _verification_present(page, verification_signal=None) -> bool:
        """Detect a visible CAPTCHA or browser-verification interstitial."""
        if verification_signal is not None and verification_signal.is_set():
            return True

        selectors = (
            'iframe[src*="hcaptcha" i], iframe[src*="captcha" i], '
            '.h-captcha, [data-sitekey]'
        )
        try:
            challenge_nodes = page.locator(selectors)
            for index in range(min(await challenge_nodes.count(), 5)):
                if await challenge_nodes.nth(index).is_visible():
                    return True
            challenge_text = page.get_by_text(
                re.compile(
                    r"verify (you are|you.re) human|security verification|captcha",
                    re.IGNORECASE,
                )
            )
            for index in range(min(await challenge_text.count(), 5)):
                if await challenge_text.nth(index).is_visible():
                    return True
        except Exception:
            pass

        try:
            body_text = (await page.locator("body").inner_text()).lower()
            return any(
                phrase in body_text
                for phrase in (
                    "verify you are human",
                    "security verification",
                    "complete the captcha",
                    "checking your browser",
                )
            )
        except Exception:
            return False

    async def _create_browserless_live_url(
        self,
        page,
    ) -> tuple[str, str, int]:
        """Create a short-lived interactive view for human verification."""
        session = await page.context.new_cdp_session(page)
        try:
            result = await session.send(
                "Browserless.liveURL",
                {
                    "interactable": True,
                    "resizable": False,
                    "showBrowserInterface": True,
                    "timeout": self.browserless_live_timeout_ms,
                    "instructions": {
                        "layout": "panel",
                        "summary": (
                            "Complete the Copart verification shown in the "
                            "browser. The vehicle search will resume "
                            "automatically."
                        ),
                    },
                },
            )
        finally:
            try:
                await session.detach()
            except Exception:
                pass

        error = result.get("error") if isinstance(result, dict) else None
        live_url = result.get("liveURL") if isinstance(result, dict) else None
        if error or not live_url:
            raise RuntimeError(
                f"Browserless could not create a verification window: "
                f"{error or 'missing live URL'}"
            )
        applied_timeout = int(
            result.get("timeout") or self.browserless_live_timeout_ms
        )
        return (
            str(live_url),
            str(result.get("liveURLId") or ""),
            applied_timeout,
        )

    @staticmethod
    async def _close_browserless_live_url(page, live_url_id: str) -> None:
        if not live_url_id:
            return
        session = await page.context.new_cdp_session(page)
        try:
            await session.send(
                "Browserless.closeLiveURL",
                {"liveURLId": live_url_id},
            )
        except Exception:
            pass
        finally:
            try:
                await session.detach()
            except Exception:
                pass

    async def _wait_for_human_verification(
        self,
        page,
        *,
        ready_selector: str,
        verification_signal=None,
        force: bool = False,
    ) -> bool:
        """Wait for a user when verification or an unknown blocking page appears."""
        ready = page.locator(ready_selector).first
        try:
            if await ready.count() and await ready.is_visible():
                return False
        except Exception:
            pass

        if not force and not await self._verification_present(
            page,
            verification_signal,
        ):
            return False

        live_url_id = ""
        event_data = {
            "message": "Copart needs your attention before the search can continue."
        }
        if self.provider == "browserless":
            (
                live_url,
                live_url_id,
                live_timeout_ms,
            ) = await self._create_browserless_live_url(page)
            event_data.update({
                "live_url": live_url,
                "expires_in_seconds": live_timeout_ms // 1000,
            })
        else:
            await self._set_browser_window(page, "normal")
            event_data["message"] = (
                "Please check the open Chrome window and complete any "
                "Copart prompt."
            )

        await emit_runtime_event(
            "verification_required",
            event_data,
        )

        if self.provider != "browserless" and self.headless:
            raise RuntimeError(
                "Copart requires human verification. Set HEADLESS=False and retry "
                "so the CAPTCHA can be completed in the browser window."
            )

        self._log(
            "HUMAN ACTION REQUIRED: Complete Copart CAPTCHA/verification in the "
            "open Chrome window. The tool will wait without a timeout."
        )
        try:
            await page.bring_to_front()
        except Exception:
            pass

        deadline = (
            time.monotonic() + (live_timeout_ms / 1000)
            if self.provider == "browserless"
            else None
        )
        while True:
            try:
                if await ready.count() and await ready.is_visible():
                    if not await self._verification_present(page):
                        self._log("Human verification completed; resuming search")
                        await self._close_browserless_live_url(
                            page,
                            live_url_id,
                        )
                        await emit_runtime_event("verification_completed", {})
                        await self._set_browser_window(page, "minimized")
                        return True
            except Exception:
                pass
            if deadline is not None and time.monotonic() >= deadline:
                await self._close_browserless_live_url(page, live_url_id)
                raise RuntimeError(
                    "The Browserless verification window expired before "
                    "verification was completed."
                )
            await page.wait_for_timeout(1000)

    async def _apply_structured_filters(
        self,
        page,
        constraints: VehicleFilterConstraints,
    ) -> dict:
        """Apply canonical featured items, facets, ranges, and toggles."""
        facets = []
        for field_name, copart_label in FACET_FIELDS.items():
            if field_name == "locations":
                # Location is intentionally handled in Copart free text and
                # then verified against each extracted yard.
                continue
            values = list(getattr(constraints, field_name, []) or [])
            if values:
                facets.append(
                    {
                        "name": copart_label,
                        "values": values,
                        "prefixes": [],
                        "search_term": values[0] if len(values) == 1 else None,
                    }
                )

        if constraints.damage:
            facets.append(
                {
                    "name": "Damage Type",
                    "values": [
                        constraints.damage,
                        f"{constraints.damage} Damage",
                    ],
                    "prefixes": [],
                    "search_term": constraints.damage,
                }
            )

        for facet_name, values in constraints.additional_facets.items():
            facets.append(
                {
                    "name": facet_name,
                    "values": values,
                    "prefixes": [],
                    "search_term": values[0] if len(values) == 1 else None,
                }
            )

        ranges = [
            {
                "name": "Odometer",
                "minimum": constraints.min_odometer,
                "maximum": constraints.max_odometer,
            },
            {
                "name": "Year",
                "minimum": constraints.min_year,
                "maximum": constraints.max_year,
            },
            {
                "name": "AutoGrade",
                "minimum": constraints.min_autograde,
                "maximum": constraints.max_autograde,
            },
            {
                "name": "Sale date",
                "minimum": constraints.sale_date_from.strftime("%m/%d/%Y")
                if constraints.sale_date_from
                else None,
                "maximum": constraints.sale_date_to.strftime("%m/%d/%Y")
                if constraints.sale_date_to
                else None,
            },
        ]
        ranges = [
            range_filter
            for range_filter in ranges
            if range_filter["minimum"] is not None
            or range_filter["maximum"] is not None
        ]

        toggles = []
        toggle_values = (
            (constraints.lots_anyone_can_bid_on, "Lots anyone can bid on"),
            (constraints.wholesale_only, "Wholesale vehicles only"),
            (constraints.exclude_upcoming_auctions, "Upcoming Auction Vehicles"),
            (constraints.exclude_purple_wave, "Purple Wave Lots"),
        )
        for enabled, label in toggle_values:
            if enabled:
                toggles.append(label)
        toggles.extend(constraints.sale_lights)

        if constraints.newly_added:
            facets.append(
                {
                    "name": "Newly added vehicles",
                    "values": [constraints.newly_added],
                    "prefixes": [],
                    "search_term": None,
                }
            )

        config = {
            "featured_items": constraints.featured_items,
            "facets": facets,
            "ranges": ranges,
            "toggles": toggles,
            "zip_code": constraints.zip_code,
            "radius_miles": constraints.radius_miles,
        }
        if not any(
            (
                config["featured_items"],
                config["facets"],
                config["ranges"],
                config["toggles"],
                config["zip_code"],
            )
        ):
            return {"status": "no_structured_filters"}

        report = await page.evaluate(
            r"""async (config) => {
                const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
                const normalize = value => (value || '')
                    .replace(/\u00a0/g, ' ')
                    .replace(/\s+/g, ' ')
                    .trim()
                    .toLowerCase();
                const withoutCount = value => normalize(value)
                    .replace(/\s*\(\s*[\d,.+]+\s*\)\s*$/, '')
                    .trim();
                const result = {
                    featured_items: {},
                    facets: {},
                    ranges: {},
                    toggles: {},
                    proximity: null
                };

                const headers = () => Array.from(document.querySelectorAll(
                    'search-filter-header, .p-accordion-header, [role="tab"]'
                ));
                const findHeader = name => {
                    const wanted = normalize(name);
                    return headers().find(node => {
                        const text = normalize(node.innerText || node.textContent);
                        return text === wanted || text.includes(wanted);
                    });
                };
                const findScope = header => {
                    const component = header?.closest(
                        'search-filter, p-accordiontab, .p-accordion-tab, '
                        + '[data-pc-name="accordionpanel"]'
                    );
                    if (component) return component;
                    let node = header?.parentElement;
                    for (let depth = 0; node && depth < 7; depth += 1, node = node.parentElement) {
                        if (
                            node.querySelectorAll(
                                'label, [role="option"], .p-checkbox-label, '
                                + 'input[type="checkbox"], input[type="radio"]'
                            ).length
                        ) return node;
                    }
                    return header?.parentElement || null;
                };
                const expand = async header => {
                    let scope = findScope(header);
                    const hasVisibleOption = () => Array.from(
                        scope?.querySelectorAll(
                            'label, [role="option"], .p-checkbox-label, '
                            + 'input[type="checkbox"], input[type="radio"]'
                        ) || []
                    ).some(node => node.offsetParent !== null);
                    if (!hasVisibleOption()) {
                        header.scrollIntoView({block: 'center'});
                        header.click();
                        await sleep(1000);
                        scope = findScope(header);
                    }
                    return scope;
                };
                const isChecked = input =>
                    input?.checked === true
                    || input?.getAttribute('aria-checked') === 'true'
                    || input?.closest('.p-checkbox')?.classList.contains('p-checkbox-checked');

                for (const featured of config.featured_items || []) {
                    const wanted = normalize(featured);
                    const nodes = Array.from(document.querySelectorAll(
                        'p-chip, button, [role="button"], span.p-cursor-pointer'
                    ));
                    const node = nodes.find(candidate =>
                        normalize(candidate.innerText || candidate.textContent) === wanted
                    );
                    if (!node) {
                        result.featured_items[featured] = 'not_found';
                        continue;
                    }
                    const selected = node.getAttribute('aria-pressed') === 'true'
                        || node.getAttribute('aria-selected') === 'true'
                        || node.classList.contains('active')
                        || node.classList.contains('selected');
                    if (!selected) {
                        node.scrollIntoView({block: 'center'});
                        node.click();
                        await sleep(600);
                    }
                    result.featured_items[featured] = selected ? 'already_selected' : 'selected';
                }

                for (const facet of config.facets || []) {
                    const header = findHeader(facet.name);
                    if (!header) {
                        result.facets[facet.name] = {status: 'facet_not_found', selected: []};
                        continue;
                    }
                    const scope = await expand(header);
                    if (!scope) {
                        result.facets[facet.name] = {status: 'scope_not_found', selected: []};
                        continue;
                    }
                    if (facet.search_term) {
                        const searchInput = Array.from(scope.querySelectorAll(
                            'input[type="search"], input[type="text"]'
                        )).find(input => {
                            const hint = normalize(
                                input.placeholder || input.getAttribute('aria-label')
                            );
                            return hint.includes('search') || hint.includes('filter');
                        });
                        if (searchInput) {
                            const setter = Object.getOwnPropertyDescriptor(
                                HTMLInputElement.prototype, 'value'
                            )?.set;
                            setter
                                ? setter.call(searchInput, facet.search_term)
                                : (searchInput.value = facet.search_term);
                            searchInput.dispatchEvent(new Event('input', {bubbles: true}));
                            searchInput.dispatchEvent(new Event('change', {bubbles: true}));
                            await sleep(800);
                        }
                    }
                    const exact = (facet.values || []).map(withoutCount);
                    const prefixes = (facet.prefixes || []).map(withoutCount);
                    const selected = [];
                    const matched = [];
                    const seen = new Set();
                    const labels = Array.from(scope.querySelectorAll(
                        'label, [role="option"], .p-checkbox-label'
                    ));
                    for (const label of labels) {
                        const text = withoutCount(label.innerText || label.textContent);
                        if (!text) continue;
                        const exactMatch = exact.some(value =>
                            text === value
                            || text.startsWith(value + ' ')
                            || value.startsWith(text + ' ')
                        );
                        const prefixMatch = prefixes.some(prefix =>
                            text === prefix || text.startsWith(prefix + ' ')
                        );
                        if (!exactMatch && !prefixMatch) continue;
                        const input = label.matches('[role="checkbox"]')
                            ? label
                            : label.querySelector('input')
                            || (label.htmlFor ? document.getElementById(label.htmlFor) : null)
                            || label.parentElement?.querySelector(
                                'input[type="checkbox"], input[type="radio"], [role="checkbox"]'
                            );
                        const key = input?.id || text;
                        if (seen.has(key)) continue;
                        seen.add(key);
                        matched.push(text);
                        if (!isChecked(input)) {
                            label.scrollIntoView({block: 'nearest'});
                            label.click();
                            selected.push(text);
                        }
                    }
                    if (selected.length) await sleep(700);
                    result.facets[facet.name] = {
                        status: matched.length ? 'applied' : 'option_not_found',
                        requested: facet.values || [],
                        unmatched: (facet.values || []).filter(value => {
                            const wanted = withoutCount(value);
                            return !matched.some(found =>
                                found === wanted
                                || found.startsWith(wanted + ' ')
                                || wanted.startsWith(found + ' ')
                            );
                        }),
                        matched,
                        selected
                    };
                }

                const setInput = (input, value) => {
                    if (!input || value == null) return false;
                    const prototype = input instanceof HTMLSelectElement
                        ? HTMLSelectElement.prototype
                        : HTMLInputElement.prototype;
                    const setter = Object.getOwnPropertyDescriptor(
                        prototype, 'value'
                    )?.set;
                    setter ? setter.call(input, String(value)) : (input.value = String(value));
                    input.dispatchEvent(new Event('input', {bubbles: true}));
                    input.dispatchEvent(new Event('change', {bubbles: true}));
                    input.dispatchEvent(new Event('blur', {bubbles: true}));
                    return true;
                };

                for (const range of config.ranges || []) {
                    const header = findHeader(range.name);
                    if (!header) {
                        result.ranges[range.name] = 'facet_not_found';
                        continue;
                    }
                    const scope = await expand(header);
                    const inputs = Array.from(scope?.querySelectorAll(
                        'input[type="number"], input[type="text"], input[type="date"]'
                    ) || []).filter(input => {
                        const hint = normalize(input.placeholder || input.getAttribute('aria-label'));
                        return input.offsetParent !== null && !hint.includes('search');
                    });
                    let minimumInput = inputs.find(input =>
                        /\b(min|from|start)\b/.test(normalize(
                            (input.placeholder || '') + ' ' + (input.getAttribute('aria-label') || '')
                        ))
                    ) || inputs[0];
                    let maximumInput = inputs.find(input =>
                        /\b(max|to|end)\b/.test(normalize(
                            (input.placeholder || '') + ' ' + (input.getAttribute('aria-label') || '')
                        ))
                    ) || inputs[1];
                    const applied = [];
                    if (setInput(minimumInput, range.minimum)) applied.push('minimum');
                    if (setInput(maximumInput, range.maximum)) applied.push('maximum');
                    if (applied.length) await sleep(700);
                    result.ranges[range.name] = applied.length ? applied : 'inputs_not_found';
                }

                for (const toggle of config.toggles || []) {
                    const wanted = normalize(toggle);
                    const candidates = Array.from(document.querySelectorAll(
                        'label, button, [role="switch"], [role="checkbox"]'
                    ));
                    const node = candidates.find(candidate =>
                        normalize(candidate.innerText || candidate.textContent).includes(wanted)
                    );
                    if (!node) {
                        result.toggles[toggle] = 'not_found';
                        continue;
                    }
                    const input = node.querySelector?.('input') || node;
                    if (!isChecked(input)) {
                        node.scrollIntoView({block: 'center'});
                        node.click();
                        await sleep(500);
                        result.toggles[toggle] = 'selected';
                    } else {
                        result.toggles[toggle] = 'already_selected';
                    }
                }

                if (config.zip_code) {
                    const header = findHeader('Search near ZIP code');
                    const scope = header ? await expand(header) : document;
                    const zipInput = Array.from(scope.querySelectorAll('input')).find(input =>
                        normalize(input.placeholder || input.getAttribute('aria-label')).includes('zip')
                    );
                    const zipApplied = setInput(zipInput, config.zip_code);
                    let radiusApplied = false;
                    if (config.radius_miles != null) {
                        const radius = Array.from(scope.querySelectorAll('select, input')).find(input =>
                            normalize(input.placeholder || input.getAttribute('aria-label') || input.name)
                                .includes('radius')
                        );
                        radiusApplied = setInput(radius, config.radius_miles);
                    }
                    if (zipApplied) await sleep(700);
                    result.proximity = {
                        status: zipApplied ? 'applied' : 'input_not_found',
                        radius_applied: radiusApplied
                    };
                }
                return result;
            }""",
            config,
        )
        self._log(f"Structured filter application: {report}")
        await page.wait_for_timeout(1000)
        return report

    async def initialize_persistent_session(self) -> dict:
        """Open headed Chrome so the user can log in and save the session manually."""
        async with async_playwright() as playwright:
            browser, context = await self._launch_browser_context(
                playwright,
                headless=False,
                force_persistent=True,
            )
            try:
                page = await self._page_for_context(context)
                await page.goto(
                    "https://www.copart.com",
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                await asyncio.to_thread(
                    input,
                    "Complete Copart login and any verification in Chrome, then press Enter here... ",
                )
                cookies = await context.cookies("https://www.copart.com")
                return {
                    "profile_dir": self.profile_dir,
                    "cookies_saved": len(cookies),
                    "current_url": page.url,
                }
            finally:
                await self._close_browser_context(browser, context)

    async def search_and_extract(
        self,
        constraints: VehicleFilterConstraints,
        *,
        scan_additional_pages: bool = True,
        max_source_pages: Optional[int] = None,
    ) -> dict:
        """Searches Copart, applies filters, and extracts vehicle cards with photos and auction dates."""
        all_extracted_items = []

        # State performs more reliably as part of Copart's free-text search
        # than through its dynamic, virtualized Location facet. The extracted
        # yard is still checked locally before any result is returned.
        full_query = self._build_search_query(constraints)

        async with async_playwright() as p:
            browser, context = await self._launch_browser_context(p)
            page = await self._page_for_context(context)
            await self._set_browser_window(page, "minimized")
            await emit_runtime_event(
                "browser_opened",
                {"headless": self.headless},
            )
            verification_signal = asyncio.Event()
            page.on(
                "pageerror",
                lambda error: self._log(f"Page JavaScript error: {error}"),
            )
            page.on(
                "request",
                lambda request: verification_signal.set()
                if "captcha" in request.url.lower()
                else None,
            )
            page.on(
                "requestfailed",
                lambda request: self._log(
                    f"Request failed: {request.url} ({request.failure})"
                ),
            )

            try:
                self._log(f"Navigating to Copart.com (headless={self.headless})...")
                try:
                    await page.goto(
                        "https://www.copart.com",
                        wait_until="domcontentloaded",
                        timeout=25000,
                    )
                except Exception as exc:
                    self._log(f"Initial navigation did not settle: {exc}")
                await page.wait_for_timeout(2500)
                await self._wait_for_human_verification(
                    page,
                    ready_selector="#input-search, input[placeholder*='Search' i]",
                    verification_signal=verification_signal,
                )

                # Auto-dismiss cookie popup if present
                try:
                    cookie_btn = page.locator("#onetrust-accept-btn-handler").first
                    if await cookie_btn.is_visible(timeout=1500):
                        await cookie_btn.click()
                except Exception:
                    pass

                # Locate search input
                search_input = page.locator("#input-search, input[placeholder*='Search' i]").first
                try:
                    await search_input.wait_for(state="visible", timeout=8000)
                except Exception:
                    pass

                query_id = f"{uuid.uuid4()}-{int(time.time() * 1000)}"
                results_url = (
                    "https://www.copart.com/lotSearchResults?free=true"
                    f"&query={quote(full_query)}&qId={query_id}"
                )
                if await search_input.is_visible():
                    verification_signal.clear()
                    self._log(f"Searching: '{full_query}'")
                    await search_input.click()
                    await search_input.fill("")
                    await search_input.press_sequentially(full_query, delay=35)
                    await page.wait_for_timeout(800)

                    search_btn = page.locator(
                        'button[data-track-id="search-icon-button"], '
                        'button.header_magnifying_glass[aria-label="Search"]'
                    ).first
                    if await search_btn.is_visible():
                        await search_btn.click()
                    else:
                        await search_input.press("Enter")
                else:
                    self._log(
                        "Copart homepage search input was unavailable; "
                        "opening the inventory URL directly"
                    )
                    try:
                        await page.goto(
                            results_url,
                            wait_until="domcontentloaded",
                            timeout=25000,
                        )
                    except Exception as exc:
                        self._log(f"Direct results navigation did not settle: {exc}")

                self._log("Waiting for inventory to load...")
                await page.wait_for_timeout(7000)

                initial_rows = await page.locator(
                    'tr[role="row"], tr.p-selectable-row, tbody tr'
                ).count()
                if initial_rows == 0:
                    if "/lotSearchResults" in page.url:
                        self._log("Results page has no rows yet; waiting once more")
                        await page.wait_for_timeout(5000)
                    else:
                        self._log("Search button did not submit; opening Copart results URL")
                        try:
                            await page.goto(
                                results_url,
                                wait_until="domcontentloaded",
                                timeout=25000,
                            )
                        except Exception as exc:
                            self._log(f"Results navigation did not settle: {exc}")
                        await page.wait_for_timeout(7000)

                    initial_rows = await page.locator(
                        'tr[role="row"], tr.p-selectable-row, tbody tr'
                    ).count()
                    if initial_rows == 0:
                        empty_state = page.get_by_text(
                            re.compile(
                                r"no (lots|vehicles|results).*(found|available)",
                                re.IGNORECASE,
                            )
                        ).first
                        has_empty_state = bool(
                            await empty_state.count()
                            and await empty_state.is_visible()
                        )
                        if not has_empty_state:
                            await self._wait_for_human_verification(
                                page,
                                ready_selector='tr[role="row"], tr.p-selectable-row, tbody tr',
                                verification_signal=verification_signal,
                                force=(self.provider == "browserless"),
                            )
                        initial_rows = await page.locator(
                            'tr[role="row"], tr.p-selectable-row, tbody tr'
                        ).count()

                    if initial_rows == 0:
                        empty_state = page.get_by_text(
                            re.compile(
                                r"no (lots|vehicles|results).*(found|available)",
                                re.IGNORECASE,
                            )
                        ).first
                        if await empty_state.count() and await empty_state.is_visible():
                            self._log("Copart returned a valid empty-results page")
                        else:
                            page_title = await page.title()
                            body_text = await page.locator("body").inner_text()
                            self._log(
                                f"Search submission diagnostics: url={page.url!r}, "
                                f"title={page_title!r}, body={body_text[:500]!r}"
                            )
                            raise RuntimeError(
                                "Copart did not load inventory after search submission and URL fallback."
                            )

                filter_application = await self._apply_structured_filters(
                    page,
                    constraints,
                )

                # Scroll for photos
                self._log("Scrolling for vehicle photos...")
                for _ in range(2):
                    await page.mouse.wheel(0, 800)
                    await page.wait_for_timeout(800)

                row_count = await page.locator('tr[role="row"], tr.p-selectable-row, tbody tr').count()
                lot_link_count = await page.locator('a[href*="/lot/"]').count()
                if row_count == 0 and "/lotSearchResults" not in page.url:
                    raise RuntimeError(
                        "Copart search did not navigate to the inventory page; retry the search."
                    )
                if row_count == 0 and "/lotSearchResults" in page.url:
                    empty_state = page.get_by_text(
                        re.compile(r"no (lots|vehicles|results).*(found|available)", re.IGNORECASE)
                    ).first
                    if not await empty_state.count():
                        raise RuntimeError(
                            "Copart results page loaded without inventory rows; retry the search."
                        )
                self._log(
                    f"Inventory DOM at {page.url}: {row_count} table rows, "
                    f"{lot_link_count} lot links"
                )
                next_page = page.locator(
                    'button.p-paginator-next, .p-paginator-next, button[aria-label="Next"]'
                ).first
                if await next_page.count():
                    self._log(
                        f"Paginator next: disabled={await next_page.is_disabled()}, "
                        f"class={await next_page.get_attribute('class')!r}"
                    )
                # Extract vehicle cards. The script is reused after advancing
                # Copart's paginator when the first 50 rows do not contain
                # enough matches for the requested filters.
                extract_script = '''() => {
                    const items = [];
                    const rows = document.querySelectorAll('tr[role="row"], tr.p-selectable-row, tbody tr');

                    for (const row of rows) {
                        const text = row.innerText.trim();
                        if (!text || text.length < 25) continue;

                        const linkEl = row.querySelector('a[href*="/lot/"]') || row.querySelector('a');
                        const link = linkEl ? linkEl.href : "";
                        
                        const imgEl = row.querySelector('img');
                        let imgSrc = "";
                        if (imgEl) {
                            imgSrc = imgEl.src || imgEl.getAttribute('data-src') || "";
                            if (imgSrc.includes('_thb.jpg')) {
                                imgSrc = imgSrc.replace('_thb.jpg', '_ful.jpg');
                            }
                        }

                        const parts = text.split('\\n').map(p => p.trim()).filter(p => p.length > 0);
                        const title = parts[0] || "Unknown Vehicle";

                        const lotNumber = text.match(/Lot\\s*#?\\s*\\|?\\s*(\\d{6,9})/i)?.[1] || "";
                        const titleStatus = text.match(/(Clean Title|Salvage Title|Certificate of Destruction|Non-repairable|Bill of Sale)[^|\\n]*/i)?.[0] || "Not Specified";
                        const damage = text.match(/([\\w\\s\\/]+Damage)/i)?.[0] || "Reported Damage";
                        const rawOdometer = text.match(/(\\d{1,3}(?:,\\d{3})*|\\d+)\\s*\\((?:ACTUAL|EXEMPT|NOT ACTUAL)\\)/i)?.[0] || "";
                        const odometer = rawOdometer.replace(/\\s+/g, ' ');
                        const odometerMiles = rawOdometer
                            ? Number.parseInt((rawOdometer.match(/[\\d,]+/)?.[0] || '').replaceAll(',', ''), 10)
                            : null;
                        const yardLocation = parts.find(
                            p => /^[A-Z]{2}\\s*-\\s*[A-Z][A-Z\\s]+$/.test(p)
                        ) || "US Yard";

                        const buyItNowMatch = text.match(/Buy\\s*it\\s*now\\s*(\\$[\\d,]+(?:\\.\\d{2})?)/i)?.[1] || "";
                        const currentBidMatch = text.match(/Current\\s*bid:?\\s*(\\$[\\d,]+(?:\\.\\d{2})?)/i)?.[1] || "Not available";
                        const saleDateMatch = text.match(/(Today|Tomorrow|[A-Z][a-z]{2}\\s+\\d{1,2},\\s+\\d{4}|Live\\s+Auction|Future\\s+Sale)/i)?.[0] || "Auction Date Pending";

                        if (link && link.includes('/lot/')) {
                            items.push({
                                title: title,
                                lot_number: lotNumber,
                                title_status: titleStatus.trim(),
                                damage: damage.trim(),
                                odometer: odometer.trim(),
                                odometer_miles: Number.isFinite(odometerMiles) ? odometerMiles : null,
                                yard_location: yardLocation.trim(),
                                auction_status: saleDateMatch,
                                buy_it_now_price: buyItNowMatch,
                                current_bid: currentBidMatch,
                                link: link,
                                image_url: imgSrc,
                                raw_text: text
                            });
                        }
                    }
                    return items;
                }'''

                page_items = await page.evaluate(extract_script)

                all_extracted_items.extend(page_items)

                pages_scanned = 1
                max_pages = max(
                    1,
                    max_source_pages
                    if max_source_pages is not None
                    else int(os.getenv("COPART_MAX_SEARCH_PAGES", "10")),
                )
                target_matches = constraints.offset + constraints.max_results + 1
                next_page = page.locator(
                    'button.p-paginator-next, .p-paginator-next, button[aria-label="Next"]'
                ).first
                source_has_more = bool(
                    await next_page.count() and not await next_page.is_disabled()
                )

                while scan_additional_pages and pages_scanned < max_pages:
                    matching_items = self._filter_items(all_extracted_items, constraints)
                    if len(matching_items) >= target_matches:
                        break

                    next_page = page.locator(
                        'button.p-paginator-next, .p-paginator-next, button[aria-label="Next"]'
                    ).first
                    if not await next_page.count() or await next_page.is_disabled():
                        break

                    previous_lots = {
                        item.get("lot_number") or item.get("link")
                        for item in all_extracted_items
                    }
                    await next_page.click()
                    await page.wait_for_timeout(3500)
                    await page.mouse.wheel(0, 800)
                    await page.wait_for_timeout(600)

                    page_items = await page.evaluate(extract_script)
                    new_items = [
                        item for item in page_items
                        if (item.get("lot_number") or item.get("link")) not in previous_lots
                    ]
                    if not new_items:
                        self._log("Paginator did not produce new vehicle rows; stopping")
                        break

                    all_extracted_items.extend(new_items)
                    pages_scanned += 1
                    self._log(
                        f"Scanned inventory page {pages_scanned}: "
                        f"{len(all_extracted_items)} unique vehicles"
                    )
                    await emit_runtime_event(
                        "search_progress",
                        {
                            "pages_scanned": pages_scanned,
                            "source_records": len(all_extracted_items),
                        },
                    )

                next_page = page.locator(
                    'button.p-paginator-next, .p-paginator-next, button[aria-label="Next"]'
                ).first
                source_has_more = bool(
                    await next_page.count() and not await next_page.is_disabled()
                )

                source_count_scanned = len(all_extracted_items)
                all_extracted_items = self._filter_items(all_extracted_items, constraints)

                final_slice = [
                    {
                        key: value
                        for key, value in item.items()
                        if key != "raw_text"
                    }
                    for item in all_extracted_items[
                        constraints.offset : constraints.offset + constraints.max_results
                    ]
                ]

            except Exception as e:
                self._log(f"Error during extraction: {str(e)}")
                raise
            finally:
                await self._close_browser_context(browser, context)

        return {
            "query": constraints.query,
            "applied_constraints": constraints.model_dump(exclude_none=True),
            "count_returned": len(final_slice),
            "has_more": len(all_extracted_items) > (constraints.offset + constraints.max_results),
            "matching_count_scanned": len(all_extracted_items),
            "source_count_scanned": source_count_scanned,
            "pages_scanned": pages_scanned,
            "source_has_more": source_has_more,
            "filter_application": filter_application,
            "vehicles": final_slice
        }

    async def get_vehicle_details(self, lot_id_or_url: str) -> dict:
        """Deep-dive vehicle inspection for full HD gallery, VIN, condition, and auction dates."""
        lot_id_or_url = lot_id_or_url.strip()
        if lot_id_or_url.isdigit():
            if not 6 <= len(lot_id_or_url) <= 10:
                raise ValueError("Copart lot number must contain 6 to 10 digits")
            target_url = f"https://www.copart.com/lot/{lot_id_or_url}"
        else:
            parsed = urlparse(lot_id_or_url)
            hostname = (parsed.hostname or "").lower()
            if (
                parsed.scheme not in {"http", "https"}
                or not (hostname == "copart.com" or hostname.endswith(".copart.com"))
                or "/lot/" not in parsed.path.lower()
            ):
                raise ValueError("Vehicle details only accepts a Copart lot number or Copart lot URL")
            target_url = lot_id_or_url

        async with async_playwright() as p:
            browser, context = await self._launch_browser_context(p)
            page = await self._page_for_context(context)
            await self._set_browser_window(page, "minimized")
            await emit_runtime_event(
                "browser_opened",
                {"headless": self.headless, "purpose": "vehicle_details"},
            )
            verification_signal = asyncio.Event()
            page.on(
                "request",
                lambda request: verification_signal.set()
                if "captcha" in request.url.lower()
                else None,
            )

            try:
                self._log(f"Inspecting vehicle lot: {target_url} (headless={self.headless})")
                try:
                    await page.goto(
                        target_url,
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )
                except Exception as exc:
                    self._log(f"Lot navigation did not settle: {exc}")
                await page.wait_for_timeout(6000)
                await self._wait_for_human_verification(
                    page,
                    ready_selector='img[src*="cs.copart.com"]',
                    verification_signal=verification_signal,
                )

                page_title = await page.title()

                photos = await page.evaluate(r'''() => {
                    const candidates = [];
                    const socialImage = document.querySelector(
                        'meta[property="og:image"], meta[name="twitter:image"]'
                    )?.content;
                    if (socialImage) candidates.push(socialImage);

                    for (const image of document.querySelectorAll('img')) {
                        candidates.push(
                            image.currentSrc,
                            image.src,
                            image.getAttribute('data-src'),
                            image.getAttribute('data-lazy-src')
                        );
                        const srcset = image.getAttribute('srcset') || image.getAttribute('data-srcset');
                        if (srcset) {
                            for (const entry of srcset.split(',')) {
                                candidates.push(entry.trim().split(/\s+/)[0]);
                            }
                        }
                    }
                    for (const source of document.querySelectorAll('source[srcset]')) {
                        for (const entry of source.srcset.split(',')) {
                            candidates.push(entry.trim().split(/\s+/)[0]);
                        }
                    }

                    const fullRes = candidates
                        .filter(Boolean)
                        .filter(url => url.includes('cs.copart.com'))
                        .map(url => url.replace('_thb.jpg', '_ful.jpg'));
                    return Array.from(new Set(fullRes));
                }''')

                raw_text = await page.evaluate("() => document.body.innerText")
                vin_match = re.search(r'VIN:?\s*([A-HJ-NPR-Z0-9*]{11,17})', raw_text, re.IGNORECASE)
                vin = vin_match.group(1) if vin_match else "Available on Lot Page"

                title_parts = [p.strip() for p in page_title.split("|")]
                vehicle_title = title_parts[0] if len(title_parts) > 0 else "Unknown Vehicle"
                condition = title_parts[1] if len(title_parts) > 1 else "Condition Not Specified"
                auction_date = title_parts[2] if len(title_parts) > 2 else "Auction Date Pending"
                location = title_parts[3] if len(title_parts) > 3 else "US Yard"

                gallery_photos = photos
                primary_image_url = gallery_photos[0] if gallery_photos else ""
                details = {
                    "lot_url": page.url,
                    "vehicle_title": vehicle_title,
                    "vin": vin,
                    "condition": condition,
                    "auction_date": auction_date,
                    "yard_location": location,
                    "photo_count": len(photos),
                    "primary_image_url": primary_image_url,
                    "gallery_photos": gallery_photos,
                    "image_loading": {
                        "eager": [primary_image_url] if primary_image_url else [],
                        "lazy": gallery_photos[1:] if primary_image_url else gallery_photos,
                    },
                }

            except Exception as e:
                self._log(f"Error inspecting lot: {str(e)}")
                raise
            finally:
                await self._close_browser_context(browser, context)

        return details

