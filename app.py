import streamlit as st
import pandas as pd
import zipfile
import io

st.set_page_config(page_title="Reporte BL ETA/ATA", layout="centered")
st.title("Reporte ETA/ATA por Bill of Lading")

st.markdown(
    """
Esta app:

1. Cuenta la cantidad de **Bill of Lading** usando:
   - Columna A = `Shipment ID`
   - Columna B = `Shipment type`
   - Considera filas donde `Shipment type = Bill_of_lading`.

2. Para filas de **contenedores** (`Shipment type = CONTAINER / CONTAINER_ID`):
   - Construye una columna **ETA/ATA**:
     - Si AK (Destination actual arrival time) es válida → usa AK.
     - Si no, pero AJ (Destination estimated arrival time) es válida → usa AJ.
     - Si ninguna es válida → `BL Invalido`.

3. Solo con filas donde `ETA/ATA` tiene un valor (no `BL Invalido`):
   - Agrupa por **Bill of lading** (columna C).
   - Calcula:
     - `Min` = fecha/hora mínima ETA/ATA por BL.
     - `Max` = fecha/hora máxima ETA/ATA por BL.
     - `diferencia` = (Max - Min) en horas.
     - `Rango`:
       - `Sin diferencia` → 0 horas
       - `Menos de 24 Hrs` → 0 < diff ≤ 24
       - `Mas de 24 Hrs` → diff > 24

4. Genera un ZIP con:
   - `detalle_eta_ata_por_contenedor.csv` (detalle por contenedor, sólo válidos)
   - `resumen_por_bl.csv` (una fila por Bill of lading)
"""
)

uploaded_file = st.file_uploader("Sube el CSV de movimientos (export Movement)", type=["csv"])


def clasificar_rango(horas):
    if horas is None or pd.isna(horas):
        return ""
    if horas == 0:
        return "Sin diferencia"
    if 0 < horas <= 24:
        return "Menos de 24 Hrs"
    return "Mas de 24 Hrs"


if uploaded_file is not None:
    try:
        # Leer todo como string
        df = pd.read_csv(uploaded_file, dtype=str)
        df = df.fillna("")

        st.write(f"Archivo cargado con **{df.shape[0]} filas** y **{df.shape[1]} columnas**.")

        # === MAPEO FIJO POR POSICIÓN ===
        # A: Shipment ID  (índice 0)
        # B: Shipment type (índice 1)
        # C: Bill of lading (índice 2)
        # AJ: Destination estimated arrival time (índice 35)
        # AK: Destination actual arrival time (índice 36)

        if df.shape[1] <= 36:
            st.error(
                "El archivo debe tener al menos 37 columnas para que existan A, B, C, AJ y AK "
                "(Shipment ID, Shipment type, Bill of lading, ETA, ATA)."
            )
        else:
            col_shipment_id = df.columns[0]
            col_shipment_type = df.columns[1]
            col_bol = df.columns[2]
            col_eta = df.columns[35]
            col_ata = df.columns[36]

            st.write("Columnas detectadas (por posición):")
            st.write(f"- Shipment ID (A): **{col_shipment_id}**")
            st.write(f"- Shipment type (B): **{col_shipment_type}**")
            st.write(f"- Bill of lading (C): **{col_bol}**")
            st.write(f"- ETA destino (AJ): **{col_eta}**")
            st.write(f"- ATA destino (AK): **{col_ata}**")

            # === PASO 1: contar BL únicos (Shipment ID, filas Bill_of_lading) ===
            mask_bl_header = df[col_shipment_type].str.strip().str.upper() == "BILL_OF_LADING"
            total_bls = df.loc[mask_bl_header, col_shipment_id].nunique()

            st.subheader("Resumen de Bill of Lading (usando Shipment ID)")
            st.write(f"Cantidad de BL únicos (Shipment ID donde Shipment type = 'Bill_of_lading'):")
            st.metric(label="BL únicos", value=int(total_bls))

            # === FILAS DE CONTENEDORES ===
            mask_containers = df[col_shipment_type].str.strip().str.upper().isin(
                ["CONTAINER", "CONTAINER_ID"]
            )
            containers = df.loc[mask_containers].copy()

            if containers.empty:
                st.warning(
                    "No se encontraron filas de contenedores (CONTAINER/CONTAINER_ID) "
                    f"en la columna '{col_shipment_type}'."
                )
            else:
                st.info(
                    f"Se detectaron {len(containers)} filas de contenedores."
                )

                # === PASO 2: ETA/ATA ===
                containers["eta_dt"] = pd.to_datetime(containers[col_eta], errors="coerce")
                containers["ata_dt"] = pd.to_datetime(containers[col_ata], errors="coerce")

                # ETA/ATA interna
                containers["etaata_dt"] = containers["ata_dt"].where(
                    containers["ata_dt"].notna(), containers["eta_dt"]
                )

                # Inicializar columna ETA/ATA en df completo
                df["ETA/ATA"] = "BL Invalido"

                # Filas de contenedores con ETA/ATA válida
                mask_valid_etaata = containers["etaata_dt"].notna()
                containers_valid = containers.loc[mask_valid_etaata].copy()

                if containers_valid.empty:
                    st.warning("No hay contenedores con ETA/ATA válida (todas son BL Invalido).")
                else:
                    containers_valid["ETA_ATA_str"] = containers_valid["etaata_dt"].dt.strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )

                    # Escribir ETA/ATA en df original
                    df.loc[containers_valid.index, "ETA/ATA"] = containers_valid["ETA_ATA_str"]

                    # === PASO 3: Min y Max por BoL (C) sólo para filas con ETA/ATA válida ===
                    mask_valid_rows = mask_containers & (df["ETA/ATA"] != "BL Invalido")
                    valid = df.loc[mask_valid_rows].copy()

                    if valid.empty:
                        st.warning(
                            "No hay filas de contenedores con ETA/ATA válida después del filtrado."
                        )
                    else:
                        # Convertir ETA/ATA a datetime
                        valid["etaata_dt"] = pd.to_datetime(valid["ETA/ATA"], errors="coerce")

                        group = valid.groupby(col_bol, dropna=False)
                        min_dt_by_bl = group["etaata_dt"].transform("min")
                        max_dt_by_bl = group["etaata_dt"].transform("max")

                        valid["Min"] = min_dt_by_bl
                        valid["Max"] = max_dt_by_bl

                        # === PASO 4: diferencia en horas ===
                        valid["diferencia_timedelta"] = valid["Max"] - valid["Min"]
                        valid["diferencia"] = (
                            valid["diferencia_timedelta"].dt.total_seconds() / 3600.0
                        )

                        # === PASO 5: Rango ===
                        valid["Rango"] = valid["diferencia"].apply(clasificar_rango)

                        # Formatear Min/Max a string para el CSV
                        valid["Min"] = valid["Min"].dt.strftime("%Y-%m-%d %H:%M:%S")
                        valid["Max"] = valid["Max"].dt.strftime("%Y-%m-%d %H:%M:%S")

                        # Escribir columnas nuevas de vuelta en df (sólo para índices válidos)
                        df.loc[valid.index, "Min"] = valid["Min"]
                        df.loc[valid.index, "Max"] = valid["Max"]
                        df.loc[valid.index, "diferencia"] = valid["diferencia"]
                        df.loc[valid.index, "Rango"] = valid["Rango"]

                        # === CSV DETALLE: sólo contenedores con ETA/ATA válida ===
                        detalle = df.loc[valid.index].copy()

                        # === CSV RESUMEN POR BL (C) ===
                        resumen = (
                            valid.groupby(col_bol, dropna=False)
                            .agg(
                                shipment_id_count=(col_shipment_id, "nunique"),
                                containers_valid=("etaata_dt", "size"),
                                Min=("Min", "first"),
                                Max=("Max", "first"),
                                diferencia_horas=("diferencia", "first"),
                                Rango=("Rango", "first"),
                            )
                            .reset_index()
                        )

                        # === CONSTRUIR ZIP EN MEMORIA ===
                        zip_buffer = io.BytesIO()
                        with zipfile.ZipFile(
                            zip_buffer, "w", compression=zipfile.ZIP_DEFLATED
                        ) as zf:
                            zf.writestr(
                                "detalle_eta_ata_por_contenedor.csv",
                                detalle.to_csv(index=False).encode("utf-8-sig"),
                            )
                            zf.writestr(
                                "resumen_por_bl.csv",
                                resumen.to_csv(index=False).encode("utf-8-sig"),
                            )

                        zip_buffer.seek(0)

                        st.success("Análisis completado. Puedes descargar el ZIP con los dos CSV.")
                        st.download_button(
                            label="Descargar ZIP (detalle + resumen)",
                            data=zip_buffer,
                            file_name="reporte_bl_eta_ata.zip",
                            mime="application/zip",
                        )

                        st.subheader("Resumen por BL (vista rápida)")
                        st.dataframe(resumen.head(50))

    except Exception as e:
        st.error(f"Error procesando el archivo: {e}")

else:
    st.info("Sube un archivo CSV para comenzar.")
