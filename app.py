import streamlit as st
import pandas as pd
import zipfile
import io

st.set_page_config(page_title="Reporte ETA/ATA por Shipment ID", layout="centered")
st.title("Reporte ETA/ATA por Shipment ID (estilo cliente)")

st.markdown(
    """
Esta app replica el enfoque de tu cliente usando **Shipment ID (columna A)** como identificador de BL:

1. Crea una columna **ETA/ATA**:
   - Usa **ATA** si existe y es válida.
   - Si no hay ATA válida, usa **ETA**.
   - Si no hay ninguna, el Shipment ID se considera **INVALIDO** para ese análisis.

2. Por cada **Shipment ID**:
   - Calcula la diferencia en **horas** entre la fecha/hora mínima y máxima de **ETA/ATA**.
   - Clasifica en:
     - `SIN_DIFERENCIA` (0 horas)
     - `ENTRE_1_Y_24_HORAS` (0 < diff ≤ 24)
     - `MAS_DE_24_HORAS` (diff > 24)
     - `INVALIDO` (sin timestamps válidos)
   - Repite el mismo análisis **solo con ETAs**.

3. Resúmenes:
   - Vista general (todos los Shipment ID) para:
     - ETA/ATA
     - Solo ETA
   - Vista por **naviera** (carrier) para ambas métricas.

Solo se consideran filas de **contenedores**
(`shipment_type` = CONTAINER / CONTAINER_ID).
"""
)

uploaded_file = st.file_uploader("Sube el CSV de movimientos", type=["csv"])


def clasificar_diferencia_horas(value):
    """Clasifica la diferencia en horas en buckets."""
    if value is None or pd.isna(value):
        return "INVALIDO"
    if value == 0:
        return "SIN_DIFERENCIA"
    if 0 < value <= 24:
        return "ENTRE_1_Y_24_HORAS"
    return "MAS_DE_24_HORAS"


def construir_resumen(df_group, bucket_col, metric_name, group_col=None):
    """
    Construye tabla resumen de buckets y porcentajes,
    opcionalmente segmentada por una columna (por ejemplo, carrier).
    La unidad es el Shipment ID (cada fila de df_group es un Shipment ID).
    """
    rows = []

    if group_col is not None:
        grouped = df_group.groupby(group_col, dropna=False)
        for group_value, sub in grouped:
            total_valid = len(sub[sub[bucket_col] != "INVALIDO"])
            counts = sub[bucket_col].value_counts(dropna=False).to_dict()

            for bucket, count in counts.items():
                if bucket == "INVALIDO" or total_valid == 0:
                    pct_valid = None
                else:
                    pct_valid = round((count / total_valid) * 100, 2)

                rows.append(
                    {
                        "metric": metric_name,
                        "group": group_value,
                        "bucket": bucket,
                        "description": bucket,
                        "count_shipments": int(count),
                        "pct_over_valid_shipments": pct_valid,
                    }
                )
    else:
        total_valid = len(df_group[df_group[bucket_col] != "INVALIDO"])
        counts = df_group[bucket_col].value_counts(dropna=False).to_dict()

        for bucket, count in counts.items():
            if bucket == "INVALIDO" or total_valid == 0:
                pct_valid = None
            else:
                pct_valid = round((count / total_valid) * 100, 2)

            rows.append(
                {
                    "metric": metric_name,
                    "group": None,
                    "bucket": bucket,
                    "description": bucket,
                    "count_shipments": int(count),
                    "pct_over_valid_shipments": pct_valid,
                }
            )

    return pd.DataFrame(
        rows,
        columns=[
            "metric",
            "group",
            "bucket",
            "description",
            "count_shipments",
            "pct_over_valid_shipments",
        ],
    )


if uploaded_file is not None:
    try:
        df = pd.read_csv(uploaded_file, dtype=str)
        df = df.fillna("")

        st.write(f"Archivo cargado con **{df.shape[0]} filas** y **{df.shape[1]} columnas**.")

        st.subheader("Mapeo de columnas")

        cols = list(df.columns)

        shipment_id_col = st.selectbox("Columna A: Shipment ID (BL para este análisis)", options=cols)
        identifier_col = st.selectbox("Columna de identificador de contenedor / fila", options=cols)
        shipment_type_col = st.selectbox("Columna de tipo de envío (shipment_type)", options=cols)
        eta_col = st.selectbox("Columna de ETA destino", options=cols)
        ata_col = st.selectbox("Columna de ATA destino", options=cols)
        carrier_col = st.selectbox("Columna de naviera / carrier", options=cols)

        if st.button("Ejecutar reporte (Shipment ID como BL) y generar ZIP"):
            work_df = df.copy()
            work_df["shipment_id"] = work_df[shipment_id_col].astype(str)
            work_df["identifier"] = work_df[identifier_col].astype(str)
            work_df["shipment_type"] = work_df[shipment_type_col].astype(str)
            work_df["eta"] = work_df[eta_col].astype(str)
            work_df["ata"] = work_df[ata_col].astype(str)
            work_df["carrier"] = work_df[carrier_col].astype(str)

            # Filtrar contenedores (CONTAINER / CONTAINER_ID)
            containers = work_df[
                work_df["shipment_type"].str.strip().str.upper().isin(["CONTAINER", "CONTAINER_ID"])
            ].copy()

            if containers.empty:
                st.warning(
                    "No se encontraron filas de contenedores. "
                    f"Busqué valores 'CONTAINER' o 'CONTAINER_ID' en la columna '{shipment_type_col}'."
                )
            else:
                st.info(
                    f"Se detectaron {len(containers)} filas de contenedores "
                    f"usando la columna '{shipment_type_col}'."
                )

                # Parseo de ETA y ATA como timestamps
                containers["eta_dt"] = pd.to_datetime(containers["eta"], errors="coerce")
                containers["ata_dt"] = pd.to_datetime(containers["ata"], errors="coerce")

                # Construir ETA/ATA: priorizar ATA, luego ETA
                containers["etaata_dt"] = containers.apply(
                    lambda r: r["ata_dt"] if pd.notna(r["ata_dt"]) else r["eta_dt"],
                    axis=1,
                )

                # Agrupación por Shipment ID (lo usamos como BL)
                grouped = containers.groupby("shipment_id", dropna=False)

                def carrier_mas_frecuente(serie):
                    m = serie.mode()
                    return m.iloc[0] if not m.empty else ""

                shipment_stats = grouped.agg(
                    carrier=("carrier", carrier_mas_frecuente),
                    n_containers=("identifier", "size"),
                    # Para ETA/ATA
                    n_etaata_present=("etaata_dt", lambda s: s.notna().sum()),
                    n_etaata_missing=("etaata_dt", lambda s: s.isna().sum()),
                    etaata_min=("etaata_dt", "min"),
                    etaata_max=("etaata_dt", "max"),
                    # Para solo ETA
                    n_eta_present=("eta_dt", lambda s: s.notna().sum()),
                    n_eta_missing=("eta_dt", lambda s: s.isna().sum()),
                    eta_min=("eta_dt", "min"),
                    eta_max=("eta_dt", "max"),
                ).reset_index()

                # Spread en horas (ETA/ATA y sólo ETA)
                shipment_stats["spread_hours_etaata"] = (
                    (shipment_stats["etaata_max"] - shipment_stats["etaata_min"])
                    .dt.total_seconds()
                    / 3600.0
                )
                shipment_stats["spread_hours_eta"] = (
                    (shipment_stats["eta_max"] - shipment_stats["eta_min"])
                    .dt.total_seconds()
                    / 3600.0
                )

                # Clasificación
                shipment_stats["spread_bucket_etaata"] = shipment_stats[
                    "spread_hours_etaata"
                ].apply(clasificar_diferencia_horas)
                shipment_stats["spread_bucket_eta"] = shipment_stats[
                    "spread_hours_eta"
                ].apply(clasificar_diferencia_horas)

                # Tablas por Shipment ID
                shipment_etaata_spread = shipment_stats[
                    [
                        "shipment_id",
                        "carrier",
                        "n_containers",
                        "n_etaata_present",
                        "n_etaata_missing",
                        "etaata_min",
                        "etaata_max",
                        "spread_hours_etaata",
                        "spread_bucket_etaata",
                    ]
                ].copy()

                shipment_eta_spread = shipment_stats[
                    [
                        "shipment_id",
                        "carrier",
                        "n_containers",
                        "n_eta_present",
                        "n_eta_missing",
                        "eta_min",
                        "eta_max",
                        "spread_hours_eta",
                        "spread_bucket_eta",
                    ]
                ].copy()

                # Resumen global (Shipment ID como unidad)
                summary_overall_etaata = construir_resumen(
                    shipment_etaata_spread,
                    bucket_col="spread_bucket_etaata",
                    metric_name="ETA_ATA",
                    group_col=None,
                )
                summary_overall_eta = construir_resumen(
                    shipment_eta_spread,
                    bucket_col="spread_bucket_eta",
                    metric_name="ETA_ONLY",
                    group_col=None,
                )
                summary_overall = pd.concat(
                    [summary_overall_etaata, summary_overall_eta], ignore_index=True
                )

                # Resumen por naviera
                summary_by_carrier_etaata = construir_resumen(
                    shipment_etaata_spread,
                    bucket_col="spread_bucket_etaata",
                    metric_name="ETA_ATA",
                    group_col="carrier",
                )
                summary_by_carrier_eta = construir_resumen(
                    shipment_eta_spread,
                    bucket_col="spread_bucket_eta",
                    metric_name="ETA_ONLY",
                    group_col="carrier",
                )
                summary_by_carrier = pd.concat(
                    [summary_by_carrier_etaata, summary_by_carrier_eta], ignore_index=True
                )

                # Construir ZIP en memoria
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr(
                        "shipment_etaata_spread.csv",
                        shipment_etaata_spread.to_csv(index=False).encode("utf-8"),
                    )
                    zf.writestr(
                        "shipment_eta_spread.csv",
                        shipment_eta_spread.to_csv(index=False).encode("utf-8"),
                    )
                    zf.writestr(
                        "summary_overall.csv",
                        summary_overall.to_csv(index=False).encode("utf-8"),
                    )
                    zf.writestr(
                        "summary_by_carrier.csv",
                        summary_by_carrier.to_csv(index=False).encode("utf-8"),
                    )

                zip_buffer.seek(0)

                st.success("Análisis completado. Puedes descargar el ZIP con todos los CSV.")
                st.download_button(
                    label="Descargar ZIP (reporte por Shipment ID)",
                    data=zip_buffer,
                    file_name="eta_ata_shipmentid_report.zip",
                    mime="application/zip",
                )

                st.subheader("Resumen global (vista rápida)")
                st.dataframe(summary_overall)

                st.subheader("Resumen por naviera (vista rápida)")
                st.dataframe(summary_by_carrier)

    except Exception as e:
        st.error(f"Error procesando el archivo: {e}")

else:
    st.info("Sube un archivo CSV para comenzar.")
