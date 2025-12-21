import csv
from io import StringIO
import pandas as pd
import streamlit as st

# Índices 0-based por letra:
# A=0 B=1 C=2 D=3 E=4 F=5 G=6 H=7 I=8 J=9 K=10 L=11 M=12 N=13
IDX_A_SHIPMENT_ID = 0
IDX_B_SHIPMENT_TYPE = 1
IDX_G_ESTIMATED = 6
IDX_H_ACTUAL = 7
IDX_N_PRIORITIZED = 13

MIN_COLS_A_TO_N = 14  # A..N


def sniff_delimiter(raw_text: str) -> str:
    sample = raw_text[:65536]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", ";", "\t", "|"])
        return dialect.delimiter
    except Exception:
        return ","


def is_blank(x) -> bool:
    """Blanco si es NaN/None o whitespace-only (incluye ' ')."""
    if x is None:
        return True
    if pd.isna(x):
        return True
    return str(x).strip() == ""


def normalize_type(x) -> str:
    """
    Normaliza Shipment type para comparación robusta:
    - strip
    - upper
    - espacios -> underscore
    """
    if is_blank(x):
        return ""
    return str(x).strip().upper().replace(" ", "_")


def ensure_min_columns(df: pd.DataFrame, has_header: bool) -> pd.DataFrame:
    """
    Asegura al menos A..N (14 columnas).
    Si faltan, agrega columnas al final para completar hasta N.
    """
    df = df.copy()
    missing = MIN_COLS_A_TO_N - df.shape[1]
    if missing <= 0:
        return df

    # Si hay headers, intentamos agregar nombres reales J..N cuando corresponda
    extra_names = ["Valid BoL", "Min", "Max", "Diferencia", "Valor priorizado"]

    if has_header:
        # Si faltan 5 => agregamos J..N completos; si faltan 4 => K..N; etc.
        start_extra_idx = max(0, len(extra_names) - missing)
        for name in extr
