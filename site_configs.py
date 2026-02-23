SITE_CONFIGS = {
    "usaridetoday": {
        "api_url": "https://www.usaridetoday.com/inventory/search",
        "listings_url": "https://www.usaridetoday.com/cars-for-sale?PageNumber=2&Sort=MakeAsc&StockNumber=&Condition=&BodyStyle=&Make=&MaxPrice=&Mileage=&SoldStatus=AllVehicles&StockNumber=",
        "preflight_url": "https://www.usaridetoday.com/cars-for-sale?PageNumber=2&Sort=MakeAsc&StockNumber=&Condition=&BodyStyle=&Make=&MaxPrice=&Mileage=&SoldStatus=AllVehicles&StockNumber=",
        "max_pages": 10,
        "request_timeout": 15,
        "headers": {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/144.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://www.usaridetoday.com",
            "Referer": "https://www.usaridetoday.com/cars-for-sale?PageNumber=2&Sort=MakeAsc&StockNumber=&Condition=&BodyStyle=&Make=&MaxPrice=&Mileage=&SoldStatus=AllVehicles&StockNumber=",
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Sec-CH-UA": '"Not(A:Brand";v="8", "Chromium";v="144", "Google Chrome";v="144"',
            "Sec-CH-UA-Arch": '"arm"',
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Model": '""',
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
        "preflight_url": "https://www.metacarstx.com/inventory/?page_no=1",
        "preflight_url_builder": lambda page: f"https://www.metacarstx.com/inventory/?page_no={page}",
        "scraper_engine": "playwright",
        "request_method": "GET",
        "max_pages": 5,
        "request_timeout": 20,
        "headers": {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/144.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
            "Referer": "https://www.metacarstx.com/inventory/",
            "Sec-CH-UA": '"Not(A:Brand";v="8", "Chromium";v="144", "Google Chrome";v="144"',
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": '"macOS"',
            "Sec-Fetch-Dest": "script",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "same-origin",
        },
        "fallback_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/144.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
            "Referer": "https://www.metacarstx.com/inventory/",
        },
        "query_params_builder": lambda page: {
            "vc": "a",
            "f": "id|sn|ye|ma|mo|tr|dt|ta|td|en|mi|dr|ec|ic|bt|pr|im|eq|vd|vin|hpg|cpg|vc|co|hi|cfx|acr|vt|cy|di|ft|lo|cfk|tb|cs|nos|sc|fp|cohd|asp|nop|vdf|ffmi|cfd|dc|ws",
            "ps": 10,
            "pn": max(page - 1, 0),
            "sb": "pr|d",
            "sp": "n",
            "cb": "dws_inventory_listing_4",
            "dcid": "18275840",
            "h": "526c06589bb95f25ca5d6e6b41e149b5",
        },
        "parser": "metacarstx_json",
    },
}
