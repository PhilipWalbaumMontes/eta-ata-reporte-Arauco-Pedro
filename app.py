# app.py
import pandas as pd
import streamlit as st
from io import BytesIO

# Columnas por posición (0-based):
# A=0 B=1 C=2 ... G=6 H=7 ... N=13
IDX_BOL = 2
IDX_ESTIMATED = 6
IDX_ACTUAL = 7
IDX_PRIORITIZED = 13  # N

EXPECTED_MIN_COLS = 14  # A..N


def is_blank(x) -> bool:
    """Blanco si es NaN/None o whitespace-only (incluye ' ')."""
    if x is None:
        return True
    if pd.isna(x):
        return True
    return str(x).strip() == ""


def ensure_min_columns(df: pd.DataFrame, min_cols: int = EXPECTED_MIN_COLS) -> pd.DataFrame:
    """Asegura al menos A..N; si faltan columnas, las agrega vacías al final."""
    df = df.copy()
    missing = min_cols - df.shape[1]
    if missing > 0:
        for i in range(missing):
            df[f"__extra_{i+1}__"] = ""
    return df


def count_unique_bol_excluding_blanks(series: pd.Series) -> int:
    """Cuenta únicos en C excluyendo NULL/blancos/solo espacios (y normalizando con strip)."""
    cleaned = []
    for v in series.tolist():
        if v is None or (isinstance(v, float) and pd.isna(v)) or pd.isna(v):
            continue
        s = str(v).strip()
        if s == "":
            continue
        cleaned.append(s)
    return int(pd.Series(cleaned).nunique(dropna=True))


def apply_prioritized_value(df: pd.DataFrame) -> pd.DataFrame:
    """
    Columna N:
    - Si H tiene valor -> N = H
    - Si no, si G tiene valor -> N = G
    - Si no -> "No Valido"
    (whitespace-only cuenta como blanco)
    """
    df = df.copy()
    g = df.iloc[:, IDX_ESTIMATED]
    h = df.iloc[:, IDX_ACTUAL]

    prioritized = []
    for hv, gv in zip(h.tolist(), g.tolist()):
        if not is_blank(hv):
            prioritized.append(str(hv).strip())
        elif not is_blank(gv):
            prioritized.append(str(gv).strip())
        else:
            prioritized.append("No Valido")

    df.iloc[:, IDX_PRIORITIZED] = prioritized
    return df


def df_to_xlsx_bytes(df: pd.DataFrame, sheet_name: str) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return output.getvalue()


st.set_page_config(page_title="Reporte - Tabla Resumen + Archivo completo", layout="wide")
st.title("Reporte: Tabla Resumen + Archivo completo")

st.write(
    """
**Reglas:**
- Columna **C**: contar valores únicos **excluyendo** blancos/NULL/solo espacios.
- Columna **N (Valor priorizado)**:
  - Si **H** tiene valor → N = H
  - Si no, si **G** tiene valor → N = G
  - Si no → **No Valido**
- Valores con **solo espacios** se consideran **en blanco**.
"""
)

uploaded = st.file_uploader("Sube tu archivo Excel", type=["xlsx", "xls"])

if uploaded:
    try:
        xls = pd.ExcelFile(uploaded)
        sheet = st.selectbox("Selecciona la hoja a procesar", xls.sheet_names, index=0)

        df = pd.read_excel(xls, sheet_name=sheet, dtype=str, keep_default_na=True)
        df = ensure_min_columns(df, EXPECTED_MIN_COLS)

        if df.shape[1] < EXPECTED_MIN_COLS:
            st.error("El archivo no tiene suficientes columnas para llegar hasta la columna N (A..N).")
            st.stop()

        if st.button("Procesar"):
            unique_bols = count_unique_bol_excluding_blanks(df.iloc[:, IDX_BOL])
            df_out = apply_prioritized_value(df)

            # Tabla Resumen (archivo 1)
            resumen = pd.DataFrame([{
                "indicador": "Cantidad de valores únicos en columna C (Bill of lading) sin blancos",
                "valor": unique_bols
            }])

            st.success("Procesamiento listo.")
            st.metric("BOL únicos (C) sin blancos", unique_bols)

            # Bytes para descarga
            resumen_bytes = df_to_xlsx_bytes(resumen, "Tabla Resumen")
            completo_bytes = df_to_xlsx_bytes(df_out, "Archivo completo")

            col1, col2 = st.columns(2)
            with col1:
                st.download_button(
                    "Descargar Tabla Resumen.xlsx",
                    data=resumen_bytes,
                    file_name="Tabla Resumen.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            with col2:
                st.download_button(
                    "Descargar Archivo completo.xlsx",
                    data=completo_bytes,
                    file_name="Archivo completo.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

            with st.expander("Vista previa (primeras 20 filas)"):
                st.dataframe(df_out.head(20), use_container_width=True)

    except Exception as e:
        st.error(f"Error leyendo o procesando el archivo: {e}")
