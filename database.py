import re
import sqlite3
import unicodedata

import pandas as pd
import streamlit as st

from utils import extract_numeric_price


DB_NAME = 'inventario_carros.db'
TABLE_NAME = 'carros'


def init_database():
    """Inicializa la base de datos SQLite para inventario de carros."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        f'''
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            miles NUM,
            year TEXT,
            marca TEXT,
            modelo TEXT,
            precio_actual REAL,
            estado TEXT,
            llave_unica TEXT UNIQUE,
            precio_previo TEXT,
            ultima_actualizacion TEXT,
            url TEXT
        )
    '''
    )

    cursor.execute(f"PRAGMA table_info({TABLE_NAME})")
    columns = [row[1] for row in cursor.fetchall()]
    if 'marca' not in columns:
        cursor.execute(f"ALTER TABLE {TABLE_NAME} ADD COLUMN marca TEXT")
    if 'miles' not in columns:
        cursor.execute(f"ALTER TABLE {TABLE_NAME} ADD COLUMN miles NUM")

    conn.commit()
    conn.close()


def build_unique_key(title: str, location: str, link: str = "") -> str:
    """Construye una llave única determinística normalizada."""

    def normalize(s: str) -> str:
        s = s.strip().lower()
        s = unicodedata.normalize("NFKD", s)
        s = s.encode("ascii", "ignore").decode("ascii")
        s = re.sub(r"[^a-z0-9]+", "-", s)
        return s.strip("-")

    title_norm = normalize(title or "")
    loc_norm = normalize(location or "")
    link_norm = normalize(link or "")

    return f"{title_norm}__{loc_norm}__{link_norm}"


def insertar_carro(
    titulo,
    year,
    miles,
    modelo,
    descripcion,
    fecha,
    marca="",
    url=None,
    llave_unica=None,
    precio_actual=None,
):
    """Inserta o actualiza un carro, guardando historial de precio y estado."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    try:
        if url is None:
            url = 'https://www.bancodeoccidente.hn/en-venta/activos-eventuales'
        if llave_unica is None:
            llave_unica = build_unique_key(titulo, modelo or "", url)

        nuevo_precio = precio_actual
        if nuevo_precio is None:
            nuevo_precio = extract_numeric_price(descripcion)
        hoy = fecha

        cursor.execute(
            f"SELECT id, precio_actual, precio_previo, ultima_actualizacion, estado "
            f"FROM {TABLE_NAME} WHERE llave_unica = ?",
            (llave_unica,),
        )
        row = cursor.fetchone()

        if row is None:
            cursor.execute(
                f'''
                INSERT INTO {TABLE_NAME}
                (titulo, year, miles, marca, modelo, precio_actual, estado,
                 llave_unica, precio_previo, ultima_actualizacion, url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    titulo,
                    str(year) if year is not None else "",
                    int(miles) if miles is not None else None,
                    marca or "",
                    modelo,
                    nuevo_precio,
                    "",
                    llave_unica,
                    "",
                    "",
                    url,
                ),
            )
            conn.commit()
            return True

        carro_id, precio_actual, precio_previo, ultima_actualizacion, _ = row
        precio_previo = precio_previo or ""
        ultima_actualizacion = ultima_actualizacion or ""

        if nuevo_precio is None or precio_actual is None:
            cursor.execute(
                f'''
                UPDATE {TABLE_NAME}
                SET titulo = ?, year = ?, miles = ?, marca = ?, modelo = ?, url = ?
                WHERE id = ?
                ''',
                (
                    titulo,
                    str(year) if year is not None else "",
                    int(miles) if miles is not None else None,
                    marca or "",
                    modelo,
                    url,
                    carro_id,
                ),
            )
            conn.commit()
            return False

        if float(nuevo_precio) == float(precio_actual):
            cursor.execute(
                f'''
                UPDATE {TABLE_NAME}
                SET titulo = ?, year = ?, miles = ?, marca = ?, modelo = ?, url = ?
                WHERE id = ?
                ''',
                (
                    titulo,
                    str(year) if year is not None else "",
                    int(miles) if miles is not None else None,
                    marca or "",
                    modelo,
                    url,
                    carro_id,
                ),
            )
            conn.commit()
            return False

        if precio_previo.strip():
            nuevo_precio_previo = f"{precio_previo},{precio_actual}"
        else:
            nuevo_precio_previo = str(precio_actual)

        if ultima_actualizacion.strip():
            nueva_ultima_actualizacion = f"{ultima_actualizacion},{hoy}"
        else:
            nueva_ultima_actualizacion = hoy

        if nuevo_precio < precio_actual:
            estado = "Precio Bajo"
        else:
            estado = "Precio Subio"

        cursor.execute(
            f'''
            UPDATE {TABLE_NAME}
            SET
                titulo = ?,
                year = ?,
                miles = ?,
                marca = ?,
                modelo = ?,
                precio_actual = ?,
                estado = ?,
                precio_previo = ?,
                ultima_actualizacion = ?,
                url = ?
            WHERE id = ?
            ''',
            (
                titulo,
                str(year) if year is not None else "",
                int(miles) if miles is not None else None,
                marca or "",
                modelo,
                nuevo_precio,
                estado,
                nuevo_precio_previo,
                nueva_ultima_actualizacion,
                url,
                carro_id,
            ),
        )
        conn.commit()
        return True

    except Exception as e:
        st.error(f"Error de base de datos: {str(e)}")
        return False
    finally:
        conn.close()


def marcar_compra(llaves_actuales: set, hoy: str):
    pass

def actualizar_carro(carro_id, precio_actual=None, miles=None, estado=None):
    """Actualiza campos editables de un carro por id."""
    campos = []
    valores = []
    if precio_actual is not None:
        campos.append("precio_actual = ?")
        valores.append(precio_actual)
    if miles is not None:
        campos.append("miles = ?")
        valores.append(miles)
    if estado is not None:
        campos.append("estado = ?")
        valores.append(estado)
    if not campos:
        return
    valores.append(carro_id)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        f"UPDATE {TABLE_NAME} SET {', '.join(campos)} WHERE id = ?",
        tuple(valores),
    )
    conn.commit()
    conn.close()
def obtener_inventario():
    """Obtiene todos los carros del inventario."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        f'''
        SELECT
            id, titulo, year, miles, marca, modelo, precio_actual, precio_previo, estado, url,
            llave_unica, ultima_actualizacion
        FROM {TABLE_NAME}
        ORDER BY id DESC
        '''
    )
    rows = cursor.fetchall()
    conn.close()
    print("rows fetched from DB:", len(rows))
    columns = [
        'id',
        'titulo',
        'year',
        'miles',
        'marca',
        'modelo',
        'precio_actual',
        'precio_previo',
        'estado',
        'url',
        'llave_unica',
        'ultima_actualizacion'
    ]
    df = pd.DataFrame(rows, columns=columns) if rows else pd.DataFrame(columns=columns)
    df.rename(columns={
        'year': 'Año',
        'titulo': 'Nombre',
        'marca': 'Marca',
        'miles': 'Millas',
        'modelo': 'Modelo',
        'precio_actual': 'Precio Actual',
        'precio_previo': 'Precio Previo',
        'estado': 'Estado',
        'url': 'URL',
        'llave_unica': 'Llave Única',
        'ultima_actualizacion': 'Última Actualización'
    }, inplace=True)
    return df


def borrar_carro(carro_id):
    """Borra un carro por id."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(f'DELETE FROM {TABLE_NAME} WHERE id = ?', (carro_id,))
    conn.commit()
    conn.close()


def borrar_todo_inventario():
    """Borra todo el inventario."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(f'DELETE FROM {TABLE_NAME}')
    conn.commit()
    conn.close()