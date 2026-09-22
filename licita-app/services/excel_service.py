# services/excel_service.py
from typing import Union
import io
import pandas as pd


def generar_excel_cotizacion(
    cotizacion_info: dict, df_items: Union[pd.DataFrame, list]
) -> bytes:
    """Genera un archivo Excel con hojas separadas para el encabezado y el detalle de ítems."""

    # Convertir a DataFrame si se pasa una lista de diccionarios
    if isinstance(df_items, list):
        df_items = pd.DataFrame(df_items)

    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_encabezado = pd.DataFrame([cotizacion_info])
        df_encabezado.to_excel(
            writer, sheet_name="Encabezado Cotización", index=False
        )

        df_items.to_excel(writer, sheet_name="Detalle Ítems", index=False)

    output.seek(0)
    return output.getvalue()


def generar_excel_licitaciones(df_licitaciones: pd.DataFrame) -> bytes:
    """Exporta el listado de oportunidades SECOP a un buffer de bytes para descarga."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_licitaciones.to_excel(
            writer, sheet_name="Licitaciones SECOP", index=False
        )
    output.seek(0)
    return output.getvalue()


def generar_plantilla_carga_masiva() -> bytes:
    """Crea una plantilla estructurada de ejemplo para la carga masiva de ítems."""
    df_plantilla = pd.DataFrame([
        {
            "Item": 1,
            "Descripción": (
                "Mantenimiento preventivo de extintor Solkaflam 3700g"
            ),
            "Cantidad": 5.0,
            "Unidad": "UNIDAD",
            "Costo Unitario (COP)": 45000.0,
            "Margen (%)": 25.0,
            "Enlace Referencia": "https://ejemplo.com/producto1",
        },
        {
            "Item": 2,
            "Descripción": "Recarga de extintor de agua a presión 2.5 gal",
            "Cantidad": 10.0,
            "Unidad": "UNIDAD",
            "Costo Unitario (COP)": 32000.0,
            "Margen (%)": 20.0,
            "Enlace Referencia": "",
        },
    ])

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_plantilla.to_excel(
            writer, sheet_name="Plantilla Carga Ítems", index=False
        )
    output.seek(0)
    return output.getvalue()


def leer_excel_items(file_buffer) -> pd.DataFrame:
    """Lee y normaliza archivos Excel (.xlsx/.xls) o CSV cargados en Streamlit st.file_uploader."""
    try:
        filename = getattr(file_buffer, "name", "").lower()
        if filename.endswith(".csv"):
            df = pd.read_csv(file_buffer)
        else:
            df = pd.read_excel(file_buffer)

        # Mapeo flexible de nombres de columnas a la estructura interna
        column_mapping = {
            "item": "numero_item",
            "posición": "numero_item",
            "posicion": "numero_item",
            "descripción": "descripcion",
            "descripcion": "descripcion",
            "detalle": "descripcion",
            "insumo": "descripcion",
            "cantidad": "cantidad",
            "cant": "cantidad",
            "unidad": "unidad_medida",
            "unidad_medida": "unidad_medida",
            "um": "unidad_medida",
            "costo": "costo_unitario",
            "costo unitario": "costo_unitario",
            "costo_unitario": "costo_unitario",
            "costo unit. (cop)": "costo_unitario",
            "margen": "margen_porcentaje",
            "margen (%)": "margen_porcentaje",
            "margen_porcentaje": "margen_porcentaje",
            "enlace": "enlace_referencia",
            "referencia": "enlace_referencia",
            "link": "enlace_referencia",
        }

        renamed_cols = {}
        for col in df.columns:
            col_clean = str(col).strip().lower()
            if col_clean in column_mapping:
                renamed_cols[col] = column_mapping[col_clean]

        df = df.rename(columns=renamed_cols)

        if "descripcion" not in df.columns:
            raise ValueError(
                "El archivo no contiene una columna válida de descripción"
                " ('Descripción' o 'Detalle')."
            )

        # Asignación de valores por defecto para campos faltantes
        if "numero_item" not in df.columns:
            df["numero_item"] = range(1, len(df) + 1)

        if "cantidad" not in df.columns:
            df["cantidad"] = 1.0

        if "unidad_medida" not in df.columns:
            df["unidad_medida"] = "UNIDAD"

        if "costo_unitario" not in df.columns:
            df["costo_unitario"] = 0.0

        if "margen_porcentaje" not in df.columns:
            df["margen_porcentaje"] = 0.0

        if "enlace_referencia" not in df.columns:
            df["enlace_referencia"] = ""

        # Sanitización de datos numéricos
        df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce").fillna(
            1.0
        )
        df["costo_unitario"] = pd.to_numeric(
            df["costo_unitario"], errors="coerce"
        ).fillna(0.0)
        df["margen_porcentaje"] = pd.to_numeric(
            df["margen_porcentaje"], errors="coerce"
        ).fillna(0.0)

        # Cálculo de precio de venta unitario y subtotal
        df["precio_venta_unitario"] = df["costo_unitario"] * (
            1 + (df["margen_porcentaje"] / 100.0)
        )
        df["subtotal_item"] = df["cantidad"] * df["precio_venta_unitario"]

        return df

    except Exception as e:
        raise ValueError(f"Error al procesar el archivo cargado: {str(e)}")