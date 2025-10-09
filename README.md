# Python API Railway Project

Este proyecto es una API construida con FastAPI y Flask, diseñada para ser desplegada en Railway. La API devuelve respuestas en formato JSON y puede ser utilizada por aplicaciones móviles, como aquellas desarrolladas en Flutter.

## Estructura del Proyecto

```
python-api-railway
├── src
│   ├── __init__.py
│   ├── config.py
│   ├── fastapi_app.py
│   └── flask_app.py
├── tests
│   └── __init__.py
├── requirements.txt
├── railway.toml
└── README.md
```

## Requisitos

Para instalar las dependencias del proyecto, asegúrate de tener `pip` instalado y ejecuta:

```
pip install -r requirements.txt
```

## Ejecución de la API

### FastAPI

Para ejecutar la aplicación FastAPI, utiliza el siguiente comando:

```
uvicorn src.fastapi_app:app --host 0.0.0.0 --port 8000 --reload
```

### Flask

Para ejecutar la aplicación Flask, utiliza el siguiente comando:

```
python src/flask_app.py
```

## Despliegue en Railway

Para desplegar la aplicación en Railway, asegúrate de tener una cuenta en [Railway](https://railway.com/) y sigue estos pasos:

1. Crea un nuevo proyecto en Railway.
2. Conecta tu repositorio de GitHub donde se encuentra este proyecto.
3. Configura el archivo `railway.toml` según tus necesidades.
4. Despliega la aplicación y accede a la URL proporcionada por Railway.

## Uso

Una vez que la API esté en funcionamiento, podrás realizar solicitudes a los endpoints definidos en `fastapi_app.py` y `flask_app.py` para obtener respuestas en formato JSON.