import pandas as pd

def money(value):
    """Thousands separators, two decimals, for labels."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if pd.isna(number):
        return ""
    return f"{number:,.2f}"

def hk(value):
    text = money(value)
    return f"HK$ {text}" if text else ""
