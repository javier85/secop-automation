# database/cotizaciones_db.py
import io
import pandas as pd
import streamlit as st
from sqlalchemy import text
from datetime import datetime
from database.connection import get_db_connection, get_engine

# ==========================================
# HELPER: EXPORTAR A EXCEL
# ==========================================
def _convertir_df_a_excel(df: pd.DataFrame) -> bytes:
    """Convierte un DataFrame a archivo Excel binario en memoria."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Banco_Items")
    return output.getvalue()

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
            SET 
                descripcion = :descripcion,
                unidad_medida = :unidad,
                cantidad = :cantidad,
                costo_unitario = :costo_unitario,
                enlace = :enlace
            WHERE id = :id;
        """)

        with engine.begin() as conn:
            for idx, col_changes in edited_rows.items():
                row_id = int(df_original.iloc[idx]["ID"])

                descripcion = col_changes.get(
                    "Descripción", df_original.iloc[idx]["Descripción"]
                )
                unidad = col_changes.get(
                    "Unidad", df_original.iloc[idx]["Unidad"]
                )
                cantidad = int(
                    col_changes.get(
                        "Cantidad", df_original.iloc[idx]["Cantidad"]
                    )
                )
                costo = float(
                    col_changes.get(
                        "Valor Unitario", df_original.iloc[idx]["Valor Unitario"]
                    )
                )
                enlace = col_changes.get(
                    "Enlace / Proveedor",
                    df_original.iloc[idx]["Enlace / Proveedor"],
                )

                conn.execute(
                    query_update,
                    {
                        "id": row_id,
                        "descripcion": descripcion,
                        "unidad": unidad,
                        "cantidad": cantidad,
                        "costo_unitario": costo,
                        "enlace": enlace,
                    },
                )

    # 2. Filas eliminadas
    deleted_rows = cambios.get("deleted_rows", [])
    if deleted_rows:
        query_delete = text(
            "DELETE FROM public.banco_items_historico WHERE id = :id;"
        )
        with engine.begin() as conn:
            for idx in deleted_rows:
                row_id = int(df_original.iloc[idx]["ID"])
                conn.execute(query_delete, {"id": row_id})

# ==========================================
# 2. INTERFAZ DE USUARIO
# ==========================================
def render_tab_banco_items():
    st.subheader("🔍 Banco de Ítems e Insumos Históricos")
    st.markdown(
        "Explora y edita el histórico de precios y costos unitarios de los artículos cotizados."
    )

    # 1. Filtros y Búsqueda
    col_search, col_clean = st.columns([4, 1])
    with col_search:
        query = st.text_input(
            "🔎 Buscar por descripción o palabra clave",
            placeholder="Ej: Extintor, Guantes, Arnés...",
            key="search_banco_items",
        )
    with col_clean:
        st.markdown(
            "<div style='margin-top: 28px;'></div>", unsafe_allow_html=True
        )
        if st.button("🔄 Refrescar", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    df_items = obtener_banco_items(busqueda=query)

    if df_items.empty:
        st.warning(
            "⚠️ No se encontraron ítems que coincidan con el criterio de búsqueda."
        )
        return

    st.caption(f"Total de artículos encontrados: **{len(df_items)}**")

    # 2. Data Editor (Edición directa, Enlace clickeable)
    edited_df = st.data_editor(
        df_items,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        key="editor_banco_items",
        disabled=[
            "ID",
            "Número del Proceso",
            "Valor Total",
            "Fecha Registro",
        ],
        column_config={
            "ID": st.column_config.NumberColumn("ID", disabled=True),
            "Número del Proceso": st.column_config.TextColumn(
                "Proceso / Licitación", disabled=True, width="medium"
            ),
            "Descripción": st.column_config.TextColumn(
                "Descripción", width="large"
            ),
            "Unidad": st.column_config.TextColumn("Unidad", width="small"),
            "Cantidad": st.column_config.NumberColumn(
                "Cantidad", format="%d", min_value=1
            ),
            "Valor Unitario": st.column_config.NumberColumn(
                "Valor Unitario", format="$ %.2f", min_value=0.0
            ),
            "Valor Total": st.column_config.NumberColumn(
                "Valor Total", format="$ %.2f", disabled=True
            ),
            "Enlace / Proveedor": st.column_config.LinkColumn(
                "Enlace / Proveedor",
                display_text="Ver Enlace / Proveedor",
                width="medium",
            ),
            "Fecha Registro": st.column_config.DatetimeColumn(
                "Fecha", format="DD/MM/YYYY", disabled=True
            ),
        },
    )

    # 3. Acciones
    cambios_pendientes = st.session_state.get("editor_banco_items", {})
    tiene_cambios = bool(
        cambios_pendientes.get("edited_rows")
        or cambios_pendientes.get("deleted_rows")
    )

    st.markdown("---")
    col_btn1, col_btn2 = st.columns(2)

    with col_btn1:
        if st.button(
            "💾 Guardar Cambios en Base de Datos",
            type="primary",
            disabled=not tiene_cambios,
            use_container_width=True,
        ):
            guardar_cambios_bd(df_items, cambios_pendientes)
            st.cache_data.clear()
            st.success("✅ Cambios actualizados correctamente en PostgreSQL.")
            st.rerun()

    with col_btn2:
        st.download_button(
            label="📥 Exportar Búsqueda a Excel",
            data=_convertir_df_a_excel(edited_df),
            file_name="banco_items_historico.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
        
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
            precio_venta_unitario, subtotal_item
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
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
    """Busca ítems en el histórico por descripción o término clave."""
    sql = """
        SELECT ci.id, ci.descripcion, ci.cantidad, ci.unidad_medida,
               ci.costo_unitario, ci.margen_porcentaje, ci.precio_venta_unitario,
               ci.subtotal_item, c.numero_cotizacion, c.numero_proceso, c.fecha_emision
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
    cotizacion_id: int, estado: str = None, observaciones: str = None
) -> bool:
    """Actualiza el estado y/u observaciones de una cotización desde el histórico."""
    fields = []
    params = []

    if estado is not None:
        fields.append("estado = %s")
        params.append(estado)
    if observaciones is not None:
        fields.append("observaciones = %s")
        params.append(observaciones)

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
    except Exception:
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
    """Obtiene los ítems pertenecientes a una cotización específica."""
    sql = """
        SELECT id, numero_item, descripcion, cantidad, unidad_medida,
               costo_unitario, margen_porcentaje, precio_venta_unitario, subtotal_item
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
def cargar_detalle_cotizacion(cotizacion_id: int) -> pd.DataFrame:
    """Obtiene los ítems de una cotización específica (alias para tab_historico.py)."""
    return cargar_items_por_cotizacion(cotizacion_id)


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

        return True, f"Se registraron {len(df_final)} ítems con éxito."

    except Exception as e:
        return False, str(e)