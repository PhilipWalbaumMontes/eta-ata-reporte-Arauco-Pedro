import streamlit as st
import pandas as pd
import zipfile
import io

st.set_page_config(page_title="Reporte BL ETA/ATA (Shipment ID)", layout="centered")
st.title("Reporte ETA/ATA por Shipment ID / Bill of Lading")

st.markdown(
    """
Esta app asume que el CSV tiene SIEMPRE estos nombres de columna:

- `Shipment ID`
- `Shipment type`
- `Bill of lading`
- `Destination estimated arrival time`  (ETA destino)
- `Destination actual arrival time`    (ATA destino)

Lógica principal:

1. **Base de BL (#BL Totales Base)**  
   - Filas donde `Shipment type = Bill_of_lading` (sin importar mayúsculas/minúsculas).  
   - Cuenta los `Shipment ID` únicos (columna A).

2. **Filas de contenedores**  
   - `Shipment type` en {`CONTAINER`, `CONTAINER_ID`} (ignorando mayúsculas/minúsculas).

3. **Columna ETA/ATA (por contenedor)**  
   - Si `Destination actual arrival time` (ATA) no está vacía → usar ATA.  
   - Si ATA vacía y `Destination estimated arrival time` (ETA) no vacía → usar ETA.  
   - Si ambas vacías → `ETA/ATA Invalido`.

4. **Sólo filas de contenedores con ETA/ATA válida** (no `ETA/ATA Invalido`):  
   - Agrupa por **Shipment ID** (columna A).  
   - Calcula por cada Shipment ID:
     - `Min` = mínima ETA/ATA.  
     - `Max` = máxima ETA/ATA.  
     - `diferencia` = (Max − Min) en horas.  
     - `Rango`:
       - `Sin diferencia` → 0 horas  
       - `Menos de 24 Hrs` → 0 < diff ≤ 24  
       - `Mas de 24 Hrs` → diff > 24  

5. **Resumen (tabla_resumen_bls) a nivel Shipment ID**

   - **#BL Totales Base**  
     - `Shipment ID` únicos con `Shipment type = Bill_of_lading`.

   - **#BL Válidos (universo prueba)**  
     - Esos mismos `Shipment ID`, pero que tienen al menos un contenedor con ETA/ATA válida **y parseable como fecha/hora**.

   - **Diferencia (BL no válidos)**  
     - Base − Válidos.

   - **BL con diferencias ETA/ATA**  
     - BL válidos con `diferencia` > 1 minuto.

   - **BL diferencia de menos de 24 horas**  
     - 1 min < diff ≤ 24 h.

   - **BL diferencia de más de 24 horas**  
     - diff > 24 h.

   Los porcentajes son siempre sobre **#BL Válidos (universo prueba)**.
"""
)

uploaded_file = st.file_uploader("Sube el CSV de movimientos (export Movement)", type=["csv"])


def clasificar_rango(horas):
    """Clasifica la diferencia en horas en los rangos pedidos."""
    if horas is None or pd.isna(horas):
        return ""
    if horas == 0:
        return "Sin diferencia"
    if 0 < horas <= 24:
        return "Menos de 24 Hrs"
    return "Mas de 24 Hrs"


if uploaded_file is not None:
    try:
        # Leer como texto
        df = pd.read_csv(uploaded_file, dtype=str)
        df = df.fillna("")

        st.write(f"Archivo cargado con **{df.shape[0]} filas** y **{df.shape[1]} columnas**.")

        # ==== 1. Verificar columnas esperadas por NOMBRE ====
        required_cols = {
            "shipment_id": "Shipment ID",
            "shipment_type": "Shipment type",
            "bol": "Bill of lading",
            "eta": "Destination estimated arrival time",
            "ata": "Destination actual arrival time",
        }

        missing = [v for v in required_cols.values() if v not in df.columns]
        if missing:
            st.error(
                "No se encontraron todas las columnas esperadas.\n"
                f"Faltan: {missing}\n\n"
                "Columnas disponibles en el archivo:"
            )
            st.write(list(df.columns))
        else:
            col_shipment_id = required_cols["shipment_id"]
            col_shipment_type = required_cols["shipment_type"]
            col_bol = required_cols["bol"]
            col_eta = required_cols["eta"]
            col_ata = required_cols["ata"]

            st.write("Columnas detectadas correctamente por nombre:")
            st.write(f"- Shipment ID: **{col_shipment_id}**")
            st.write(f"- Shipment type: **{col_shipment_type}**")
            st.write(f"- Bill of lading: **{col_bol}**")
            st.write(f"- ETA destino: **{col_eta}**")
            st.write(f"- ATA destino: **{col_ata}**")

            # Normalizar Shipment type en mayúsculas para filtros
            stype_upper = df[col_shipment_type].astype(str).str.strip().str.upper()

            # ==== 2. #BL Totales Base (Shipment ID, filas Bill_of_lading) ====
            mask_header_bl = stype_upper == "BILL_OF_LADING"
            header_df = df.loc[mask_header_bl, [col_shipment_id, col_bol]].copy()
            header_df["shipment_id_norm"] = header_df[col_shipment_id].astype(str).str.strip()
            header_df["bol_norm"] = header_df[col_bol].astype(str).str.strip()

            base_shipments = header_df["shipment_id_norm"].unique()
            base_shipments_set = set(base_shipments)
            total_bl_base = len(base_shipments)

            st.subheader("#BL Totales Base (Shipment ID con Shipment type = Bill_of_lading)")
            st.metric("BL Totales Base (#BL Totales Base)", int(total_bl_base))

            # ==== 3. Filas de contenedores ====
            mask_containers = stype_upper.isin(["CONTAINER", "CONTAINER_ID"])
            containers = df.loc[mask_containers].copy()

            if containers.empty:
                st.warning(
                    "No se encontraron filas de contenedores (CONTAINER/CONTAINER_ID) "
                    f"en la columna '{col_shipment_type}'."
                )
            else:
                st.info(f"Se detectaron {len(containers)} filas de contenedores.")

                # ==== 4. Construir ETA/ATA (string) por contenedor ====
                containers["eta_str"] = containers[col_eta].astype(str).str.strip()
                containers["ata_str"] = containers[col_ata].astype(str).str.strip()

                # Prioriza ATA, luego ETA
                containers["etaata_str"] = containers["ata_str"]
                mask_etaata_blank = containers["etaata_str"] == ""
                containers.loc[mask_etaata_blank, "etaata_str"] = containers.loc[
                    mask_etaata_blank, "eta_str"
                ]

                # Inicializar ETA/ATA en todo el df
                df["ETA/ATA"] = "ETA/ATA Invalido"

                # Contenedores con ETA/ATA no vacía (válidos para análisis de presencia)
                mask_valid_etaata_str = (
                    containers["etaata_str"].notna()
                    & (containers["etaata_str"].str.strip() != "")
                )
                containers_valid = containers.loc[mask_valid_etaata_str].copy()

                st.write(
                    f"Contenedores con ETA/ATA no vacía (válidos para análisis): "
                    f"**{len(containers_valid)}**"
                )

                if containers_valid.empty:
                    st.warning("No hay contenedores con ETA/ATA no vacía (todos ETA/ATA Invalido).")
                else:
                    # Escribir ETA/ATA en df original
                    df.loc[containers_valid.index, "ETA/ATA"] = containers_valid["etaata_str"]

                    # ==== 5. Subconjunto 'valid' = contenedores con ETA/ATA válida (no Invalido) ====
                    mask_valid_rows = mask_containers & (df["ETA/ATA"] != "ETA/ATA Invalido")
                    valid = df.loc[mask_valid_rows].copy()

                    if valid.empty:
                        st.warning(
                            "No hay filas de contenedores con ETA/ATA válida después del filtrado."
                        )
                    else:
                        # Normalizar Shipment ID en 'valid'
                        valid["shipment_id_norm"] = (
                            valid[col_shipment_id].astype(str).str.strip()
                        )

                        # ==== 6. Parsear ETA/ATA a datetime y calcular Min/Max por Shipment ID ====
                        valid["etaata_dt"] = pd.to_datetime(
                            valid["ETA/ATA"], errors="coerce"
                        )

                        group_ship = valid.groupby("shipment_id_norm", dropna=False)
                        ship_stats = group_ship.agg(
                            containers_valid=("ETA/ATA", "size"),
                            min_dt=("etaata_dt", "min"),
                            max_dt=("etaata_dt", "max"),
                        ).reset_index()

                        # Diferencia en horas y rango
                        ship_stats["diferencia_horas"] = (
                            (ship_stats["max_dt"] - ship_stats["min_dt"]).dt.total_seconds()
                            / 3600.0
                        )
                        ship_stats["Rango"] = ship_stats["diferencia_horas"].apply(
                            clasificar_rango
                        )

                        # Min/Max en string
                        ship_stats["Min"] = ship_stats["min_dt"].dt.strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                        ship_stats["Max"] = ship_stats["max_dt"].dt.strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )

                        # ==== NUEVO: quedarnos sólo con Shipment ID donde min_dt y max_dt son parseables ====
                        ship_stats_valid = ship_stats[
                            ship_stats["min_dt"].notna() & ship_stats["max_dt"].notna()
                        ].copy()

                        # ---- DataFrame resumen por Shipment ID (para CSV) ----
                        resumen_por_bl = ship_stats_valid.rename(
                            columns={"shipment_id_norm": col_shipment_id}
                        )[
                            [
                                col_shipment_id,
                                "containers_valid",
                                "Min",
                                "Max",
                                "diferencia_horas",
                                "Rango",
                            ]
                        ].copy()

                        # ==== 7. Escribir Min/Max/diferencia/Rango en df detalle (a nivel contenedor) ====
                        # Merge por shipment_id_norm usando sólo ship_stats_valid
                        valid = valid.merge(
                            ship_stats_valid[
                                ["shipment_id_norm", "Min", "Max", "diferencia_horas", "Rango"]
                            ],
                            on="shipment_id_norm",
                            how="left",
                            suffixes=("", "_agg"),
                        )

                        # Copiar al df original
                        df.loc[valid.index, "Min"] = valid["Min"]
                        df.loc[valid.index, "Max"] = valid["Max"]
                        df.loc[valid.index, "diferencia"] = valid["diferencia_horas"]
                        df.loc[valid.index, "Rango"] = valid["Rango"]

                        # CSV detalle = solo contenedores con ETA/ATA válida
                        detalle = df.loc[valid.index].copy()

                        # ==== 8. Tabla resumen pedida (a nivel Shipment ID) ====

                        # 8.1 BL Totales Base: Shipment ID únicos con Shipment type = Bill_of_lading
                        total_bl_base = len(base_shipments)

                        # 8.2 BL válidos (universo prueba):
                        # Shipment ID de base que estén en ship_stats_valid
                        ship_valid_ids = ship_stats_valid["shipment_id_norm"].astype(str).unique()
                        ship_valid_ids_set = set(ship_valid_ids)

                        valid_shipments = list(base_shipments_set & ship_valid_ids_set)
                        total_bl_validos = len(valid_shipments)

                        # 8.3 Diferencia (BL no válidos) = base - válidos
