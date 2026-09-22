# utils/cotizacion_utils.py

# Mapeo global de Margen Real -> Factor Divisor (de 0% a 90% en pasos de 5%)
OPCIONES_MARGEN = {
    f"{p}% Margen Real (÷ {1 - p/100:.2f})": p / 100.0 for p in range(0, 95, 5)
}

def calcular_desglose_item(costo_ingresado: float, modo_iva: str, tarifa_iva: float, margen_decimal: float, cantidad: float = 1.0):
    """Calcula el costo base neto, el factor divisor y el precio de venta final aplicando la fórmula del margen real."""
    if modo_iva == "Con IVA Incluido" and tarifa_iva > 0:
        costo_base = costo_ingresado / (1 + (tarifa_iva / 100.0))
    else:
        costo_base = costo_ingresado

    factor_divisor = 1.0 - margen_decimal

    if factor_divisor <= 0:
        precio_venta_unitario = costo_base
    else:
        precio_venta_unitario = costo_base / factor_divisor

    subtotal_item = precio_venta_unitario * cantidad
    return costo_base, factor_divisor, precio_venta_unitario, subtotal_item