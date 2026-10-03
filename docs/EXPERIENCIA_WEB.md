# Experiencia web

Implementé una aplicación React con TypeScript y Vite en `web/` que consume la API v1. No calcula importes en el navegador: muestra lo que devuelve el backend y solo da formato a montos, fechas y porcentajes.

## Recorrido

1. **Inicio:** explico qué hace la herramienta y ofrezco iniciar sesión o ver una demo.
2. **Alta progresiva** en tres pasos:
   - moneda, ingreso y gasto mensual, e inclusión de pagos mínimos;
   - saldo disponible y meses de reserva;
   - una meta.

   Cada importe se marca como «Dato», «Estimación» o «No lo sé». Un dato desconocido no se convierte en cero, y cero es un valor declarado. Sin ingreso o gasto, guardo los datos y explico que hace falta al menos una estimación para calcular el plan.
3. **Situación:**
   - la próxima acción y su motivo;
   - el presupuesto del mes (disponible, reserva, deuda, metas y sin asignar);
   - las restricciones que cambian el reparto;
   - los datos declarados, con su procedencia.
4. **Plan mensual:** el reparto por meta y el historial de versiones.
5. **Metas:** alta, edición y baja con confirmación.
6. **Escenarios:** simular cambios de ingreso, gasto y rendimiento, comparar con el plan vigente y adoptar con confirmación explícita. Simular no cambia el plan.
7. **Revisión mensual:** comparar lo previsto con lo registrado y registrar aportes indicando si salieron del excedente o de ahorros ya declarados.
8. **Cómo lo calculé:**
   - fecha del cálculo, reglas aplicadas y versión del motor;
   - fórmulas;
   - supuestos y datos faltantes;
   - límites.
9. **Cuenta:** descargar los datos, cerrar sesión y borrar la cuenta (pide escribir «BORRAR» para confirmar).

La interfaz está en castellano y muestra montos con su código de moneda. No muestra identificadores internos, el modo del proveedor, probabilidades ni el catálogo ilustrativo.

## Sesión y almacenamiento

Uso `oidc-client-ts` con código de autorización y PKCE:

- El token queda solo en memoria (`InMemoryWebStorage`): al recargar la página hay que volver a ingresar.
- El estado temporal de PKCE usa `sessionStorage` durante la redirección.
- No guardo perfiles ni credenciales en `localStorage`. Una prueba unitaria y una de navegador lo verifican.
- Los datos de la cuenta viven en un proveedor de React que se vuelve a montar con cada sesión, así que otra cuenta no hereda datos en memoria.
- Si la sesión vence, muestro un aviso, conservo el formulario y ofrezco volver a iniciar sesión en una ventana emergente para no perder lo escrito. Si en esa ventana se ingresa con otra cuenta, descarto los datos de la anterior.

Para desarrollo y QA, `scripts/dev_oidc_provider.py` implementa un proveedor OIDC local: descubrimiento, autorización con PKCE S256, canje de código, JWKS y cierre de sesión. Escucha solo en 127.0.0.1, genera claves en memoria y acepta redirecciones únicamente a 127.0.0.1 o localhost. La API lo acepta solo fuera de producción.

## Estados y envíos

Cada vista contempla carga, vacío, error con reintento, sesión vencida y plan desactualizado; este último viene de `freshness` de la API.

Los botones de envío se deshabilitan con un guardia síncrono, porque el estado de React no alcanza a evitar dos clics seguidos. Las creaciones usan `Idempotency-Key` estable entre reintentos de un mismo envío. Si el alta falla a mitad de camino, al reintentar continúa desde el paso que falló sin duplicar la meta.

## Demo

`/demo` muestra datos ficticios generados con la API real por `scripts/build_web_demo.py`, sobre una base temporal. Está identificada como demo, es de solo lectura y no guarda nada.

## Seguridad del render

React escapa todo el texto; no uso `dangerouslySetInnerHTML`. El build agrega una política de seguridad de contenido que solo permite conectar con la API y el proveedor de identidad configurados, sin scripts ni estilos en línea.

## Ejecución

```bash
cd web
npm ci
cp .env.example .env.local
npm run dev
```

En otra terminal levanto el proveedor local (`python scripts/dev_oidc_provider.py`) y la API con:

- `OIDC_ISSUER=http://127.0.0.1:8765`
- `OIDC_AUDIENCE=financial-copilot-local`
- `OIDC_JWKS_URL=http://127.0.0.1:8765/jwks`
- `ALLOWED_ORIGINS=["http://127.0.0.1:5173"]`

## Verificación

El 3 de octubre de 2026 ejecuté:

- **Vitest (41 pruebas):**
  - lectura de importes y porcentajes;
  - selección de la próxima acción;
  - cliente HTTP (token, idempotencia, 401, errores con código, fallos de red);
  - alta con dato desconocido, estimado y cero;
  - formulario conservado ante un fallo;
  - doble clic sin envíos duplicados (esta prueba falla sin el guardia síncrono);
  - reintento con la misma clave, sin reenviar el perfil;
  - ausencia de escrituras en `localStorage`;
  - demo identificada y sin indicadores retirados;
  - descarte de datos al cambiar de cuenta.
- **Playwright con Chrome (18 pruebas):** los mismos 9 recorridos en escritorio (1280×800) y en móvil (360×740), contra la API real, el proveedor OIDC local y una base temporal:
  - alta → plan → escenario → adopción → avance mensual → «Cómo lo calculé»;
  - plan desactualizado y recálculo;
  - demo;
  - otra cuenta no ve datos de la anterior;
  - recargar no deja sesión guardada;
  - sesión vencida con el formulario conservado y reautenticación en ventana emergente;
  - análisis automático de accesibilidad (axe, WCAG 2.1 A y AA) en todas las páginas, sin desplazamiento horizontal a 360 px;
  - alta completa con teclado, con foco visible y foco en el título al navegar.

Revisé a ojo las capturas del recorrido con datos ficticios. Quedan fuera del repositorio, en el directorio de resultados de Playwright.

En la QA encontré y corregí tres errores:

- La API no permitía `Idempotency-Key` en CORS, así que el navegador bloqueaba las creaciones.
- Un doble clic podía enviar dos veces.
- A 360 px, el contenedor desplazable de las tablas no se podía recorrer con teclado.

No ejecuté el flujo de integración continua en GitHub ni revisé la consola del navegador en busca de avisos de la política de seguridad de contenido. No realicé pruebas con participantes: la usabilidad que reporto proviene de pruebas automatizadas y de mi revisión, no de personas usuarias.
