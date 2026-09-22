import io
import pandas as pd
import streamlit as st
from sqlalchemy import text
from datetime import datetime
from database.connection import get_db_connection, get_engine
# Ejemplo si está en database/db.py o database/connection.py


def cargar_catalogo_completo() -> pd.DataFrame:
    """Carga todos los campos de la tabla banco_items_historico para la IA y la vista."""
    try:
        engine = get_engine()
        query = """
            SELECT 
                id, 
                numero_proceso, 
                descripcion, 
                unidad_medida, 
                cantidad, 
                costo_unitario, 
                creado_en
            FROM public.banco_items_historico
            ORDER BY id DESC;
        """
        return pd.read_sql(query, con=engine)
    except Exception as e:
        st.error(f"Error cargando el catálogo de PostgreSQL: {e}")
        return pd.DataFrame()
    
def convertir_df_a_excel(df: pd.DataFrame) -> bytes:
    """Convierte un DataFrame de pandas a bytes en formato Excel (.xlsx)."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Banco_Items")
    return output.getvalue()

# ==========================================
# 1. CONSULTA Y ACTUALIZACIÓN (CRUD)
# ==========================================
@st.cache_data(ttl=60)
def obtener_banco_items(busqueda: str = "") -> pd.DataFrame:
    try:
        engine = get_engine()
        query = text("""
            SELECT 
                id AS "ID",
                COALESCE(numero_proceso, 'S/N') AS "Número del Proceso", 
                descripcion AS "Descripción", 
                unidad_medida AS "Unidad", 
                cantidad AS "Cantidad", 
                costo_unitario AS "Valor Unitario",
                (cantidad * costo_unitario) AS "Valor Total",
                enlace AS "Enlace / Proveedor",
                creado_en AS "Fecha Registro"
            FROM public.banco_items_historico
            WHERE (:busqueda = '' 
               OR descripcion ILIKE :param 
               OR COALESCE(numero_proceso, '') ILIKE :param)
            ORDER BY id DESC;
        """)

        busqueda_clean = busqueda.strip()
        param = f"%{busqueda_clean}%"

        with engine.connect() as conn:
            return pd.read_sql(
                query,
                con=conn,
                params={"busqueda": busqueda_clean, "param": param},
            )
    except Exception as e:
        st.error(f"Error al consultar el Banco de Ítems: {e}")
        return pd.DataFrame()
    
def guardar_cambios_bd(df_original: pd.DataFrame, cambios: dict):
    """Aplica las modificaciones directamente en la base de datos PostgreSQL."""
    engine = get_engine()

    # 1. Filas editadas
    edited_rows = cambios.get("edited_rows", {})
    if edited_rows:
        query_update = text("""
            UPDATE public.banco_items_historico
            SET descripcion = :descripcion, unidad_medida = :unidad,
                cantidad = :cantidad, costo_unitario = :costo_unitario, enlace = :enlace
            WHERE id = :id;
        """)

        with engine.begin() as conn:
            for idx, col_changes in edited_rows.items():
                row_id = int(df_original.iloc[idx]["ID"])
                conn.execute(query_update, {
                    "id": row_id,
                    "descripcion": col_changes.get("Descripción", df_original.iloc[idx]["Descripción"]),
                    "unidad": col_changes.get("Unidad", df_original.iloc[idx]["Unidad"]),
                    "cantidad": int(col_changes.get("Cantidad", df_original.iloc[idx]["Cantidad"]) or 0),
                    "costo_unitario": float(col_changes.get("Valor Unitario", df_original.iloc[idx]["Valor Unitario"]) or 0.0),
                    "enlace": col_changes.get("Enlace / Proveedor", df_original.iloc[idx]["Enlace / Proveedor"]),
                })

    # 2. Filas nuevas agregadas dinámicamente
    added_rows = cambios.get("added_rows", [])
    if added_rows:
        query_insert = text("""
            INSERT INTO public.banco_items_historico (
                numero_proceso, descripcion, unidad_medida, cantidad, costo_unitario, enlace
            ) VALUES (:numero_proceso, :descripcion, :unidad, :cantidad, :costo_unitario, :enlace);
        """)
        with engine.begin() as conn:
            for new_row in added_rows:
                conn.execute(query_insert, {
                    "numero_proceso": new_row.get("Número del Proceso", "S/N"),
                    "descripcion": new_row.get("Descripción", ""),
                    "unidad": new_row.get("Unidad", "UNIDAD"),
                    "cantidad": int(new_row.get("Cantidad", 1) or 1),
                    "costo_unitario": float(new_row.get("Valor Unitario", 0.0) or 0.0),
                    "enlace": new_row.get("Enlace / Proveedor", ""),
                })

    # 3. Filas eliminadas
    deleted_rows = cambios.get("deleted_rows", [])
    if deleted_rows:
        query_delete = text("DELETE FROM public.banco_items_historico WHERE id = :id;")
        with engine.begin() as conn:
            for idx in deleted_rows:
                conn.execute(query_delete, {"id": int(df_original.iloc[idx]["ID"])})


        
def generar_numero_cotizacion() -> str:
    """Genera un consecutivo automático en formato COT-AAAA-XXX."""
    anio_actual = datetime.now().year
    prefix = f"COT-{anio_actual}-"

    query = """
        SELECT numero_cotizacion 
        FROM cotizaciones 
        WHERE numero_cotizacion LIKE %s 
        ORDER BY id DESC 
        LIMIT 1;
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (f"{prefix}%",))
                row = cur.fetchone()
                if row:
                    ultimo_num = row[0]
                    partes = ultimo_num.split("-")
                    if len(partes) == 3 and partes[2].isdigit():
                        siguiente = int(partes[2]) + 1
                        return f"{prefix}{siguiente:03d}"
                return f"{prefix}001"
    except Exception:
        return f"{prefix}001"


def guardar_cotizacion(
    numero_cotizacion: str,
    numero_proceso: str,
    tipo_cotizacion: str,
    porcentaje_iva: float,
    subtotal: float,
    impuesto_iva: float,
    total: float,
    observaciones: str,
    items: list,
) -> dict:
    """Inserta o actualiza una cotización con sus ítems en la base de datos."""
    sql_cotizacion = """
        INSERT INTO cotizaciones (
            numero_cotizacion, numero_proceso, tipo_cotizacion,
            porcentaje_iva, subtotal, impuesto_iva, total, observaciones
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (numero_cotizacion) DO UPDATE SET
            numero_proceso = EXCLUDED.numero_proceso,
            tipo_cotizacion = EXCLUDED.tipo_cotizacion,
            porcentaje_iva = EXCLUDED.porcentaje_iva,
            subtotal = EXCLUDED.subtotal,
            impuesto_iva = EXCLUDED.impuesto_iva,
            total = EXCLUDED.total,
            observaciones = EXCLUDED.observaciones
        RETURNING id;
    """

    sql_delete_items = "DELETE FROM cotizacion_items WHERE cotizacion_id = %s;"

    sql_item = """
        INSERT INTO cotizacion_items (
            cotizacion_id, numero_item, descripcion, cantidad,
            unidad_medida, costo_unitario, margen_porcentaje,
            precio_venta_unitario, subtotal_item, enlace_referencia
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
    """

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql_cotizacion,
                    (
                        numero_cotizacion,
                        numero_proceso or None,
                        tipo_cotizacion,
                        porcentaje_iva,
                        subtotal,
                        impuesto_iva,
                        total,
                        observaciones,
                    ),
                )
                cotizacion_id = cur.fetchone()[0]

                cur.execute(sql_delete_items, (cotizacion_id,))

                for it in items:
                    cur.execute(
                        sql_item,
                        (
                            cotizacion_id,
                            it.get("numero_item"),
                            it.get("descripcion"),
                            it.get("cantidad"),
                            it.get("unidad_medida", "UNIDAD"),
                            it.get("costo_unitario", 0.0),
                            it.get("margen_porcentaje", 20.0),
                            it.get("precio_venta_unitario", 0.0),
                            it.get("subtotal_item", 0.0),
                            it.get("enlace_referencia", ""), # Campo nuevo
                        ),
                    )
            conn.commit()
        return {"exito": True, "id": cotizacion_id}
    except Exception as e:
        return {"exito": False, "error": str(e)}


def cargar_cotizaciones() -> pd.DataFrame:
    """Recupera la lista general de cotizaciones guardadas."""
    query = """
        SELECT c.id, c.numero_cotizacion, c.numero_proceso, c.tipo_cotizacion,
               c.fecha_emision, c.porcentaje_iva, c.subtotal, c.impuesto_iva,
               c.total, c.estado, c.observaciones
        FROM cotizaciones c
        ORDER BY c.id DESC;
    """
    try:
        with get_db_connection() as conn:
            return pd.read_sql(query, conn)
    except Exception:
        return pd.DataFrame()


def cargar_items_historicos() -> pd.DataFrame:
    """Recupera el catálogo completo de ítems históricos."""
    return buscar_items_globales("")


def buscar_items_globales(query_texto: str = "") -> pd.DataFrame:
    sql = """
        SELECT ci.id, ci.descripcion, ci.cantidad, ci.unidad_medida,
               ci.costo_unitario, ci.margen_porcentaje, ci.precio_venta_unitario,
               ci.subtotal_item, ci.enlace_referencia, c.numero_cotizacion, 
               c.numero_proceso, c.fecha_emision
        FROM cotizacion_items ci
        JOIN cotizaciones c ON ci.cotizacion_id = c.id
    """
    params = []
    if query_texto.strip():
        sql += " WHERE ci.descripcion ILIKE %s"
        params.append(f"%{query_texto.strip()}%")

    sql += " ORDER BY ci.id DESC;"

    try:
        with get_db_connection() as conn:
            return pd.read_sql(sql, conn, params=params if params else None)
    except Exception:
        return pd.DataFrame()


def actualizar_estado_cotizacion(cotizacion_id: int, estado: str) -> bool:
    """Actualiza la columna estado de una cotización específica."""
    sql = "UPDATE cotizaciones SET estado = %s WHERE id = %s;"
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (estado, cotizacion_id))
            conn.commit()
        return True
    except Exception:
        return False

def actualizar_encabezado_cotizacion(
    cotizacion_id: int,
    tipo_cotizacion: str = None,
    numero_proceso: str = None,
    observaciones: str = None,
    estado: str = None,
) -> bool:
    """Actualiza el tipo, número de proceso, observaciones y/o estado de una cotización."""
    fields = []
    params = []

    if tipo_cotizacion is not None:
        fields.append("tipo_cotizacion = %s")
        params.append(tipo_cotizacion)
    if numero_proceso is not None:
        fields.append("numero_proceso = %s")
        params.append(numero_proceso if numero_proceso.strip() else None)
    if observaciones is not None:
        fields.append("observaciones = %s")
        params.append(observaciones)
    if estado is not None:
        fields.append("estado = %s")
        params.append(estado)

    if not fields:
        return True

    params.append(cotizacion_id)
    sql = f"UPDATE cotizaciones SET {', '.join(fields)} WHERE id = %s;"

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
            conn.commit()
        return True
    except Exception as e:
        st.error(f"Error actualizando el encabezado: {e}")
        return False

def agregar_item_a_cotizacion_existente(cotizacion_id: int, item: dict) -> bool:
    """Añade un nuevo ítem a una cotización registrada y recomputa subtotal, IVA y total."""
    sql_max_item = "SELECT COALESCE(MAX(numero_item), 0) + 1 FROM cotizacion_items WHERE cotizacion_id = %s;"
    sql_insert_item = """
        INSERT INTO cotizacion_items (
            cotizacion_id, numero_item, descripcion, cantidad,
            unidad_medida, costo_unitario, margen_porcentaje,
            precio_venta_unitario, subtotal_item, enlace_referencia
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
    """
    sql_recalcular = """
        WITH totales AS (
            SELECT 
                COALESCE(SUM(subtotal_item), 0) AS nuevo_subtotal,
                porcentaje_iva
            FROM cotizaciones c
            LEFT JOIN cotizacion_items ci ON c.id = ci.cotizacion_id
            WHERE c.id = %s
            GROUP BY c.id, c.porcentaje_iva
        )
        UPDATE cotizaciones
        SET 
            subtotal = totales.nuevo_subtotal,
            impuesto_iva = totales.nuevo_subtotal * (COALESCE(totales.porcentaje_iva, 0.0) / 100.0),
            total = totales.nuevo_subtotal * (1 + (COALESCE(totales.porcentaje_iva, 0.0) / 100.0))
        FROM totales
        WHERE cotizaciones.id = %s;
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql_max_item, (cotizacion_id,))
                num_item = cur.fetchone()[0]

                cur.execute(
                    sql_insert_item,
                    (
                        cotizacion_id,
                        num_item,
                        item["descripcion"],
                        item["cantidad"],
                        item.get("unidad_medida", "UNIDAD"),
                        item.get("costo_unitario", 0.0),
                        item.get("margen_porcentaje", 20.0),
                        item.get("precio_venta_unitario", 0.0),
                        item.get("subtotal_item", 0.0),
                        item.get("enlace_referencia", ""),
                    ),
                )
                cur.execute(sql_recalcular, (cotizacion_id, cotizacion_id))
            conn.commit()
        return True
    except Exception as e:
        st.error(f"Error al añadir ítem: {e}")
        return False

def eliminar_cotizacion(cotizacion_id: int) -> bool:
    """Elimina una cotización y sus ítems asociados."""
    sql = "DELETE FROM cotizaciones WHERE id = %s;"
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (cotizacion_id,))
            conn.commit()
        return True
    except Exception:
        return False


def cargar_items_por_cotizacion(cotizacion_id: int) -> pd.DataFrame:
    sql = """
        SELECT id, numero_item, descripcion, cantidad, unidad_medida,
               costo_unitario, margen_porcentaje, precio_venta_unitario, 
               subtotal_item, enlace_referencia
        FROM cotizacion_items
        WHERE cotizacion_id = %s
        ORDER BY numero_item ASC;
    """
    try:
        with get_db_connection() as conn:
            return pd.read_sql(sql, conn, params=(cotizacion_id,))
    except Exception:
        return pd.DataFrame()

# Alias y funciones de compatibilidad para las vistas
def cargar_detalle_cotizacion(cotizacion_id, numero_cotizacion=None):
    """Carga los ítems de la cotización asegurando tipos de datos nativos de Python."""
    # Convertir cotizacion_id de numpy.int64 a int nativo de Python
    try:
        cotizacion_id_native = int(cotizacion_id) if cotizacion_id is not None else None
    except (ValueError, TypeError):
        cotizacion_id_native = cotizacion_id

    query_id = "SELECT * FROM cotizacion_items WHERE cotizacion_id = %s ORDER BY id ASC;"
    
    try:
        with get_db_connection() as conn:
            # 1. Intentar por ID entero nativo
            df = pd.read_sql(query_id, conn, params=(cotizacion_id_native,))
            
            # 2. Fallback por número de cotización si no se encontraron ítems
            if df.empty and numero_cotizacion:
                query_num = "SELECT * FROM cotizacion_items WHERE cotizacion_id = %s OR numero_cotizacion = %s ORDER BY id ASC;"
                df = pd.read_sql(query_num, conn, params=(str(cotizacion_id_native), str(numero_cotizacion)))
                
            return df
    except Exception as e:
        st.error(f"Error cargando detalle de cotización: {e}")
        return pd.DataFrame()


def eliminar_cotizacion_completa(cotizacion_id: int) -> bool:
    """Elimina una cotización y sus ítems (alias para tab_historico.py)."""
    return eliminar_cotizacion(cotizacion_id)


@st.cache_data(ttl=300)  # Recarga automáticamente cada 5 minutos
def cargar_catalogo_historico() -> pd.DataFrame:
    """Consulta los ítems del catálogo histórico en PostgreSQL."""
    try:
        engine = get_engine()
        query = """
            SELECT id, numero_proceso, descripcion, unidad_medida, cantidad, costo_unitario 
            FROM public.banco_items_historico;
        """
        df = pd.read_sql(query, con=engine)
        return df
    except Exception as e:
        st.error(f"Error cargando catálogo desde BD: {e}")
        return pd.DataFrame()


def guardar_items_masivos_db(df_items: pd.DataFrame) -> tuple[bool, str]:
    """Limpia, desduplica columnas e inserta solo los campos válidos en 'banco_items_historico'."""
    try:
        engine = get_engine()
        df = df_items.copy()

        # 1. Mapeo de nombres de columnas
        mapeo_columnas = {
            "Número del Proceso": "numero_proceso",
            "numero_proceso": "numero_proceso",
            "descripcion": "descripcion",
            "Descripción": "descripcion",
            "unidad_medida": "unidad_medida",
            "Unidad": "unidad_medida",
            "cantidad": "cantidad",
            "Cantidad": "cantidad",
            "Costo Sugerido (COP)": "costo_unitario",
            "Valor Unitario": "costo_unitario",
            "costo_unitario": "costo_unitario",
            "enlace_referencia": "enlace_referencia",
        }

        df = df.rename(columns=mapeo_columnas)

        # 2. Desduplicar columnas conservando únicamente la primera aparición
        df = df.loc[:, ~df.columns.duplicated()]

        # 3. Filtrar columnas permitidas por la tabla PostgreSQL
        columnas_permitidas = [
            "numero_proceso",
            "descripcion",
            "unidad_medida",
            "cantidad",
            "costo_unitario",
        ]

        cols_existentes = [
            col for col in columnas_permitidas if col in df.columns
        ]
        df_final = df[cols_existentes].copy()

        # 4. Limpieza de tipos de datos sobre Series individuales
        if "cantidad" in df_final.columns:
            df_final["cantidad"] = (
                pd.to_numeric(df_final["cantidad"], errors="coerce")
                .fillna(0)
                .astype(int)
            )

        if "costo_unitario" in df_final.columns:
            serie_costo = df_final["costo_unitario"].astype(str)
            serie_costo = serie_costo.str.replace(r"[^\d.]", "", regex=True)
            df_final["costo_unitario"] = pd.to_numeric(
                serie_costo, errors="coerce"
            ).fillna(0.0)

        # 5. Inserción masiva en la base de datos
        df_final.to_sql(
            "banco_items_historico",
            con=engine,
            if_exists="append",
            index=False,
        )

        # 6. Invalidación de caché de consultas afectadas
        obtener_banco_items.clear()
        cargar_catalogo_historico.clear()

        return True, f"Se registraron {len(df_final)} ítems con éxito."

    except Exception as e:
        return False, str(e)

def actualizar_items_y_cotizacion_db(cotizacion_id: int, df_items: pd.DataFrame) -> bool:
    """Reemplaza los ítems de una cotización y recalcula Subtotal, IVA y Total en PostgreSQL."""
    sql_delete = "DELETE FROM cotizacion_items WHERE cotizacion_id = %s;"
    sql_insert = """
        INSERT INTO cotizacion_items (
            cotizacion_id, numero_item, descripcion, cantidad,
            unidad_medida, costo_unitario, margen_porcentaje,
            precio_venta_unitario, subtotal_item, enlace_referencia
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
    """
    sql_recalcular = """
        WITH totales AS (
            SELECT 
                COALESCE(SUM(subtotal_item), 0.0) AS nuevo_subtotal,
                porcentaje_iva
            FROM cotizaciones c
            LEFT JOIN cotizacion_items ci ON c.id = ci.cotizacion_id
            WHERE c.id = %s
            GROUP BY c.id, c.porcentaje_iva
        )
        UPDATE cotizaciones
        SET 
            subtotal = totales.nuevo_subtotal,
            impuesto_iva = totales.nuevo_subtotal * (COALESCE(totales.porcentaje_iva, 0.0) / 100.0),
            total = totales.nuevo_subtotal * (1 + (COALESCE(totales.porcentaje_iva, 0.0) / 100.0))
        FROM totales
        WHERE cotizaciones.id = %s;
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql_delete, (cotizacion_id,))
                
                for idx, (_, row) in enumerate(df_items.iterrows(), start=1):
                    cant = float(row.get("cantidad", 0.0) or 0.0)
                    costo = float(row.get("costo_unitario", 0.0) or 0.0)
                    margen = float(row.get("margen_porcentaje", 0.0) or 0.0)
                    p_venta = costo * (1 + (margen / 100.0))
                    subtotal = cant * p_venta

                    cur.execute(
                        sql_insert,
                        (
                            cotizacion_id,
                            idx,
                            str(row.get("descripcion", "") or "").strip(),
                            cant,
                            str(row.get("unidad_medida", "UNIDAD") or "UNIDAD").strip(),
                            costo,
                            margen,
                            p_venta,
                            subtotal,
                            str(row.get("enlace_referencia", "") or "").strip(),
                        ),
                    )

                cur.execute(sql_recalcular, (cotizacion_id, cotizacion_id))
            conn.commit()
        return True
    except Exception as e:
        st.error(f"Error al actualizar ítems en la base de datos: {e}")
        return False