import streamlit as st
import pandas as pd
import zipfile
import io

st.set_page_config(page_title="Reporte BL ETA/ATA", layout="centered")
st.title("Reporte ETA/ATA por Bill of Lading / Shipment ID")

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
   - Agrupa por `Bill of lading` (columna C).  
   - Calcula por BoL:
     - `Min` = mínima ETA/ATA.  
     - `Max` = máxima ETA/ATA.  
     - `diferencia` = (Max − Min) en horas.  
     - `Rango`:
       - `Sin diferencia` → 0 horas  
       - `Menos de 24 Hrs` → 0 < diff ≤ 24  
       - `Mas de 24 Hrs` → diff > 24  

5. **Resumen a nivel Shipment ID (tabla resumen)**

   - **#BL Totales Base**  
     - `Shipment ID` únicos con `Shipment type = Bill_of_lading`.

   - **#BL Válidos (universo prueba)**  
     - Esos mismos `Shipment ID`, pero cuyos BoL (columna C) tienen al menos un contenedor con ETA/ATA válida.

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


def clasificar_rango(horas: float | None) -> str:
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
                df["ETA/ATA"] = "ETA/ATA Invalido
