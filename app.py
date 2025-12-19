import streamlit as st
import pandas as pd

st.set_page_config(page_title="Conteo BL válidos e inválidos", layout="centered")
st.title("Análisis simple de BL válidos / inválidos (columna AM)")

st.markdown(
    """
Esta app hace lo siguiente:

1. Pide que subas un CSV de Movement.
2. Cuenta la cantidad de **Shipment ID únicos** (columna A)  
   donde **Shipment type (columna B) = Bill_of_lading** (ignorando mayúsculas/minúsculas).
3. De esos Shipment ID, cuenta cuántos tienen en la **columna AM** el valor **"BL Invalido"**
   (también ignorando mayúsculas/minúsculas y espacios).
"""
)

uploaded_file = st.file_uploader("Sube el CSV", type=["csv"])

if uploaded_file is not None:
    try:
        # Leer todo como texto
        df = pd.read_csv(uploaded_file, dtype=str)
        df = df.fillna("")

        st.write(f"Archivo cargado con **{df.shape[0]} filas** y **{df.shape[1]} columnas**.")

        # Verificamos que haya suficientes columnas para A, B y AM
        if df.shape[1] <= 38:
            st.error(
                "El archivo tiene menos de 39 columnas.\n\n"
                "Necesito al menos:\n"
                "- Columna A (Shipment ID)\n"
                "- Columna B (Shipment type)\n"
                "- Columna AM (posicionalmente, la número 39)\n"
            )
        else:
            # Identificar columnas por POSICIÓN, como en Excel:
            # A = índice 0, B = índice 1, ..., AM = índice 38
            col_A = df.columns[0]    # Shipment ID
            col_B = df.columns[1]    # Shipment type
            col_AM = df.columns[38]  # ETA/ATA o BL Invalido

            st.write("Columnas detectadas por posición:")
            st.write(f"- Columna A (Shipment ID): **{col_A}**")
            st.write(f"- Columna B (Shipment type): **{col_B}**")
            st.write(f"- Columna AM: **{col_AM}**")

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
            else:
                # Normalizar Shipment ID
                header_df["shipment_id_norm"] = header_df[col_A].astype(str).str.strip()

                # Set de Shipment ID base
                base_shipments = header_df["shipment_id_norm"].unique()
                total_bl_base = len(base_shipments)

                # 2) Dentro de esas filas, ver AM = 'BL Invalido'
                am_upper = header_df[col_AM].astype(str).str.strip().str.upper()
                mask_am_invalid = am_upper == "BL INVALIDO"

                header_invalid = header_df.loc[mask_am_invalid].copy()
                invalid_shipments = header_invalid["shipment_id_norm"].unique()
                total_bl_invalid = len(invalid_shipments)

                # Mostrar resultados
                st.subheader("Resultados del análisis")

                st.metric(
                    label="#BL Totales Base (Shipment ID únicos con Shipment type = Bill_of_lading)",
                    value=int(total_bl_base),
                )

                st.metric(
                    label="#BL con AM = 'BL Invalido' (dentro de la base)",
                    value=int(total_bl_invalid),
                )

                if total_bl_base > 0:
                    pct_invalid = round(total_bl_invalid / total_bl_base * 100, 2)
                else:
                    pct_invalid = None

                st.write(f"**Porcentaje de BL inválidos (sobre la base):** {pct_invalid}%")

                # Opcional: mostrar listado de Shipment ID inválidos
                st.subheader("Listado de Shipment ID con AM = 'BL Invalido'")
                st.dataframe(pd.DataFrame({"Shipment ID inválidos": invalid_shipments}))

    except Exception as e:
        st.error(f"Error procesando el archivo: {e}")

else:
    st.info("Sube un archivo CSV para comenzar.")
