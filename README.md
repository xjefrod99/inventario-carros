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
