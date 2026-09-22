
import os
import psycopg2
from contextlib import contextmanager
from sqlalchemy import create_engine
from config import DATABASE_URL, DB_HOST, DB_NAME, DB_PASS, DB_PORT, DB_USER

_engine = None

DB_URL = os.getenv("DATABASE_URL", "postgresql://usuario:password@localhost:5432/nombre_db")
def obtener_conexion():
    """Retorna una conexión directa de psycopg2 a la base de datos."""
    if DATABASE_URL:
        return psycopg2.connect(DATABASE_URL)
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
    )

# Definir la variable global 'engine'
engine = create_engine(DB_URL)
def inicializar_tabla_banco_items():
    engine = get_engine()
    create_table_sql = text("""
        CREATE TABLE IF NOT EXISTS public.banco_items_historico (
            id SERIAL PRIMARY KEY,
            numero_proceso VARCHAR(100),
            descripcion TEXT NOT NULL,
            unidad_medida VARCHAR(50),
            cantidad INT DEFAULT 1,
            costo_unitario NUMERIC(15, 2) DEFAULT 0.00,
            enlace TEXT,
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    with engine.begin() as conn:
        conn.execute(create_table_sql)
        
def get_engine():
    """Devuelve una instancia reutilizable del motor (Engine) de SQLAlchemy."""
    global _engine
    if _engine is None:
        if DATABASE_URL:
            db_url = DATABASE_URL
        else:
            db_url = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        _engine = create_engine(db_url, pool_pre_ping=True)
    return _engine


@contextmanager
def get_db_connection():
    """Proporciona un contexto de conexión seguro a PostgreSQL."""
    conn = None
    try:
        if DATABASE_URL:
            conn = psycopg2.connect(DATABASE_URL)
        else:
            conn = psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASS,
            )
        yield conn
    finally:
        if conn:
            conn.close()


def init_db_schema():
    """Verifica el estado de la conexión a la base de datos al iniciar la app."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
    except Exception as e:
        print(f"Error comprobando conexión a BD: {e}")