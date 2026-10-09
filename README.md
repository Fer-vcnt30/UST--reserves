# UST Reservas · Prototipo de evaluación

Sistema de reserva de salas de estudio para estudiantes y el encargado de biblioteca, basado en el repositorio original `Fer-vcnt30/UST--reserves` (c66a314). Conserva la paleta `#009688`, `#00695c`, `#f47c20` y los fondos claros.

## Alcance

Esta versión permite probar el proceso completo: solicitud de cuenta, aprobación presencial, ingreso, consulta de disponibilidad, reserva de grupo, consulta y cancelación. Tiene exactamente dos roles: estudiante y administrador de biblioteca. No utiliza el inicio de sesión institucional ni recibe contraseñas de Microsoft/UST.

Las siete salas, capacidad de seis personas, seis bloques de dos horas entre 08:00 y 20:00 y límite de dos bloques diarios son **parámetros iniciales del prototipo**, derivados de la web anterior. Deben validarse con biblioteca; no representan una normativa institucional confirmada. No se han configurado feriados, cierre de fines de semana ni salas fuera de servicio. La zona horaria es `America/Santiago`.

## Reglas que valida el servidor

- Reservas solo para el día actual y antes del inicio del bloque. Una reserva que terminó continúa contando para el límite del día.
- Una sola reserva vigente por sala, fecha y bloque.
- Cada estudiante puede participar en una sola sala por bloque, tanto como responsable como integrante.
- Máximo dos reservas vigentes por persona al día, sumando su participación en todos los grupos.
- El responsable se incluye automáticamente. Máximo seis personas en total, sin repetir integrantes.
- Los integrantes deben ser estudiantes habilitados; se agregan por RUT exacto. El RUT se normaliza y valida mediante su dígito verificador.
- El estudiante puede cancelar sus propias reservas antes de su inicio. Los integrantes pueden consultar la reserva, pero deben pedir al responsable o a biblioteca su cancelación.
- El encargado puede cancelar una reserva vigente, incluso después de iniciada, con motivo obligatorio.
- Cancelar libera el bloque de la sala y de cada integrante; conserva el historial. Las cancelaciones administrativas también liberan el cupo diario, por lo que deben utilizarse con criterio.
- Los estudiantes no pueden crear administradores ni administrar usuarios. El encargado gestiona reservas, pero no realiza reservas como estudiante.

## Ejecución local

Requiere Python 3.11 o superior con la base de zonas horarias. En Windows, instalar `tzdata` si Python no la incluye. No requiere Node ni compilación del frontend.

```text
python -m pip install tzdata
python manage.py init
python manage.py create-admin
python manage.py serve
```

Abrir **http://127.0.0.1:8000** (usar exactamente ese origen, no `localhost`). `create-admin` solicita nombre, correo y contraseña sin mostrar la contraseña. No existen credenciales predeterminadas. La base local queda en `instance/pilot.sqlite3`, excluida de Git.

1. Crea el encargado con `create-admin`.
2. En la web, el estudiante elige **Solicitar cuenta**, con nombre, RUT, correo `@alumnos.santotomas.cl` y una contraseña exclusiva de 12 a 128 caracteres.
3. El encargado verifica presencialmente la identidad y el correo; luego selecciona **Estudiantes → Habilitar**.
4. El estudiante ingresa, selecciona un bloque y una sala, agrega integrantes habilitados y confirma.
5. El encargado ve el resultado en la agenda. El responsable y los integrantes lo ven en **Mis reservas**.

Se pueden usar distintos perfiles de navegador para probar simultáneamente estudiantes y administrador. Después de las 18:00 no quedan nuevos bloques: es el comportamiento esperado al impedir reservas de bloques que ya comenzaron. Las pruebas automatizadas usan un reloj controlado a las 07:30 para cubrir todos los horarios.

## Contraseñas y sesiones

Las contraseñas usan PBKDF2-HMAC-SHA256, 600.000 iteraciones y una sal aleatoria individual. Las sesiones duran ocho horas; en la base solo se guarda el resumen SHA-256 del identificador aleatorio. La cookie es `HttpOnly`, `SameSite=Lax` y `Secure` en producción. Cada escritura autenticada valida el origen y un token CSRF. No se guardan credenciales ni sesiones en `localStorage`.

El encargado puede restablecer una contraseña de estudiante. La contraseña temporal se muestra una sola vez y obliga a cambiarla antes de reservar. Restablecer, cambiar contraseña, deshabilitar la cuenta y cerrar sesión invalidan las sesiones correspondientes. Para recuperar el acceso del encargado desde la consola del servidor:

```text
python manage.py reset-admin
```

El correo no se verifica mediante mensajes automáticos. La revisión presencial es parte del flujo del piloto; validar solo el dominio o el dígito del RUT no demuestra identidad.

## Arquitectura

- `index.html`, `static/style.css`, `static/app.js`: interfaz sin librerías externas, acceso por roles, formularios, agenda e historial. Los textos dinámicos se crean como nodos de texto, sin interpolar datos en HTML.
- `app.py`: aplicación WSGI, rutas JSON, cookies, origen, CSRF, límites de tamaño y cabeceras de seguridad.
- `service.py`: autenticación, permisos, reglas y transacciones de reservas.
- `storage.py`: SQLite local y PostgreSQL en producción, consultas parametrizadas e índices únicos.
- `domain.py`: validaciones, contraseñas, bloques, salas y zona horaria.
- `manage.py`: inicialización, alta/recuperación del encargado y servidor de desarrollo.
- `tests/test_system.py`: pruebas automatizadas de reglas, autorización y solicitudes concurrentes.

El servidor Python WSGI reemplaza el archivo Flask anterior; el punto de entrada de Gunicorn sigue siendo `app:app`. Esto permite ejecutar y probar el prototipo local con la biblioteca estándar de Python. La interfaz y la API se sirven desde **el mismo origen**; no se usa CORS abierto. El servidor local `wsgiref` es exclusivamente para desarrollo, nunca para Internet.

Las decisiones de escritura se serializan en SQLite con `BEGIN IMMEDIATE` y en PostgreSQL con un bloqueo transaccional `pg_advisory_xact_lock`. Los índices únicos refuerzan que no se duplique una sala ni una persona en el mismo bloque. Este enfoque privilegia consistencia y simplicidad para un piloto de siete salas; el bloqueo global debe reevaluarse si aumenta considerablemente la escala.

## Despliegue propuesto en Render

No reemplazar la web actual sin revisar y probar esta versión. El paquete no contiene una base de datos ni credenciales.

1. Crear una **base PostgreSQL nueva y separada para el piloto**.
2. Crear un servicio web Python con el código de esta versión.
3. Comando de instalación: `pip install -r requirements.txt`.
4. Comando de inicio: `gunicorn app:app --workers 2 --bind 0.0.0.0:$PORT`.
5. Configurar `DATABASE_URL` con la conexión del nuevo piloto y `APP_ORIGIN` con el origen HTTPS exacto donde se abre la web (sin ruta). Para Netlify, usar `https://reservaust.netlify.app`. Si se usa únicamente Render y no se define `APP_ORIGIN`, se utiliza `RENDER_EXTERNAL_URL`, proporcionado por Render.
6. `DB_SSLMODE` usa `require`. Para verificar el certificado y el nombre del servidor, configurar `verify-full` y la CA apropiada según el proveedor de PostgreSQL. No deshabilitar TLS.
7. Desde la consola privada del servicio, ejecutar `python manage.py create-admin`.
8. Probar registro, aprobación, reservas desde dos navegadores, cancelación, cierre de sesión y persistencia tras reiniciar.

### Mantener Netlify como dirección de la web

El archivo `netlify.toml` incorpora el proxy `/api/*` hacia `https://ust-reserves.onrender.com/api/*`. El navegador continúa usando la dirección de Netlify para las solicitudes y cookies. El comando `node scripts/build-static.mjs` prepara `dist/` con solo los archivos públicos; no publica Python, pruebas ni bases de datos.

1. En Render → Environment, establecer `APP_ORIGIN=https://reservaust.netlify.app` y verificar que `DATABASE_URL` exista con la conexión PostgreSQL del piloto. No copiar esa conexión al frontend ni al repositorio.
2. Guardar los cambios y volver a desplegar Render.
3. En Netlify, desplegar el mismo commit y usar el comando y carpeta de publicación definidos en `netlify.toml` (`node scripts/build-static.mjs` y `dist`).
4. Abrir la dirección de Netlify. Sin iniciar sesión, `/api/session` debe responder **401 con JSON**, no 404 ni HTML. Ese 401 confirma que la solicitud llegó a la API protegida.
5. Probar ingreso y cierre de sesión; los POST deben conservar el origen de Netlify y las cookies deben permanecer en ese origen. No es necesario habilitar CORS abierto.

También se puede servir la web directamente desde Render, configurando `APP_ORIGIN` con su dirección. Se debe usar el origen configurado para las operaciones de escritura; si se cambia de proveedor o dominio, actualizarlo.

### Diagnóstico de inicio

- Error antiguo `Producción requiere APP_ORIGIN=https://... y DATABASE_URL`: faltaba alguna de las dos variables. La versión corregida identifica en los logs cuál falta y devuelve 503 sin una excepción no controlada.
- `HEAD /` y `HEAD /health`: están admitidos, conservan las cabeceras de GET y no devuelven cuerpo.
- `/reservas`: endpoint retirado; responde 410 y pide recargar la web. No se restablece el acceso anónimo anterior.
- 503 relacionado con datos anteriores: revisar la sección de migración; no borrar registros para evitar el control.
- Fallo de conexión: revisar `DATABASE_URL`, disponibilidad del PostgreSQL y dependencias. La aplicación no incluye secretos en la respuesta de error.

Referencias de despliegue: [variables automáticas de Render](https://render.com/docs/environment-variables) y [proxy de Netlify](https://docs.netlify.com/manage/routing/redirects/rewrites-proxies/).

### Datos anteriores

No se migran ni se borran automáticamente. Si se detecta una tabla `reservas` anterior con registros, el inicio se detiene con un mensaje. Las reservas anteriores no cuentan con identidad verificada; asignarlas automáticamente a las cuentas nuevas sería inseguro. Conservar una copia de la base original y acordar con biblioteca qué registros migrar y cómo verificar sus responsables. Mantener las dos instalaciones separadas hasta resolverlo.

### Operación del piloto

Definir con biblioteca días hábiles, horarios, capacidades reales, criterio de aprobación, tratamiento de cancelaciones después del inicio y retención de registros. Los datos permanecen en la base hasta que se aplique una política de retención; no existe purga automática. Configurar copias de seguridad y probar la recuperación. El registro de auditoría es consultable en la base; no tiene una pantalla propia.

Los límites de intentos de ingreso y registro se guardan en la base. Detrás de un proxy, `REMOTE_ADDR` puede representar al proxy y agrupar varios usuarios; calibrar los límites durante el piloto y configurar el perímetro de red. No se confía automáticamente en `X-Forwarded-For`.

## Verificación

```text
python -m unittest discover -s tests -v
node --check static/app.js
```

La suite cubre la API WSGI y SQLite sin abrir sockets, incluidos conflictos simultáneos entre usuarios. Ver `docs/VALIDACION.md` para los resultados y límites de la revisión. Falta ejecutar las pruebas contra PostgreSQL de ensayo y revisar visualmente en navegadores reales antes de publicar.

El tablero informa **bloques reservados**: no representa asistencia o uso físico comprobado. Los registros del prototipo sirven para evaluar su funcionamiento; no son evidencia de una mejora institucional hasta realizar y medir un piloto autorizado.
