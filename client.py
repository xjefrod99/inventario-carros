import json
import importlib
import re
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
            collect_vehicles(parsed)
        except Exception:
            continue

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


def _get_sync_playwright():
    try:
        module = importlib.import_module("playwright.sync_api")
        return module.sync_playwright
    except Exception:
        return None


def _playwright_fetch_text(
    api_url,
    method,
    query_params,
    post_data,
    headers,
    preflight_url,
    inventario_url,
    request_timeout,
    prefer_script_src_contains=None,
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

    try:
        timeout_ms = int(request_timeout * 1000)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=headers.get("User-Agent"))
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
    except Exception as e:
        return None, None, repr(e)


def scrape_properties(site_name: str = "usaridetoday", scraper_engine_override: str | None = None):
    """Extrae inventario de carros desde el sitio configurado."""
    site_config = SITE_CONFIGS.get(site_name)
    if site_config is None:
        supported_sites = ", ".join(sorted(SITE_CONFIGS.keys()))
        st.error(f"Unsupported site '{site_name}'. Supported: {supported_sites}")
        return []

    api_url = site_config["api_url"]
    request_headers_base = site_config["headers"]
    inventario_url = site_config["listings_url"]
    pagination_payload_builder = site_config.get("pagination_payload_builder")
    query_params_builder = site_config.get("query_params_builder")
    parser_name = site_config.get("parser", "usaridetoday")
    scraper_engine = (scraper_engine_override or site_config.get("scraper_engine", "requests")).lower()
    request_method = site_config.get("request_method", "POST").upper()
    preflight_url = site_config.get("preflight_url")
    preflight_url_builder = site_config.get("preflight_url_builder")
    cookie_header = site_config.get("cookie")
    fallback_headers = site_config.get("fallback_headers")
    max_pages = site_config.get("max_pages", 50)
    request_timeout = site_config.get("request_timeout", 10)
    debug_enabled = site_config.get("debug", True)

    def debug(message: str):
        if debug_enabled:
            print(f"[DEBUG][{site_name}] {message}")

    debug(
        f"config cargada engine={scraper_engine} method={request_method} parser={parser_name} max_pages={max_pages} timeout={request_timeout}"
    )

    carros_extraidos = []
    pagina_actual = 1
    http_session = requests.Session()

    try:
        while pagina_actual <= max_pages:
            print(f"🔎 Fetching page {pagina_actual} from API...")
            post_data = pagination_payload_builder(pagina_actual) if pagination_payload_builder else None
            query_params = query_params_builder(pagina_actual) if query_params_builder else None
            request_headers = dict(request_headers_base)
            if cookie_header:
                request_headers["Cookie"] = cookie_header

            target_preflight_url = (
                preflight_url_builder(pagina_actual) if preflight_url_builder else preflight_url
            )
            preflight_html = None
            if target_preflight_url:
                debug(f"preflight_url pagina={pagina_actual}: {target_preflight_url}")
                try:
                    preflight_headers = {
                        "User-Agent": request_headers_base.get("User-Agent", "Mozilla/5.0"),
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": request_headers_base.get("Accept-Language", "en-US,en;q=0.9"),
                        "Referer": request_headers_base.get("Referer", target_preflight_url),
                    }
                    preflight_response = http_session.get(
                        target_preflight_url,
                        headers=preflight_headers,
                        timeout=request_timeout,
                    )
                    debug(
                        f"preflight status={preflight_response.status_code} bytes={len(preflight_response.text or '')}"
                    )
                    if preflight_response.status_code == 200:
                        preflight_html = preflight_response.text
                except Exception as e:
                    print("⚠️ Preflight GET failed:", repr(e))

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
                    prefer_script_src_contains=(
                        "/inv-scripts-v2/inv/vehicles" if parser_name == "metacarstx_json" else None
                    ),
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

            if cleaned_text is None:
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
                        if cookie_header:
                            retry_headers["Cookie"] = cookie_header

                        response = http_session.get(
                            api_url,
                            params=query_params,
                            headers=retry_headers,
                            timeout=request_timeout,
                        )
                        debug(f"retry status={response.status_code}")
                else:
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
                print("🔎 First 4 raw bytes:", list(raw_bytes[:4]))
                cleaned_text = raw_bytes.decode("utf-8-sig")
                debug(f"requests payload_bytes={len(raw_bytes)} payload_chars={len(cleaned_text)}")

            print("Status code:", response_status)
            print("🔎 Cleaned text preview (repr):", repr(cleaned_text[:120]))

            if response_status != 200:
                print("⚠️ Non-200 status, stopping pagination.")
                break

            text_payload = _build_text_from_response(cleaned_text)

            if parser_name == "usaridetoday_ldjson":
                vehiculos_ldjson = _extract_vehicles_from_ldjson(text_payload)
                print(f"✅ Page {pagina_actual}: found {len(vehiculos_ldjson)} Vehicle objects in ld+json")

                agregados_en_pagina = 0
                for idx, vehiculo in enumerate(vehiculos_ldjson, start=1):
                    title = vehiculo.get("name")
                    year = vehiculo.get("vehicleModelDate")
                    modelo = vehiculo.get("model")

                    manufacturer = vehiculo.get("manufacturer")
                    if isinstance(manufacturer, dict):
                        marca = manufacturer.get("name", "")
                    else:
                        marca = manufacturer or ""

                    offers = vehiculo.get("offers") if isinstance(vehiculo.get("offers"), dict) else {}
                    price_value = offers.get("price")

                    url = vehiculo.get("url") or inventario_url
                    if not title:
                        continue

                    unique_key = build_unique_key(title, f"{year or ''}-{modelo or ''}", url)
                    carros_extraidos.append(
                        {
                            "title": title,
                            "property_type": "",
                            "location": modelo or "",
                            "description": f"Price: {price_value} | Link: {url}",
                            "source_url": url,
                            "unique_key": unique_key,
                            "year": str(year) if year is not None else "",
                            "modelo": modelo or "",
                            "marca": marca,
                            "precio_actual": price_value,
                        }
                    )
                    agregados_en_pagina += 1

                    print(
                        f"🚗 Page {pagina_actual} Vehicle {idx}: "
                        f"titulo={title!r}, year={year!r}, marca={marca!r}, modelo={modelo!r}, precio={price_value!r}"
                    )

                print(
                    f"✅ Page {pagina_actual} usaridetoday vehicles collected so far: "
                    f"{len(carros_extraidos)} (this page: {agregados_en_pagina})"
                )

            elif parser_name == "metacarstx_json":
                filas_inventario = _extract_metacarstx_rows(cleaned_text)
                print(f"✅ Page {pagina_actual}: found {len(filas_inventario)} metacarstx rows")
                if filas_inventario:
                    debug(
                        "sample row keys=" + ",".join(sorted(filas_inventario[0].keys()))
                    )
                else:
                    debug("metacarstx parser devolvió 0 filas")

                agregados_en_pagina = 0
                for idx, fila in enumerate(filas_inventario, start=1):
                    year = fila.get("ye") or fila.get("VehicleYear") or fila.get("Year")
                    marca = fila.get("ma") or fila.get("VehicleMake") or fila.get("Make") or ""
                    modelo = fila.get("mo") or fila.get("VehicleModel") or fila.get("Model") or ""
                    stock_no = fila.get("sn") or fila.get("StockNumber") or ""
                    vin = fila.get("vin") or fila.get("VIN") or ""
                    price_value = _to_float(
                        fila.get("pr")
                        or fila.get("Price")
                        or fila.get("SalePrice")
                        or fila.get("VehiclePrice")
                        or fila.get("AskingPrice")
                    )
                    detail_url = (
                        fila.get("vd")
                        or fila.get("DetailsUrl")
                        or fila.get("VehicleDetailsUrl")
                        or inventario_url
                    )

                    title = (
                        fila.get("ta")
                        or fila.get("Title")
                        or f"{year or ''} {marca} {modelo}".strip()
                    )
                    if not title:
                        continue

                    unique_key = build_unique_key(title, vin or stock_no, detail_url)
                    carros_extraidos.append(
                        {
                            "title": title,
                            "property_type": "",
                            "location": modelo,
                            "description": f"Price: {price_value if price_value is not None else ''} | Link: {detail_url}",
                            "source_url": detail_url,
                            "unique_key": unique_key,
                            "year": str(year) if year is not None else "",
                            "modelo": modelo,
                            "marca": marca,
                            "precio_actual": price_value,
                        }
                    )
                    agregados_en_pagina += 1

                    print(
                        f"🚙 Page {pagina_actual} Row {idx}: "
                        f"titulo={title!r}, year={year!r}, marca={marca!r}, modelo={modelo!r}, precio={price_value!r}"
                    )

                print(
                    f"✅ Page {pagina_actual} metacarstx vehicles collected so far: "
                    f"{len(carros_extraidos)} (this page: {agregados_en_pagina})"
                )

            else:
                try:
                    data = json.loads(cleaned_text)
                except Exception as e:
                    print(f"❌ json.loads failed on page {pagina_actual}:", repr(e))
                    break

                html_content = data.get("propiedades", "")
                if not html_content:
                    print(f"⚠️ Empty 'propiedades' on page {pagina_actual}, stopping.")
                    break

                soup = BeautifulSoup(html_content, "html.parser")
                cards = soup.find_all("a", class_="property-card")
                print(f"✅ Page {pagina_actual}: found {len(cards)} cards")

                if not cards:
                    print(f"⚠️ No cards on page {pagina_actual}.")

                carros_cortes_en_pagina = 0

                for idx, card in enumerate(cards, start=1):
                    title_elem = card.find("h2")
                    title = title_elem.get_text(strip=True) if title_elem else None

                    location_elem = card.find("span", class_="subtitle")
                    location = (
                        location_elem.get_text(strip=True) if location_elem else "Not specified"
                    )

                    price_elem = card.find("span", class_="price")
                    price = price_elem.get_text(strip=True) if price_elem else "No price"

                    link = card.get(
                        "href",
                        inventario_url,
                    )

                    print(
                        f"🏠 Page {pagina_actual} Card {idx}: "
                        f"title={title!r}, location={location!r}, price={price!r}"
                    )

                    loc_lower = location.lower()
                    if title and ("cortés" in loc_lower or "cortes" in loc_lower):
                        unique_key = build_unique_key(title, location, link)
                        carros_extraidos.append(
                            {
                                "title": title,
                                "property_type": "Cortés",
                                "location": location,
                                "description": f"Price: {price} | Link: {link}",
                                "source_url": link,
                                "unique_key": unique_key,
                            }
                        )
                        carros_cortes_en_pagina += 1

                print(
                    f"✅ Page {pagina_actual} Cortés properties collected so far: "
                    f"{len(carros_extraidos)} (this page: {carros_cortes_en_pagina})"
                )

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
