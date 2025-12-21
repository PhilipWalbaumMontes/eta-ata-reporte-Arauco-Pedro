# app.py
import csv
from io import BytesIO, StringIO
from pathlib import Path

import pandas as pd
import streamlit as st

# Índices 0-based por letra:
# A=0 B=1 C=2 D=3 E=4 F=5 G=6 H=7 I=8 J=9 K=10 L=11 M=12 N=13
IDX_BOL = 2
IDX_ESTIMATED = 6
IDX_ACTUAL = 7
IDX_PRIORITIZED = 13  # N
MIN_COLS_A_TO_N = 14  # A..N


def sniff_delimiter(raw_text: str) -> str:
    sample = raw_text[:65536]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", ";", "\t", "|"])
        return dialect.delimiter
    except Exception:
        # fallback
        return ","


def is_blank(x) -> bool:
    """Blanco si es NaN/None o whitespace-only (incluye ' ')."""
    if x is None:
        return True
    if pd.isna(x):
        return True
    return str(x).strip() == ""


def ensure_min_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Asegura al menos A..N (14 cols).
    Si faltan, agrega columnas J..N con nombres correctos (si hay headers).
    """
    df = df.copy()
    missing = MIN_COLS_A_TO_N - df.shape[1]
    if missing <= 0:
        return df

    # Nombres sugeridos para J..N (en orden)
    extra_names = ["Valid BoL", "Min", "Max", "Diferencia", "Valor priorizado"]
    # Determinar desde qué columna extra partimos (si faltan varias)
    # Si df tiene 9 columnas (A..I), faltan 5 => añadimos J..N completos.
    # Si df tiene 10 columnas, faltan 4 => añadimos K..N, etc.
    start_extra_idx = max(0, len(extra_names) - missing)

    for name in extra_names[start_extra_idx:]:
        df[name] = ""

    # Si aún faltara algo por un caso raro, completa genérico
    while df.shape[1] < MIN_COLS_A_TO_N:
        df[f"__extra_{df.shape[1]+1}__"] = ""

    return df


def count_unique_bol_excluding_blanks(series_c: pd.Series) -> int:
    """
    Cuenta únicos en columna C excluyendo:
    - NaN/None
    - "" o whitespace-only
    Normaliza usando strip() para evitar que "ABC" y "ABC " cuenten distinto.
    """
    vals = []
    for v in series_c.tolist():
        if is_blank(v):
            continue
        vals.append(str(v).strip())
    return int(pd.Series(vals).nunique(dropna=True))


def compute_prioritized_column(df: pd.DataFrame) -> pd.DataFrame:
    """
    Columna N:
    - Si H tiene valor -> N = H
    - Si no, si G tiene valor -> N = G
    - Si no -> "No Valido"
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
    # utf-8-sig para que Excel lo abra bien (especialmente tildes)
    return s.encode("utf-8-sig")


st.set_page_config(page_title="Reporte CSV - Tabla Resumen + Archivo completo", layout="wide")
st.title("Reporte (CSV): Tabla Resumen + Archivo completo")

st.write(
    """
**Reglas:**
1) Contar valores únicos en **columna C (Bill of lading)** excluyendo blancos/NULL/solo espacios.  
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
    # Leer bytes -> texto (con tolerancia a BOM)
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

        if st.button("Procesar"):
            # 1) Conteo únicos en C (excluyendo blancos)
            unique_count = count_unique_bol_excluding_blanks(df.iloc[:, IDX_BOL])

            # 2) Columna N (Valor priorizado)
            df_out = compute_prioritized_column(df)

            # Archivo 1: Tabla Resumen
            resumen = pd.DataFrame([{
                "indicador": "Cantidad de valores únicos en columna C (Bill of lading) sin blancos",
                "valor": unique_count
            }])

            # Convertir a bytes para descarga
            resumen_bytes = df_to_csv_bytes(resumen, delimiter=",", include_header=True)
            completo_bytes = df_to_csv_bytes(df_out, delimiter=delim, include_header=has_header)

            st.success("Listo.")
            st.metric("BOL únicos (columna C) sin blancos", unique_count)

            c1, c2 = st.columns(2)
            with c1:
                st.download_button(
                    "Descargar Tabla Resumen.csv",
                    data=resumen_bytes,
                    file_name="Tabla Resumen.csv",
                    mime="text/csv",
                )
            with c2:
                st.download_button(
                    "Descargar Archivo completo.csv",
                    data=completo_bytes,
                    file_name="Archivo completo.csv",
                    mime="text/csv",
                )

            with st.expander("Vista previa (primeras 20 filas del Archivo completo)"):
                st.dataframe(df_out.head(20), use_container_width=True)

    except Exception as e:
        st.error(f"Error leyendo o procesando el CSV: {e}")
