# Integraciones de tiendas

No hay integraciones de tiendas reales implementadas ni habilitadas en esta etapa. Las tiendas se registran con estado inicial `pending` y deshabilitado por defecto. Está disponible `FixtureHtmlAdapter` para probar el contrato con documentos HTML locales. Sus URLs usan el dominio reservado `.invalid` y se mapean a una lista cerrada de archivos bajo `backend/app/collectors/fixtures`; no hacen solicitudes de red.

## Contrato y resultado

Los adaptadores implementan `StoreAdapter` en `backend/app/collectors/contracts.py`: declaran `domain`, verifican `supports_url(source_url)` y devuelven `ProductObservation` mediante `extract(source_url)`. La observación incluye dominio y URL de origen, identificador externo opcional, título, importe entero en unidades menores, moneda explícita opcional, disponibilidad, fecha UTC, método de extracción y estado (`verified` o `pending_review`).

Un dato incompleto —por ejemplo, sin precio, moneda o disponibilidad— queda pendiente de revisión; el precio ausente es `None`, nunca cero, y la disponibilidad desconocida no se confunde con falta de stock ni con un error. Una extracción fallida se comunica mediante errores tipados (`UnsupportedURLError`, `InvalidPriceError`, `ExtractionFailedError` o `SourceUnavailableError`), no como un resultado exitoso vacío.

## Incorporar un adaptador

1. Revisar documentación, condiciones de uso, límites y método de acceso permitido de la tienda. No implementar el adaptador hasta confirmar ese acceso; evitar CAPTCHA, autenticación, límites y restricciones.
2. Crear una clase en `backend/app/collectors/` que implemente `StoreAdapter`. Declarar el dominio exacto y validar esquema, hostname y forma de las URLs antes de consultar.
3. Obtener la fuente usando únicamente un método permitido; si se usa HTTP, aplicar controles SSRF, límites de tamaño/tiempo y validación de redirecciones antes de habilitarlo.
4. Normalizar explícitamente precio y unidad menor, moneda, disponibilidad, identificador y título. No inferir moneda ni envío, no convertir datos ausentes en cero y marcar `pending_review` si falta evidencia.
5. Devolver `ProductObservation` con fecha UTC, método y procedencia. Traducir fuente inaccesible, URL no admitida, extracción fallida y precio inválido a los errores tipados del contrato.
6. Agregar pruebas aisladas con respuestas simuladas o HTML local controlado para éxito, datos incompletos, valores inválidos y errores. Nunca depender de la disponibilidad de la tienda.

El comparador consumirá `ProductObservation` y no necesitará modificar su lógica al agregar implementaciones del contrato. `FixtureHtmlAdapter` es solo un recurso de prueba; no constituye una tienda real ni una integración habilitada.

La API y el servicio de actualización persisten observaciones verificadas en el historial existente, con método, fuente, disponibilidad y fecha UTC. Si una consulta falla o una observación requiere revisión, solo se actualiza la fecha del último intento y se registra el error; la observación válida anterior no se modifica.

## Comparación

El motor de `backend/app/pricing/comparator.py` consume observaciones del contrato junto con una identidad canónica y de variante verificada y una condición explícita de envío. Un adaptador no debe intentar decidir qué otras publicaciones son el mismo producto ni elegir ganador; esas responsabilidades quedan fuera del colector. La identidad debe ser resuelta por catálogo o validación confiable antes de que la observación llegue al comparador.

## Estado de la primera integración real

Revisión del 13 de octubre de 2026: se evaluó Mercado Libre como posible primera fuente y se intentó consultar su portal oficial para desarrolladores, incluyendo documentación de búsquedas/artículos, autenticación y políticas/límites:

- https://developers.mercadolibre.com.ar/es_ar/items-y-busquedas
- https://developers.mercadolibre.com.ar/es_ar/autenticacion-y-autorizacion
- https://developers.mercadolibre.com.ar/es_ar/guia-para-politicas-y-limites-de-uso

El acceso a esas páginas devolvió HTTP 403 en esta revisión. Por lo tanto no fue posible confirmar qué endpoints son utilizables para este caso, si requieren credenciales/autorización, las cuotas aplicables ni las condiciones relevantes. No se llamó a endpoints de productos ni se hizo scraping. Mercado Libre no está implementado ni activado y el registro de adaptadores de producción está vacío.

Para avanzar con la primera integración hace falta una fuente documental accesible/oficial que confirme el alcance permitido, o que el usuario indique otra tienda y aporte/identifique la documentación o feed autorizado aplicable. Hasta entonces, las ejecuciones manuales registran `AdapterNotReadyError`; el planificador periódico solo considera tiendas habilitadas con adaptador registrado, así que no genera solicitudes de red.
