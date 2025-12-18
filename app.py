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

                # Contenedores con ETA/ATA no vacía (válidos para análisis)
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

                    # ==== 5. Subconjunto 'valid' = contenedores con ETA/ATA válida ====
                    mask_valid_rows = mask_containers & (df["ETA/ATA"] != "ETA/ATA Invalido")
                    valid = df.loc[mask_valid_rows].copy()

                    if valid.empty:
                        st.warning(
                            "No hay filas de contenedores con ETA/ATA válida después del filtrado."
                        )
                    else:
                        # Normalizar BoL en 'valid'
                        valid["bol_norm"] = valid[col_bol].astype(str).str.strip()

                        # ==== 6. Parsear ETA/ATA a datetime y calcular Min/Max por BoL (col C) ====
                        valid["etaata_dt"] = pd.to_datetime(
                            valid["ETA/ATA"], errors="coerce"
                        )

                        group_bol = valid.groupby("bol_norm", dropna=False)
                        bol_stats = group_bol.agg(
                            shipment_id_count=(col_shipment_id, lambda s: s.astype(str).str.strip().nunique()),
                            containers_valid=("ETA/ATA", "size"),
                            min_dt=("etaata_dt", "min"),
                            max_dt=("etaata_dt", "max"),
                        ).reset_index()

                        bol_stats["diferencia_horas"] = (
                            (bol_stats["max_dt"] - bol_stats["min_dt"]).dt.total_seconds()
                            / 3600.0
                        )
                        bol_stats["Rango"] = bol_stats["diferencia_horas"].apply(clasificar_rango)

                        # Convertir Min/Max a string
                        bol_stats["Min"] = bol_stats["min_dt"].dt.strftime("%Y-%m-%d %H:%M:%S")
                        bol_stats["Max"] = bol_stats["max_dt"].dt.strftime("%Y-%m-%d %H:%M:%S")

                        # ---- DataFrame resumen por BoL (para CSV) ----
                        resumen_por_bl = bol_stats.rename(columns={"bol_norm": col_bol})[
                            [
                                col_bol,
                                "shipment_id_count",
                                "containers_valid",
                                "Min",
                                "Max",
                                "diferencia_horas",
                                "Rango",
                            ]
                        ].copy()

                        # ==== 7. Escribir Min/Max/diferencia/Rango en df detalle (a nivel contenedor) ====
                        # Hacemos un merge por bol_norm
                        valid = valid.merge(
                            bol_stats[["bol_norm", "Min", "Max", "diferencia_horas", "Rango"]],
                            on="bol_norm",
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
                        # Shipment ID de base que estén asociados a un BoL con ETA/ATA válida

                        # Set de BoL válidos (BoL que aparecen en bol_stats)
                        valid_bols_set = set(bol_stats["bol_norm"].astype(str).unique())

                        # Filtramos cabeceras para Shipment ID - BoL y nos quedamos con los válidos
                        header_norm = header_df[["shipment_id_norm", "bol_norm"]].drop_duplicates()
                        valid_shipments = header_norm[
                            header_norm["bol_norm"].astype(str).isin(valid_bols_set)
                        ]["shipment_id_norm"].unique()

                        total_bl_validos = len(valid_shipments)

                        # 8.3 Diferencia (BL no válidos) = base - válidos
                        total_bl_no_validos = total_bl_base - total_bl_validos

                        # 8.4 Diferencias por Shipment ID (usando diferencia_horas del BoL)
                        # Merge: Shipment ID (cabecera) + bol_norm + diferencia_horas (por BoL)
                        ship_bol_diff = header_norm.merge(
                            bol_stats[["bol_norm", "diferencia_horas"]],
                            on="bol_norm",
                            how="left",
                        )

                        # Nos quedamos solo con los Shipment ID válidos (universo prueba)
                        ship_bol_diff = ship_bol_diff[
                            ship_bol_diff["shipment_id_norm"].isin(valid_shipments)
                        ].drop_duplicates(subset=["shipment_id_norm"])

                        # Umbral de 1 minuto en horas
                        one_minute_hours = 1.0 / 60.0

                        bl_con_diferencias = (
                            ship_bol_diff["diferencia_horas"] > one_minute_hours
                        ).sum()

                        bl_diff_menor_24 = (
                            (ship_bol_diff["diferencia_horas"] > one_minute_hours)
                            & (ship_bol_diff["diferencia_horas"] <= 24)
                        ).sum()

                        bl_diff_mayor_24 = (
                            ship_bol_diff["diferencia_horas"] > 24
                        ).sum()

                        # Construir tabla_resumen_bls
                        rows = []

                        def pct_valid(count):
                            if total_bl_validos == 0:
                                return None
                            return round((count / total_bl_validos) * 100, 2)

                        # #BL Totales Base
                        rows.append(
                            {
                                "indicador": "#BL Totales Base (Shipment ID, Shipment type = Bill_of_lading)",
                                "cantidad": int(total_bl_base),
                                "porcentaje_sobre_validos": "",
                            }
                        )

                        # #BL Válidos (universo prueba)
                        rows.append(
                            {
                                "indicador": "#BL Válidos (universo prueba, con ETA/ATA válida)",
                                "cantidad": int(total_bl_validos),
                                "porcentaje_sobre_validos": pct_valid(total_bl_validos),
                            }
                        )

                        # Diferencia (BL no válidos)
                        rows.append(
                            {
                                "indicador": "Diferencia (BL no válidos)",
                                "cantidad": int(total_bl_no_validos),
                                "porcentaje_sobre_validos": "",
                            }
                        )

                        # BL con diferencias ETA/ATA (> 1 minuto)
                        rows.append(
                            {
                                "indicador": "BL con diferencias ETA/ATA (> 1 minuto)",
                                "cantidad": int(bl_con_diferencias),
                                "porcentaje_sobre_validos": pct_valid(bl_con_diferencias),
                            }
                        )

                        # BL diferencia de menos de 24 horas
                        rows.append(
                            {
                                "indicador": "BL diferencia de menos de 24 horas (1 min < diff ≤ 24 h)",
                                "cantidad": int(bl_diff_menor_24),
                                "porcentaje_sobre_validos": pct_valid(bl_diff_menor_24),
                            }
                        )

                        # BL diferencia de más de 24 horas
                        rows.append(
                            {
                                "indicador": "BL diferencia de más de 24 horas (diff > 24 h)",
                                "cantidad": int(bl_diff_mayor_24),
                                "porcentaje_sobre_validos": pct_valid(bl_diff_mayor_24),
                            }
                        )

                        tabla_resumen = pd.DataFrame(
                            rows,
                            columns=["indicador", "cantidad", "porcentaje_sobre_validos"],
                        )

                        # ==== 9. Construir ZIP con los 3 CSV ====
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
                                resumen_por_bl.to_csv(index=False).encode("utf-8-sig"),
                            )
                            zf.writestr(
                                "tabla_resumen_bls.csv",
                                tabla_resumen.to_csv(index=False).encode("utf-8-sig"),
                            )

                        zip_buffer.seek(0)

                        st.success("Análisis completado. Puedes descargar el ZIP con los tres CSV.")
                        st.download_button(
                            label="Descargar ZIP (detalle + resumen por BL + tabla resumen)",
                            data=zip_buffer,
                            file_name="reporte_bl_eta_ata.zip",
                            mime="application/zip",
                        )

                        st.subheader("Tabla resumen (vista rápida)")
                        st.dataframe(tabla_resumen)

                        st.subheader("Resumen por BL (vista rápida)")
                        st.dataframe(resumen_por_bl.head(50))

    except Exception as e:
        st.error(f"Error procesando el archivo: {e}")

else:
    st.info("Sube un archivo CSV para comenzar.")
