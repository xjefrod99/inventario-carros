import asyncio
import json
import importlib
import os
import random
import re
import sys
import threading
import time
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup
import requests
import streamlit as st

from database import build_unique_key
from site_configs import SITE_CONFIGS


def _build_text_from_response(cleaned_text: str):
    """Return HTML/text payload even if response is JSON-wrapped."""
    try:
        parsed = json.loads(cleaned_text)
    except Exception:
        return cleaned_text

    if isinstance(parsed, str):
        return parsed

    if isinstance(parsed, dict):
        for key in ["propiedades", "html", "results", "content", "data"]:
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return value

    return cleaned_text


def _extract_vehicles_from_ldjson(text_payload: str):
    soup = BeautifulSoup(text_payload, "html.parser")
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})

    vehicles = []

    def collect_vehicles(item):
        if isinstance(item, dict):
            item_type = item.get("@type")
            if item_type == "Vehicle" or (isinstance(item_type, list) and "Vehicle" in item_type):
                vehicles.append(item)

            graph = item.get("@graph")
            if isinstance(graph, list):
                for sub in graph:
                    collect_vehicles(sub)

        elif isinstance(item, list):
            for sub in item:
                collect_vehicles(sub)

    for script in scripts:
        raw = script.string or script.get_text(strip=True)
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except Exception:
            continue

        # Collect Vehicle objects from this script tag
        before = len(vehicles)
        collect_vehicles(parsed)
        newly_added = vehicles[before:]

        if not newly_added:
            continue

        # The <script> appears immediately before its <li class="vehicle-snapshot">
        # sibling in the page HTML.  Walk forward through siblings until we find it.
        snapshot_li = None
        sibling = script.next_sibling
        while sibling is not None:
            if getattr(sibling, "name", None) == "li":
                if "vehicle-snapshot" in (sibling.get("class") or []):
                    snapshot_li = sibling
                break
            sibling = sibling.next_sibling

        miles_from_html = None
        detail_url = None

        if snapshot_li is not None:
            # Extract mileage from the labelled info-item div
            for info_item in snapshot_li.find_all("div", class_="vehicle-snapshot__main-info-item"):
                label_div = info_item.find("div", class_="vehicle-snapshot__label")
                value_div = info_item.find("div", class_="vehicle-snapshot__main-info")
                if label_div and value_div:
                    if "mileage" in label_div.get_text(strip=True).lower():
                        raw_miles = value_div.get_text(strip=True).replace(",", "").strip()
                        miles_from_html = _to_float(raw_miles) if raw_miles else None
                        break

            # Extract the detail-page href from the title link
            title_link = snapshot_li.find("a", attrs={"data-trackingid": "search-vehicle-title"})
            if title_link and title_link.get("href"):
                detail_url = title_link["href"]

        # Inject into each vehicle dict so existing field lookup still works
        for v in newly_added:
            if not v.get("mileageFromOdometer") and miles_from_html is not None:
                v["mileageFromOdometer"] = miles_from_html
            if detail_url and not v.get("detail_url"):
                v["detail_url"] = detail_url

            # Detect SOLD status from the price display in the HTML snapshot
            if snapshot_li is not None and not v.get("_is_sold"):
                for info_item in snapshot_li.find_all("div", class_="vehicle-snapshot__main-info-item"):
                    label_div = info_item.find("div", class_="vehicle-snapshot__label")
                    value_div = info_item.find("div", class_="vehicle-snapshot__main-info")
                    if label_div and value_div:
                        if "price" in label_div.get_text(strip=True).lower():
                            price_text = value_div.get_text(strip=True).upper()
                            if "SOLD" in price_text:
                                v["_is_sold"] = True
                            break

    return vehicles


def _extract_metacarstx_rows(cleaned_text: str):
    payload = cleaned_text.strip()

    if payload.endswith(");") and "(" in payload:
        start = payload.find("(")
        end = payload.rfind(")")
        if start != -1 and end != -1 and end > start:
            payload = payload[start + 1 : end]

    try:
        data = json.loads(payload)
    except Exception:
        return []

    if isinstance(data, dict):
        direct_vehicles = data.get("Vehicles")
        if isinstance(direct_vehicles, list):
            return direct_vehicles

    candidate_lists = []

    def walk(obj):
        if isinstance(obj, list):
            if obj and isinstance(obj[0], dict):
                candidate_lists.append(obj)
            for item in obj:
                walk(item)
        elif isinstance(obj, dict):
            for value in obj.values():
                walk(value)

    walk(data)

    for rows in candidate_lists:
        sample = rows[0] if rows else {}
        if any(
            key in sample
            for key in [
                "ma",
                "mo",
                "ye",
                "pr",
                "vin",
                "sn",
                "VehicleYear",
                "VehicleMake",
                "VehicleModel",
                "Price",
                "VIN",
                "StockNumber",
            ]
        ):
            return rows

    return []


def _to_float(value):
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return float(value)
        cleaned = re.sub(r"[^0-9.]", "", str(value))
        return float(cleaned) if cleaned else None
    except Exception:
        return None


def _extract_metacarstx_runtime_params(preflight_html: str, base_url: str):
    """Extract dynamic query params from metacarstx inventory script src."""
    if not preflight_html:
        return {}

    soup = BeautifulSoup(preflight_html, "html.parser")
    script_tags = soup.find_all("script", src=True)

    for tag in script_tags:
        src = tag.get("src", "")
        if "/inv-scripts-v2/inv/vehicles" not in src:
            continue

        full_src = urljoin(base_url, src)
        parsed = urlparse(full_src)
        query_map = parse_qs(parsed.query)
        flat = {key: values[-1] for key, values in query_map.items() if values}
        if flat:
            return flat

    return {}


def _vehicle_from_ldjson(vehiculo, inventario_url):
    """Map one LD+JSON Vehicle object to a standard record dict, or None if missing title."""
    title = vehiculo.get("name")
    if not title:
        return None

    if vehiculo.get("_is_sold"):
        return None

    year = vehiculo.get("vehicleModelDate")
    modelo = vehiculo.get("model") or ""
    manufacturer = vehiculo.get("manufacturer")
    marca = manufacturer.get("name", "") if isinstance(manufacturer, dict) else (manufacturer or "")

    offers = vehiculo.get("offers") if isinstance(vehiculo.get("offers"), dict) else {}
    price_value = offers.get("price")

    mileage_data = vehiculo.get("mileageFromOdometer")
    miles_value = mileage_data.get("value") if isinstance(mileage_data, dict) else mileage_data
    miles = _to_float(miles_value)

    detail_url = vehiculo.get("detail_url")
    if detail_url and inventario_url:
        detail_url = urljoin(inventario_url, detail_url)
    url = vehiculo.get("url") or detail_url or inventario_url
    return {
        "title": title,
        "description": f"Price: {price_value} | Link: {url}",
        "source_url": url,
        "unique_key": build_unique_key(title, f"{year or ''}-{modelo}", url),
        "year": str(year) if year is not None else "",
        "modelo": modelo,
        "miles": int(miles) if miles is not None else None,
        "marca": marca,
        "precio_actual": price_value,
    }


def _vehicle_from_metacarstx(fila, inventario_url):
    """Map one metacarstx row dict to a standard record dict, or None if missing title."""
    year = fila.get("ye") or fila.get("VehicleYear") or fila.get("Year")
    marca = fila.get("ma") or fila.get("VehicleMake") or fila.get("Make") or ""
    modelo = fila.get("mo") or fila.get("VehicleModel") or fila.get("Model") or ""
    stock_no = fila.get("sn") or fila.get("StockNumber") or ""
    vin = fila.get("vin") or fila.get("VIN") or fila.get("Vin") or ""
    price_value = _to_float(
        fila.get("pr")
        or fila.get("Price")
        or fila.get("SalePrice")
        or fila.get("VehiclePrice")
        or fila.get("AskingPrice")
    )
    miles_value = _to_float(
        fila.get("mi")
        or fila.get("Odometer")
        or fila.get("Mileage")
    )

    # Build detail URL: https://www.metacarstx.com/inventory/{make}/{model}/{StockNumber}/
    detail_url = fila.get("vd") or fila.get("DetailsUrl") or fila.get("VehicleDetailsUrl")
    if not detail_url and marca and modelo and stock_no:
        model_slug = modelo.replace(" ", "-").lower()
        make_slug = marca.lower()
        detail_url = f"https://www.metacarstx.com/inventory/{make_slug}/{model_slug}/{stock_no}/"
    if not detail_url:
        detail_url = inventario_url

    title = fila.get("ta") or fila.get("Title") or f"{year or ''} {marca} {modelo}".strip()
    if not title:
        return None

    return {
        "title": title,
        "description": f"Price: {price_value if price_value is not None else ''} | Link: {detail_url}",
        "source_url": detail_url,
        "unique_key": build_unique_key(title, vin or stock_no, detail_url),
        "year": str(year) if year is not None else "",
        "modelo": modelo,
        "miles": int(miles_value) if miles_value is not None else None,
        "marca": marca,
        "precio_actual": price_value,
    }


def _vehicle_from_afccars_ldjson(vehiculo, inventario_url):
    """Map one afccars LD+JSON Vehicle object to a standard record dict."""
    title = vehiculo.get("name")
    if not title:
        return None

    year = vehiculo.get("releaseDate")
    marca = vehiculo.get("brand") or ""
    modelo = vehiculo.get("model") or ""
    sku = vehiculo.get("sku") or vehiculo.get("productID") or ""
    vin = vehiculo.get("vehicleIdentificationNumber") or ""

    offers = vehiculo.get("offers") if isinstance(vehiculo.get("offers"), dict) else {}
    price_value = _to_float(offers.get("price"))

    mileage_raw = vehiculo.get("mileageFromOdometer")
    miles_value = mileage_raw.get("value") if isinstance(mileage_raw, dict) else mileage_raw
    miles = _to_float(miles_value)

    detail_url = f"https://www.afccars.com/VehicleDetails/8712/{sku}" if sku else inventario_url

    return {
        "title": title,
        "description": f"Price: {price_value if price_value is not None else ''} | Link: {detail_url}",
        "source_url": detail_url,
        "unique_key": build_unique_key(title, vin or sku, detail_url),
        "year": str(year) if year is not None else "",
        "modelo": modelo,
        "miles": int(miles) if miles is not None else None,
        "marca": marca,
        "precio_actual": price_value,
    }


def _parse_page(parser_name, cleaned_text, inventario_url, page_num):
    """Parse one page of scrape results; returns a list of standard vehicle record dicts."""
    records = []

    if parser_name == "usaridetoday_ldjson":
        text_payload = _build_text_from_response(cleaned_text)
        vehiculos = _extract_vehicles_from_ldjson(text_payload)
        print(f"✅ Page {page_num}: found {len(vehiculos)} Vehicle objects in ld+json")
        for idx, vehiculo in enumerate(vehiculos, start=1):
            record = _vehicle_from_ldjson(vehiculo, inventario_url)
            if not record:
                continue
            records.append(record)
            print(
                f"🚗 Page {page_num} Vehicle {idx}: "
                f"titulo={record['title']!r}, year={record['year']!r}, "
                f"marca={record['marca']!r}, modelo={record['modelo']!r}, precio={record['precio_actual']!r}"
            )

    elif parser_name == "metacarstx_json":
        filas = _extract_metacarstx_rows(cleaned_text)
        print(f"✅ Page {page_num}: found {len(filas)} metacarstx rows")
        for idx, fila in enumerate(filas, start=1):
            record = _vehicle_from_metacarstx(fila, inventario_url)
            if not record:
                continue
            records.append(record)
            print(
                f"🚙 Page {page_num} Row {idx}: "
                f"titulo={record['title']!r}, year={record['year']!r}, "
                f"marca={record['marca']!r}, modelo={record['modelo']!r}, precio={record['precio_actual']!r}"
            )

    elif parser_name == "afccars_ldjson":
        vehiculos = _extract_vehicles_from_ldjson(cleaned_text)
        print(f"✅ Page {page_num}: found {len(vehiculos)} Vehicle objects in ld+json")
        for idx, vehiculo in enumerate(vehiculos, start=1):
            record = _vehicle_from_afccars_ldjson(vehiculo, inventario_url)
            if not record:
                continue
            records.append(record)
            print(
                f"🚗 Page {page_num} Vehicle {idx}: "
                f"titulo={record['title']!r}, year={record['year']!r}, "
                f"marca={record['marca']!r}, modelo={record['modelo']!r}, precio={record['precio_actual']!r}"
            )

    print(f"✅ Page {page_num}: {len(records)} records collected")
    return records


def _prepare_preflight_headers(configured_headers, request_headers_base, target_preflight_url):
    headers = {
        "User-Agent": request_headers_base.get("User-Agent", "Mozilla/5.0"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": request_headers_base.get("Accept-Language", "en-US,en;q=0.9"),
        "Referer": request_headers_base.get("Referer", target_preflight_url),
    }

    ignored_headers = []
    for key, value in (configured_headers or {}).items():
        if value in (None, ""):
            continue
        if key.startswith(":"):
            ignored_headers.append(key)
            continue
        headers[key] = value

    if not headers.get("Referer"):
        headers["Referer"] = target_preflight_url

    return headers, ignored_headers


def _log_preflight_diagnostics(debug, response, sent_headers, ignored_headers, session_cookies):
    debug(
        "preflight request headers claves=" + ",".join(sorted(sent_headers.keys()))
    )
    if ignored_headers:
        debug(
            "preflight headers ignorados por requests=" + ",".join(sorted(ignored_headers))
        )

    debug(
        "preflight response "
        f"status={response.status_code} "
        f"final_url={response.url} "
        f"history={len(response.history)} "
        f"bytes={len(response.text or '')}"
    )

    response_header_subset = {}
    for key in [
        "content-type",
        "server",
        "location",
        "x-datadome",
        "x-datadome-cid",
        "cf-ray",
        "set-cookie",
    ]:
        value = response.headers.get(key)
        if value:
            response_header_subset[key] = value
    if response_header_subset:
        debug(f"preflight response headers relevantes={response_header_subset}")

    session_cookie_names = _get_cookie_names(session_cookies)
    debug(
        "preflight session cookies=" + ",".join(session_cookie_names)
        if session_cookie_names
        else "preflight session cookies=vacio"
    )

    body_preview = (response.text or "").strip().replace("\n", " ").replace("\r", " ")[:300]
    if body_preview:
        debug(f"preflight body preview={body_preview!r}")

    if response.status_code >= 400:
        print("⚠️ Preflight returned non-200 status:", response.status_code)
        print("⚠️ Preflight final URL:", response.url)
        print("⚠️ Preflight redirect count:", len(response.history))
        print("⚠️ Preflight sent headers:", sent_headers)
        if ignored_headers:
            print("⚠️ Preflight headers ignored by requests:", ignored_headers)
        print("⚠️ Preflight relevant response headers:", response_header_subset)
        print("⚠️ Preflight session cookies:", session_cookie_names)
        print("⚠️ Preflight body preview:", body_preview)


def _get_sync_playwright():
    try:
        module = importlib.import_module("playwright.sync_api")
        return module.sync_playwright
    except Exception:
        return None


def _get_curl_cffi_requests():
    try:
        module = importlib.import_module("curl_cffi")
        return module.requests
    except Exception:
        return None


def _build_http_session(site_config):
    http_client = (site_config.get("http_client") or "requests").lower()
    if http_client == "curl_cffi":
        curl_requests = _get_curl_cffi_requests()
        if curl_requests is None:
            return None, "curl_cffi no esta instalado"

        impersonate = site_config.get("curl_impersonate") or "chrome136"
        return curl_requests.Session(impersonate=impersonate), None

    return requests.Session(), None


def _run_warmup_requests(http_session, warmup_urls, request_timeout, debug):
    warmup_success = True

    for index, warmup in enumerate(warmup_urls or [], start=1):
        if isinstance(warmup, str):
            url = warmup
            headers = {}
        else:
            url = warmup.get("url")
            headers = dict(warmup.get("headers") or {})

        if not url:
            continue

        try:
            response = http_session.get(url, headers=headers, timeout=request_timeout)
            session_cookie_names = _get_cookie_names(http_session.cookies)
            debug(
                f"warmup {index} status={response.status_code} url={response.url} cookies={','.join(session_cookie_names) if session_cookie_names else 'vacio'}"
            )
            print(f"🔎 Warmup {index}: status={response.status_code} url={response.url}")
            if response.status_code >= 400:
                warmup_success = False
                print("⚠️ Warmup returned non-200 status:", response.status_code)
                print("⚠️ Warmup response headers:", dict(response.headers))
                print(
                    "⚠️ Warmup body preview:",
                    (response.text or "").strip().replace("\n", " ").replace("\r", " ")[:300],
                )
        except Exception as e:
            warmup_success = False
            print("⚠️ Warmup request failed:", repr(e))
            debug(f"warmup exception={repr(e)} url={url}")

    return warmup_success


# ---------------------------------------------------------------------------
# Stealth / anti-detection helpers
# ---------------------------------------------------------------------------

_STEALTH_JS = """
// ---- navigator.webdriver ----
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
delete navigator.__proto__.webdriver;

// ---- chrome runtime ----
window.chrome = {
    runtime: {
        onConnect: { addListener: function() {} },
        onMessage: { addListener: function() {} },
        sendMessage: function() {},
        connect: function() { return { onMessage: { addListener: function() {} } } },
        PlatformOs: { MAC: 'mac', WIN: 'win', ANDROID: 'android', CROS: 'cros', LINUX: 'linux', OPENBSD: 'openbsd' },
        PlatformArch: { ARM: 'arm', X86_32: 'x86-32', X86_64: 'x86-64', MIPS: 'mips', MIPS64: 'mips64' },
    },
    loadTimes: function() { return { requestTime: Date.now() / 1000, startLoadTime: Date.now() / 1000, commitLoadTime: Date.now() / 1000, finishDocumentLoadTime: Date.now() / 1000, finishLoadTime: Date.now() / 1000, firstPaintTime: Date.now() / 1000, firstPaintAfterLoadTime: 0, navigationType: 'Other' }; },
    csi: function() { return { startE: Date.now(), onloadT: Date.now(), pageT: Date.now(), tran: 15 }; },
};

// ---- navigator.plugins ----
const makeFakePlugin = (name, description, filename, mimeType) => {
    const plugin = Object.create(Plugin.prototype);
    Object.defineProperties(plugin, {
        name: { value: name }, description: { value: description },
        filename: { value: filename }, length: { value: 1 },
        0: { value: { type: mimeType, suffixes: '', description: '', enabledPlugin: plugin } },
    });
    return plugin;
};
const fakePlugins = [
    makeFakePlugin('Chrome PDF Plugin', 'Portable Document Format', 'internal-pdf-viewer', 'application/x-google-chrome-pdf'),
    makeFakePlugin('Chrome PDF Viewer', '', 'mhjfbmdgcfjbbpaeojofohoefgiehjai', 'application/pdf'),
    makeFakePlugin('Native Client', '', 'internal-nacl-plugin', 'application/x-nacl'),
];
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const arr = fakePlugins;
        arr.item = i => arr[i]; arr.namedItem = n => arr.find(p => p.name === n);
        arr.refresh = () => {};
        return arr;
    },
});

// ---- navigator.mimeTypes ----
Object.defineProperty(navigator, 'mimeTypes', {
    get: () => {
        const arr = fakePlugins.map(p => p[0]);
        arr.item = i => arr[i]; arr.namedItem = n => arr.find(m => m.type === n);
        return arr;
    },
});

// ---- navigator.languages ----
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'language', { get: () => 'en-US' });

// ---- navigator.permissions ----
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters)
);

// ---- iframe contentWindow ----
try {
    const origAttachShadow = Element.prototype.attachShadow;
    Element.prototype.attachShadow = function() { return origAttachShadow.apply(this, arguments); };
} catch(e) {}

// ---- WebGL vendor/renderer ----
const getParameterOrig = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(param) {
    if (param === 37445) return 'Google Inc. (NVIDIA)';        // UNMASKED_VENDOR_WEBGL
    if (param === 37446) return 'ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 vs_5_0 ps_5_0, D3D11)'; // UNMASKED_RENDERER_WEBGL
    return getParameterOrig.call(this, param);
};
const getParameterOrig2 = WebGL2RenderingContext.prototype.getParameter;
WebGL2RenderingContext.prototype.getParameter = function(param) {
    if (param === 37445) return 'Google Inc. (NVIDIA)';
    if (param === 37446) return 'ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 vs_5_0 ps_5_0, D3D11)';
    return getParameterOrig2.call(this, param);
};

// ---- Canvas fingerprint noise ----
const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
HTMLCanvasElement.prototype.toDataURL = function(type) {
    if (this.width === 0 && this.height === 0) return origToDataURL.apply(this, arguments);
    const ctx = this.getContext('2d');
    if (ctx) {
        const style = ctx.fillStyle;
        ctx.fillStyle = 'rgba(0,0,1,0.003)';
        ctx.fillRect(0, 0, 1, 1);
        ctx.fillStyle = style;
    }
    return origToDataURL.apply(this, arguments);
};

const origToBlob = HTMLCanvasElement.prototype.toBlob;
HTMLCanvasElement.prototype.toBlob = function() {
    const ctx = this.getContext('2d');
    if (ctx) {
        const style = ctx.fillStyle;
        ctx.fillStyle = 'rgba(0,0,1,0.003)';
        ctx.fillRect(0, 0, 1, 1);
        ctx.fillStyle = style;
    }
    return origToBlob.apply(this, arguments);
};

// ---- navigator.hardwareConcurrency ----
Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });

// ---- navigator.deviceMemory ----
Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });

// ---- navigator.maxTouchPoints (desktop) ----
Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 0 });

// ---- navigator.connection ----
if (!navigator.connection) {
    Object.defineProperty(navigator, 'connection', {
        get: () => ({ effectiveType: '4g', rtt: 50, downlink: 10, saveData: false }),
    });
}

// ---- window.outerWidth/outerHeight ----
Object.defineProperty(window, 'outerWidth', { get: () => window.innerWidth });
Object.defineProperty(window, 'outerHeight', { get: () => window.innerHeight + 85 });

// ---- Notification & Permissions ----
if (typeof Notification !== 'undefined') {
    Object.defineProperty(Notification, 'permission', { get: () => 'default' });
}

// ---- prevent toString detection on patched functions ----
const nativeToString = Function.prototype.toString;
const customToString = function() {
    if (this === WebGLRenderingContext.prototype.getParameter) return 'function getParameter() { [native code] }';
    if (this === WebGL2RenderingContext.prototype.getParameter) return 'function getParameter() { [native code] }';
    if (this === HTMLCanvasElement.prototype.toDataURL) return 'function toDataURL() { [native code] }';
    if (this === HTMLCanvasElement.prototype.toBlob) return 'function toBlob() { [native code] }';
    if (this === window.navigator.permissions.query) return 'function query() { [native code] }';
    return nativeToString.call(this);
};
Function.prototype.toString = customToString;
"""


def _simulate_human_behavior(pw_page):
    """Simulate realistic human browsing: mouse moves, hovers, scrolls, pauses."""
    try:
        width = 1920
        height = 1080

        # Initial mouse movement to random spot (like moving from address bar)
        pw_page.mouse.move(
            random.randint(200, width - 200),
            random.randint(150, 400),
            steps=random.randint(10, 25),
        )
        time.sleep(random.uniform(0.5, 1.2))

        # Hover over a few elements (links, images)
        hover_selectors = [
            "a", "img", "li", "div.vehicle-snapshot",
            "h2", "h3", "span", "button",
        ]
        random.shuffle(hover_selectors)
        hovers_done = 0
        for sel in hover_selectors:
            if hovers_done >= random.randint(2, 4):
                break
            try:
                elements = pw_page.query_selector_all(sel)
                if elements:
                    el = random.choice(elements[:10])
                    box = el.bounding_box()
                    if box and box["y"] < 2000:
                        pw_page.mouse.move(
                            box["x"] + box["width"] / 2 + random.uniform(-5, 5),
                            box["y"] + box["height"] / 2 + random.uniform(-3, 3),
                            steps=random.randint(8, 20),
                        )
                        time.sleep(random.uniform(0.3, 0.9))
                        hovers_done += 1
            except Exception:
                pass

        # Scroll down gradually (like reading the page)
        scroll_count = random.randint(3, 6)
        for i in range(scroll_count):
            scroll_amount = random.randint(200, 500)
            pw_page.mouse.wheel(0, scroll_amount)
            time.sleep(random.uniform(0.8, 2.0))

            # Occasionally move mouse while scrolling
            if random.random() < 0.5:
                pw_page.mouse.move(
                    random.randint(100, width - 100),
                    random.randint(100, height - 100),
                    steps=random.randint(5, 15),
                )
                time.sleep(random.uniform(0.2, 0.6))

        # Scroll back up partially
        pw_page.mouse.wheel(0, -random.randint(100, 300))
        time.sleep(random.uniform(0.5, 1.5))

        # Final idle pause (like reading)
        time.sleep(random.uniform(1.0, 3.0))

    except Exception:
        pass


def _playwright_scrape_all_pages(
    preflight_url_builder,
    preflight_url,
    inventario_url,
    api_url,
    headers,
    storage_state_path,
    request_timeout,
    max_pages,
    page_delay=10,
    headless=True,
    debug_captcha=False,
):
    """Fetch all pages with a single persistent browser to preserve DataDome cookies."""
    sync_playwright = _get_sync_playwright()
    if sync_playwright is None:
        return [], "Playwright no está instalado"

    def _is_captcha(content):
        return len(content) < 5000 and "captcha-delivery.com" in content

    def _launch_browser(p, ua, is_headless):
        return p.chromium.launch(
            headless=is_headless,
            channel="chrome",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-infobars",
                "--disable-dev-shm-usage",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows",
                "--lang=en-US,en",
            ],
        )

    def _create_context(browser, ua, state_path):
        ctx = browser.new_context(
            user_agent=ua,
            storage_state=state_path,
            viewport={"width": 1920, "height": 1080},
            screen={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/Chicago",
            color_scheme="light",
        )
        ctx.add_init_script(_STEALTH_JS)
        return ctx

    def _run():
        timeout_ms = int(request_timeout * 1000)
        results = []
        ua = headers.get("User-Agent")
        with sync_playwright() as p:
            browser = _launch_browser(p, ua, headless)
            context = _create_context(browser, ua, storage_state_path)
            page = context.new_page()
            switched_to_visible = False

            for page_num in range(1, max_pages + 1):
                if page_num > 1:
                    delay = random.uniform(page_delay, page_delay + 8)
                    print(f"⏳ Waiting {delay:.1f}s before page {page_num}...")
                    time.sleep(delay)

                nav_url = (
                    preflight_url_builder(page_num)
                    if preflight_url_builder
                    else preflight_url or inventario_url or api_url
                )
                print(f"[DEBUG][playwright] navigating to: {nav_url}")
                try:
                    page.goto(nav_url, wait_until="networkidle", timeout=timeout_ms)
                except Exception as exc:
                    print(f"⚠️ Playwright navigation error on page {page_num}: {exc}")
                    break

                _simulate_human_behavior(page)

                content = page.content()
                print(f"[DEBUG][playwright] page {page_num} content_chars={len(content)}")

                if _is_captcha(content):
                    if debug_captcha:
                        print(f"⚠️ DataDome captcha on page {page_num}, switching to visible browser...")
                        browser.close()

                        # Reopen as VISIBLE and keep it for all remaining pages
                        browser = _launch_browser(p, ua, False)
                        context = _create_context(browser, ua, storage_state_path)
                        page = context.new_page()
                        switched_to_visible = True

                        try:
                            page.goto(nav_url, wait_until="domcontentloaded", timeout=60000)
                        except Exception as exc:
                            print(f"⚠️ [debugCaptcha] Navigation error: {exc}")

                        # Poll until user solves captcha in the visible window
                        print("⏳ [debugCaptcha] Waiting for captcha to be solved...")
                        while True:
                            time.sleep(2)
                            try:
                                content = page.content()
                                if not _is_captcha(content):
                                    print("✅ [debugCaptcha] Captcha solved!")
                                    break
                            except Exception:
                                break

                        # Re-check content (page may have auto-navigated after solve)
                        try:
                            page.wait_for_load_state("networkidle", timeout=timeout_ms)
                        except Exception:
                            pass
                        content = page.content()
                        print(f"[DEBUG][playwright] page {page_num} after captcha content_chars={len(content)}")

                        if _is_captcha(content):
                            print(f"⚠️ Still captcha after solve on page {page_num}, stopping")
                            results.append((200, content))
                            break

                        # Captcha solved — simulate human then collect
                        _simulate_human_behavior(page)
                        content = page.content()
                    else:
                        print(f"⚠️ DataDome captcha on page {page_num}, stopping pagination")
                        results.append((200, content))
                        break

                results.append((200, content))

            # Save updated storage state so cookies stay fresh for next run
            if storage_state_path:
                try:
                    context.storage_state(path=storage_state_path)
                    print(f"[DEBUG][playwright] storage state updated: {storage_state_path}")
                except Exception:
                    pass

            if switched_to_visible:
                print("[DEBUG][playwright] scraping complete, closing visible browser")

            browser.close()
        return results

    try:
        result_holder = [None]
        error_holder = [None]

        def _thread_target():
            try:
                if sys.platform == "win32":
                    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
                result_holder[0] = _run()
            except Exception as exc:
                error_holder[0] = repr(exc)

        # Allow extra time per page when debug_captcha is on (user solving manually)
        captcha_budget = 300 if debug_captcha else 0
        total_timeout = (request_timeout + page_delay + 30 + captcha_budget) * max_pages
        t = threading.Thread(target=_thread_target, daemon=True)
        t.start()
        t.join(timeout=total_timeout)
        if t.is_alive():
            return [], "Playwright timeout (thread did not finish)"
        if error_holder[0]:
            return [], error_holder[0]
        return result_holder[0] or [], None
    except Exception as e:
        return [], repr(e)


def _playwright_scrape_metacarstx(
    preflight_url_builder,
    headers,
    storage_state_path,
    request_timeout,
    max_pages,
    page_delay=10,
    headless=True,
):
    """Scrape metacarstx by navigating inventory pages and intercepting the API response."""
    sync_playwright = _get_sync_playwright()
    if sync_playwright is None:
        return [], "Playwright no está instalado"

    def _run():
        timeout_ms = int(request_timeout * 1000)
        results = []
        ua = headers.get("User-Agent")

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=headless,
                channel="chrome",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-infobars",
                    "--disable-dev-shm-usage",
                    "--lang=en-US,en",
                ],
            )
            ctx_kwargs = {
                "user_agent": ua,
                "viewport": {"width": 1920, "height": 1080},
                "screen": {"width": 1920, "height": 1080},
                "locale": "en-US",
                "timezone_id": "America/Chicago",
                "color_scheme": "light",
            }
            if storage_state_path:
                ctx_kwargs["storage_state"] = storage_state_path

            context = browser.new_context(**ctx_kwargs)
            context.add_init_script(_STEALTH_JS)
            page = context.new_page()

            for page_num in range(1, max_pages + 1):
                if page_num > 1:
                    delay = random.uniform(page_delay, page_delay + 8)
                    print(f"⏳ Waiting {delay:.1f}s before page {page_num}...")
                    time.sleep(delay)

                captured_response = [None]

                def _on_response(response, _holder=captured_response):
                    if "/inv-scripts-v2/inv/vehicles" in response.url:
                        try:
                            _holder[0] = response.text()
                            print(
                                f"[DEBUG][metacarstx] intercepted API response on page {page_num}: "
                                f"{len(_holder[0])} chars"
                            )
                        except Exception as exc:
                            print(f"[DEBUG][metacarstx] failed to read intercepted response: {exc}")

                page.on("response", _on_response)

                nav_url = preflight_url_builder(page_num)
                print(f"[DEBUG][metacarstx] navigating to: {nav_url}")

                try:
                    page.goto(nav_url, wait_until="networkidle", timeout=timeout_ms)
                except Exception as exc:
                    print(f"⚠️ Playwright navigation error on page {page_num}: {exc}")
                    page.remove_listener("response", _on_response)
                    break

                _simulate_human_behavior(page)
                page.remove_listener("response", _on_response)

                if captured_response[0]:
                    results.append((200, captured_response[0]))
                else:
                    print(f"⚠️ No API response captured on page {page_num}, stopping pagination")
                    break

            if storage_state_path:
                try:
                    context.storage_state(path=storage_state_path)
                    print(f"[DEBUG][metacarstx] storage state updated: {storage_state_path}")
                except Exception:
                    pass

            browser.close()
        return results

    try:
        result_holder = [None]
        error_holder = [None]

        def _thread_target():
            try:
                if sys.platform == "win32":
                    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
                result_holder[0] = _run()
            except Exception as exc:
                error_holder[0] = repr(exc)

        total_timeout = (request_timeout + page_delay + 30) * max_pages
        t = threading.Thread(target=_thread_target, daemon=True)
        t.start()
        t.join(timeout=total_timeout)
        if t.is_alive():
            return [], "Playwright timeout (thread did not finish)"
        if error_holder[0]:
            return [], error_holder[0]
        return result_holder[0] or [], None
    except Exception as e:
        return [], repr(e)


def _playwright_fetch_text(
    api_url,
    method,
    query_params,
    post_data,
    headers,
    preflight_url,
    inventario_url,
    request_timeout,
    browser_cookies=None,
    prefer_script_src_contains=None,
    storage_state_path=None,
):
    sync_playwright = _get_sync_playwright()
    if sync_playwright is None:
        return None, None, "Playwright no está instalado"

    def build_fetch_headers(src_headers):
        allowed = ["Accept", "Accept-Language", "Content-Type", "X-Requested-With"]
        result = {}
        for key in allowed:
            value = src_headers.get(key)
            if value:
                result[key] = value
        return result

    def _run_in_playwright():
        timeout_ms = int(request_timeout * 1000)
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )
            context = browser.new_context(
                user_agent=headers.get("User-Agent"),
                storage_state=storage_state_path if storage_state_path else None,
            )
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            if not storage_state_path and browser_cookies:
                context.add_cookies(browser_cookies)

            # When we have saved storage state and don't need in-page script
            # extraction, navigate to the listing page directly and return its
            # HTML content.  This lets DataDome's JS validate the saved cookie
            # inside a real browser context, avoiding the API-only path that
            # gets fingerprinted.
            if storage_state_path and not prefer_script_src_contains:
                page = context.new_page()
                nav_url = preflight_url or inventario_url or api_url
                print(f"[DEBUG][playwright] navigating to: {nav_url}")
                page.goto(nav_url, wait_until="networkidle", timeout=timeout_ms)
                content = page.content()
                browser.close()
                return 200, content, None

            # Fallback: navigate to a page and execute fetch() from the
            # browser JS context (needed when we must extract script URLs).
            page = context.new_page()

            target_preflight = preflight_url or inventario_url
            if target_preflight:
                page.goto(target_preflight, wait_until="domcontentloaded", timeout=timeout_ms)

            fetch_headers = build_fetch_headers(headers)

            if method == "GET":
                fetch_url = None

                if prefer_script_src_contains:
                    fetch_url = page.evaluate(
                        """({ scriptNeedle }) => {
                            const scripts = Array.from(document.querySelectorAll('script[src]'));
                            const match = scripts.find(s => (s.getAttribute('src') || '').includes(scriptNeedle));
                            if (!match) return null;
                            return new URL(match.getAttribute('src'), window.location.origin).href;
                        }""",
                        {"scriptNeedle": prefer_script_src_contains},
                    )

                if not fetch_url:
                    query = urlencode(query_params or {}, doseq=True)
                    fetch_url = f"{api_url}?{query}" if query else api_url

                result = page.evaluate(
                    """async ({ url, headers }) => {
                        const resp = await fetch(url, {
                            method: 'GET',
                            headers,
                            credentials: 'include'
                        });
                        const text = await resp.text();
                        return { status: resp.status, text };
                    }""",
                    {"url": fetch_url, "headers": fetch_headers},
                )
            else:
                result = page.evaluate(
                    """async ({ url, headers, body }) => {
                        const payload = new URLSearchParams(body || {}).toString();
                        const resp = await fetch(url, {
                            method: 'POST',
                            headers,
                            body: payload,
                            credentials: 'include'
                        });
                        const text = await resp.text();
                        return { status: resp.status, text };
                    }""",
                    {"url": api_url, "headers": fetch_headers, "body": post_data or {}},
                )

            browser.close()
            return result.get("status"), result.get("text"), None

    try:
        result_holder = [None]
        error_holder = [None]

        def _thread_target():
            try:
                if sys.platform == "win32":
                    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
                result_holder[0] = _run_in_playwright()
            except Exception as exc:
                error_holder[0] = repr(exc)

        t = threading.Thread(target=_thread_target, daemon=True)
        t.start()
        t.join(timeout=request_timeout + 30)
        if t.is_alive():
            return None, None, "Playwright timeout (thread did not finish)"
        if error_holder[0]:
            return None, None, error_holder[0]
        if result_holder[0] is None:
            return None, None, "Playwright thread returned no result"
        return result_holder[0]
    except Exception as e:
        return None, None, repr(e)


def scrape_properties(site_name: str = "usaridetoday", scraper_engine_override: str | None = None, debug_captcha: bool = False):
    """Extrae inventario de carros desde el sitio configurado."""
    site_config = SITE_CONFIGS.get(site_name)
    if site_config is None:
        supported_sites = ", ".join(sorted(SITE_CONFIGS.keys()))
        st.error(f"Unsupported site '{site_name}'. Supported: {supported_sites}")
        return []
    api_url = site_config.get("api_url")
    request_headers_base = site_config.get("headers")
    inventario_url = site_config.get("listings_url")
    pagination_payload_builder = site_config.get("pagination_payload_builder")
    query_params_builder = site_config.get("query_params_builder")
    parser_name = site_config.get("parser", "usaridetoday")
    scraper_engine = (scraper_engine_override or site_config.get("scraper_engine", "requests")).lower()
    request_method = site_config.get("request_method", "POST").upper()
    preflight_url = site_config.get("preflight_url")
    preflight_url_builder = site_config.get("preflight_url_builder")
    preflight_headers_config = site_config.get("preflight_headers")
    cookie_header = site_config.get("cookie")
    fallback_headers = site_config.get("fallback_headers")
    allow_requests_fallback = site_config.get("allow_requests_fallback", True)
    use_preflight = site_config.get("use_preflight", True)
    warmup_urls = site_config.get("warmup_urls") or []
    max_pages = site_config.get("max_pages", 50)
    request_timeout = site_config.get("request_timeout", 10)
    debug_enabled = site_config.get("debug", True)

    storage_state_path = None
    _state_file = os.path.join(".playwright_state", f"{site_name}.json")
    if os.path.exists(_state_file):
        storage_state_path = _state_file

    def debug(message: str):
        if debug_enabled:
            print(f"[DEBUG][{site_name}] {message}")

    debug(
        f"config cargada engine={scraper_engine} method={request_method} parser={parser_name} max_pages={max_pages} timeout={request_timeout}"
    )
    if storage_state_path:
        debug(f"playwright storage state encontrado: {storage_state_path}")

    carros_extraidos = []
    pagina_actual = 1
    http_session, http_session_error = _build_http_session(site_config)
    if http_session_error:
        st.error(http_session_error)
        return []

    warmup_completed = False

    # --- Intercept-based path for metacarstx (Playwright + network capture) ---
    if scraper_engine == "playwright" and parser_name == "metacarstx_json":
        debug("usando playwright intercept para metacarstx")
        page_delay = site_config.get("page_delay", 10)
        headless = site_config.get("headless", True)
        page_results, pw_error = _playwright_scrape_metacarstx(
            preflight_url_builder=preflight_url_builder,
            headers=request_headers_base,
            storage_state_path=storage_state_path,
            request_timeout=request_timeout,
            max_pages=max_pages,
            page_delay=page_delay,
            headless=headless,
        )
        if pw_error:
            print(f"⚠️ Metacarstx playwright intercept failed: {pw_error}")
            debug(f"metacarstx playwright error={pw_error}")
            st.error(f"Playwright error: {pw_error}")
            return []

        for page_num, (status, content) in enumerate(page_results, 1):
            cleaned_text = content.lstrip("\ufeff")
            print(f"Status code: {status}")
            print(f"🔎 Cleaned text preview (repr): {repr(cleaned_text[:120])}")

            page_records = _parse_page(parser_name, cleaned_text, inventario_url, page_num)
            carros_extraidos.extend(page_records)
            debug(f"fin pagina={page_num} total_acumulado={len(carros_extraidos)}")

        print(f"✅ Terminamos paginacion, se encontraron {len(carros_extraidos)}")
        return carros_extraidos

    # --- Persistent-browser path for playwright + storage_state or persistent_browser flag ---
    if (
        scraper_engine == "playwright"
        and parser_name != "metacarstx_json"
        and (storage_state_path or site_config.get("persistent_browser"))
    ):
        debug("usando persistent browser para todas las paginas")
        page_delay = site_config.get("page_delay", 10)
        headless = site_config.get("headless", True)
        page_results, pw_error = _playwright_scrape_all_pages(
            preflight_url_builder=preflight_url_builder,
            preflight_url=preflight_url,
            inventario_url=inventario_url,
            api_url=api_url,
            headers=request_headers_base,
            storage_state_path=storage_state_path,
            request_timeout=request_timeout,
            max_pages=max_pages,
            page_delay=page_delay,
            headless=headless,
            debug_captcha=debug_captcha,
        )
        if pw_error:
            print(f"⚠️ Persistent playwright session failed: {pw_error}")
            debug(f"persistent playwright error={pw_error}")
            st.error(f"Playwright error: {pw_error}")
            return []

        for page_num, (status, content) in enumerate(page_results, 1):
            cleaned_text = content.lstrip("\ufeff")
            print(f"Status code: {status}")
            print(f"🔎 Cleaned text preview (repr): {repr(cleaned_text[:120])}")

            if len(cleaned_text) < 5000 and "captcha-delivery.com" in cleaned_text:
                debug(f"pagina {page_num} fue captcha, ignorando")
                continue

            page_records = _parse_page(parser_name, cleaned_text, inventario_url, page_num)
            carros_extraidos.extend(page_records)
            debug(f"fin pagina={page_num} total_acumulado={len(carros_extraidos)}")

        print(f"✅ Terminamos paginacion, se encontraron {len(carros_extraidos)}")
        return carros_extraidos

    # --- Original per-page loop (requests fallback, metacarstx, etc.) ---

    parse_preflight = site_config.get("parse_preflight", False)

    # For sites like afccars: do ONE preflight GET, parse it as the first batch of vehicles,
    # then fall into the loop for subsequent POST pages.
    if parse_preflight and preflight_url and scraper_engine == "requests":
        debug(f"parse_preflight: GET {preflight_url}")
        try:
            preflight_headers, _ = _prepare_preflight_headers(
                preflight_headers_config, request_headers_base, preflight_url
            )
            preflight_response = http_session.get(
                preflight_url, headers=preflight_headers, timeout=request_timeout
            )
            print(f"🔎 Preflight GET status={preflight_response.status_code} url={preflight_url}")
            if preflight_response.status_code == 200:
                preflight_text = preflight_response.text.lstrip("\ufeff")
                preflight_records = _parse_page(parser_name, preflight_text, inventario_url, 0)
                carros_extraidos.extend(preflight_records)
                debug(f"parse_preflight: {len(preflight_records)} records from initial GET")
        except Exception as e:
            print("⚠️ parse_preflight GET failed:", repr(e))
            debug(f"parse_preflight exception={repr(e)}")

    try:
        while pagina_actual <= max_pages:
            if pagina_actual > 1 or carros_extraidos:
                print(f"⏳ Waiting 5 seconds before fetching page {pagina_actual}...")
                time.sleep(5)
            print(f"🔎 Fetching page {pagina_actual} from API...")
            post_data = pagination_payload_builder(pagina_actual) if pagination_payload_builder else None
            query_params = query_params_builder(pagina_actual) if query_params_builder else None
            request_headers = dict(request_headers_base)
            if cookie_header:
                request_headers["Cookie"] = cookie_header

            if warmup_urls and not warmup_completed and scraper_engine != "playwright":
                debug("ejecutando warmup_urls antes del request real")
                _run_warmup_requests(http_session, warmup_urls, request_timeout, debug)
                warmup_completed = True

            target_preflight_url = (
                preflight_url_builder(pagina_actual) if preflight_url_builder else preflight_url
            )
            preflight_html = None
            preflight_has_datadome_cookie = False
            # Skip in-loop preflight for parse_preflight sites — the GET was already done above
            if use_preflight and target_preflight_url and not parse_preflight:
                debug(f"preflight_url pagina={pagina_actual}: {target_preflight_url}")
                try:
                    preflight_headers, ignored_preflight_headers = _prepare_preflight_headers(
                        preflight_headers_config,
                        request_headers_base,
                        target_preflight_url,
                    )
                    if cookie_header:
                        preflight_headers["Cookie"] = cookie_header

                    preflight_response = http_session.get(
                        target_preflight_url,
                        headers=preflight_headers,
                        timeout=request_timeout,
                    )
                    _log_preflight_diagnostics(
                        debug,
                        preflight_response,
                        preflight_headers,
                        ignored_preflight_headers,
                        http_session.cookies,
                    )
                    preflight_has_datadome_cookie = _has_cookie(http_session.cookies, "datadome")
                    if preflight_has_datadome_cookie:
                        datadome_value = _get_cookie_value(http_session.cookies, "datadome")
                        datadome_preview = f"{datadome_value[:24]}..." if datadome_value else "vacio"
                        print(
                            "⚠️ Preflight returned DataDome cookie; continuing with actual request using session cookies."
                        )
                        debug(f"preflight datadome cookie detectada={datadome_preview}")
                    if preflight_response.status_code == 200:
                        preflight_html = preflight_response.text
                except Exception as e:
                    print("⚠️ Preflight GET failed:", repr(e))
                    debug(f"preflight exception={repr(e)}")

            merged_cookie_header = _merge_cookie_header(cookie_header, http_session.cookies)
            if merged_cookie_header:
                request_headers["Cookie"] = merged_cookie_header
                debug(
                    "request cookies after preflight="
                    + ",".join(_get_cookie_names(http_session.cookies))
                )
            browser_cookies = _cookiejar_to_playwright_cookies(http_session.cookies)

            if parser_name == "metacarstx_json" and preflight_html:
                runtime_params = _extract_metacarstx_runtime_params(preflight_html, target_preflight_url)
                if runtime_params:
                    if query_params is None:
                        query_params = {}
                    query_params.update(runtime_params)
                    debug("runtime_params extraidos claves=" + ",".join(sorted(runtime_params.keys())))
                    debug(
                        f"runtime_params resumen pn={runtime_params.get('pn')} h={runtime_params.get('h')} cb={runtime_params.get('cb')}"
                    )
                else:
                    debug("runtime_params vacio: no se pudo extraer script params del preflight")

            print(f"🔎 Fetching page {pagina_actual} with data={post_data} params={query_params}")
            debug("request headers claves=" + ",".join(sorted(request_headers.keys())))

            cleaned_text = None
            response_status = None

            if scraper_engine == "playwright":
                debug("ejecutando via playwright")
                status, text, pw_error = _playwright_fetch_text(
                    api_url=api_url,
                    method=request_method,
                    query_params=query_params,
                    post_data=post_data,
                    headers=request_headers,
                    preflight_url=target_preflight_url,
                    inventario_url=inventario_url,
                    request_timeout=request_timeout,
                    browser_cookies=browser_cookies,
                    prefer_script_src_contains=(
                        "/inv-scripts-v2/inv/vehicles" if parser_name == "metacarstx_json" else None
                    ),
                    storage_state_path=storage_state_path,
                )
                if pw_error:
                    print(f"⚠️ Playwright path failed, fallback to requests: {pw_error}")
                    debug(f"playwright error={pw_error}")
                else:
                    response_status = status
                    cleaned_text = (text or "").lstrip("\ufeff")
                    debug(
                        f"playwright status={response_status} payload_chars={len(cleaned_text)}"
                    )
            debug(cleaned_text)
            if cleaned_text is None or len(cleaned_text) == 1787:
                if scraper_engine == "playwright" and not allow_requests_fallback and not preflight_has_datadome_cookie:
                    print("⚠️ Playwright failed and requests fallback is disabled for this site.")
                    debug("playwright returned no content and requests fallback is disabled")
                    break
                if scraper_engine == "playwright" and not allow_requests_fallback and preflight_has_datadome_cookie:
                    print("⚠️ Playwright failed, but requests fallback is allowed because preflight returned a DataDome cookie.")
                    debug("playwright failed but continuing via requests because datadome cookie exists")

                debug("ejecutando via requests")
                if request_method == "GET":
                    response = http_session.get(
                        api_url,
                        params=query_params,
                        headers=request_headers,
                        timeout=request_timeout,
                    )

                    if response.status_code == 403 and fallback_headers:
                        print("⚠️ 403 on GET. Retrying once with fallback headers after preflight...")
                        debug("activando retry con fallback_headers")
                        if target_preflight_url:
                            try:
                                http_session.get(
                                    target_preflight_url,
                                    headers=fallback_headers,
                                    timeout=request_timeout,
                                )
                            except Exception as e:
                                print("⚠️ Retry preflight GET failed:", repr(e))
                                debug(f"retry preflight error={repr(e)}")

                        retry_headers = dict(fallback_headers)
                        retry_cookie_header = _merge_cookie_header(cookie_header, http_session.cookies)
                        if retry_cookie_header:
                            retry_headers["Cookie"] = retry_cookie_header

                        response = http_session.get(
                            api_url,
                            params=query_params,
                            headers=retry_headers,
                            timeout=request_timeout,
                        )
                        debug(f"retry status={response.status_code}")
                else:
                    if merged_cookie_header:
                        request_headers["Cookie"] = merged_cookie_header
                    response = http_session.post(
                        api_url,
                        data=post_data,
                        headers=request_headers,
                        timeout=request_timeout,
                    )
                response_status = response.status_code
                if response_status != 200:
                    if response_status == 403:
                        print("⚠️ 403 received. Response headers:", dict(response.headers))
                    debug(
                        f"non-200 status={response_status} response_headers={dict(response.headers)}"
                    )
                    print("⚠️ Non-200 status, stopping pagination.")
                    break

                raw_bytes = response.content
                cleaned_text = raw_bytes.decode("utf-8-sig")
                debug(f"requests payload_bytes={len(raw_bytes)} payload_chars={len(cleaned_text)}")

            print("Status code:", response_status)
            print("🔎 Cleaned text preview (repr):", repr(cleaned_text[:120]))

            if response_status != 200:
                print("⚠️ Non-200 status, stopping pagination.")
                break

            page_records = _parse_page(parser_name, cleaned_text, inventario_url, pagina_actual)
            carros_extraidos.extend(page_records)

            pagina_actual += 1
            debug(f"fin pagina={pagina_actual - 1} total_acumulado={len(carros_extraidos)}")

        print("✅ Terminamos paginacion, se encontraron ", len(carros_extraidos))
        return carros_extraidos

    except requests.exceptions.RequestException as e:
        print("❌ RequestException in pagination:", repr(e))
        st.error(f"Error scraping website: {str(e)}")
        return []
    except Exception as e:
        print("❌ General exception in scrape_properties (pagination):", repr(e))
        st.error(f"Error parsing properties: {str(e)}")
        return []
    

def _iter_normalized_cookies(session_cookies):
    normalized = []

    if not session_cookies:
        return normalized

    try:
        items = list(session_cookies.items())
    except Exception:
        items = None

    if items is not None:
        for name, value in items:
            normalized.append(
                {
                    "name": str(name),
                    "value": "" if value is None else str(value),
                    "domain": "",
                    "path": "/",
                    "secure": False,
                    "expires": None,
                }
            )

        try:
            jar_iterable = list(session_cookies.jar)
        except Exception:
            jar_iterable = []

        if jar_iterable:
            by_name = {item["name"]: item for item in normalized}
            for cookie in jar_iterable:
                entry = by_name.get(getattr(cookie, "name", ""))
                if not entry:
                    continue
                entry["domain"] = getattr(cookie, "domain", "") or ""
                entry["path"] = getattr(cookie, "path", "/") or "/"
                entry["secure"] = bool(getattr(cookie, "secure", False))
                entry["expires"] = getattr(cookie, "expires", None)

        return normalized

    try:
        for cookie in session_cookies:
            if hasattr(cookie, "name"):
                normalized.append(
                    {
                        "name": str(cookie.name),
                        "value": "" if cookie.value is None else str(cookie.value),
                        "domain": getattr(cookie, "domain", "") or "",
                        "path": getattr(cookie, "path", "/") or "/",
                        "secure": bool(getattr(cookie, "secure", False)),
                        "expires": getattr(cookie, "expires", None),
                    }
                )
            else:
                name = str(cookie)
                value = ""
                getter = getattr(session_cookies, "get", None)
                if callable(getter):
                    raw_value = getter(name)
                    value = "" if raw_value is None else str(raw_value)

                normalized.append(
                    {
                        "name": name,
                        "value": value,
                        "domain": "",
                        "path": "/",
                        "secure": False,
                        "expires": None,
                    }
                )
    except Exception:
        return []

    return normalized


def _get_cookie_names(session_cookies):
    return sorted(
        {
            cookie_info["name"]
            for cookie_info in _iter_normalized_cookies(session_cookies)
            if cookie_info.get("name")
        }
    )


def _get_cookie_value(session_cookies, cookie_name):
    for cookie_info in _iter_normalized_cookies(session_cookies):
        if cookie_info.get("name") == cookie_name:
            return cookie_info.get("value")
    return None


def _has_cookie(session_cookies, cookie_name):
    return _get_cookie_value(session_cookies, cookie_name) is not None


def _merge_cookie_header(existing_cookie_header, session_cookies):
    cookie_map = {}

    if existing_cookie_header:
        for part in existing_cookie_header.split(";"):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            cookie_map[key.strip()] = value.strip()

    for cookie_info in _iter_normalized_cookies(session_cookies):
        name = cookie_info.get("name")
        value = cookie_info.get("value")
        if name:
            cookie_map[name] = value

    return "; ".join(f"{key}={value}" for key, value in cookie_map.items()) if cookie_map else None


def _cookiejar_to_playwright_cookies(session_cookies):
    browser_cookies = []

    for cookie_info in _iter_normalized_cookies(session_cookies):
        domain = cookie_info.get("domain") or ""
        if domain.startswith("."):
            domain = domain[1:]

        browser_cookie = {
            "name": cookie_info["name"],
            "value": cookie_info["value"],
            "path": cookie_info.get("path") or "/",
            "secure": bool(cookie_info.get("secure", False)),
        }

        if domain:
            browser_cookie["domain"] = domain

        if cookie_info.get("expires"):
            browser_cookie["expires"] = float(cookie_info["expires"])

        browser_cookies.append(browser_cookie)

    return browser_cookies