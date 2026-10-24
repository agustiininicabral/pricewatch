# API REST local

Base URL predeterminada: `http://127.0.0.1:8000` (el puerto se puede cambiar con `PRICEWATCH_PORT`, sin alterar el host loopback). OpenAPI/Swagger está disponible en `/docs` y el esquema OpenAPI en `/openapi.json`.

## Ejecutar en Windows

Desde PowerShell, con el entorno virtual del proyecto activado:

```powershell
# Opcional: cambiarlo si el puerto 8000 está ocupado.
$env:PRICEWATCH_PORT = "8765"
Set-Location backend
alembic upgrade head
python -m app.main
```

El servidor se enlaza solo a `127.0.0.1` (puerto 8000 por defecto). `PRICEWATCH_PORT` solo cambia el puerto, nunca la interfaz de red. La API no descarga ni visita las URL almacenadas.

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/health` | Estado de API y consulta de base (`SELECT 1`). |
| `GET` | `/api/products` | Productos activos; `?include_inactive=true` incluye desactivados. |
| `POST` | `/api/products` | Crear producto canónico. |
| `GET` | `/api/products/{product_id}` | Consultar producto. |
| `PATCH` | `/api/products/{product_id}` | Actualizar nombre, clave, marca, descripción o activación. |
| `DELETE` | `/api/products/{product_id}` | Desactivar sin borrar historial. |
| `GET` | `/api/products/{product_id}/listings` | Listar publicaciones, tienda y estado de integración. |
| `POST` | `/api/products/{product_id}/listings` | Registrar URL pendiente sin crear una observación o precio. |
| `POST` | `/api/products/{product_id}/observations` | Registrar observación normalizada y publicación. |
| `GET` | `/api/products/{product_id}/history` | Historial ascendente por fecha; admite `?listing_id=ID`. |
| `POST` | `/api/listings/{listing_id}/shipping` | Registrar cotización explícita conocida/desconocida. |
| `GET` | `/api/products/{product_id}/comparison` | Comparar último precio de cada publicación; acepta `?variant_key=...`. |
| `POST` | `/api/products/{product_id}/update` | Encolar actualización manual de las publicaciones habilitadas del producto (`202`). |
| `POST` | `/api/listings/{listing_id}/update` | Encolar actualización manual de una publicación (`202`). |
| `GET` | `/api/executions/latest` | Ver la última ejecución; filtros opcionales `product_id` y `listing_id`. |
| `GET` | `/api/executions/{run_id}` | Consultar estado, contadores y errores de una ejecución. |

Errores comunes: `404` para recursos inexistentes, `409` para claves/publicaciones en conflicto, `422` para entradas inválidas y `503` si falla la consulta de salud a la base. Los errores de validación de FastAPI incluyen el detalle del campo rechazado.

La página de PriceWatch está disponible en `http://127.0.0.1:8000/` y los recursos de la interfaz se sirven desde `/assets/` en el mismo origen. La interfaz puede crear un producto con su primera URL o añadir nuevas URLs a un producto seguido. La publicación y la tienda quedan pendientes y sin habilitar una integración; no se consulta la URL ni se inventan observaciones de precio. Desde el detalle se pueden registrar manualmente el precio observado y el envío. Solo los datos marcados como comprobados, con stock y envío conocido, pueden producir una ganadora. La búsqueda del panel filtra el catálogo local; no busca productos en sitios externos. Si el registro de la primera URL falla después de crear el producto, la interfaz indica que el producto sí quedó creado.

## Ejemplos PowerShell

Crear producto:

```powershell
$product = Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/products `
  -ContentType application/json `
  -Body '{"name":"Auriculares","canonical_key":"auriculares-modelo-x"}'
```

Registrar una URL sin declarar un precio:

```powershell
$listing = @{
  store_name = "Tienda observada"
  source_url = "https://tienda.example.com/producto"
  title = "Auriculares modelo X"
} | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/products/$($product.id)/listings" `
  -ContentType application/json -Body $listing
```

Registrar un precio observado manualmente. El `store_domain` debe corresponder al hostname de la URL; la tienda queda pendiente y deshabilitada. `observed_at` debe incluir zona horaria y se normaliza a UTC.

```powershell
$body = @{
  store_name = "Tienda observada"
  store_slug = "tienda-observada"
  store_domain = "tienda.example.com"
  source_url = "https://tienda.example.com/producto"
  title = "Auriculares modelo X"
  amount_minor = 125000
  currency = "ARS"
  availability = "in_stock"
  observed_at = "2026-10-13T12:00:00-03:00"
  extraction_method = "manual"
  validation_status = "pending_review"
} | ConvertTo-Json

$observation = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/products/$($product.id)/observations" `
  -ContentType application/json -Body $body
```

Las observaciones `pending_review` se conservan en el historial con esa condición y no participan como verificadas en la comparación. Solo deben enviarse como `verified` datos comprobados por un origen autorizado.

Agregar envío gratuito confirmado (cero es explícito, no es el valor predeterminado):

```powershell
$shipping = @{
  status = "known"
  amount_minor = 0
  currency = "ARS"
  source = "confirmado manualmente"
} | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/listings/$($observation.listing_id)/shipping" `
  -ContentType application/json -Body $shipping
```

Una cotización `unknown` se registra con `status: "unknown"` y sin importe ni moneda. Sin cotización conocida, el comparador no declara un ganador definitivo.

Consultar historial y comparación:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/products/$($product.id)/history"
Invoke-RestMethod "http://127.0.0.1:8000/api/products/$($product.id)/comparison"
```

Las actualizaciones manuales se encolan en un único worker y no bloquean la API. Si ya hay una ejecución activa para la misma publicación, la solicitud devuelve `409`. Un error de adaptador queda registrado en la ejecución y no reemplaza el último precio persistido. En esta etapa no hay adaptadores reales habilitados, por lo que la actualización manual registrada falla explícitamente como `AdapterNotReadyError`.

No hay endpoints para comprar, pagar ni autenticarse en tiendas.
