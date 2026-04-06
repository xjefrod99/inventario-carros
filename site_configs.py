import random

SITE_CONFIGS = {
    "usaridetoday": {
        "api_url": "https://www.usaridetoday.com/inventory/search",
        "listings_url": "https://www.usaridetoday.com/cars-for-sale",
        "preflight_url": "https://www.usaridetoday.com/cars-for-sale",
        "preflight_url_builder": lambda page: (
            f"https://www.usaridetoday.com/cars-for-sale"
            f"?PageNumber={page}&Sort=MakeAsc&StockNumber=&Condition=&BodyStyle="
            f"&Make=&MaxPrice=&Mileage=&SoldStatus=AvailableVehicles"
        ),
        "scraper_engine": "playwright",
        "allow_requests_fallback": False,
        "use_preflight": False,
        "warmup_urls": [
            "https://www.usaridetoday.com/cars-for-sale",
        ],
        "preflight_headers":
        {
            ":authority": "www.usaridetoday.com",
            ":method": "GET",
            ":path": "/cars-for-sale",
            ":scheme": "https",
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "accept-encoding": "gzip, deflate, br, zstd",
            "priority": "u=0, i",
            "referer": "https://www.usaridetoday.com/",
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "same-origin",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
        },
        "max_pages": 8,
        "request_timeout": 15,
        "headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/146.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://www.usaridetoday.com",
            "Referer": "https://www.usaridetoday.com/cars-for-sale",
            "X-Requested-With": "XMLHttpRequest"
        },
        "pagination_payload_builder": lambda page: {
            "PageNumber": page,
            "SoldStatus": "AvailableVehicles",
            "Sort": "MakeAsc",
            "StockNumber": "",
            "Condition": "",
            "BodyStyle": "",
            "Make": "",
            "MaxPrice": "",
            "Mileage": "",
        },
        "parser": "usaridetoday_ldjson",
    },
    "metacarstx": {
        "api_url": "https://www.metacarstx.com/inv-scripts-v2/inv/vehicles",
        "listings_url": "https://www.metacarstx.com/inventory/",
        "preflight_url": "https://www.metacarstx.com/inventory/?pager=25&page_no=1",
        "preflight_url_builder": lambda page: f"https://www.metacarstx.com/inventory/?pager=25&page_no={page}",
        "scraper_engine": "playwright",
        "request_method": "GET",
        "max_pages": 3,
        "request_timeout": 20,
        "headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/146.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
            "Referer": "https://www.metacarstx.com/inventory/",
        },
        "parser": "metacarstx_json",
    },
    "afccars": {
        "api_url": "https://www.afccars.com/index.php",
        "listings_url": "https://www.afccars.com/inventory?locations=|HOUSTON_8712",
        "preflight_url": "https://www.afccars.com/inventory?locations=|HOUSTON_8712",
        "scraper_engine": "requests",
        "request_method": "POST",
        "use_preflight": True,
        "parse_preflight": True,
        "max_pages": 3,
        "request_timeout": 15,
        "headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/146.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": "https://www.afccars.com/inventory?locations=|HOUSTON_8712",
            "Origin": "https://www.afccars.com",
            "X-Requested-With": "XMLHttpRequest",
        },
        "pagination_payload_builder": lambda page: {
            "fromAjax": "y",
            "sid": str(random.random()),
            "doWhat": "inventorySearch",
            "func": "getNextPage",
        },
        "parser": "afccars_ldjson",
    },
    "astroautoworld": {
        "api_url": "https://www.astroautoworld.com/inventory/search",
        "listings_url": "https://www.astroautoworld.com/cars-for-sale",
        "preflight_url": "https://www.astroautoworld.com/cars-for-sale",
        "preflight_url_builder": lambda page: (
            "https://www.astroautoworld.com/cars-for-sale?PageSize=25"
            if page == 1 else
            f"https://www.astroautoworld.com/cars-for-sale"
            f"?PageNumber={page}&Sort=MakeAsc&StockNumber=&Condition=&BodyStyle="
            f"&Make=&MaxPrice=&Mileage=&SoldStatus=AvailableVehicles&StockNumber="
        ),
        "scraper_engine": "playwright",
        "persistent_browser": True,
        "allow_requests_fallback": False,
        "use_preflight": False,
        "warmup_urls": [
            "https://www.astroautoworld.com/cars-for-sale",
        ],
        "max_pages": 8,
        "request_timeout": 15,
        "headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/146.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://www.astroautoworld.com",
            "Referer": "https://www.astroautoworld.com/cars-for-sale",
            "X-Requested-With": "XMLHttpRequest",
        },
        "pagination_payload_builder": lambda page: {
            "PageNumber": page,
            "SoldStatus": "AvailableVehicles",
            "Sort": "MakeAsc",
            "StockNumber": "",
            "Condition": "",
            "BodyStyle": "",
            "Make": "",
            "MaxPrice": "",
            "Mileage": "",
        },
        "parser": "usaridetoday_ldjson",
    },
}