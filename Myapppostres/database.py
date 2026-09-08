import sqlite3

def get_db_connection():
    conn = sqlite3.connect('tortas.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Tabla de Tortas / Catálogo
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS productos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            descripcion TEXT,
            precio_usd REAL NOT NULL
        )
    ''')

    # Tabla Agenda de Encargos
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS agenda_pedidos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_nombre TEXT NOT NULL,
            cliente_telefono TEXT,
            descripcion_pedido TEXT NOT NULL,
            fecha_entrega DATE NOT NULL,
            hora_entrega TEXT,
            monto_total_usd REAL NOT NULL,
            abono_usd REAL DEFAULT 0.0,
            saldo_pendiente_usd REAL NOT NULL,
            estado TEXT DEFAULT 'Pendiente',
            fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Tabla de Ventas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ventas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL,
            detalle TEXT NOT NULL,
            monto_usd REAL NOT NULL,
            monto_bs REAL NOT NULL,
            tasa_aplicada REAL NOT NULL,
            metodo_pago TEXT,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Tabla de Egresos / Gastos
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS egresos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            concepto TEXT NOT NULL,
            categoria TEXT NOT NULL, -- Materia Prima, Empaques/Bases, Servicios, Transporte, Otros
            monto_usd REAL NOT NULL,
            monto_bs REAL NOT NULL,
            tasa_aplicada REAL NOT NULL,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Configuración de Tasa
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS configuracion (
            clave TEXT PRIMARY KEY,
            valor REAL NOT NULL
        )
    ''')
    cursor.execute("INSERT OR IGNORE INTO configuracion (clave, valor) VALUES ('tasa_dolar', 50.0)")

    conn.commit()
    conn.close()
    print("Base de datos tortas.db actualizada correctamente.")

if __name__ == '__main__':
    init_db()