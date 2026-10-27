# PriceWatch

PriceWatch es una aplicación local para organizar productos y publicaciones, registrar observaciones de precios y comparar ofertas verificadas. La compra siempre es manual: PriceWatch no procesa pagos ni guarda credenciales bancarias.

## Estado y límites actuales

- El panel, la API, el catálogo de productos, las publicaciones, las observaciones manuales, el historial, la comparación y el planificador local están implementados.
- **No hay integraciones reales con tiendas ni adaptadores de producción registrados.** Agregar una URL solo la guarda; no visita el sitio ni obtiene precios. Las actualizaciones no producen precios reales hasta que se incorpore un adaptador autorizado y probado.
- Sin adaptadores, una actualización manual termina informando `AdapterNotReadyError`. No cambia ni borra la última observación válida.
- El planificador espera 24 horas antes de su primer ciclo por defecto y no realiza consultas a tiendas sin adaptador registrado.
- El adaptador HTML existente es únicamente para fixtures locales controlados, no para consultar tiendas reales.
- **Las alertas no son funcionales:** existen modelos de datos, pero no hay gestión de reglas, evaluación ni notificaciones disponibles en la aplicación.
- No hay scraping general, compras ni pagos automáticos. Los precios que se comparan deben registrarse manualmente; la aplicación no los verifica con una tienda.

## Requisitos

- Windows 10/11 y Python 3.12.
- PowerShell.
- Node.js/npm únicamente si se quieren ejecutar las pruebas JavaScript del frontend. No hace falta Node para usar la interfaz.

## Instalación inicial

Desde la raíz del proyecto, en PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
```

No es necesario crear un archivo `.env`: la aplicación no carga archivos `.env` automáticamente. Los valores por defecto están documentados abajo. Si necesitás cambiarlos, definí las variables de entorno en la misma sesión de PowerShell antes de iniciar.

## Iniciar y detener

```powershell
.\start-pricewatch.ps1
```

El script comprueba que `uvicorn` esté instalado, aplica las migraciones pendientes y solo entonces inicia el servidor mediante `python -m app.main`, enlazado explícitamente a `127.0.0.1` (puerto predeterminado 8000). Abrí:

- Interfaz: <http://127.0.0.1:8000/>
- Documentación interactiva: <http://127.0.0.1:8000/docs>
- Salud de API/base de datos: <http://127.0.0.1:8000/api/health>

Detené el servidor con `Ctrl+C` en la terminal donde se ejecuta el script. No uses `uvicorn --host 0.0.0.0`, un túnel o un proxy público.

### Base de datos y configuración

Por defecto, SQLite guarda `backend\pricewatch.db`, relativa al directorio `backend` desde el que se inicia la aplicación. El script de inicio preserva los datos existentes y aplica solo migraciones pendientes. **No borres ni reemplaces la base para actualizar el proyecto.**

Variables opcionales (los mínimos se validan al inicializar el servicio):

```powershell
$env:PRICEWATCH_DATABASE_URL = "sqlite:///./pricewatch.db"
$env:PRICEWATCH_PORT = "8000"
$env:PRICEWATCH_UPDATE_INTERVAL_SECONDS = "86400"
$env:PRICEWATCH_MIN_REQUEST_INTERVAL_SECONDS = "60"
.\start-pricewatch.ps1
```

Si el puerto 8000 ya está ocupado, cambiá el valor por otro puerto local, por ejemplo `$env:PRICEWATCH_PORT = "8765"`.

- `PRICEWATCH_DATABASE_URL`: URL de SQLAlchemy para SQLite. Una ruta relativa se interpreta desde `backend`.
- `PRICEWATCH_PORT`: puerto local entre 1 y 65535; predeterminado 8000. Si está ocupado, elegí otro, por ejemplo 8765. El host continúa siendo siempre `127.0.0.1`.
- `PRICEWATCH_UPDATE_INTERVAL_SECONDS`: frecuencia automática; predeterminado 86400 (24 horas), mínimo 3600 (una hora).
- `PRICEWATCH_MIN_REQUEST_INTERVAL_SECONDS`: pausa por dominio; predeterminado 60 segundos, mínimo 10.

Las variables quedan establecidas en esa sesión de PowerShell. Cerrarla elimina esos valores del entorno de la terminal.

La aplicación enlaza solo a `127.0.0.1`; no la expongas directamente a Internet ni la ejecutes detrás de un proxy público.

## Migraciones manuales

El script de inicio ejecuta `alembic upgrade head`. Para aplicar migraciones por separado:

```powershell
Push-Location backend
try {
    ..\.venv\Scripts\python.exe -m alembic upgrade head
}
finally {
    Pop-Location
}
```

## Pruebas y comprobaciones

Suite backend (incluye las pruebas de API con bases temporales):

```powershell
Push-Location backend
try {
    ..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
}
finally {
    Pop-Location
}
```

Pruebas del cliente (requieren Node.js):

```powershell
Push-Location frontend
try {
    npm test
}
finally {
    Pop-Location
}
```

Verificá además la sintaxis del JavaScript:

```powershell
node --check frontend\src\app.js
node --check frontend\src\api.js
node --check frontend\src\actions.js
```

## Flujo de uso

1. Iniciá PriceWatch y abrí el panel local.
2. Creá un producto con su primera URL o agregá más publicaciones a un producto existente.
3. Las publicaciones nuevas quedan pendientes; registrar la URL **no** consulta la tienda.
4. En el detalle, abrí **Ingresar precio y envío manualmente** para cada publicación y cargá los datos que observaste. Un precio solo participa en la comparación si marcás que lo comprobaste manualmente, hay stock confirmado y el envío está indicado como gratuito o con costo conocido. Los valores pendientes, sin stock o con envío desconocido no producen una ganadora.
5. Una actualización manual consulta el estado de la ejecución hasta que finaliza. Si la fuente no está integrada, la UI muestra el fallo y preserva cualquier observación válida previa.
6. El enlace original abre la tienda para que el usuario complete cualquier compra personalmente.

La API y ejemplos se describen en [docs/api.md](docs/api.md). La arquitectura está en [docs/architecture.md](docs/architecture.md), la revisión de acceso a tiendas en [docs/store-integrations.md](docs/store-integrations.md) y las pautas de seguridad en [docs/security.md](docs/security.md).

## Estructura

- `backend\app\`: API, adaptadores, comparación, planificador y persistencia.
- `backend\migrations\`: migraciones versionadas de Alembic.
- `backend\tests\`: suite pytest con SQLite temporal y fuentes simuladas/locales.
- `frontend\src\`: UI de HTML, CSS y JavaScript sin servidor de desarrollo.
- `frontend\tests\`: pruebas Node del cliente y flujos de actualización.
- `docs\`: arquitectura, API, seguridad e integraciones.

GitHub Actions ejecuta las pruebas de backend en Windows con Python 3.12 y las pruebas de frontend con Node.js. El frontend no declara dependencias npm de ejecución, por lo que sus pruebas usan el runner integrado `node --test`.

La base local, sus archivos auxiliares SQLite, `.env`, entornos virtuales, cachés y archivos de claves privadas están excluidos mediante `.gitignore`. No publiques bases de datos locales ni credenciales.


## Alertas de precio (API local)

PriceWatch permite crear reglas por producto con un precio objetivo y/o una reducción mínima respecto de la observación anterior de cada publicación. La evaluación usa únicamente observaciones ya guardadas y válidas en la misma moneda. No consulta tiendas ni envía notificaciones.

1. Crea un producto y registra observaciones de prueba mediante la API.
2. Crea una regla: `POST /api/products/{product_id}/alerts`, por ejemplo `{"target_amount_minor":20000,"currency":"ARS"}`.
3. Ejecuta `POST /api/alerts/{rule_id}/evaluate`. Si la condición se cumple, devuelve un evento `pending`.
4. Consulta reglas con `GET /api/products/{product_id}/alerts` y eventos con `GET /api/alerts/{rule_id}/events`.

Para reglas de reducción, envía `{"minimum_reduction_basis_points":500,"currency":"ARS"}`; 500 puntos básicos equivalen a una reducción del 5 %. Se puede combinar con un precio objetivo. La clave de deduplicación impide crear el mismo evento más de una vez para una regla, observación y tipo de alerta.

**Alcance actual:** los eventos quedan pendientes para revisión; no hay envío de correo, push ni mensajería. La evaluación es manual mediante API, no un proceso programado. Los importes están expresados en unidades menores de la moneda, igual que el resto de la API.

La interfaz web permite crear reglas de precio objetivo o reducción mínima desde el detalle del producto y evaluarlas manualmente contra observaciones guardadas. Los eventos quedan pendientes; no se envían notificaciones.
