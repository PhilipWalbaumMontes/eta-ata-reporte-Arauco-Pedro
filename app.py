import csv
from pathlib import Path
import pandas as pd


def detect_delimiter(path: str, sample_bytes: int = 65536) -> str:
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        sample = f.read(sample_bytes)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", "\t", ";", "|"])
        return dialect.delimiter
    except Exception:
        return ","


def is_blank(x) -> bool:
    """Blanco si es NaN/None o whitespace-only (incluye ' ')."""
    if x is None:
        return True
    if pd.isna(x):
        return True
    return str(x).strip() == ""


def ensure_cols(df: pd.DataFrame, total_cols: int = 14) -> pd.DataFrame:
    """Asegura columnas hasta N (A..N = 14 columnas). Si faltan, agrega vacías."""
    df = df.copy()
    missing = total_cols - df.shape[1]
    if missing > 0:
        for i in range(missing):
            df[f"__extra_{i+1}__"] = ""
    return df


def generar_reportes(input_csv: str, output_dir: str) -> tuple[str, str]:
    """
    Devuelve rutas de:
    - Tabla Resumen.csv
    - Archivo completo.csv
    """
    delim = detect_delimiter(input_csv)

    df = pd.read_csv(
        input_csv,
        delimiter=delim,
        dtype=str,
        keep_default_na=True
    )

    # Asegurar A..N
    df = ensure_cols(df, total_cols=14)

    # Índices 0-based:
    # A=0 B=1 C=2 D=3 E=4 F=5 G=6 H=7 I=8 ... N=13
    col_C = df.iloc[:, 2]  # Bill of lading
    col_G = df.iloc[:, 6]  # Destination estimated arrival time
    col_H = df.iloc[:, 7]  # Destination actual arrival time

    # (1) Conteo de únicos en C excluyendo blancos/NULL/solo espacios
    c_clean = col_C.astype(object).where(~col_C.isna(), None)
    c_stripped = c_clean.apply(lambda v: None if v is None else str(v).strip())
    c_nonblank = c_stripped.dropna()
    c_nonblank = c_nonblank[c_nonblank != ""]
    unique_bol_count = int(c_nonblank.nunique(dropna=True))

    # (2) Columna N: Valor priorizado
    n_values = []
    for h, g in zip(col_H.tolist(), col_G.tolist()):
        if not is_blank(h):
            n_values.append(str(h))
        elif not is_blank(g):
            n_values.append(str(g))
        else:
            n_values.append("No Valido")

    df.iloc[:, 13] = n_values  # N

    # Salidas
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    tabla_resumen_path = str(out_dir / "Tabla Resumen.csv")
    archivo_completo_path = str(out_dir / "Archivo completo.csv")

    tabla_resumen = pd.DataFrame([{
        "indicador": "Cantidad de Bill of lading únicos (columna C) sin blancos",
        "valor": unique_bol_count
    }])
    tabla_resumen.to_csv(tabla_resumen_path, index=False)

    df.to_csv(archivo_completo_path, index=False, sep=delim)

    return tabla_resumen_path, archivo_completo_path


# Ejemplo de uso:
# generar_reportes("input.csv", "./salida")
