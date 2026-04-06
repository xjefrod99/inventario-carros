# Inventario de Carros

Aplicación en Streamlit para extraer, guardar y gestionar inventario de carros desde sitios configurados.

## Requisitos previos

- Python 3.10+
- `pip`
- (Opcional pero recomendado) entorno virtual (`venv`)

## 1) Instalar dependencias

Desde la carpeta `inventario`:

```bash
cd /directorio/inventario
```

### Opción recomendada: usar entorno virtual
### Descargar `venv` usando pip
pip install virtualenv


```bash
python3 -m 2026 .venv
./Scripts/activate
```

### Instalar paquetes de Python

```bash
pip install -r requirements.txt
```

### Instalar navegadores de Playwright

> Necesario para el modo de scraping con Playwright.

```bash
playwright install chromium
```

## (Opcional) 4 Guardar sesión Playwright (anti-bot) / Es necesario solo para usaridetoday y astroautoworld

Algunos sitios pueden bloquear `requests`/Playwright en modo headless (VPN/IPs compartidas). Puedes abrir un navegador visible, pasar el challenge manualmente una vez y guardar la sesión (cookies/storage_state) para reutilizarla.

```bash
python init_playwright_state.py --site usaridetoday
```

```bash
python init_playwright_state.py --site astroautoworld
```
Esto guarda un archivo en `.playwright_state/` y la app lo reutiliza automáticamente cuando el motor sea Playwright.

## 2) Ejecutar la aplicación

Desde la carpeta `inventario`:

```bash
streamlit run main.py
```

Luego abre en tu navegador la URL que muestra Streamlit (normalmente `http://localhost:8501`).

## 3) Uso rápido

- Ve a la sección **Actualizar**.
- Elige el **Sitio**.
- Elige el **Motor de scraping**:
  - **Auto**: usa el motor definido en configuración.
  - **Playwright**: fuerza Playwright para esa ejecución.
  - **Requests**: fuerza requests para esa ejecución.
- Presiona **Extrayendo** para cargar datos al inventario.

## Notas

- La base de datos local se crea automáticamente como `inventario_carros.db`.
- Si faltan paquetes o hay errores de importación, vuelve a ejecutar:

```bash
pip install -r requirements.txt
```
