-- --------------------------------------------------
-- 1. Extensiones Básicas
-- --------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- --------------------------------------------------
-- 2. Tablas Principales
-- --------------------------------------------------

-- Tabla de Clientes
CREATE TABLE IF NOT EXISTS clientes (
    id SERIAL PRIMARY KEY,
    nombre_razon_social VARCHAR(255) NOT NULL,
    nit_cedula VARCHAR(50) UNIQUE NOT NULL,
    contacto_nombre VARCHAR(150),
    contacto_email VARCHAR(150),
    telefono VARCHAR(50),
    direccion VARCHAR(255),
    ciudad VARCHAR(100) DEFAULT 'Manizales',
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Tabla de Cotizaciones (Cabecera)
CREATE TABLE IF NOT EXISTS cotizaciones (
    id SERIAL PRIMARY KEY,
    numero_cotizacion VARCHAR(100) UNIQUE NOT NULL,
    numero_proceso VARCHAR(100),
    tipo_cotizacion VARCHAR(50) DEFAULT 'GENERAL',
    cliente_id INT REFERENCES clientes(id) ON DELETE SET NULL, -- Ahora opcional
    fecha_emision TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    porcentaje_iva NUMERIC(5,2) DEFAULT 19.00,
    subtotal NUMERIC(15,2) DEFAULT 0.00,
    impuesto_iva NUMERIC(15,2) DEFAULT 0.00,
    total NUMERIC(15,2) DEFAULT 0.00,
    estado VARCHAR(50) DEFAULT 'BORRADOR',
    observaciones TEXT
);

-- Detalle de Ítems Cotizados
CREATE TABLE IF NOT EXISTS cotizacion_items (
    id SERIAL PRIMARY KEY,
    cotizacion_id INT NOT NULL REFERENCES cotizaciones(id) ON DELETE CASCADE,
    numero_item INT NOT NULL,
    descripcion TEXT NOT NULL,
    cantidad NUMERIC(12, 2) NOT NULL DEFAULT 1.00,
    unidad_medida VARCHAR(50) DEFAULT 'UNIDAD',
    costo_unitario NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    margen_porcentaje NUMERIC(5, 2) NOT NULL DEFAULT 20.00, -- Ej: 20.00%
    precio_venta_unitario NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    subtotal_item NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    UNIQUE (cotizacion_id, numero_item)
);

-- --------------------------------------------------
-- 3. Índices de Rendimiento
-- --------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_clientes_nit ON clientes(nit_cedula);
CREATE INDEX IF NOT EXISTS idx_cotizaciones_cliente ON cotizaciones(cliente_id);
CREATE INDEX IF NOT EXISTS idx_cotizacion_items_cotizacion ON cotizacion_items(cotizacion_id);

-- --------------------------------------------------
-- 4. Datos de Prueba Iniciales
-- --------------------------------------------------

-- Insertar Cliente de prueba
INSERT INTO clientes (nombre_razon_social, nit_cedula, contacto_nombre, contacto_email, telefono, ciudad) VALUES
('Distribuidora El Rebaño SAS', '900123456-1', 'Carlos Londoño', 'contacto@elrebano.com', '6068800000', 'Manizales'),
('Servicios & Soluciones Tecnológicas', '800987654-3', 'Ana María Luna', 'ventas@soluciones.co', '6068811111', 'Pereira');

-- Insertar Cotización de prueba (COT-2026-001)
INSERT INTO cotizaciones (numero_cotizacion, cliente_id, fecha_emision, fecha_vencimiento, subtotal, impuesto_iva, total, estado, observaciones) VALUES
('COT-2026-001', 1, CURRENT_DATE, CURRENT_DATE + INTERVAL '15 days', 2500000.00, 475000.00, 2975000.00, 'BORRADOR', 'Cotización inicial para infraestructura y switches.');

-- Insertar Ítems de la Cotización COT-2026-001
-- Fórmula: precio_venta_unitario = costo_unitario * (1 + (margen_porcentaje / 100))
INSERT INTO cotizacion_items (cotizacion_id, numero_item, descripcion, cantidad, unidad_medida, costo_unitario, margen_porcentaje, precio_venta_unitario, subtotal_item) VALUES
(1, 1, 'Switch administrable de 24 puertos Gigabit PoE+', 2.00, 'UNIDAD', 800000.00, 25.00, 1000000.00, 2000000.00),
(1, 2, 'Servicio de configuración e instalación en rack', 1.00, 'SERVICIO', 400000.00, 25.00, 500000.00, 500000.00);