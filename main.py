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
    actualizar_carro
)
from site_configs import SITE_CONFIGS


def run_app():
    st.set_page_config(page_title="Inventario de Carros", layout="wide")

    init_database()

    st.sidebar.title("📋 Administrador de Inventario")
    page = st.sidebar.radio(
        "Selecciona una página", ["Inicio", "Actualizar", "Agregar Carro", "Editar Carro", "Configuración"]
    )

    if page == "Inicio":
        st.title("Inventario de Carros")
        st.markdown("---")

        col1, col2, col3 = st.columns(3)

        with col1:
            filter_type = st.selectbox("Filtrar por Estado", ["Todos", "Disponible", "Comprado"], index=1)

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
            df = df[(df['Estado'].isna()) | (df['Estado'] == "")  | (df['Estado'] != "COMPRADO")]
        elif filter_type == "Comprado":
            df = df[df['Estado'] == 'COMPRADO']

        if search_text.strip() and not df.empty:
            words = [w.lower() for w in search_text.split() if w.strip()]
            searchable_columns = ['Nombre', 'Año', 'Marca', 'Modelo', 'Estado']
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
                label="📥 Descargar para Excel",
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

        st.subheader("Sitios disponibles")
        st.caption("Haz clic en 'Extraer' para el sitio que quieras actualizar.")

        engine_choice = st.selectbox(
            "Motor de scraping (por ejecución)",
            ["Auto", "Playwright", "Requests"],
            index=0,
        )

        debug_captcha = st.checkbox(
            "🛡️ Resolver Captcha (manual en navegador visible)",
            value=False,
            help="Cuando se detecta un captcha, se abrirá una ventana de Chrome visible para que puedas resolverlo. El scraping se reanudará automáticamente después.",
        )

        sitio_seleccionado = None
        for sitio in sorted(SITE_CONFIGS.keys()):
            row_left, row_right = st.columns([4, 1])
            with row_left:
                st.markdown(f"**{sitio}**")
            with row_right:
                if st.button("🔄 Extraer", key=f"extraer_{sitio}", use_container_width=True):
                    sitio_seleccionado = sitio

        if sitio_seleccionado:
            engine_override = None
            if engine_choice == "Playwright":
                engine_override = "playwright"
            elif engine_choice == "Requests":
                engine_override = "requests"

            with st.spinner(f"Extrayendo datos de {sitio_seleccionado}..."):
                properties = scrape_properties(
                    site_name=sitio_seleccionado,
                    scraper_engine_override=engine_override,
                    debug_captcha=debug_captcha,
                )

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
                            miles=prop.get('miles'),
                            modelo=prop.get('modelo', prop.get('location', "")),
                            descripcion=prop['description'],
                            fecha=today,
                            marca=prop.get('marca', ""),
                            url=prop.get('source_url'),
                            llave_unica=prop.get('unique_key'),
                            precio_actual=prop.get('precio_actual'),
                        ):
                            changed += 1

                st.success(f"✅ {changed} carros agregados/actualizados.")
            else:
                st.warning("⚠️ No se encontraron carros. La estructura del sitio web puede haber cambiado.")

    elif page == "Agregar Carro":
        st.title("➕ Agregar Nuevo Carro")
        st.markdown("---")

        with st.form("add_car_form"):
            title = st.text_input("Título del Carro *", placeholder="e.g., 2020 Toyota Camry")

            col1, col2, col3 = st.columns(3)
            with col1:
                year = st.text_input("Año", placeholder="e.g., 2020")
            with col2:
                marca = st.text_input("Marca", placeholder="e.g., Toyota")
            with col3:
                modelo = st.text_input("Modelo", placeholder="e.g., Camry")

            col4, col5 = st.columns(2)
            with col4:
                miles = st.number_input("Millas", min_value=0, step=1000, value=None)
            with col5:
                precio_actual = st.number_input("Precio Actual ($)", min_value=0.0, step=100.0, value=None)

            url = st.text_input("URL", placeholder="https://...")
            description = st.text_area("Descripción", placeholder="Detalles del carro", height=100)
            date_added = st.date_input("Fecha de Adición")

            submitted = st.form_submit_button("💾 Guardar Carro", use_container_width=True)

            if submitted:
                if title.strip():
                    date_str = date_added.strftime("%Y-%m-%d")
                    if insertar_carro(
                        titulo=title,
                        year=year,
                        miles=int(miles) if miles else None,
                        modelo=modelo,
                        descripcion=description,
                        fecha=date_str,
                        marca=marca,
                        url=url or None,
                        precio_actual=float(precio_actual) if precio_actual else None,
                    ):
                        st.success("✅ Carro agregado/actualizado correctamente!")
                else:
                    st.error("❌ Por favor ingrese un título para el carro")

    elif page == "Editar Carro":
            st.title("🛠️ Editar Carros")
            st.markdown("---")

            df = obtener_inventario()

            # ── EDITAR ──────────────────────────────────────────────
            st.subheader("✏️ Editar Carro por ID")
            with st.form("edit_car_form"):
                edit_id = st.number_input("ID del Carro", min_value=1, step=1, value=None)

                col1, col2, col3 = st.columns(3)
                with col1:
                    nuevo_precio = st.number_input(
                        "Precio Actual ($)", min_value=0.0, step=100.0, value=None
                    )
                with col2:
                    nuevas_millas = st.number_input(
                        "Millas", min_value=0, step=1000, value=None
                    )
                with col3:
                    nuevo_estado = st.selectbox(
                        "Estado",
                        ["", "COMPRADO", "Precio Bajo", "Precio Subio"],
                        index=0,
                    )

                edit_submitted = st.form_submit_button("💾 Guardar Cambios", use_container_width=True)

                if edit_submitted:
                    if not edit_id:
                        st.error("❌ Por favor ingrese un ID válido.")
                    else:
                        actualizar_carro(
                            carro_id=int(edit_id),
                            precio_actual=float(nuevo_precio) if nuevo_precio is not None else None,
                            miles=int(nuevas_millas) if nuevas_millas is not None else None,
                            estado=nuevo_estado if nuevo_estado != "" else None,
                        )
                        st.success(f"✅ Carro ID {int(edit_id)} actualizado!")
                        st.rerun()

            if not df.empty:
                st.dataframe(
                    df[['id', 'Nombre', 'Año', 'Marca', 'Modelo', 'Precio Actual', 'Estado']],
                    use_container_width=True,
                    height=300,
                )

            # ── BORRAR ──────────────────────────────────────────────
            st.markdown("---")
            st.subheader("🗑️ Borrar Carros")

            if not df.empty:
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

                st.markdown("")
                for _, row in df.iterrows():
                    col1, col2 = st.columns([4, 1])
                    with col1:
                        st.write(
                            f"**[{row['id']}]** {row['Nombre']} - {row.get('Modelo', '')} ({row.get('Año', '')}) - Estado: {row.get('Estado', '')}"
                        )
                    with col2:
                        if st.button("🗑️ Borrar", key=f"delete_{row['id']}"):
                            borrar_carro(row['id'])
                            st.success("✅ Carro eliminado!")
                            st.rerun()
            else:
                st.info("No hay carros para gestionar")

    elif page == "Configuración":
        st.title("⚙️ Configuración")
        st.markdown("---")

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Información de la Base de Datos")
            df = obtener_inventario()
            st.metric("Total Carros", len(df))

            if not df.empty:
                st.write(f"**Última actualización:** {df.iloc[0]['Última Actualización']}")

        with col2:
            st.subheader("Acciones")

            if st.button("🔄 Actualizar Datos", use_container_width=True):
                st.rerun()

            if st.button("🗑️ Borrar Todos los Datos", use_container_width=True):
                if st.session_state.get('confirm_delete'):
                    borrar_todo_inventario()
                    st.success("✅ Todos los datos eliminados!")
                    st.session_state.confirm_delete = False
                else:
                    st.session_state.confirm_delete = True
                    st.warning("⚠️ Haga clic nuevamente para confirmar la eliminación de todos los datos.")

        st.markdown("---")
        st.info(f"📱 Última actualización: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    run_app()
