import pandas as pd
from pathlib import Path

# === CONFIGURACIÓN BÁSICA ===
INPUT_CSV = "input_movements.csv"  # <-- cambia esto al nombre de tu archivo original
OUTPUT_DETALLE_CSV = "detalle_eta_ata_por_contenedor.csv"
OUTPUT_RESUMEN_CSV = "resumen_por_bl.csv"

# === LECTURA DEL ARCHIVO ===
df = pd.read_csv(INPUT_CSV, dtype=str)
df = df.fillna("")

# Mapeo por posición de columna (títulos fijos, posiciones tipo Excel)
col_shipment_id = df.columns[0]   # A: Shipment ID
col_shipment_type = df.columns[1] # B: Shipment type
col_bol = df.columns[2]           # C: Bill of lading

# AJ (Destination estimated arrival time) -> índice 35 (AJ es la columna nº 36)
col_eta = df.columns[35]
# AK (Destination actual arrival time) -> índice 36 (AK es la columna nº 37)
col_ata = df.columns[36]

print(f"Shipment ID: {col_shipment_id}")
print(f"Shipment type: {col_shipment_type}")
print(f"Bill of lading: {col_bol}")
print(f"ETA (AJ): {col_eta}")
print(f"ATA (AK): {col_ata}")

# === PASO 1: BoL únicos usando Shipment type = Bill_of_lading ===
mask_bl_header = df[col_shipment_type].str.strip().str.upper() == "BILL_OF_LADING"
unique_bls_by_shipment_id = df.loc[mask_bl_header, col_shipment_id].nunique()
print(f"Cantidad de BL únicos (Shipment ID, filas Bill_of_lading): {unique_bls_by_shipment_id}")

# === IDENTIFICAR FILAS DE CONTENEDORES ===
mask_containers = df[col_shipment_type].str.strip().str.upper().isin(["CONTAINER", "CONTAINER_ID"])
containers = df.loc[mask_containers].copy()

if containers.empty:
    raise ValueError(
        "No se encontraron filas de contenedores (CONTAINER/CONTAINER_ID) en la columna Shipment type."
    )

# === PASO 2: Construir ETA/ATA (AQ) priorizando AK, luego AJ ===
containers["eta_dt"] = pd.to_datetime(containers[col_eta], errors="coerce")
containers["ata_dt"] = pd.to_datetime(containers[col_ata], errors="coerce")

# ETA/ATA en formato datetime interno
containers["etaata_dt"] = containers["ata_dt"].where(
    containers["ata_dt"].notna(), containers["eta_dt"]
)

# Inicializar columna ETA/ATA en el df completo con "BL Invalido"
df["ETA/ATA"] = "BL Invalido"

# Filas de contenedor con ETA/ATA válida (no NaT)
mask_valid_etaata = containers["etaata_dt"].notna()

# Formatear a string para escribir en CSV (ej: 2025-01-31 14:30:00)
containers_valid = containers.loc[mask_valid_etaata].copy()
containers_valid["ETA_ATA_str"] = containers_valid["etaata_dt"].dt.strftime("%Y-%m-%d %H:%M:%S")

# Escribir ETA/ATA en df original solo para contenedores válidos
df.loc[containers_valid.index, "ETA/ATA"] = containers_valid["ETA_ATA_str"]

# === PASO 3: Min y Max por BoL (columna C) solo para filas con ETA/ATA válida ===
mask_valid_rows = mask_containers & (df["ETA/ATA"] != "BL Invalido")
valid = df.loc[mask_valid_rows].copy()

if valid.empty:
    raise ValueError("No hay filas de contenedores con ETA/ATA válida (todas son BL Invalido).")

# Convertir ETA/ATA (string) de vuelta a datetime para cálculo
valid["etaata_dt"] = pd.to_datetime(valid["ETA/ATA"], errors="coerce")

# Agrupar por Bill of lading (columna C)
group = valid.groupby(col_bol, dropna=False)

min_dt_by_bl = group["etaata_dt"].transform("min")
max_dt_by_bl = group["etaata_dt"].transform("max")

valid["Min"] = min_dt_by_bl
valid["Max"] = max_dt_by_bl

# === PASO 4: diferencia (AT) = Max - Min en horas ===
valid["diferencia_timedelta"] = valid["Max"] - valid["Min"]
valid["diferencia"] = valid["diferencia_timedelta"].dt.total_seconds() / 3600.0

# === PASO 5: Rango (AU) según diferencia en horas ===
def clasificar_rango(horas):
    if pd.isna(horas):
        return ""
    if horas == 0:
        return "Sin diferencia"
    if 0 < horas <= 24:
        return "Menos de 24 Hrs"
    return "Mas de 24 Hrs"

valid["Rango"] = valid["diferencia"].apply(clasificar_rango)

# Pasar Min/Max a string legible en el CSV
valid["Min"] = valid["Min"].dt.strftime("%Y-%m-%d %H:%M:%S")
valid["Max"] = valid["Max"].dt.strftime("%Y-%m-%d %H:%M:%S")

# Escribir columnas nuevas de vuelta en el df completo solo para índices válidos
df.loc[valid.index, "Min"] = valid["Min"]
df.loc[valid.index, "Max"] = valid["Max"]
df.loc[valid.index, "diferencia"] = valid["diferencia"]
df.loc[valid.index, "Rango"] = valid["Rango"]

# === PASO 6: Generar CSV detalle (solo contenedores con ETA/ATA válida) ===
detalle = df.loc[valid.index].copy()
detalle.to_csv(OUTPUT_DETALLE_CSV, index=False, encoding="utf-8-sig")
print(f"CSV de detalle generado: {OUTPUT_DETALLE_CSV}")

# === CSV resumen por BoL (columna C) ===
resumen = (
    valid.groupby(col_bol, dropna=False)
    .agg(
        shipment_id_count=(col_shipment_id, "nunique"),
        containers_valid=("etaata_dt", "size"),
        Min=("Min", "first"),  # todas las filas del BL tienen el mismo Min
        Max=("Max", "first"),  # igual para Max
        diferencia_horas=("diferencia", "first"),  # misma diferencia para todo el BL
        Rango=("Rango", "first"),
    )
    .reset_index()
)

resumen.to_csv(OUTPUT_RESUMEN_CSV, index=False, encoding="utf-8-sig")
print(f"CSV resumen por BL generado: {OUTPUT_RESUMEN_CSV}")
