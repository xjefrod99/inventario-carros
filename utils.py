import re


price_pattern = re.compile(r"Price:\s*(.*?)\s*\|")


def extract_numeric_price(description: str):
    """Parse numeric price from 'Price: Lx,xxx.xx | Link: ...'."""
    if not description:
        return None
    m = price_pattern.search(description)
    if not m:
        return None
    raw = m.group(1)
    clean = re.sub(r"[^0-9.,]", "", raw).replace(",", "")
    try:
        return float(clean)
    except ValueError:
        return None
