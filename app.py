import streamlit as st
import pandas as pd
import zipfile
import io

st.set_page_config(page_title="Conteo BL + diferencias por Container_ID", layout="centered")
st.title("Análisis de BL inválidos y diferencias por Container_ID")

st.markdown(
    """
Esta app hace:

1. Pide que subas un CSV.
2. Cuenta la cantidad de **Shipment ID únicos (columna A)** donde `Shipment type` (columna B) = `Bill_of_lading`
   (sin sensibilidad a mayúsculas/minúsculas).
3. Dentro de esos BL base, cuenta cuántos tienen en la **columna AM** el valor `BL Invalido`.
4. Para los BL **no inválidos**:
   - Toma filas donde `Shipment type` (B) es `Container_id` / `CONTAINER_ID` / `CONTAINER`.
   - Agrupa por columna **C** (Container_ID).
   - Calcula fecha/hora **mínima** y **máxima** en **AL** para cada Container_ID.
   - Escribe:
     - Min en **AO**
     - Max en **AP**
     - Diferencia (AP − AO) en horas en **AN**.
5. Genera un ZIP con:
   - `bl_resumen_base_invalidos.csv`
   - `bl_invalidos_lista.csv`
   - `container_diferencias_horas.csv` (A,B,C,AJ,AK,AL,AM,AN,AO,AP)
"""
)

uploaded_file = st.file_uploader("Sube el CSV", type=["csv"])

if uploaded_file is not None:
    try:
        # Leer todo como texto
        df = pd.read_csv(uploaded_file, dtype=str)
        df = df.fillna("")

        st.write(f"Archivo cargado con **{df.shape[0]} filas** y **{df.shape[1]} columnas**.")

        # Verificar que existan suficientes columnas hasta AP (índice 41 -> 42 columnas)
        if df.shape[1] <= 41:
            st.error(
                "El archivo tiene menos de 42 columnas.\n\n"
                "Necesito al menos:\n"
                "- Columna A (Shipment ID)\n"
                "- Columna B (Shipment type)\n"
                "- Columna C\n"
                "- Columna AJ (índice 35)\n"
                "- Columna AK (índice 36)\n"
                "- Columna AL (índice 37)\n"
                "- Columna AM (índice 38)\n"
                "- Columna AN (índice 39)\n"
                "- Columna AO (índice 40)\n"
                "- Columna AP (índice 41)\n"
            )
        else:
            # Mapear columnas por posición como en Excel
            col_A = df.columns[0]    # Shipment ID
            col_B = df.columns[1]    # Shipment type
            col_C = df.columns[2]    # Container_ID / BoL (según export)
            col_AJ = df.columns[35]
            col_AK = df.columns[36]
            col_AL = df.columns[37]
            col_AM = df.columns[38]
            col_AN = df.columns[39]
            col_AO = df.columns[40]
            col_AP = df.columns[41]

            st.write("Columnas detectadas por posición:")
            st.write(f"- Columna A (Shipment ID): **{col_A}**")
            st.write(f"- Columna B (Shipment type): **{col_B}**")
            st.write(f"- Columna C: **{col_C}**")
            st.write(f"- Columna AJ: **{col_AJ}**")
            st.write(f"- Columna AK: **{col_AK}**")
            st.write(f"- Columna AL: **{col_AL}**")
            st.write(f"- Columna AM: **{col_AM}**")
            st.write(f"- Columna AN: **{col_AN}**")
            st.write(f"- Columna AO: **{col_AO}**")
            st.write(f"- Columna AP: **{col_AP}**")

            # =========================
            # PARTE 1: Base e inválidos
            # =========================

            # Normalizar Shipment type para filtrar Bill_of_lading
            stype_upper = df[col_B].astype(str).str.strip().str.upper()

            # 1) Filas donde Shipment type = Bill_of_lading (flexible en mayúsculas)
            mask_bol_header = stype_upper == "BILL_OF_LADING"
            header_df = df.loc[mask_bol_header].copy()

            if header_df.empty:
                st.warning(
                    "No encontré filas donde la columna B tenga 'Bill_of_lading' "
                    "(revisado sin sensibilidad a mayúsculas)."
                )
                # En este caso igual armamos ZIP con archivos vacíos
                resumen_base = pd.DataFrame(
                    [
                        {
                            "indicador": "#BL Totales Base (Shipment ID, Shipment type = Bill_of_lading)",
                            "cantidad": 0,
                            "porcentaje": "",
                        },
                        {
                            "indicador": "#BL con AM = 'BL Invalido' (dentro de la base)",
                            "cantidad": 0,
                            "porcentaje": "",
                        },
                        {
                            "indicador": "#BL Válidos (base - inválidos)",
                            "cantidad": 0,
                            "porcentaje": "",
                        },
                    ]
                )
                df_invalid_list = pd.DataFrame(
                    {"Shipment ID inválidos (AM = BL Invalido)": []}
                )
                container_report = pd.DataFrame(
                    columns=[col_A, col_B, col_C, col_AJ, col_AK, col_AL, col_AM, col_AN, col_AO, col_AP]
                )
            else:
                # Normalizar Shipment ID
                header_df["shipment_id_norm"] = header_df[col_A].astype(str).str.strip()

                # Set de Shipment ID base
                base_shipments = header_df["shipment_id_norm"].unique()
                base_shipments_set = set(base_shipments)
                total_bl_base = len(base_shipments)

                # Dentro de esas filas, ver AM = 'BL Invalido'
                am_upper = header_df[col_AM].astype(str).str.strip().str.upper()
                mask_am_invalid = am_upper == "BL INVALIDO"

                header_invalid = header_df.loc[mask_am_invalid].copy()
                invalid_shipments = header_invalid["shipment_id_norm"].unique()
                invalid_shipments_set = set(invalid_shipments)
                total_bl_invalid = len(invalid_shipments)

                # BL válidos = base - inválidos
                valid_shipments_set = base_shipments_set - invalid_shipments_set
                total_bl_valid = len(valid_shipments_set)

                # Métricas en pantalla
                st.subheader("Resultados del análisis de BL base")
                st.metric(
                    label="#BL Totales Base (Shipment ID únicos con Shipment type = Bill_of_lading)",
                    value=int(total_bl_base),
                )

                st.metric(
                    label="#BL con AM = 'BL Invalido' (dentro de la base)",
                    value=int(total_bl_invalid),
                )

                st.metric(
                    label="#BL Válidos (base - inválidos)",
                    value=int(total_bl_valid),
                )

                if total_bl_base > 0:
                    pct_invalid = round(total_bl_invalid / total_bl_base * 100, 2)
                    pct_valid = round(total_bl_valid / total_bl_base * 100, 2)
                else:
                    pct_invalid = ""
                    pct_valid = ""

                # DataFrames para el ZIP
                resumen_base = pd.DataFrame(
                    [
                        {
                            "indicador": "#BL Totales Base (Shipment ID, Shipment type = Bill_of_lading)",
                            "cantidad": int(total_bl_base),
                            "porcentaje": "",
                        },
                        {
                            "indicador": "#BL con AM = 'BL Invalido' (dentro de la base)",
                            "cantidad": int(total_bl_invalid),
                            "porcentaje": pct_invalid,
                        },
                        {
                            "indicador": "#BL Válidos (base - inválidos)",
                            "cantidad": int(total_bl_valid),
                            "porcentaje": pct_valid,
                        },
                    ]
                )

                df_invalid_list = pd.DataFrame(
                    {"Shipment ID inválidos (AM = BL Invalido)": list(invalid_shipments_set)}
                )

                st.subheader("Listado de Shipment ID con AM = 'BL Invalido'")
                st.dataframe(df_invalid_list)

                # ============================================
                # PARTE 2: Cálculo para BL válidos en C/AL→AN
                # ============================================

                # Filas de contenedores: Shipment type = Container_id / CONTAINER_ID / CONTAINER
                mask_containers = stype_upper.isin(["CONTAINER_ID", "CONTAINER"])
                containers = df.loc[mask_containers].copy()

                if containers.empty:
                    st.warning(
                        "No se encontraron filas de contenedores (CONTAINER/CONTAINER_ID) "
                        f"en la columna '{col_B}'."
                    )
                    container_report = pd.DataFrame(
                        columns=[col_A, col_B, col_C, col_AJ, col_AK, col_AL, col_AM, col_AN, col_AO, col_AP]
                    )
                else:
                    st.info(f"Se detectaron {len(containers)} filas de contenedores en total.")

                    # Normalizar Shipment ID y Container_ID (columna C)
                    containers["shipment_id_norm"] = containers[col_A].astype(str).str.strip()
                    containers["container_id_norm"] = containers[col_C].astype(str).str.strip()

                    # Filtrar sólo contenedores cuyos Shipment ID están en BL válidos
                    containers_valid_bl = containers[
                        containers["shipment_id_norm"].isin(valid_shipments_set)
                    ].copy()

                    if containers_valid_bl.empty:
                        st.warning(
                            "No hay filas de contenedores asociadas a Shipment ID válidos "
                            "(sin AM = BL Invalido)."
                        )
                        container_report = pd.DataFrame(
                            columns=[col_A, col_B, col_C, col_AJ, col_AK, col_AL, col_AM, col_AN, col_AO, col_AP]
                        )
                    else:
                        st.info(
                            f"Filas de contenedores asociadas a BL válidos: "
                            f"{len(containers_valid_bl)}"
                        )

                        # Parsear AL a datetime
                        containers_valid_bl["AL_dt"] = pd.to_datetime(
                            containers_valid_bl[col_AL], errors="coerce"
                        )

                        # Agrupar por Container_ID (columna C) y calcular min/max
                        group_cont = containers_valid_bl.groupby(
                            "container_id_norm", dropna=False
                        )
                        min_dt = group_cont["AL_dt"].transform("min")
                        max_dt = group_cont["AL_dt"].transform("max")

                        containers_valid_bl["min_dt"] = min_dt
                        containers_valid_bl["max_dt"] = max_dt

                        # Diferencia en horas (max - min)
                        diff_td = containers_valid_bl["max_dt"] - containers_valid_bl["min_dt"]
                        containers_valid_bl["diff_hours"] = (
                            diff_td.dt.total_seconds() / 3600.0
                        )

                        # Escribir Min/Max en string para AO/AP
                        containers_valid_bl["AO_val"] = containers_valid_bl["min_dt"].dt.strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                        containers_valid_bl["AP_val"] = containers_valid_bl["max_dt"].dt.strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )

                        # Actualizar columnas AO, AP, AN en el df original
                        df.loc[containers_valid_bl.index, col_AO] = containers_valid_bl["AO_val"]
                        df.loc[containers_valid_bl.index, col_AP] = containers_valid_bl["AP_val"]
                        df.loc[containers_valid_bl.index, col_AN] = containers_valid_bl[
                            "diff_hours"
                        ]

                        # Armar reporte con columnas pedidas
                        cols_report = [
                            col_A,
                            col_B,
                            col_C,
                            col_AJ,
                            col_AK,
                            col_AL,
                            col_AM,
                            col_AN,
                            col_AO,
                            col_AP,
                        ]
                        container_report = df.loc[containers_valid_bl.index, cols_report].copy()

                        st.subheader("Muestra del reporte de contenedores (con diferencias en AL)")
                        st.dataframe(container_report.head(50))

            # ============================
            # PARTE 3: Construir ZIP final
            # ============================

            # Asegurar que container_report tenga las columnas correctas aunque esté vacío
            if 'container_report' not in locals() or container_report is None:
                container_report = pd.DataFrame(
                    columns=[col_A, col_B, col_C, col_AJ, col_AK, col_AL, col_AM, col_AN, col_AO, col_AP]
                )

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(
                    "bl_resumen_base_invalidos.csv",
                    resumen_base.to_csv(index=False).encode("utf-8-sig"),
                )
                zf.writestr(
                    "bl_invalidos_lista.csv",
                    df_invalid_list.to_csv(index=False).encode("utf-8-sig"),
                )
                # Siempre escribimos el CSV de contenedores, aunque esté vacío
                zf.writestr(
                    "container_diferencias_horas.csv",
                    container_report.to_csv(index=False).encode("utf-8-sig"),
                )

            zip_buffer.seek(0)

            st.success("Análisis completado. Puedes descargar el ZIP con los reportes.")
            st.download_button(
                label="Descargar ZIP (resumen BL + inválidos + contenedores)",
                data=zip_buffer,
                file_name="reporte_bl_invalidos_y_contenedores.zip",
                mime="application/zip",
            )

    except Exception as e:
        st.error(f"Error procesando el archivo: {e}")

else:
    st.info("Sube un archivo CSV para comenzar.")
