import streamlit as st
import pandas as pd
import zipfile
import io

st.set_page_config(page_title="Reporte BL ETA/ATA", layout="centered")
st.title("Reporte ETA/ATA por Bill of Lading")

st.markdown(
    """
Esta app asume que el CSV tiene SIEMPRE estos nombres de columna:

- `Shipment ID`
- `Shipment type`
- `Bill of lading`
- `Destination estimated arrival time`  (ETA destino)
- `Destination actual arrival time`    (ATA destino)

Lógica:

1. Considera solo filas de **contenedores**:
   - `Shipment type` = `CONTAINER` o `CONTAINER_ID` (sin importar mayúsculas/minúsculas).

2. Construye la columna **ETA/ATA** por fila de contenedor:
   - Si `Destination actual arrival time` (ATA) no está vacía → usa ATA.
   - Si ATA está vacía pero `Destination estimated arrival time` (ETA) no está vacía → usa ETA.
   - Si ambas están vacías → `BL Invalido`.

3. Solo con filas donde `ETA/ATA` NO es `BL Invalido`:
   - Agrupa por **`Bill of lading`**.
   - Calcula por cada BL:
     - `Min` = fecha/hora mínima de ETA/ATA.
     - `Max` = fecha/hora máxima de ETA/ATA.
     - `diferencia` = (Max - Min) en horas.
     - `Rango`:
       - `Sin diferencia` → 0 horas
       - `Menos de 24 Hrs` → 0 < diff ≤ 24
       - `Mas de 24 Hrs` → diff > 24

4. Genera un ZIP con 3 CSV:
   - `detalle_eta_ata_por_contenedor.csv`  (todas las filas válidas de contenedor)
   - `resumen_por_bl.csv`                  (una fila por Bill of lading)
   - `tabla_resumen_bls.csv`               (resumen en número de BL y % sobre BL válidos)
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
        # Leer todo como texto
        df = pd.read_csv(uploaded_file, dtype=str)
        df = df.fillna("")

        st.write(f"Archivo cargado con **{df.shape[0]} filas** y **{df.shape[1]} columnas**.")

        # === VERIFICAR QUE EXISTEN LAS COLUMNAS ESPERADAS POR NOMBRE ===
        required_cols = [
            "Shipment ID",
            "Shipment type",
            "Bill of lading",
            "Destination estimated arrival time",
            "Destination actual arrival time",
        ]

        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            st.error(
                "No se encontraron todas las columnas esperadas.\n"
                f"Faltan: {missing}\n\n"
                "Columnas disponibles en el archivo:"
            )
            st.write(list(df.columns))
        else:
            col_shipment_id = "Shipment ID"
            col_shipment_type = "Shipment type"
            col_bol = "Bill of lading"
            col_eta = "Destination estimated arrival time"
            col_ata = "Destination actual arrival time"

            st.write("Columnas detectadas correctamente por nombre.")
            st.write(f"- Shipment ID: **{col_shipment_id}**")
            st.write(f"- Shipment type: **{col_shipment_type}**")
            st.write(f"- Bill of lading: **{col_bol}**")
            st.write(f"- ETA destino: **{col_eta}**")
            st.write(f"- ATA destino: **{col_ata}**")

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
                st.info(f"Se detectaron {len(containers)} filas de contenedores.")

                # === PASO 1: BL TOTALES (por columna C en contenedores) ===
                all_bls_series = containers[col_bol].astype(str)
                all_bls_set = set(all_bls_series.unique())
                total_bls_totales = len(all_bls_set)

                st.subheader("Resumen inicial por Bill of lading (columna C)")
                st.metric(
                    label="BL totales (Bill of lading distintos en filas de contenedores)",
                    value=int(total_bls_totales),
                )

                # === PASO 2: Construir ETA/ATA por string (no vacíos) ===
                containers["eta_str"] = containers[col_eta].astype(str).str.strip()
                containers["ata_str"] = containers[col_ata].astype(str).str.strip()

                # ETA/ATA string: prioriza ATA; si no, ETA; si ambas vacías → vacío
                containers["etaata_str"] = containers["ata_str"]
                mask_empty_etaata = containers["etaata_str"] == ""
                containers.loc[mask_empty_etaata, "etaata_str"] = containers.loc[
                    mask_empty_etaata, "eta_str"
                ]

                # Inicializar en df completo como BL Invalido
                df["ETA/ATA"] = "BL Invalido"

                # Filas de contenedores con ETA/ATA NO vacía (válidos según definición)
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
                    st.warning("No hay contenedores con ETA/ATA no vacía (todos BL Invalido).")
                else:
                    # Escribir ETA/ATA en df original en las mismas filas
                    df.loc[containers_valid.index, "ETA/ATA"] = containers_valid["etaata_str"]

                    # === PASO 3: Min y Max por BoL (C) sólo para filas con ETA/ATA válida ===
                    mask_valid_rows = mask_containers & (df["ETA/ATA"] != "BL Invalido")
                    valid = df.loc[mask_valid_rows].copy()

                    if valid.empty:
                        st.warning(
                            "No hay filas de contenedores con ETA/ATA válida después del filtrado."
                        )
                    else:
                        # Parsear la columna ETA/ATA a datetime para min/max/diferencia
                        # No forzamos utc ni nada raro; dejamos que pandas lo interprete.
                        valid["etaata_dt"] = pd.to_datetime(
                            valid["ETA/ATA"], errors="coerce"
                        )

                        group = valid.groupby(col_bol, dropna=False)
                        min_dt_by_bl = group["etaata_dt"].transform("min")
                        max_dt_by_bl = group["etaata_dt"].transform("max")

                        valid["Min_dt"] = min_dt_by_bl
                        valid["Max_dt"] = max_dt_by_bl

                        # === PASO 4: diferencia en horas ===
                        valid["diferencia_timedelta"] = valid["Max_dt"] - valid["Min_dt"]
                        valid["diferencia"] = (
                            valid["diferencia_timedelta"].dt.total_seconds() / 3600.0
                        )

                        # === PASO 5: Rango ===
                        valid["Rango"] = valid["diferencia"].apply(clasificar_rango)

                        # Formatear Min/Max a string para el CSV
                        valid["Min"] = valid["Min_dt"].dt.strftime("%Y-%m-%d %H:%M:%S")
                        valid["Max"] = valid["Max_dt"].dt.strftime("%Y-%m-%d %H:%M:%S")

                        # Escribir columnas nuevas de vuelta en df (solo índices válidos)
                        df.loc[valid.index, "Min"] = valid["Min"]
                        df.loc[valid.index, "Max"] = valid["Max"]
                        df.loc[valid.index, "diferencia"] = valid["diferencia"]
                        df.loc[valid.index, "Rango"] = valid["Rango"]

                        # === CSV DETALLE: solo contenedores con ETA/ATA válida ===
                        detalle = df.loc[valid.index].copy()

                        # === CSV RESUMEN POR BL (C) ===
                        resumen = (
                            valid.groupby(col_bol, dropna=False)
                            .agg(
                                shipment_id_count=(col_shipment_id, "nunique"),
                                containers_valid=("ETA/ATA", "size"),
                                Min=("Min", "first"),
                                Max=("Max", "first"),
                                diferencia_horas=("diferencia", "first"),
                                Rango=("Rango", "first"),
                            )
                            .reset_index()
                        )

                        # === TABLA RESUMEN (USANDO BILL OF LADING COMO UNIDAD) ===

                        # BL válidos = BoL que aparecen en el resumen
                        valid_bls_series = resumen[col_bol].astype(str)
                        valid_bls_set = set(valid_bls_series.unique())
                        total_bls_validos = len(valid_bls_set)

                        # BL no válidos = BL totales (col C en contenedores) - BL válidos
                        non_valid_bls_set = all_bls_set - valid_bls_set
                        total_bls_no_validos = len(non_valid_bls_set)

                        # Contadores por rango (solo BL válidos, es decir, filas de resumen)
                        bl_con_diferencias = (resumen["Rango"] != "Sin diferencia").sum()
                        bl_diff_menor_24 = (resumen["Rango"] == "Menos de 24 Hrs").sum()
                        bl_diff_mayor_24 = (resumen["Rango"] == "Mas de 24 Hrs").sum()

                        rows = []

                        def pct_valid(count):
                            if total_bls_validos == 0:
                                return None
                            return round((count / total_bls_validos) * 100, 2)

                        # 1) Bill of Lading Totales
                        rows.append(
                            {
                                "indicador": "Bill of Lading Totales (columna C en contenedores)",
                                "cantidad": int(total_bls_totales),
                                "porcentaje_sobre_validos": "",
                            }
                        )

                        # 2) Bill of Lading Totales Válidos
                        rows.append(
                            {
                                "indicador": "Bill of Lading Totales Válidos (al menos 1 ETA/ATA válida)",
                                "cantidad": int(total_bls_validos),
                                "porcentaje_sobre_validos": pct_valid(total_bls_validos),
                            }
                        )

                        # 3) Diferencia (BL no válidos)
                        rows.append(
                            {
                                "indicador": "Diferencia (BL no válidos)",
                                "cantidad": int(total_bls_no_validos),
                                "porcentaje_sobre_validos": "",
                            }
                        )

                        # 4) BL con diferencias ETA/ATA
                        rows.append(
                            {
                                "indicador": "BL con diferencias ETA/ATA (Rango ≠ 'Sin diferencia')",
                                "cantidad": int(bl_con_diferencias),
                                "porcentaje_sobre_validos": pct_valid(bl_con_diferencias),
                            }
                        )

                        # 5) BL diferencia de menos de 24 horas
                        rows.append(
                            {
                                "indicador": "BL diferencia de menos de 24 horas",
                                "cantidad": int(bl_diff_menor_24),
                                "porcentaje_sobre_validos": pct_valid(bl_diff_menor_24),
                            }
                        )

                        # 6) BL diferencia de más de 24 horas
                        rows.append(
                            {
                                "indicador": "BL diferencia de más de 24 horas",
                                "cantidad": int(bl_diff_mayor_24),
                                "porcentaje_sobre_validos": pct_valid(bl_diff_mayor_24),
                            }
                        )

                        tabla_resumen = pd.DataFrame(
                            rows,
                            columns=["indicador", "cantidad", "porcentaje_sobre_validos"],
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
                        st.dataframe(resumen.head(50))

    except Exception as e:
        st.error(f"Error procesando el archivo: {e}")

else:
    st.info("Sube un archivo CSV para comenzar.")
