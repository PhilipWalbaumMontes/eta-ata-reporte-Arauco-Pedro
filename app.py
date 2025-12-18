import streamlit as st
import pandas as pd
import zipfile
import io

st.set_page_config(page_title="Reporte BL ETA/ATA", layout="centered")
st.title("Reporte ETA/ATA por Bill of Lading")

st.markdown(
    """
Esta app:

1. Usa columnas fijas:
   - A = `Shipment ID`
   - B = `Shipment type`
   - C = `Bill of lading`
   - AJ = `Destination estimated arrival time` (ETA)
   - AK = `Destination actual arrival time` (ATA)

2. Considera filas de **contenedores** (`Shipment type = CONTAINER / CONTAINER_ID`).

3. Construye la columna **ETA/ATA**:
   - Si AK tiene valor (no vacío) → usa AK.
   - Si no, pero AJ tiene valor → usa AJ.
   - Si ninguna tiene valor → `BL Invalido`.

4. Solo con filas donde `ETA/ATA` tiene valor (no `BL Invalido`):
   - Agrupa por **Bill of lading** (columna C).
   - Calcula:
     - `Min` = fecha/hora mínima ETA/ATA.
     - `Max` = fecha/hora máxima ETA/ATA.
     - `diferencia` = (Max - Min) en horas.
     - `Rango`:
       - `Sin diferencia` → 0 horas
       - `Menos de 24 Hrs` → 0 < diff ≤ 24
       - `Mas de 24 Hrs` → diff > 24

5. Genera un ZIP con:
   - `detalle_eta_ata_por_contenedor.csv`
   - `resumen_por_bl.csv`
   - `tabla_resumen_bls.csv` (tabla resumen en número de BL y % sobre BL válidos, usando columna C).
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

        # === MAPEO FIJO POR POSICIÓN ===
        # A: Shipment ID  (0)
        # B: Shipment type (1)
        # C: Bill of lading (2)
        # AJ: Destination estimated arrival time (35)
        # AK: Destination actual arrival time (36)

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

                st.subheader("Resumen de Bill of Lading (por columna C en contenedores)")
                st.metric(
                    label="BL totales (columna C, contenedores)",
                    value=int(total_bls_totales),
                )

                # === PASO 2: Construir ETA/ATA por string (no vacíos) ===
                containers["eta_str"] = containers[col_eta].astype(str).str.strip()
                containers["ata_str"] = containers[col_ata].astype(str).str.strip()

                # ETA/ATA string: prioriza ATA; si no, ETA; si ambas vacías → vacío
                containers["etaata_str"] = containers["ata_str"]
                containers.loc[
                    containers["etaata_str"] == "", "etaata_str"
                ] = containers.loc[
                    containers["etaata_str"] == "", "eta_str"
                ]

                # Inicializar en df completo
                df["ETA/ATA"] = "BL Invalido"

                # Filas de contenedores con ETA/ATA NO vacía (válidos según tu definición)
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
                    # Escribir ETA/ATA en df original
                    df.loc[containers_valid.index, "ETA/ATA"] = containers_valid["etaata_str"]

                    # === PASO 3: Min y Max por BoL (C) sólo para filas con ETA/ATA válida ===
                    mask_valid_rows = mask_containers & (df["ETA/ATA"] != "BL Invalido")
                    valid = df.loc[mask_valid_rows].copy()

                    if valid.empty:
                        st.warning(
                            "No hay filas de contenedores con ETA/ATA válida después del filtrado."
                        )
                    else:
                        # Parsear la columna ETA/ATA a datetime para poder calcular min/max/diferencia
                        valid["etaata_dt"] = pd.to_datetime(
                            valid["ETA/ATA"], errors="coerce", utc=True
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

                        # BL válidos = BoL que aparecen en el resumen (tienen al menos un contenedor con ETA/ATA no vacía)
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
                                "indicador": "Bill of Lading Totales",
                                "cantidad": int(total_bls_totales),
                                "porcentaje_sobre_validos": "",
                            }
                        )

                        # 2) Bill of Lading Totales Válidos
                        rows.append(
                            {
                                "indicador": "Bill of Lading Totales Válidos (con ETA/ATA no vacía)",
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
