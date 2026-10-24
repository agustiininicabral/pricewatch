# Arquitectura de PriceWatch

## Etapas completadas

El backend se organiza por responsabilidad bajo `backend/app`: API, adaptadores de tiendas, catálogo canónico, comparación de precios, alertas, programación, seguridad y persistencia. La Etapa 2 incorpora `StoreAdapter`, un contrato independiente del transporte/API, y `FixtureHtmlAdapter`, que lee exclusivamente HTML local controlado y no ejecuta JavaScript ni accede a la red. La Etapa 3 implementa `compare_offers` como función pura que recibe observaciones y una identidad de producto/variante verificada más una cotización de envío explícita. La Etapa 4 agrega rutas FastAPI bajo `/api`, conectadas a SQLAlchemy y al SQLite existente. La Etapa 5 añade un worker serializado, coordinador de ejecuciones y planificador diario con intervalo por tienda.

SQLAlchemy 2 define el esquema y Alembic versiona cambios. SQLite es el almacenamiento local predeterminado. La base mantiene tiendas, productos canónicos, variantes, publicaciones, observaciones de precios, cotizaciones de envío, reglas/eventos de alertas e historial de ejecuciones.

## Persistencia y datos monetarios

Los importes se almacenan como enteros en unidades monetarias mínimas (`amount_minor`), acompañados por código ISO de moneda. No se usan números de punto flotante para dinero. Un envío desconocido se representa explícitamente con estado `unknown` y sin importe.

Las fechas se generan en UTC con timestamps conscientes de zona horaria. SQLite puede devolver timestamps sin información de zona; la aplicación debe tratarlos como UTC al leerlos y convertirlos a `America/Argentina/Buenos_Aires` únicamente al presentarlos.

Las claves únicas protegen identidades canónicas, publicaciones y deduplicación de eventos. Las claves foráneas y restricciones CHECK protegen referencias, importes y estados.

## Comparación de ofertas

El motor central no se conecta a adaptadores, API ni a la base. El llamador asigna a cada observación una `ProductIdentity` cuya clave canónica y variante exacta estén verificadas; la identidad queda sin verificar por defecto y las identidades pendientes se excluyen. El precio requiere una observación `verified`, positiva, con moneda explícita y stock confirmado. Los datos rechazados aparecen en `ComparisonResult.excluded` con motivo, y `summary` explica el alcance o por qué faltan datos.

`ShippingCost` diferencia explícitamente `free`, `paid` y `unknown`. El costo total solo se calcula si el precio es válido y el envío conocido; el envío pago debe usar la misma moneda del artículo. No se realizan conversiones: resultados con distinta identidad, variante o moneda se mantienen en grupos separados. Cada grupo ordena totales comparables y reporta la diferencia respecto de la opción más económica solo cuando no hay ofertas verificadas comparables que bloqueen la decisión. Si existe una oferta disponible con envío desconocido, el grupo explica el impedimento y no proclama ganadora.

## API local

La aplicación ASGI está en `app.main:app`. Al ejecutar `python -m app.main` enlaza explícitamente `127.0.0.1:8000`; `PRICEWATCH_PORT` permite cambiar el puerto sin modificar la dirección loopback. No se configura CORS abierto ni se consultan URLs de publicaciones. Las tablas se crean/actualizan mediante Alembic antes de iniciar el servidor. `DELETE /api/products/{id}` desactiva el producto en lugar de eliminarlo para conservar publicaciones e historial.

La API registra una tienda nueva como `pending` y deshabilitada. Cada observación pendiente queda almacenada con `is_valid=False`; solo el estado de validación verificado puede marcarla válida. La ausencia de una cotización se trata como envío desconocido. Ver `docs/api.md` para rutas.

## Interfaz local

La UI está implementada como HTML, CSS y módulos JavaScript nativos en `frontend/src`; no requiere React, servidor de desarrollo ni dependencias npm de ejecución. FastAPI sirve la página en `/` y los recursos bajo `/assets/`, desde el mismo origen y loopback. El cliente no reimplementa reglas de comparación: obtiene grupos, ofertas, bloqueos y ganadores exclusivamente de `/api/products/{id}/comparison`. Los importes se presentan usando el código de moneda y sus dígitos fraccionarios ISO. El historial se muestra en un gráfico SVG generado en el navegador con observaciones verificadas.

Registrar una publicación por URL no genera precios ni hace solicitudes a la tienda. El endpoint crea la tienda pendiente/deshabilitada y una publicación sin observaciones. Al pedir una actualización, la UI consulta el estado persistido de la ejecución hasta que sea terminal y muestra los errores; no interpreta el HTTP 202 como éxito.

## Actualizador y planificador

`UpdateService` toma el registro inyectable de adaptadores con claves de dominio, y solo consulta una tienda si está `active` y habilitada y su adaptador también declara ese dominio. En el servidor actual el registro está vacío. `UpdateCoordinator` reserva publicaciones en memoria para evitar actualizaciones concurrentes duplicadas y ejecuta una tarea a la vez. `PeriodicScheduler` espera el intervalo configurado antes del primer ciclo y se detiene junto con el lifespan de FastAPI.

`PRICEWATCH_UPDATE_INTERVAL_SECONDS` es 86400 (un día) por defecto, con mínimo de 3600 segundos. `PRICEWATCH_MIN_REQUEST_INTERVAL_SECONDS` es 60 por defecto y admite un mínimo de 10 segundos por dominio. Errores quedan en `ExecutionRun`; no se añade `PriceObservation` en error o revisión pendiente y la observación válida anterior se conserva. La migración 0002 añade vínculos opcionales a producto/publicación para consultar el alcance de cada ejecución.

## Próximas etapas

1. Alertas persistentes.
2. Interfaz y adaptador real, cuando se confirme acceso autorizado y viable.

Las integraciones reales permanecerán pendientes hasta verificar por tienda las condiciones de acceso y probar un método permitido. No se implementan compras ni pagos automáticos.
