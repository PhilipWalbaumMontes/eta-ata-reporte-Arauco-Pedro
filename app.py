import csv
import unicodedata
from io import StringIO

import pandas as pd
import streamlit as st

# Índices 0-based por letra:
# A=0 B=1 C=2 D=3 E=4 F=5 G=6 H=7 I=8 J=9 K=10 L=11 M=12 N=13 O=14
IDX_A_SHIPMENT_ID = 0
IDX_B_SHIPMENT_TYPE = 1
IDX_C_BOL = 2

IDX_G_ESTIMATED = 6
IDX_H_ACTUAL = 7

IDX_J_DIFF_HOURS = 9          # J = DIFERENCIA (horas)
IDX_K_MIN = 10                # K = Min (fecha)
IDX_L_MAX = 11                # L = Max (fecha)
IDX_N_PRIORITIZED = 13        # N = Valor priorizado (fecha)
IDX_O_RANGE = 14              # O = RANGO DIFERENCIA

MIN_COLS_A_TO_O = 15  # A..O


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
    Normaliza texto para comparar (ej: 'No Valido' vs 'no válido'):
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


def clean_bol_key(x) -> str:
    """Clave limpia para agrupar BOL (col C)."""
    if is_blank(x):
        return ""
    s = str(x).strip()
    if s.lower() == "nan":
        return ""
    return s


def ensure_min_columns(df: pd.DataFrame, has_header: bool) -> pd.DataFrame:
    """
    Asegura al menos A..O (15 columnas). Si faltan, agrega columnas vacías al final.
    """
    df = df.copy()
    missing = MIN_COLS_A_TO_O - df.shape[1]
    if missing <= 0:
        return df

    # J..O (6 columnas) cuando faltan:
    extra_names = ["DIFERENCIA", "Min", "Max", "Diferencia", "Valor priorizado", "RANGO DIFERENCIA"]

    if has_header:
        start = max(0, len(extra_names) - missing)
        for name in extra_names[start:]:
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

    while df.shape[1] < MIN_COLS_A_TO_O:
        df[f"__extra_{df.shape[1]+1}__"] = ""

    return df


def compute_valor_priorizado(df: pd.DataFrame) -> pd.DataFrame:
    """
    Columna N (Valor priorizado):
    - Si H tiene valor -> N = H
    - Si no, si G tiene valor -> N = G
    - Si no -> "No Valido"
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


def parse_dates(series: pd.Series, mode: str, dayfirst=None) -> pd.Series:
    """
    mode:
      - "MDY": month/day/year (dayfirst=False)
      - "DMY": day/month/year (dayfirst=True)
      - "AUTO": si dayfirst viene definido lo usa, si no decide por cantidad de parseos
    """
    if mode == "MDY":
        return pd.to_datetime(series, errors="coerce", dayfirst=False)
    if mode == "DMY":
        return pd.to_datetime(series, errors="coerce", dayfirst=True)

    # AUTO
    if dayfirst is not None:
        return pd.to_datetime(series, errors="coerce", dayfirst=dayfirst)

    dt_mdy = pd.to_datetime(series, errors="coerce", dayfirst=False)
    dt_dmy = pd.to_datetime(series, errors="coerce", dayfirst=True)
    return dt_dmy if dt_dmy.notna().sum() > dt_mdy.notna().sum() else dt_mdy


def fill_n_for_bol_from_containers(df: pd.DataFrame, date_mode: str) -> pd.DataFrame:
    """
    Ajuste requerido:
    Si una fila BILL_OF_LADING queda con N = "No Valido" (porque H/G están vacíos),
    entonces debe tomar una fecha desde sus contenedores (mismo C):

      1) Si hay al menos un container con H (ATA) válido -> usar la fecha MÍNIMA de H
      2) Si no, pero hay G (ETA) válido -> usar la fecha MÍNIMA de G
      3) Si no hay nada -> mantiene "No Valido"
    """
    df = df.copy()

    types_norm = df.iloc[:, IDX_B_SHIPMENT_TYPE].apply(normalize_type)
    mask_container = types_norm.str.contains("CONTAINER", na=False) & ~types_norm.str.contains("BILL_OF_LADING", na=False)
    mask_bol = types_norm.str.contains("BILL_OF_LADING", na=False)

    if mask_bol.sum() == 0 or mask_container.sum() == 0:
        return df

    bol_cont = df.loc[mask_container].iloc[:, IDX_C_BOL].apply(clean_bol_key)
    h_raw = df.loc[mask_container].iloc[:, IDX_H_ACTUAL]
    g_raw = df.loc[mask_container].iloc[:, IDX_G_ESTIMATED]

    def clean_date_str(v):
        if is_blank(v):
            return None
        if normalize_text_for_compare(v) == "no valido":
            return None
        return str(v).strip()

    h_clean = h_raw.apply(clean_date_str)
    g_clean = g_raw.apply(clean_date_str)

    dayfirst = None
    if date_mode == "AUTO":
        combined = pd.concat([h_clean, g_clean], ignore_index=True)
        dt_mdy = pd.to_datetime(combined, errors="coerce", dayfirst=False)
        dt_dmy = pd.to_datetime(combined, errors="coerce", dayfirst=True)
        dayfirst = dt_dmy.notna().sum() > dt_mdy.notna().sum()

    h_dt = parse_dates(h_clean, mode=date_mode, dayfirst=dayfirst)
    g_dt = parse_dates(g_clean, mode=date_mode, dayfirst=dayfirst)

    sub = pd.DataFrame({"bol": bol_cont, "h": h_clean, "g": g_clean, "h_dt": h_dt, "g_dt": g_dt})
    sub = sub[sub["bol"] != ""]

    bol_n_map = {}
    for bol_id, grp in sub.groupby("bol", sort=False):
        valid_h = grp[grp["h_dt"].notna()]
        if not valid_h.empty:
            min_dt = valid_h["h_dt"].min()
            bol_n_map[bol_id] = valid_h.loc[valid_h["h_dt"] == min_dt, "h"].iloc[0]
            continue

        valid_g = grp[grp["g_dt"].notna()]
        if not valid_g.empty:
            min_dt = valid_g["g_dt"].min()
            bol_n_map[bol_id] = valid_g.loc[valid_g["g_dt"] == min_dt, "g"].iloc[0]
            continue

        bol_n_map[bol_id] = "No Valido"

    n_col = df.columns[IDX_N_PRIORITIZED]

    bol_keys_bol = df.loc[mask_bol].iloc[:, IDX_C_BOL].apply(clean_bol_key)
    n_norm = df.loc[mask_bol, n_col].apply(normalize_text_for_compare)
    override = (n_norm == "") | (n_norm == "no valido")

    mapped = bol_keys_bol.map(bol_n_map)
    idx_override = df.loc[mask_bol].index[override]
    df.loc[idx_override, n_col] = mapped.loc[override].fillna("No Valido")

    return df


def min_max_from_row_g_h(g_val, h_val, date_mode: str) -> tuple[str, str]:
    """
    Para el caso especial (archivo con 1 solo valor único en C):
    calcula Min/Max usando SOLO las fechas de la misma fila (G y H).
    """
    def clean_date_cell(v):
        if is_blank(v):
            return None
        if normalize_text_for_compare(v) == "no valido":
            return None
        return str(v).strip()

    g_str = clean_date_cell(g_val)
    h_str = clean_date_cell(h_val)

    if g_str is None and h_str is None:
        return "No Valido", "No Valido"
    if g_str is not None and h_str is None:
        return g_str, g_str
    if g_str is None and h_str is not None:
        return h_str, h_str

    dt = parse_dates(pd.Series([g_str, h_str]), mode=date_mode)
    g_dt, h_dt = dt.iloc[0], dt.iloc[1]

    if pd.isna(g_dt) and pd.isna(h_dt):
        return "No Valido", "No Valido"
    if pd.isna(g_dt) and not pd.isna(h_dt):
        return h_str, h_str
    if not pd.isna(g_dt) and pd.isna(h_dt):
        return g_str, g_str

    if g_dt <= h_dt:
        return g_str, h_str
    return h_str, g_str


def compute_min_max_maps_from_containers(df: pd.DataFrame, date_mode: str):
    """
    Calcula mapas bol->min_str y bol->max_str usando SOLO filas contenedor (B contiene CONTAINER),
    agrupando por C, tomando fechas desde N (ignorando blancos y "No Valido").
    """
    types_norm = df.iloc[:, IDX_B_SHIPMENT_TYPE].apply(normalize_type)
    mask_container = types_norm.str.contains("CONTAINER", na=False) & ~types_norm.str.contains("BILL_OF_LADING", na=False)

    if mask_container.sum() == 0:
        return {}, {}

    bol = df.loc[mask_container].iloc[:, IDX_C_BOL].apply(clean_bol_key)
    n_raw = df.loc[mask_container].iloc[:, IDX_N_PRIORITIZED]

    n_clean = n_raw.apply(
        lambda v: None
        if (is_blank(v) or normalize_text_for_compare(v) == "no valido")
        else str(v).strip()
    )
    dt = parse_dates(n_clean, mode=date_mode)

    sub = pd.DataFrame({"bol": bol, "n": n_clean, "dt": dt})
    sub = sub[sub["bol"] != ""]

    min_map = {}
    max_map = {}

    for bol_id, g in sub.groupby("bol", sort=False):
        valid = g[g["dt"].notna()]
        if valid.empty:
            min_map[bol_id] = "No Valido"
            max_map[bol_id] = "No Valido"
            continue

        min_dt = valid["dt"].min()
        max_dt = valid["dt"].max()

        min_str = valid.loc[valid["dt"] == min_dt, "n"].iloc[0]
        max_str = valid.loc[valid["dt"] == max_dt, "n"].iloc[0]

        min_map[bol_id] = min_str
        max_map[bol_id] = max_str

    return min_map, max_map


def fill_k_l_for_container_rows(df: pd.DataFrame, min_map: dict, max_map: dict) -> pd.DataFrame:
    """Rellena K/L SOLO en filas contenedor usando col C como llave."""
    df = df.copy()
    types_norm = df.iloc[:, IDX_B_SHIPMENT_TYPE].apply(normalize_type)
    mask_container = types_norm.str.contains("CONTAINER", na=False) & ~types_norm.str.contains("BILL_OF_LADING", na=False)

    if mask_container.sum() == 0:
        return df

    bol_keys = df.loc[mask_container].iloc[:, IDX_C_BOL].apply(clean_bol_key)

    colK = df.columns[IDX_K_MIN]
    colL = df.columns[IDX_L_MAX]

    df.loc[mask_container, colK] = bol_keys.map(min_map).fillna("No Valido")
    df.loc[mask_container, colL] = bol_keys.map(max_map).fillna("No Valido")
    return df


def fill_k_l_for_bol_rows_from_containers(df: pd.DataFrame, min_map: dict, max_map: dict, date_mode: str) -> pd.DataFrame:
    """
    K/L para filas BILL_OF_LADING:

    - Si el archivo tiene SOLO 1 valor único (no vacío) en C:
        K/L desde su propia fila usando MIN/MAX entre G y H.
        (Si G/H no válidos, hace fallback a contenedores si existieran.)
    - Si el archivo tiene MÁS de 1 valor en C:
        K/L SIEMPRE desde contenedores (min_map/max_map), NO desde su propia fila.
    """
    df = df.copy()
    types_norm = df.iloc[:, IDX_B_SHIPMENT_TYPE].apply(normalize_type)
    mask_bol = types_norm.str.contains("BILL_OF_LADING", na=False)

    if mask_bol.sum() == 0:
        return df

    colK = df.columns[IDX_K_MIN]
    colL = df.columns[IDX_L_MAX]

    all_keys = df.iloc[:, IDX_C_BOL].apply(clean_bol_key)
    unique_nonblank_c = pd.unique(all_keys[all_keys != ""])
    only_one_unique_in_file = len(unique_nonblank_c) == 1

    if only_one_unique_in_file:
        bol_indexes = df.loc[mask_bol].index.tolist()
        k_values = []
        l_values = []

        for idx in bol_indexes:
            g_val = df.at[idx, df.columns[IDX_G_ESTIMATED]]
            h_val = df.at[idx, df.columns[IDX_H_ACTUAL]]
            mn, mx = min_max_from_row_g_h(g_val, h_val, date_mode=date_mode)

            if mn == "No Valido" and mx == "No Valido":
                key = clean_bol_key(df.at[idx, df.columns[IDX_C_BOL]])
                mn = min_map.get(key, "No Valido")
                mx = max_map.get(key, "No Valido")

            k_values.append(mn)
            l_values.append(mx)

        df.loc[mask_bol, colK] = pd.Series(k_values, index=bol_indexes).fillna("No Valido")
        df.loc[mask_bol, colL] = pd.Series(l_values, index=bol_indexes).fillna("No Valido")
        return df

    # Caso normal: más de 1 valor en C -> BOL toma min/max desde contenedores
    bol_keys = all_keys[mask_bol]
    df.loc[mask_bol, colK] = bol_keys.map(min_map).fillna("No Valido")
    df.loc[mask_bol, colL] = bol_keys.map(max_map).fillna("No Valido")
    return df


def fill_hours_diff_in_j(df: pd.DataFrame, date_mode: str) -> pd.DataFrame:
    """
    Columna J (DIFERENCIA):
    - Diferencia en horas entre L y K: (L - K) en horas
    - Si K/L no es fecha válida o es "No Valido" => J = "No Valido"
    """
    df = df.copy()

    k_raw = df.iloc[:, IDX_K_MIN]
    l_raw = df.iloc[:, IDX_L_MAX]

    k_clean = k_raw.apply(lambda v: None if (is_blank(v) or normalize_text_for_compare(v) == "no valido") else str(v).strip())
    l_clean = l_raw.apply(lambda v: None if (is_blank(v) or normalize_text_for_compare(v) == "no valido") else str(v).strip())

    dayfirst = None
    if date_mode == "AUTO":
        combined = pd.concat([k_clean, l_clean], ignore_index=True)
        dt_mdy = pd.to_datetime(combined, errors="coerce", dayfirst=False)
        dt_dmy = pd.to_datetime(combined, errors="coerce", dayfirst=True)
        dayfirst = dt_dmy.notna().sum() > dt_mdy.notna().sum()

    k_dt = parse_dates(k_clean, mode=date_mode, dayfirst=dayfirst)
    l_dt = parse_dates(l_clean, mode=date_mode, dayfirst=dayfirst)

    diff_hours = (l_dt - k_dt) / pd.Timedelta(hours=1)

    def fmt_hours(x):
        if pd.isna(x):
            return "No Valido"
        if abs(float(x) - round(float(x))) < 1e-9:
            return str(int(round(float(x))))
        return f"{float(x):.2f}"

    df.iloc[:, IDX_J_DIFF_HOURS] = diff_hours.apply(fmt_hours)
    return df


def fill_range_in_o(df: pd.DataFrame) -> pd.DataFrame:
    """
    Columna O (RANGO DIFERENCIA) usando J (DIFERENCIA en horas):
      - J == 0            => "0"
      - 0 < J <= 24       => "0 - 24 Hrs"
      - J > 24            => "+ de 24 Hrs"
      - inválido/No Valido => "No Valido"
    """
    df = df.copy()
    j_raw = df.iloc[:, IDX_J_DIFF_HOURS]

    def parse_hours(v):
        if is_blank(v) or normalize_text_for_compare(v) == "no valido":
            return None
        s = str(v).strip().replace(",", ".")
        try:
            return float(s)
        except Exception:
            return None

    def bucket(v):
        h = parse_hours(v)
        if h is None or h < 0:
            return "No Valido"
        if abs(h) < 1e-9:
            return "0"
        if h <= 24:
            return "0 - 24 Hrs"
        return "+ de 24 Hrs"

    df.iloc[:, IDX_O_RANGE] = j_raw.apply(bucket)
    return df


def build_summary_counts(df_out: pd.DataFrame) -> pd.DataFrame:
    """
    Tabla Resumen (solo filas BILL_OF_LADING, contadas por BL único = col A):
    - BL únicos
    - BL válidos (N != No Valido)
    - BLs con diferencia 0
    - BLs con diferencia 0 - 24 Hrs
    - BLs con diferencia + de 24 Hrs
    """
    types_norm = df_out.iloc[:, IDX_B_SHIPMENT_TYPE].apply(normalize_type)
    mask_bol = types_norm.str.contains("BILL_OF_LADING", na=False)

    if mask_bol.sum() == 0:
        return pd.DataFrame([
            {"indicador": "BL únicos", "valor": 0},
            {"indicador": "BL válidos", "valor": 0},
            {"indicador": "BLs con diferencia 0", "valor": 0},
            {"indicador": "BLs con diferencia 0 - 24 Hrs", "valor": 0},
            {"indicador": "BLs con diferencia + de 24 Hrs", "valor": 0},
        ])

    bol_df = df_out.loc[mask_bol].copy()

    bol_df["_bl_id"] = bol_df.iloc[:, IDX_A_SHIPMENT_ID].apply(lambda v: None if is_blank(v) else str(v).strip())
    bol_df = bol_df[bol_df["_bl_id"].notna()]
    bol_df = bol_df.drop_duplicates(subset=["_bl_id"], keep="first")

    bl_unicos = int(bol_df["_bl_id"].nunique())

    n_norm = bol_df.iloc[:, IDX_N_PRIORITIZED].apply(normalize_text_for_compare)
    bl_validos = int(((n_norm != "") & (n_norm != "no valido")).sum())

    o_val = bol_df.iloc[:, IDX_O_RANGE].apply(lambda v: "" if is_blank(v) else str(v).strip())
    diff_0 = int((o_val == "0").sum())
    diff_0_24 = int((o_val == "0 - 24 Hrs").sum())
    diff_gt_24 = int((o_val == "+ de 24 Hrs").sum())

    return pd.DataFrame([
        {"indicador": "BL únicos", "valor": bl_unicos},
        {"indicador": "BL válidos", "valor": bl_validos},
        {"indicador": "BLs con diferencia 0", "valor": diff_0},
        {"indicador": "BLs con diferencia 0 - 24 Hrs", "valor": diff_0_24},
        {"indicador": "BLs con diferencia + de 24 Hrs", "valor": diff_gt_24},
    ])


def to_csv_bytes(df: pd.DataFrame, sep: str, include_header: bool) -> bytes:
    return df.to_csv(index=False, sep=sep, header=include_header).encode("utf-8-sig")


# ---------------- Streamlit UI ----------------
st.set_page_config(page_title="Reporte CSV", layout="wide")
st.title("Reporte CSV: Tabla Resumen + Archivo completo")

uploaded = st.file_uploader("Sube tu archivo CSV", type=["csv"])
has_header = st.checkbox("Mi archivo tiene encabezados (header)", value=True)

if uploaded:
    raw_text = uploaded.getvalue().decode("utf-8-sig", errors="replace")
    detected = sniff_delimiter(raw_text)
    sep = st.selectbox("Delimitador", options=[detected, ",", ";", "\t", "|"], index=0)

    date_mode = st.selectbox(
        "Formato de fecha para cálculos (N/K/L)",
        options=["AUTO", "MDY", "DMY"],
        index=0,
    )

    try:
        if has_header:
            df = pd.read_csv(StringIO(raw_text), sep=sep, dtype=str, keep_default_na=True)
        else:
            df = pd.read_csv(StringIO(raw_text), sep=sep, header=None, dtype=str, keep_default_na=True)

        df = ensure_min_columns(df, has_header)

        if df.shape[1] < MIN_COLS_A_TO_O:
            st.error("El archivo no tiene suficientes columnas para llegar hasta la columna O (A..O).")
            st.stop()

        if st.button("Procesar"):
            df_out = compute_valor_priorizado(df)

            # ✅ NUEVO: si el BOL no tiene G/H, traer N desde contenedores del mismo C
            df_out = fill_n_for_bol_from_containers(df_out, date_mode=date_mode)

            min_map, max_map = compute_min_max_maps_from_containers(df_out, date_mode=date_mode)

            df_out = fill_k_l_for_container_rows(df_out, min_map=min_map, max_map=max_map)
            df_out = fill_k_l_for_bol_rows_from_containers(df_out, min_map=min_map, max_map=max_map, date_mode=date_mode)

            df_out = fill_hours_diff_in_j(df_out, date_mode=date_mode)
            df_out = fill_range_in_o(df_out)

            resumen = build_summary_counts(df_out)

            st.success("Listo.")

            st.subheader("Tabla Resumen")
            st.dataframe(resumen, use_container_width=True)

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

            with st.expander("Vista previa (primeras 20 filas)"):
                st.dataframe(df_out.head(20), use_container_width=True)

    except Exception as e:
        st.error(f"Error leyendo o procesando el CSV: {e}")
