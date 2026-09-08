import os
import sqlite3
import calendar
from datetime import datetime
import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "clave_secreta_postresmv"
DB_NAME = 'tortas.db'

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def obtener_tasa():
    conn = get_db_connection()
    tasa = conn.execute("SELECT valor FROM configuracion WHERE clave = 'tasa_dolar'").fetchone()
    conn.close()
    return float(tasa['valor']) if tasa else 50.0

@app.context_processor
def inject_global_data():
    return dict(tasa_dolar=obtener_tasa())

# --- DASHBOARD (INICIO) ---
@app.route('/')
@app.route('/dashboard')
def dashboard():
    conn = get_db_connection()
    tasa = obtener_tasa()

    pedidos_proximos = conn.execute('''
        SELECT * FROM agenda_pedidos 
        WHERE estado != 'Entregado' AND estado != 'Cancelado'
        ORDER BY fecha_entrega ASC, hora_entrega ASC
    ''').fetchall()

    total_por_cobrar = conn.execute('''
        SELECT SUM(saldo_pendiente_usd) as total 
        FROM agenda_pedidos 
        WHERE estado != 'Entregado' AND estado != 'Cancelado'
    ''').fetchone()['total'] or 0.0

    ventas_hoy = conn.execute('''
        SELECT SUM(monto_usd) as total_usd, SUM(monto_bs) as total_bs 
        FROM ventas 
        WHERE DATE(fecha) = DATE('now')
    ''').fetchone()
    total_ventas_hoy_usd = ventas_hoy['total_usd'] or 0.0
    total_ventas_hoy_bs = ventas_hoy['total_bs'] or 0.0

    ventas_mes = conn.execute('''
        SELECT SUM(monto_usd) as total_usd, SUM(monto_bs) as total_bs 
        FROM ventas 
        WHERE strftime('%Y-%m', fecha) = strftime('%Y-%m', 'now')
    ''').fetchone()
    total_ventas_mes_usd = ventas_mes['total_usd'] or 0.0
    total_ventas_mes_bs = ventas_mes['total_bs'] or 0.0

    egresos_mes = conn.execute('''
        SELECT SUM(monto_usd) as total_usd, SUM(monto_bs) as total_bs 
        FROM egresos 
        WHERE strftime('%Y-%m', fecha) = strftime('%Y-%m', 'now')
    ''').fetchone()
    total_egresos_mes_usd = egresos_mes['total_usd'] or 0.0
    total_egresos_mes_bs = egresos_mes['total_bs'] or 0.0

    ganancia_neta_usd = total_ventas_mes_usd - total_egresos_mes_usd
    ganancia_neta_bs = total_ventas_mes_bs - total_egresos_mes_bs

    conn.close()
    return render_template('dashboard.html', 
                           pedidos=pedidos_proximos,
                           por_cobrar=total_por_cobrar,
                           ventas_hoy_usd=total_ventas_hoy_usd,
                           ventas_hoy_bs=total_ventas_hoy_bs,
                           ventas_mes_usd=total_ventas_mes_usd,
                           ventas_mes_bs=total_ventas_mes_bs,
                           egresos_mes_usd=total_egresos_mes_usd,
                           egresos_mes_bs=total_egresos_mes_bs,
                           ganancia_neta_usd=ganancia_neta_usd,
                           ganancia_neta_bs=ganancia_neta_bs)

# --- EGRESOS ---
@app.route('/egresos', methods=['GET', 'POST'])
def egresos():
    conn = get_db_connection()
    tasa = obtener_tasa()
    if request.method == 'POST':
        concepto = request.form['concepto']
        categoria = request.form.get('categoria', 'Otros')
        monto_usd = float(request.form['monto_usd'])
        monto_bs = monto_usd * tasa

        conn.execute('''
            INSERT INTO egresos (concepto, categoria, monto_usd, monto_bs, tasa_aplicada)
            VALUES (?, ?, ?, ?, ?)
        ''', (concepto, categoria, monto_usd, monto_bs, tasa))
        conn.commit()
        flash('Gasto registrado exitosamente.', 'success')
        return redirect(url_for('egresos'))

    historial_egresos = conn.execute('SELECT * FROM egresos ORDER BY fecha DESC LIMIT 50').fetchall()
    egresos_mes = conn.execute('''
        SELECT SUM(monto_usd) as total_usd, SUM(monto_bs) as total_bs 
        FROM egresos 
        WHERE strftime('%Y-%m', fecha) = strftime('%Y-%m', 'now')
    ''').fetchone()
    total_egresos_usd = egresos_mes['total_usd'] or 0.0
    total_egresos_bs = egresos_mes['total_bs'] or 0.0

    conn.close()
    return render_template('egresos.html', 
                           egresos=historial_egresos,
                           total_egresos_usd=total_egresos_usd,
                           total_egresos_bs=total_egresos_bs)

@app.route('/egresos/eliminar/<int:id>', methods=['POST'])
def eliminar_egreso(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM egresos WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    flash('Gasto eliminado.', 'warning')
    return redirect(url_for('egresos'))

# --- AGENDA ---
@app.route('/agenda', methods=['GET', 'POST'])
def agenda():
    conn = get_db_connection()
    if request.method == 'POST':
        cliente = request.form['cliente_nombre']
        telefono = request.form.get('cliente_telefono', '')
        descripcion = request.form['descripcion_pedido']
        fecha_entrega = request.form['fecha_entrega']
        hora_entrega = request.form.get('hora_entrega', '')
        total = float(request.form['monto_total_usd'])
        abono = float(request.form.get('abono_usd', 0.0))

        if abono > total:
            flash('El abono inicial no puede ser mayor al total del pedido.', 'danger')
            conn.close()
            return redirect(url_for('agenda'))

        saldo = max(0.0, total - abono)

        conn.execute('''
            INSERT INTO agenda_pedidos 
            (cliente_nombre, cliente_telefono, descripcion_pedido, fecha_entrega, hora_entrega, monto_total_usd, abono_usd, saldo_pendiente_usd, estado)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Pendiente')
        ''', (cliente, telefono, descripcion, fecha_entrega, hora_entrega, total, abono, saldo))
        conn.commit()
        flash('Encargo agendado exitosamente.', 'success')
        return redirect(url_for('agenda'))

    pedidos = conn.execute('SELECT * FROM agenda_pedidos ORDER BY fecha_entrega ASC').fetchall()
    productos = conn.execute('SELECT * FROM productos ORDER BY nombre ASC').fetchall()
    conn.close()
    return render_template('agenda.html', pedidos=pedidos, productos=productos)

@app.route('/agenda/editar/<int:id>', methods=['POST'])
def editar_pedido(id):
    conn = get_db_connection()
    pedido = conn.execute('SELECT * FROM agenda_pedidos WHERE id = ?', (id,)).fetchone()
    
    if not pedido:
        flash('Encargo no encontrado.', 'danger')
        conn.close()
        return redirect(url_for('agenda'))

    if pedido['estado'] == 'Entregado':
        flash('No se puede editar un encargo que ya fue marcado como Entregado.', 'warning')
        conn.close()
        return redirect(url_for('agenda'))

    cliente = request.form['cliente_nombre']
    telefono = request.form.get('cliente_telefono', '')
    descripcion = request.form['descripcion_pedido']
    fecha_entrega = request.form['fecha_entrega']
    hora_entrega = request.form.get('hora_entrega', '')
    total = float(request.form['monto_total_usd'])
    abono = float(request.form.get('abono_usd', 0.0))

    if abono > total:
        flash('El monto abonado no puede superar el total del pedido.', 'danger')
        conn.close()
        return redirect(url_for('agenda'))

    saldo = max(0.0, total - abono)

    conn.execute('''
        UPDATE agenda_pedidos
        SET cliente_nombre = ?,
            cliente_telefono = ?,
            descripcion_pedido = ?,
            fecha_entrega = ?,
            hora_entrega = ?,
            monto_total_usd = ?,
            abono_usd = ?,
            saldo_pendiente_usd = ?
        WHERE id = ?
    ''', (cliente, telefono, descripcion, fecha_entrega, hora_entrega, total, abono, saldo, id))
    conn.commit()
    conn.close()
    flash(f'Encargo de {cliente} actualizado correctamente.', 'success')
    return redirect(url_for('agenda'))

@app.route('/agenda/actualizar_estado/<int:id>', methods=['POST'])
def actualizar_estado_pedido(id):
    nuevo_estado = request.form['nuevo_estado']
    conn = get_db_connection()
    pedido = conn.execute('SELECT * FROM agenda_pedidos WHERE id = ?', (id,)).fetchone()

    if pedido:
        if nuevo_estado == 'Entregado' and pedido['estado'] != 'Entregado':
            tasa = obtener_tasa()
            monto_usd = pedido['monto_total_usd']
            monto_bs = monto_usd * tasa
            conn.execute('''
                INSERT INTO ventas (tipo, detalle, monto_usd, monto_bs, tasa_aplicada, metodo_pago)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', ('Encargo Entregado', f"Torta Encargo: {pedido['cliente_nombre']} - {pedido['descripcion_pedido']}", monto_usd, monto_bs, tasa, 'Encargo'))
            conn.execute('UPDATE agenda_pedidos SET estado = ?, saldo_pendiente_usd = 0.0, abono_usd = monto_total_usd WHERE id = ?', (nuevo_estado, id))
            flash(f"Encargo de {pedido['cliente_nombre']} entregado y registrado en ventas.", 'success')
        else:
            conn.execute('UPDATE agenda_pedidos SET estado = ? WHERE id = ?', (nuevo_estado, id))
            flash('Estado actualizado.', 'info')
        conn.commit()
    conn.close()
    return redirect(url_for('agenda'))

@app.route('/agenda/eliminar/<int:id>', methods=['POST'])
def eliminar_pedido(id):
    conn = get_db_connection()
    pedido = conn.execute('SELECT * FROM agenda_pedidos WHERE id = ?', (id,)).fetchone()

    if pedido:
        if pedido['estado'] == 'Entregado':
            patron_detalle = f"Torta Encargo: {pedido['cliente_nombre']} - {pedido['descripcion_pedido']}"
            conn.execute('''
                DELETE FROM ventas 
                WHERE tipo = 'Encargo Entregado' AND detalle = ?
            ''', (patron_detalle,))

        conn.execute('DELETE FROM agenda_pedidos WHERE id = ?', (id,))
        conn.commit()
        flash(f"Encargo de {pedido['cliente_nombre']} eliminado correctamente.", 'warning')
    else:
        flash("El encargo no fue encontrado.", "danger")

    conn.close()
    return redirect(url_for('agenda'))

@app.route('/agenda/abonar/<int:id>', methods=['POST'])
def abonar_pedido(id):
    abono_adicional = float(request.form['abono_adicional'])
    conn = get_db_connection()
    pedido = conn.execute('SELECT * FROM agenda_pedidos WHERE id = ?', (id,)).fetchone()
    
    if pedido:
        if pedido['estado'] == 'Entregado':
            flash('No se pueden registrar abonos a un pedido ya entregado.', 'warning')
            conn.close()
            return redirect(url_for('agenda'))

        saldo_actual = pedido['saldo_pendiente_usd']

        if abono_adicional > saldo_actual:
            flash(f'Error: No puedes abonar más del saldo restante (${saldo_actual:.2f}).', 'danger')
            conn.close()
            return redirect(url_for('agenda'))

        nuevo_abono = pedido['abono_usd'] + abono_adicional
        nuevo_saldo = max(0.0, pedido['monto_total_usd'] - nuevo_abono)

        conn.execute('UPDATE agenda_pedidos SET abono_usd = ?, saldo_pendiente_usd = ? WHERE id = ?',
                     (nuevo_abono, nuevo_saldo, id))
        conn.commit()
        flash('Abono registrado con éxito.', 'success')
    conn.close()
    return redirect(url_for('agenda'))

# --- GENERADOR DE RECIBOS ---
@app.route('/recibo/pedido/<int:id>')
def recibo_pedido(id):
    conn = get_db_connection()
    pedido = conn.execute('SELECT * FROM agenda_pedidos WHERE id = ?', (id,)).fetchone()
    conn.close()
    if not pedido:
        flash("Encargo no encontrado.", "danger")
        return redirect(url_for('agenda'))
    
    tasa = obtener_tasa()
    return render_template('recibo.html', tipo='encargo', item=pedido, tasa=tasa, ahora=datetime.now())

@app.route('/recibo/venta/<int:id>')
def recibo_venta(id):
    conn = get_db_connection()
    venta = conn.execute('SELECT * FROM ventas WHERE id = ?', (id,)).fetchone()
    conn.close()
    if not venta:
        flash("Venta no encontrada.", "danger")
        return redirect(url_for('ventas'))
    
    return render_template('recibo.html', tipo='venta', item=venta, tasa=venta['tasa_aplicada'], ahora=datetime.now())

# --- VENTAS ---
@app.route('/ventas', methods=['GET', 'POST'])
def ventas():
    conn = get_db_connection()
    tasa = obtener_tasa()
    if request.method == 'POST':
        detalle = request.form['detalle']
        monto_usd = float(request.form['monto_usd'])
        monto_bs = monto_usd * tasa
        metodo = request.form.get('metodo_pago', 'Pago Móvil')

        conn.execute('''
            INSERT INTO ventas (tipo, detalle, monto_usd, monto_bs, tasa_aplicada, metodo_pago)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', ('Venta Directa', detalle, monto_usd, monto_bs, tasa, metodo))
        conn.commit()
        flash('Venta registrada con éxito.', 'success')
        return redirect(url_for('ventas'))

    historial = conn.execute('SELECT * FROM ventas ORDER BY fecha DESC LIMIT 50').fetchall()
    prods = conn.execute('SELECT * FROM productos ORDER BY nombre ASC').fetchall()

    ventas_mes = conn.execute('''
        SELECT SUM(monto_usd) as total_usd, SUM(monto_bs) as total_bs 
        FROM ventas 
        WHERE strftime('%Y-%m', fecha) = strftime('%Y-%m', 'now')
    ''').fetchone()
    total_mes_usd = ventas_mes['total_usd'] or 0.0
    total_mes_bs = ventas_mes['total_bs'] or 0.0

    conn.close()
    return render_template('ventas.html', 
                           ventas=historial, 
                           productos=prods,
                           ventas_mes_usd=total_mes_usd,
                           ventas_mes_bs=total_mes_bs)

# --- CALENDARIO HISTÓRICO ---
@app.route('/calendario')
def calendario():
    ahora = datetime.now()
    year = int(request.args.get('year', ahora.year))
    month = int(request.args.get('month', ahora.month))

    conn = get_db_connection()
    mes_str = f"{year:04d}-{month:02d}"
    filas = conn.execute('''
        SELECT strftime('%d', fecha) as dia, 
               SUM(monto_usd) as total_usd, 
               SUM(monto_bs) as total_bs,
               COUNT(id) as total_transacciones
        FROM ventas 
        WHERE strftime('%Y-%m', fecha) = ?
        GROUP BY strftime('%d', fecha)
    ''', (mes_str,)).fetchall()

    datos_dias = {int(f['dia']): f for f in filas}

    total_mes_usd = conn.execute('''
        SELECT SUM(monto_usd) as total FROM ventas WHERE strftime('%Y-%m', fecha) = ?
    ''', (mes_str,)).fetchone()['total'] or 0.0

    total_mes_bs = conn.execute('''
        SELECT SUM(monto_bs) as total FROM ventas WHERE strftime('%Y-%m', fecha) = ?
    ''', (mes_str,)).fetchone()['total'] or 0.0

    dia_seleccionado = request.args.get('dia')
    detalle_dia = []
    if dia_seleccionado:
        fecha_completa = f"{mes_str}-{int(dia_seleccionado):02d}"
        detalle_dia = conn.execute('''
            SELECT * FROM ventas WHERE DATE(fecha) = ? ORDER BY fecha DESC
        ''', (fecha_completa,)).fetchall()

    conn.close()

    cal = calendar.Calendar(firstweekday=0)
    semanas = cal.monthdayscalendar(year, month)
    meses_nombres = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

    prev_month = 12 if month == 1 else month - 1
    prev_year = year - 1 if month == 1 else year
    next_month = 1 if month == 12 else month + 1
    next_year = year + 1 if month == 12 else year

    return render_template('calendario.html',
                           semanas=semanas,
                           year=year,
                           month=month,
                           nombre_mes=meses_nombres[month],
                           datos_dias=datos_dias,
                           total_mes_usd=total_mes_usd,
                           total_mes_bs=total_mes_bs,
                           prev_month=prev_month,
                           prev_year=prev_year,
                           next_month=next_month,
                           next_year=next_year,
                           dia_seleccionado=dia_seleccionado,
                           detalle_dia=detalle_dia)

# --- PRODUCTOS ---
@app.route('/productos', methods=['GET', 'POST'])
def productos():
    conn = get_db_connection()
    if request.method == 'POST':
        nombre = request.form['nombre']
        descripcion = request.form.get('descripcion', '')
        precio = float(request.form['precio_usd'])
        conn.execute('INSERT INTO productos (nombre, descripcion, precio_usd) VALUES (?, ?, ?)',
                     (nombre, descripcion, precio))
        conn.commit()
        flash('Torta guardada en catálogo.', 'success')
        return redirect(url_for('productos'))

    items = conn.execute('SELECT * FROM productos ORDER BY nombre ASC').fetchall()
    conn.close()
    return render_template('productos.html', productos=items)

@app.route('/productos/eliminar/<int:id>', methods=['POST'])
def eliminar_producto(id):
    conn = get_db_connection()
    conn.execute('DELETE FROM productos WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    flash('Producto eliminado.', 'warning')
    return redirect(url_for('productos'))

# --- BASE DE DATOS ---
@app.route('/basededatos')
def basededatos():
    tamano_kb = 0
    if os.path.exists(DB_NAME):
        tamano_kb = round(os.path.getsize(DB_NAME) / 1024, 2)
    return render_template('basededatos.html', tamano_kb=tamano_kb)

@app.route('/basededatos/exportar')
def exportar_db():
    if os.path.exists(DB_NAME):
        nombre_descarga = f"postresmv_respaldo_{datetime.now().strftime('%Y%m%d_%H%M')}.db"
        return send_file(DB_NAME, as_attachment=True, download_name=nombre_descarga)
    flash("No se encontró la base de datos para exportar.", "danger")
    return redirect(url_for('basededatos'))

@app.route('/basededatos/importar', methods=['POST'])
def importar_db():
    if 'archivo_db' not in request.files:
        flash("No se seleccionó ningún archivo.", "warning")
        return redirect(url_for('basededatos'))
    
    file = request.files['archivo_db']
    if file.filename == '':
        flash("No seleccionaste un archivo válido.", "warning")
        return redirect(url_for('basededatos'))

    if file and file.filename.endswith('.db'):
        filename = secure_filename(file.filename)
        file.save(DB_NAME)
        flash("Base de datos restaurada correctamente.", "success")
    else:
        flash("El archivo debe tener extensión .db", "danger")

    return redirect(url_for('basededatos'))

# --- TASA OFICIAL ---
@app.route('/actualizar_tasa', methods=['POST'])
def actualizar_tasa():
    nueva_tasa = float(request.form['tasa_dolar'])
    conn = get_db_connection()
    conn.execute("UPDATE configuracion SET valor = ? WHERE clave = 'tasa_dolar'", (nueva_tasa,))
    conn.commit()
    conn.close()
    flash('Tasa actualizada correctamente.', 'info')
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/sincronizar_tasa')
def sincronizar_tasa():
    try:
        url = "https://www.bcv.org.ve"
        r = requests.get(url, verify=False, timeout=8)
        soup = BeautifulSoup(r.content, 'html.parser')
        dolar_div = soup.find('div', id='dolar')
        tasa_texto = dolar_div.find('strong').text.strip().replace(',', '.')
        valor = float(tasa_texto)

        conn = get_db_connection()
        conn.execute("UPDATE configuracion SET valor = ? WHERE clave = 'tasa_dolar'", (valor,))
        conn.commit()
        conn.close()
        flash(f'Tasa BCV sincronizada en Bs. {valor:.2f}', 'success')
    except Exception as e:
        flash(f'No se pudo sincronizar automáticamente: {str(e)}', 'danger')
    return redirect(request.referrer or url_for('dashboard'))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)