# Validación de la versión propuesta

Fecha: 9 de octubre de 2026. Base de referencia: commit c66a314 del repositorio original.

## Resultado automatizado

38 pruebas aprobadas con Python y SQLite, incluyendo solicitudes WSGI directamente a la aplicación. Ver código reproducible en `tests/test_system.py`.

| Brecha | Control incorporado | Evidencia |
|---|---|---|
| El mismo estudiante reserva dos salas al mismo tiempo | Integrantes normalizados por cuenta y unicidad por persona/fecha/bloque | Pruebas de responsable, integrante y seis solicitudes concurrentes |
| Dos grupos obtienen la misma sala | Transacción de escritura e índice único | Seis solicitudes simultáneas: una confirmación |
| Se supera el límite diario entre grupos | Cuenta todas las participaciones, incluida la del responsable | Seis solicitudes en horarios distintos: solo dos confirmaciones |
| Suplantación mediante campos del navegador | El responsable se toma de la sesión verificada | Se ignora el responsable falsificado en el JSON |
| Lectura o cancelación de reservas ajenas | Roles y autorización en el servidor | Sin sesión no se entregan datos; otro estudiante no puede cancelar |
| Datos personales entregados en disponibilidad | Se publican únicamente salas y bloques a usuarios autenticados | Respuestas sin correo ni RUT de otros grupos |
| Pérdida de evidencia al cancelar | Cancelación registrada con autor, fecha y motivo | Se libera disponibilidad y se conserva historial |
| Contraseñas expuestas y sesiones sin revocación | Hash de contraseñas, sesiones aleatorias, expiración, CSRF | Pruebas de hash, vencimiento, cambio de clave, cierre y origen |
| RUT repetidos o inválidos | Identidad única y validación del dígito | Pruebas de duplicados y formato |
| Alteración accidental de la base anterior | Bloqueo de inicio ante datos del esquema anterior | La tabla original permanece intacta |

## Límites de esta revisión

- No se ejecutó contra el servicio Render actual ni se modificó la base existente.
- El adaptador PostgreSQL y la configuración Gunicorn requieren una prueba de integración en un entorno de ensayo.
- La verificación visual e interactiva de escritorio/móvil no pudo completarse: la conexión al servidor local fue bloqueada por permisos de red del entorno. El servidor de desarrollo alcanzó a iniciar, pero no fue accesible desde el navegador.
- La comprobación de JavaScript verifica sintaxis, no reemplaza una prueba de interacción en navegador.
- No se verificaron políticas institucionales: horarios, capacidad, días de cierre, identidad, privacidad y retención requieren definición con biblioteca.

## Prueba de aceptación antes de activar

1. Crear al encargado sin credenciales predeterminadas y registrar dos estudiantes de prueba.
2. Confirmar que las cuentas pendientes no ingresan; aprobarlas tras verificar los datos.
3. Reservar una sala desde el primer estudiante y comprobarla en ambos paneles.
4. Intentar una segunda sala en el mismo horario: debe rechazarse, tanto como responsable como integrante.
5. Enviar dos confirmaciones simultáneas a la misma sala: una debe confirmarse y la otra mostrar un conflicto.
6. Cancelar como responsable antes del inicio y verificar que todos los integrantes recuperan disponibilidad; confirmar que un integrante no puede cancelar.
7. Confirmar que el tercer bloque diario se rechaza y que un bloque ya iniciado no puede reservarse.
8. Revisar formulario, calendario y diálogos en un teléfono de 360–390 px, escritorio y solo con teclado.
9. Reiniciar el servicio de ensayo y verificar persistencia, cookies seguras y cierre real de sesiones.
10. Validar backup/restauración, datos anteriores, reglas institucionales y política de retención antes de reemplazar producción.
