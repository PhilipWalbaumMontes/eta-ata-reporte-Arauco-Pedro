# app.py
import csv
from io import StringIO
import pandas as pd
import streamlit as st

# Índices 0-based por letra:
# A=0 B=1 C=2 D=3 E=4 F=5 G=6 H=7 I=8 J=9 K=10 L=11 M=12 N=13
IDX_SHIPMENT_ID = 0        # A
IDX_SHIPMENT_TYPE = 1      # B
IDX_ESTIMATED = 6          # G
IDX_ACTUAL = 7             # H
IDX_PRIORITIZED = 13       # N
MIN_COLS_A_TO_N = 14       # A..N

TARGET_TYPE = "BILL_OF_LADING"


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


def ensure_min_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Asegura al menos A..N (14 cols).
    Si faltan, agrega columnas hasta completar.
    """
    df = df.copy()
    missing = MIN_COLS_A_TO_N - df.shape[1]
    if missing <= 0:
        return df

    # Nombres sugeridos para J..N (en orden) si existen headers
    extra_names = ["Valid BoL", "Min", "Max", "Diferencia", "Valor priorizado"]

    # Si faltan 5, añadimos J..N; si faltan 4, añadimos K..N, etc.
    start_extra_idx = max(0, len(extra_names) - missing)
    for name in extra_names[start_extra_idx:]:
        df[name] = ""

    while df.shape[1] < MIN_COLS_A_TO_N:
        df[f"__extra_{df.shape[1]+1}__"] = ""

    return df


def count_unique_shipment_id_where_type_is_bol(df: pd.DataFrame) -> int:
    """
    Paso 1:
    Cuenta únicos de columna A (Shipment ID) SOLO donde columna B es BILL_OF_LADING,
    excluyendo blancos/NULL/solo espacios.
    """
    types = df.iloc[:, IDX_SHIPMENT_TYPE].apply(normalize_type)
    mask_bol = (types == TARGET_TYPE)

    ids = df.loc[mask_bol].iloc[:, IDX_SHIPMENT_ID]

    cleaned = []
    for v in ids.tolist():
        if is_blank(v):
            continue
        cleaned.append(str(v).strip())

    return int(pd.Series(cleaned).nunique(dropna=True))


def compute_prioritized_column(df: pd.DataFrame) -> pd.DataFrame:
    """
    Paso 2: Columna N (Valor priorizado)
    - Si H tiene valor -> N = H
    - Si no, si G tiene valor -> N = G
    - Si no -> "No Valido"
    (whitespace-only cuenta como blanco)
    """
    df = df.copy()
    g = df.iloc[:, IDX_ESTIMATED]
    h = df.iloc[:, IDX_ACTUAL]

    out = []
    for hv, gv in zip(h.tolist(), g.tolist()):
        if not is_blank(hv):
            out.append(str(hv).strip())
        elif not is_blank(gv):
            out.append(str(gv).strip())
        else:
            out.append("No Valido")

    df.iloc[:, IDX_PRIORITIZED] = out
    return df


def df_to_csv_bytes(df: pd.DataFrame, delimiter: str, include_header: bool) -> bytes:
    s = df.to_csv(index=False, sep=delimiter, header=include_header)
    # utf-8-sig ayuda a que Excel lo abra bien (tildes)
    return s.encode("utf-8-sig")


st.set_page_config(page_title="Reporte CSV - Tabla Resumen + Archivo completo", layout="wide")
st.title("Reporte (CSV): Tabla Resumen + Archivo completo")

st.write(
    """
**Reglas (solo lo pedido):**
1) Contar **Shipment ID únicos (columna A)** **solo** en filas donde **Shipment type (columna B)** es **BILL_OF_LADING**, excluyendo blancos/NULL/solo espacios.  
2) Calcular **columna N (Valor priorizado)**:
- Si **H** tiene valor → N = H  
- Si no, si **G** tiene valor → N = G  
- Si no → **No Valido**  
**Nota:** valores con solo espacios cuentan como blanco.
"""
)

uploaded = st.file_uploader("Sube tu archivo CSV", type=["csv"])
has_header = st.checkbox("Mi archivo tiene encabezados (header)", value=True)

if uploaded:
    raw_bytes = uploaded.getvalue()
    raw_text = raw_bytes.decode("utf-8-sig", errors="replace")

    detected_delim = sniff_delimiter(raw_text)
    delim = st.selectbox("Delimitador", options=[detected_delim, ",", ";", "\t", "|"], index=0)

    try:
        if has_header:
            df = pd.read_csv(StringIO(raw_text), sep=delim, dtype=str, keep_default_na=True)
        else:
            df = pd.read_csv(StringIO(raw_text), sep=delim, header=None, dtype=str, keep_default_na=True)

        df = ensure_min_columns(df)

        if df.shape[1] < MIN_COLS_A_TO_N:
