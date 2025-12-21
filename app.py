import csv
import unicodedata
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


def sniff_delimiter(text: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(text[:65536], delimiters=[",", ";", "\t", "|"])
        return dialect.delimiter
    except Exception:
        return ","


def is_blank(x) -> bool:
    """Blanco si es None/NaN o whitespace-only (incluye ' ')."""
    if x is None:
        return True
    try:
        if pd.isna(x):
            return True
    except Exception:
        pass
    return str(x).strip() == ""


def normalize_type(x) -> str:
    """Normaliza Shipment type para comparación robusta."""
    if is_blank(x):
        return ""
    return str(x).strip().upper().replace(" ", "_")


def normalize_text_for_compare(x) -> str:
    """
    Normaliza texto para comparar (por ejemplo 'No Valido' vs 'no válido'):
    - strip
    - lower
    - colapsa espacios
    - elimina tildes/acentos
    """
    if is_blank(x):
        return ""
    s = str(x).strip().lower()
    s = " ".join(s.split())
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s


def ensure_min_columns(df: pd.DataFrame, has_header: bool) -> pd.DataFrame:
    """
    Asegura al menos A..N (14 columnas). Si faltan, agrega columnas vacías al final.
    """
    df = df.copy()
    missing = MIN_COLS_A_TO_N - df.shape[1]
    if missing <= 0:
        return df

    # Nombres sugeridos para J..N cuando hay encabezados
    extra_names = ["Valid BoL", "Min", "Max", "Diferencia", "Valor priorizado"]

    if has_header:
        start = max(0, len(extra_names) - missing)
        for name in extra_names[start:]:
            # Evita choque si ya existe el nombre
            col_name = name
            if col_name in df.columns:
                i = 2
                while f"{col_name}_{i}" in df.columns:
                    i += 1
                col_name = f"{col_name}_{i}"
            df[col_name] = ""
    else:
        for i in range(missing):
            df[f"__extra_{i+1}__"] = ""

    while df.shape[1] < MIN_COLS_A_TO_N:
        df[f"__extra_{df.shape[1]+1}__"] = ""

    return df


def unique_ids_where_type_contains_bill_of_lading(df: pd.DataFrame) -> list[str]:
    """
    Lista de Shipment ID únicos (col A) donde Shipment type (col B)
    CONTIENE 'BILL_OF_LADING'. Excluye blancos en A.
    """
    types_norm = df.iloc[:, IDX_B_SHIPMENT_TYPE].apply(normalize_type)
    mask = types_norm.str.contains("BILL_OF_LADING", na=False)

    ids = df.loc[mask].iloc[:, IDX_A_SHIPMENT_ID]

    unique_ids = set()
    for v in ids.tolist():
        if is_blank(v):
            continue
        unique_ids.add(str(v).strip())

    return sorted(unique_ids)


def unique_ids_where_type_contains_bill_of_lading_and_n_is_no_valido(df: pd.DataFrame) -> list[str]:
    """
    Lista de Shipment ID únicos (col A) donde:
    - B contiene BILL_OF_LADING
    - N (Valor priorizado) == 'No Valido' (robusto a mayúsculas/tildes)
    Excluye blancos en A.
    """
    types_norm = df.iloc[:, IDX_B_SHIPMENT_TYPE].apply(normalize_type)
    mask_type = types_norm.str.contains("BILL_OF_LADING", na=False)

    n_norm = df.iloc[:, IDX_N_PRIORITIZED].apply(normalize_text_for_compare)
    mask_invalid = (n_norm == "no valido")

    ids = df.loc[mask_type & mask_invalid].iloc[:, IDX_A_SHIPMENT_ID]

    unique_ids = set()
    for v in ids.tolist():
        if is_blank(v):
            continue
        unique_ids.add(str(v).strip())

    return sorted(unique_ids)


def compute_valor_priorizado(df: pd.DataFrame) -> pd.DataFrame:
    """
    Columna N (Valor priorizado):
    - Si H tiene valor -> N = H
    - Si no, si G tiene valor -> N = G
    - Si no -> "No Valido"
    (whitespace-only cuenta como blanco)
    """
    df = df.copy()
    g = df.iloc[:, IDX_G_ESTIMATED]
    h = df.iloc[:, IDX_H_ACTUAL]

    out = []
    for hv, gv in zip(h.tolist(), g.tolist()):
        if not is_blank(hv):
            out.append(str(hv).strip())
        elif not is_blank(gv):
            out.append(str(gv).strip())
        else:
            out.append("No Valido")

    df.iloc[:, IDX_N_PRIORITIZED] = out
    return df


def to_csv_bytes(df: pd.DataFrame, sep: str, include_header: bool) -> bytes:
    return df.to_csv(index=False, sep=sep, header=include_header).encode("utf-8-sig")


# ---------------- Streamlit UI ----------------
st.set_page_config(page_title="Reporte CSV", layout="wide")
st.title("Reporte CSV: Tabla Resumen + Archivo completo")

st.markdown(
    """
**Reglas (incluye el nuevo Paso 3):**
1) **Paso 1:** BoL únicos = valores únicos de **col A** en filas donde **col B contiene `BILL_OF_LADING`** (excluye blancos).  
2) **Paso 2:** Calcula **col N (Valor priorizado)** = H si existe, si no G, si no `No Valido`.  
3) **Paso 3:** De los BoL únicos del Paso 1, **¿cuántos tienen col N = `No Valido`?**
"""
)

uploaded = st.file_uploader("Sube tu archivo CSV", type=["csv"])
has_header = st.checkbox("Mi archivo tiene encabezados (header)", value=True)

if uploaded:
    raw_text = uploaded.getvalue().decode("utf-8-sig", errors="replace")
    detected = sniff_delimiter(raw_text)
    sep = st.selectbox("Delimitador", options=[detected, ",", ";", "\t", "|"], index=0)

    try:
        if has_header:
            df = pd.read_csv(StringIO(raw_text), sep=sep, dtype=str, keep_default_na=True)
        else:
            df = pd.read_csv(StringIO(raw_text), sep=sep, header=None, dtype=str, keep_default_na=True)

        df = ensure_min_columns(df, has_header)

        if df.shape[1] < MIN_COLS_A_TO_N:
            st.error("El archivo no tiene suficientes columnas para llegar hasta la columna N (A..N).")
            st.stop()

        if st.button("Procesar"):
            # Paso 2 primero: calcular N
            df_out = compute_valor_priorizado(df)

            # Paso 1: BoL únicos (A) donde B contiene BILL_OF_LADING
            bol_unique_ids = unique_ids_where_type_contains_bill_of_lading(df_out)
            bol_unique_count = len(bol_unique_ids)

            # Paso 3: BoL únicos cuyo N = No Valido
            bol_invalid_ids = unique_ids_where_type_contains_bill_of_lading_and_n_is_no_valido(df_out)
            bol_invalid_count = len(bol_invalid_ids)

            # Tabla Resumen (2 métricas)
            resumen = pd.DataFrame([
                {
                    "indicador": "BoL únicos (col A) donde Shipment type (col B) contiene BILL_OF_LADING (sin blancos)",
                    "valor": bol_unique_count,
                },
                {
                    "indicador": "De esos BoL únicos, cuántos tienen Valor priorizado (col N) = No Valido",
                    "valor": bol_invalid_count,
                },
            ])

            st.success("Listo.")
            c1, c2 = st.columns(2)
            with c1:
                st.metric("BoL únicos (A con B contiene BILL_OF_LADING)", bol_unique_count)
            with c2:
                st.metric("BoL únicos con N = No Valido", bol_invalid_count)

            # Descargas (2 archivos)
            st.download_button(
                "Descargar Tabla Resumen.csv",
                data=to_csv_bytes(resumen, sep=",", include_header=True),
                file_name="Tabla Resumen.csv",
                mime="text/csv",
            )

            st.download_button(
                "Descargar Archivo completo.csv",
                data=to_csv_bytes(df_out, sep=sep, include_header=has_header),
                file_name="Archivo completo.csv",
                mime="text/csv",
            )

            with st.expander("Ver BoL únicos (filtrados)"):
                st.dataframe(pd.DataFrame({"BoL (Shipment ID col A)": bol_unique_ids}), use_container_width=True)

            with st.expander("Ver BoL únicos con N = No Valido"):
                st.dataframe(pd.DataFrame({"BoL (Shipment ID col A)": bol_invalid_ids}), use_container_width=True)

            with st.expander("Vista previa (primeras 20 filas del Archivo completo)"):
                st.dataframe(df_out.head(20), use_container_width=True)

    except Exception as e:
        st.error(f"Error leyendo o procesando el CSV: {e}")
