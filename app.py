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
        # Si faltan 5 => agrega J..N; si faltan 4 => agrega K..N; etc.
        start = max(0, len(extra_names) - missing)
        for name in extra_names[start:]:
            df[name] = ""
    else:
        for i in range(missing):
            df[f"__extra_{i+1}__"] = ""

    while df.shape[1] < MIN_COLS_A_TO_N:
        df[f"__extra_{df.shape[1]+1}__"] = ""

    return df


def unique_shipment_ids_where_type_contains_bol(df: pd.DataFrame) -> list[str]:
    """
    Paso 1:
    Revisa todos los valores únicos de A (Shipment ID) SOLO donde B contiene BILL_OF_LADING.
    Excluye blancos/NULL/solo espacios.
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


def compute_valor_priorizado(df: pd.DataFrame) -> pd.DataFrame:
    """
    Paso 2:
    N (Valor priorizado) = H si existe, si no G, si no 'No Valido'
    (valores con solo espacios cuentan como blanco)
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
**Reglas (solo lo pedido):**
1) **Paso 1:** Revisar **Shipment ID únicos (col A)** donde **Shipment type (col B) contiene `BILL_OF_LADING`**  
   - excluye blancos/NULL/solo espacios  
2) **Paso 2:** Calcular **columna N (Valor priorizado)**  
   - si **H** tiene valor → N = H  
   - si no, si **G** tiene valor → N = G  
   - si no → `No Valido`
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
            # Paso 1
            unique_ids = unique_shipment_ids_where_type_contains_bol(df)
            unique_count = len(unique_ids)

            # Paso 2
            df_out = compute_valor_priorizado(df)

            # Archivo 1: Tabla Resumen (solo el conteo)
            resumen = pd.DataFrame([{
                "indicador": "Shipment ID únicos (col A) donde Shipment type (col B) contiene BILL_OF_LADING (sin blancos)",
                "valor": unique_count
            }])

            st.success("Listo.")
            st.metric("Shipment ID únicos filtrados", unique_count)

            # Para revisar (sin crear un 3er archivo)
            with st.expander("Ver lista de Shipment ID únicos filtrados"):
                st.dataframe(pd.DataFrame({"Shipment ID": unique_ids}), use_container_width=True)

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

            with st.expander("Vista previa (primeras 20 filas del Archivo completo)"):
                st.dataframe(df_out.head(20), use_container_width=True)

    except Exception as e:
        st.error(f"Error leyendo o procesando el CSV: {e}")
