from app.services.storage_service import save_raw_records
from harvester.src.web_scraper.scraper import fetch_page_html

async def run_scraper_job(manufacturer: str, url: str):
    result = await fetch_page_html(url)

    if not result.ok:
        return {
            "success": False,
            "error": result.error,
            "records": []
        }

    # temporary placeholder records
    records = [
        {
            "manufacturer": manufacturer,
            "source_url": result.final_url or url,
            "device_name": "Sample Device A",
            "outer_diameter": "2.5 cm",
            "weight": "0.5 kg",
            "volume": "1.2 l"
        },
        {
            "manufacturer": manufacturer,
            "source_url": result.final_url or url,
            "device_name": "Sample Device B",
            "outer_diameter": "4 in",
            "weight": "16 oz",
            "volume": "500 ml"
        }
    ]

    save_raw_records(records)

    return {
        "success": True,
        "error": None,
        "records": records,
        "status": result.status,
        "attempts": result.attempts,
        "elapsed_ms": result.elapsed_ms,
    }