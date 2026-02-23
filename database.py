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
                (titulo, year, marca, modelo, precio_actual, estado,
                 llave_unica, precio_previo, ultima_actualizacion, url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    titulo,
                    str(year) if year is not None else "",
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
                SET titulo = ?, year = ?, marca = ?, modelo = ?, url = ?
                WHERE id = ?
                ''',
                (
                    titulo,
                    str(year) if year is not None else "",
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
                SET titulo = ?, year = ?, marca = ?, modelo = ?, url = ?
                WHERE id = ?
                ''',
                (
                    titulo,
                    str(year) if year is not None else "",
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
            estado = "Precio Baja"
        else:
            estado = "Precio Sube"

        cursor.execute(
            f'''
            UPDATE {TABLE_NAME}
            SET
                titulo = ?,
                year = ?,
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
    """Marca como COMPRADO los carros cuya llave_unica no apareció en el scrape actual."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT id, llave_unica, estado FROM {TABLE_NAME}")
        rows = cursor.fetchall()

        ids_a_marcar = []
        for carro_id, llave, estado in rows:
            if not llave:
                continue
            if llave not in llaves_actuales and estado != "COMPRADO":
                ids_a_marcar.append(carro_id)

        if ids_a_marcar:
            for carro_id in ids_a_marcar:
                cursor.execute(
                    f"SELECT ultima_actualizacion FROM {TABLE_NAME} WHERE id = ?",
                    (carro_id,),
                )
                (ultima_actualizacion,) = cursor.fetchone()
                ultima_actualizacion = (ultima_actualizacion or "").strip()
                if ultima_actualizacion:
                    nueva_ultima_actualizacion = f"{ultima_actualizacion},{hoy}"
                else:
                    nueva_ultima_actualizacion = hoy

                cursor.execute(
                    f'''
                    UPDATE {TABLE_NAME}
                    SET estado = ?, ultima_actualizacion = ?
                    WHERE id = ?
                    ''',
                    ("COMPRADO", nueva_ultima_actualizacion, carro_id),
                )

            conn.commit()
    finally:
        conn.close()


def obtener_inventario():
    """Obtiene todos los carros del inventario."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        f'''
        SELECT
            id, titulo, year, marca, modelo, precio_actual, estado,
            llave_unica, precio_previo, ultima_actualizacion, url
        FROM {TABLE_NAME}
        ORDER BY id DESC
        '''
    )
    rows = cursor.fetchall()
    conn.close()

    columns = [
        'id',
        'titulo',
        'year',
        'marca',
        'modelo',
        'precio_actual',
        'estado',
        'llave_unica',
        'precio_previo',
        'ultima_actualizacion',
        'url',
    ]

    return pd.DataFrame(rows, columns=columns) if rows else pd.DataFrame(columns=columns)


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
