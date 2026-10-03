import { ApiError, NetworkError, SessionExpiredError } from "../api/client";
import { errorText } from "../i18n/explanations";

export function describeError(error: unknown): string {
  if (error instanceof SessionExpiredError) return "Tu sesión venció. Iniciá sesión de nuevo para continuar; lo que escribiste sigue en pantalla.";
  if (error instanceof NetworkError) return "No pudimos conectar con el servicio. Revisá tu conexión y volvé a intentar.";
  if (error instanceof ApiError) {
    if (error.code && errorText[error.code]) return errorText[error.code];
    if (error.status === 404) return errorText.not_found;
    if (error.status === 422) return "Revisá los datos ingresados: hay un valor que no es válido.";
    if (error.status === 429) return "Hiciste muchos pedidos seguidos. Esperá un minuto y volvé a intentar.";
    if (error.status >= 500) return "Hubo un problema del servicio. Volvé a intentar en unos minutos.";
  }
  return "Algo salió mal. Volvé a intentar.";
}
