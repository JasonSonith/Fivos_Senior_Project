import asyncio
import time
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List

from playwright.async_api import async_playwright, TimeoutError as PWTimeoutError


@dataclass
class FetchResult:
    url: str
    ok: bool
    status: Optional[int] = None
    final_url: Optional[str] = None
    html: Optional[str] = None
    error: Optional[str] = None
    attempts: int = 0
    elapsed_ms: Optional[int] = None


class AsyncRateLimiter:
    """
    Simple global rate limiter: ensures at least `delay_s` between *starts* of requests.
    Good enough for a project; you can upgrade to per-domain later.
    """
    def __init__(self, delay_s: float = 2.0):
        self.delay_s = delay_s
        self._lock = asyncio.Lock()
        self._last_ts = 0.0

    async def wait(self):
        async with self._lock:
            now = time.monotonic()
            wait_for = self.delay_s - (now - self._last_ts)
            if wait_for > 0:
                await asyncio.sleep(wait_for)
            self._last_ts = time.monotonic()


class BrowserEngine:
    def __init__(
        self,
        *,
        max_concurrency: int = 5,
        page_timeout_ms: int = 30_000,
        retries: int = 3,
        retry_delay_s: float = 5.0,
        rate_limit_delay_s: float = 2.0,
        user_agent: Optional[str] = None,
        headless: bool = True,
    ):
        self.max_concurrency = max_concurrency
        self.page_timeout_ms = page_timeout_ms
        self.retries = retries
        self.retry_delay_s = retry_delay_s
        self.rate_limiter = AsyncRateLimiter(rate_limit_delay_s)
        self.user_agent = user_agent
        self.headless = headless

        self._sem = asyncio.Semaphore(max_concurrency)
        self._playwright = None
        self._browser = None

    async def __aenter__(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def fetch(self, url: str) -> FetchResult:
        """
        Public method with concurrency limit + retry logic.
        """
        async with self._sem:
            await self.rate_limiter.wait()
            return await self._fetch_with_retries(url)

    async def _fetch_with_retries(self, url: str) -> FetchResult:
        start = time.monotonic()

        last_err = None
        for attempt in range(1, self.retries + 1):
            try:
                result = await self._fetch_once(url)
                result.attempts = attempt
                result.elapsed_ms = int((time.monotonic() - start) * 1000)
                return result
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
                # log attempt failure
                print(f"[WARN] attempt {attempt}/{self.retries} failed for {url}: {last_err}")

                if attempt < self.retries:
                    await asyncio.sleep(self.retry_delay_s)

        # all failed
        return FetchResult(
            url=url,
            ok=False,
            error=last_err or "Unknown error",
            attempts=self.retries,
            elapsed_ms=int((time.monotonic() - start) * 1000),
        )

    async def _fetch_once(self, url: str) -> FetchResult:
        """
        Single attempt: open isolated context/page, navigate, wait for JS, return HTML.
        """
        context_kwargs: Dict[str, Any] = {}
        if self.user_agent:
            context_kwargs["user_agent"] = self.user_agent

        context = await self._browser.new_context(**context_kwargs)
        page = await context.new_page()
        page.set_default_navigation_timeout(self.page_timeout_ms)
        page.set_default_timeout(self.page_timeout_ms)

        try:
            # Navigate and wait for DOM content to load quickly
            resp = await page.goto(url, wait_until="domcontentloaded")

            status = resp.status if resp else None
            final_url = page.url

            # Wait for JS-heavy content. Options:
            # - "networkidle" can hang on some sites, so we use it with timeout protection.
            try:
                await page.wait_for_load_state("networkidle", timeout=self.page_timeout_ms)
            except PWTimeoutError:
                # Not fatal: many pages never become "idle" due to long polling/ads.
                pass

            html = await page.content()

            ok = (status is not None and 200 <= status < 400)
            return FetchResult(
                url=url,
                ok=ok,
                status=status,
                final_url=final_url,
                html=html,
                error=None if ok else f"Non-OK HTTP status: {status}",
            )

        except PWTimeoutError as e:
            raise TimeoutError(f"Page load exceeded {self.page_timeout_ms}ms") from e
        finally:
            await page.close()
            await context.close()


async def main():
    urls = [
        "https://www.medtronic.com/en-us/healthcare-professionals/products/cardiovascular/peripheral-drug-coated-balloons/inpact-admiral-drug-coated-balloon.html",
        "https://www.goremedical.com/products/vbx/specifications",
        "https://www.goremedical.com/products/viabahn/specifications",
        "https://www.bostonscientific.com/content/dam/bostonscientific/pi/product-catalog/PI_Product_Catalog.pdf",
        "https://www.cookmedical.com/products/224e3666-308f-4244-8695-6fd23bbd671c/",
        "https://shockwavemedical.com/en-eu/products/shockwave-m5-plus/",
        "https://www.medtronic.com/en-us/healthcare-professionals/products/cardiovascular/peripheral-biliary-stents/protege-everflex-self-expanding-biliary-stent-system.html",
        "https://www.medtronic.com/en-us/healthcare-professionals/products/cardiovascular/directional-atherectomy-systems/hawkone-directional-atherectomy-system.html",
        "https://www.cardiovascular.abbott/us/en/hcp/products/peripheral-intervention/atherectomy-systems/diamondback-360/ordering-information.html",
        "https://www.cardiovascular.abbott/us/en/hcp/products/peripheral-intervention/peripheral-stents/omnilink-elite-vascular/ordering-information.html",
        "https://www.cardiovascular.abbott/us/en/hcp/products/peripheral-intervention/peripheral-stents/absolute-pro-vascular/ordering-information.html",
        "https://www.medtronic.com/en-us/healthcare-professionals/products/cardiovascular/peripheral-biliary-stents/everflex-stent-system-with-entrust.html",
        "https://www.medtronic.com/en-us/healthcare-professionals/products/cardiovascular/peripheral-biliary-stents/visi-pro-balloon-expandable-peripheral-stent-system.html",
        "https://www.cardiovascular.abbott/us/en/hcp/products/peripheral-intervention/supera-stent-system/ordering.html",
        "https://cordis.com/na/products/intervene/endovascular/self-expanding-stents/s-m-a-r-t-control-vascular-stent-system",
        "https://shockwavemedical.com/products/shockwave-e8/",
        "https://www.medtronic.com/en-us/healthcare-professionals/products/cardiovascular/peripheral-biliary-stents/protege-gps-self-expanding-peripheral-biliary-stent-system.html",
        "https://shockwavemedical.com/wp-content/uploads/2024/11/S4-Tech-Sheet-Global-SPL-66024-Rev.-B.pdf",
        "https://www.cookmedical.com/products/esc_zilbs635/",
        "https://www.terumois.com/products/stents/r2p-misago2.html",
        "https://www.medtronic.com/en-us/healthcare-professionals/products/cardiovascular/peripheral-drug-coated-balloons/inpact-av-drug-coated-balloon.html",
        "https://shockwavemedical.com/products/shockwave-l6/",
        "https://www.medtronic.com/en-us/healthcare-professionals/products/cardiovascular/coronary-stents/resolute-onyx-drug-eluting-stent.html",
        "https://www.cookmedical.com/products/di_ziv_webds/",
        "https://www.medtronic.com/en-us/healthcare-professionals/products/cardiovascular/directional-atherectomy-systems/silverhawk-peripheral-plaque-excision-system.html",
        "https://www.cardiovascular.abbott/us/en/hcp/products/peripheral-intervention/esprit-btk-resorbable-scaffold-system.html",
        "https://cordis.com/apac/products/intervene/endovascular/balloon-expandble-stents/palmaz-genesis-peripheral-stent",
        "https://www.cardiovascular.abbott/us/en/hcp/products/percutaneous-coronary-intervention/xience-family/xience-skypoint/ordering-information-extra-large.html",
        "https://www.cookmedical.com/products/cf1fddb1-9f10-4002-b9a5-3f4c83c28cbc/",
        "https://www.medtronic.com/en-us/healthcare-professionals/products/cardiovascular/directional-atherectomy-systems/turbohawk-peripheral-plaque-excision-system.html"
    ]

    async with BrowserEngine(
        max_concurrency=3,
        page_timeout_ms=30_000,
        retries=3,
        retry_delay_s=5.0,
        rate_limit_delay_s=2.0,
        headless=True,
    ) as engine:
        results: List[FetchResult] = await asyncio.gather(*(engine.fetch(u) for u in urls))

    for r in results:
        print(asdict(r))
        # This is what you'd pass to Jason's extractor:
        # if r.ok: extractor.extract(r.html)

if __name__ == "__main__":
    asyncio.run(main())
