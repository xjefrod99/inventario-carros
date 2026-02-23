from datetime import datetime
import sqlite3

import streamlit as st

from client import scrape_properties
from database import (
    borrar_carro,
    borrar_todo_inventario,
    obtener_inventario,
    init_database,
    insertar_carro,
    marcar_compra,
)
from site_configs import SITE_CONFIGS


def run_app():
    st.set_page_config(page_title="Inventario de Carros", layout="wide")

    init_database()

    st.sidebar.title("📋 Administrador de Inventario")
    page = st.sidebar.radio(
        "Selecciona una página", ["Inicio", "Actualizar", "Agregar Carro", "Gestionar", "Configuración"]
    )

    if page == "Inicio":
        st.title("Inventario de Carros")
        st.markdown("---")

        col1, col2, col3 = st.columns(3)

        with col1:
            filter_type = st.selectbox("Filtrar por Estado", ["Todos", "Disponible", "Comprado"])

        with col2:
            sort_option = st.selectbox("Ordenar por", ["Más recientes", "Más antiguos", "Título A-Z"])

        with col3:
            st.markdown("###")

        search_text = st.text_input(
            "Buscar en tabla",
            placeholder="Escribe una o más palabras para filtrar carros...",
        )

        df = obtener_inventario()
        if filter_type == "Disponible":
            df = df[(df['estado'].isna()) | (df['estado'] == "")]
        elif filter_type == "Comprado":
            df = df[df['estado'] == 'COMPRADO']

        if search_text.strip() and not df.empty:
            words = [w.lower() for w in search_text.split() if w.strip()]
            searchable_columns = ['titulo', 'year', 'marca', 'modelo', 'estado', 'url']
            existing_cols = [c for c in searchable_columns if c in df.columns]

            if words and existing_cols:
                row_text = (
                    df[existing_cols]
                    .fillna("")
                    .astype(str)
                    .agg(" ".join, axis=1)
                    .str.lower()
                )
                mask = row_text.apply(lambda text: all(word in text for word in words))
                df = df[mask]

        if not df.empty:
            if sort_option == "Más antiguos":
                df = df.iloc[::-1]
            elif sort_option == "Título A-Z":
                df = df.sort_values('titulo')

            st.subheader(f"Total Carros: {len(df)}")
            st.dataframe(df, use_container_width=True, height=500)

            csv = df.to_csv(index=False)
            st.download_button(
                label="📥 Download as CSV",
                data=csv,
                file_name=f"inventario_carros_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
            )
        else:
            st.info("📭 No hay carros. Intenta hacer scraping primero.")

    elif page == "Actualizar":
        st.title("🌐 Actualizar Inventario de Carros")
        st.markdown("---")

        st.write(
            "Esta función extrae datos de sitios web configurados y actualiza el inventario. Asegúrate de que la estructura del sitio web no haya cambiado para obtener resultados precisos."
        )

        col_site, col_action = st.columns([4, 1])
        with col_site:
            site_name = st.selectbox("Sitio", list(SITE_CONFIGS.keys()), index=0)

        with col_action:
            st.markdown("###")
            run_extract = st.button("🔄 Extrayer", use_container_width=True)

        if run_extract:
            with st.spinner("Extrayendo datos del sitio web..."):
                properties = scrape_properties(site_name=site_name)

            if properties:
                st.success(f"✅ Encontre {len(properties)} carros!")

                today = datetime.now().strftime("%Y-%m-%d")
                llaves_actuales = set()

                with st.spinner("Guardando en la base de datos..."):
                    changed = 0
                    for prop in properties:
                        llaves_actuales.add(prop['unique_key'])
                        if insertar_carro(
                            titulo=prop['title'],
                            year=prop.get('year', ""),
                            modelo=prop.get('modelo', prop.get('location', "")),
                            descripcion=prop['description'],
                            fecha=today,
                            marca=prop.get('marca', ""),
                            url=prop.get('source_url'),
                            llave_unica=prop.get('unique_key'),
                            precio_actual=prop.get('precio_actual'),
                        ):
                            changed += 1

                    if llaves_actuales:
                        conn = sqlite3.connect('inventario_carros.db')
                        cursor = conn.cursor()
                        placeholders = ",".join(["?"] * len(llaves_actuales))
                        cursor.execute(
                            f"UPDATE carros SET estado = '' "
                            f"WHERE estado = 'COMPRADO' AND llave_unica IN ({placeholders})",
                            tuple(llaves_actuales),
                        )
                        conn.commit()
                        conn.close()

                    marcar_compra(llaves_actuales, today)

                st.success(f"✅ {changed} carros agregados/actualizados. Estados de VENDIDO actualizados.")
            else:
                st.warning("⚠️ No se encontraron carros. La estructura del sitio web puede haber cambiado.")

    elif page == "Agregar Carro":
        st.title("➕ Agregar Nuevo Carro")
        st.markdown("---")

        with st.form("add_car_form"):
            title = st.text_input("Título del Carro *", placeholder="e.g., Carro en Cortes")
            property_type = st.selectbox(
                "Tipo de Carro", ["Cortes", "Apartamento", "Casa", "Terreno", "Comercial", "Otro"]
            )
            location = st.text_input("Ubicación", placeholder="e.g., Cortes, Honduras")
            description = st.text_area("Descripción", placeholder="Detalles del carro", height=150)

            col1, col2 = st.columns(2)
            with col1:
                date_added = st.date_input("Fecha de Adición")
            with col2:
                st.markdown("###")

            submitted = st.form_submit_button("💾 Guardar Carro", use_container_width=True)

            if submitted:
                if title.strip():
                    date_str = date_added.strftime("%Y-%m-%d")
                    if insertar_carro(title, property_type, location, description, date_str):
                        st.success("✅ Carro agregado/actualizado correctamente!")
                else:
                    st.error("❌ Por favor ingrese un título para el carro")

    elif page == "Gestionar":
        st.title("🛠️ Gestionar Carros")
        st.markdown("---")

        df = obtener_inventario()

        if not df.empty:
            st.subheader("Borrar Todos los Carros")
            col_da1, col_da2 = st.columns([3, 1])
            with col_da1:
                confirm_delete_all = st.checkbox(
                    "Entiendo que esto eliminará permanentemente todos los carros.",
                    key="confirm_delete_all_manage",
                )
            with col_da2:
                if st.button("🧨 Borrar TODOS", use_container_width=True):
                    if confirm_delete_all:
                        borrar_todo_inventario()
                        st.success("✅ Todos los carros eliminados!")
                        st.rerun()
                    else:
                        st.warning("⚠️ Por favor marque la casilla de confirmación primero.")

            st.markdown("---")
            st.subheader("Borrar Carros Individuales")

            for _, row in df.iterrows():
                col1, col2 = st.columns([4, 1])

                with col1:
                    st.write(
                        f"**{row['titulo']}** - {row.get('modelo', '')} ({row.get('year', '')}) - Estado: {row.get('estado', '')}"
                    )

                with col2:
                    if st.button("🗑️ Borrar", key=f"delete_{row['id']}"):
                        borrar_carro(row['id'])
                        st.success("✅ Carro eliminado!")
                        st.rerun()
        else:
            st.info("No hay carros para gestionar")

    elif page == "Settings":
        st.title("⚙️ Configuración")
        st.markdown("---")

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Información de la Base de Datos")
            df = obtener_inventario()
            st.metric("Total Carros", len(df))

            if not df.empty:
                st.write(f"**Última actualización:** {df.iloc[0]['ultima_actualizacion']}")

        with col2:
            st.subheader("Acciones")

            if st.button("🔄 Actualizar Datos", use_container_width=True):
                st.rerun()

            if st.button("🗑️ Borrar Todos los Datos", use_container_width=True):
                if st.session_state.get('confirm_delete'):
                    borrar_todo_inventario()
                    st.success("✅ Todos los datos eliminados!")
                else:
                    st.session_state.confirm_delete = True
                    st.warning("⚠️ Haga clic nuevamente para confirmar la eliminación de todos los datos.")

        st.markdown("---")
        st.info(f"📱 Última actualización: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    run_app()
