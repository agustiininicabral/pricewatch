# Seguridad

- El proyecto no automatiza compras ni procesa pagos y no debe almacenar datos de tarjetas o credenciales bancarias.
- La base SQLite local y los archivos `.env` están excluidos de Git.
- Las publicaciones parten pendientes de validación; no se deben consultar URLs antes de validar esquema, dominio y destino de red.
- Las consultas HTTP futuras deben limitar tiempo y tamaño, validar DNS y cada redirección, y rechazar destinos locales/privados. No se deben eludir controles de acceso o frecuencia.
- Los errores guardados deben omitir secretos, cookies, tokens y datos personales.
- Solo se consultan dominios con tienda habilitada en estado `active` y adaptador registrado para el dominio exacto. En la configuración actual no hay adaptadores de red activos.
- El actualizador es serial y mantiene una pausa mínima configurable por dominio; el valor predeterminado es 60 segundos. Los adaptadores futuros deben además aplicar límites/timeout propios y reportar CAPTCHA, bloqueo y cambios de formato como errores, sin reintentos evasivos.

El endpoint de registro admite solo URLs HTTP(S), sin credenciales ni puertos no estándar; el hostname debe tener formato válido y se rechazan hostnames locales conocidos (`localhost`, `.localhost`, `.local`) y direcciones IP privadas/reservadas. El registro solo persiste el enlace. No se realiza resolución DNS ni se abre una conexión al registrarlo.

El servidor enlaza solo a `127.0.0.1`. No hay cliente HTTP en el servicio de producción y el registro de adaptadores del servidor está vacío, así que las URLs de usuarios no causan consultas automáticas ni manuales a tiendas. La validación DNS, direcciones resueltas y redirecciones debe implementarse y probarse antes de habilitar cualquier adaptador de red futuro; la validación de entrada por sí sola no se considera una defensa SSRF completa.
