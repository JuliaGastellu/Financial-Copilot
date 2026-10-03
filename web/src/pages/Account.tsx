import { useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { TextField } from "../components/fields";
import { Alert, Button, ConfirmDialog, PageTitle } from "../components/ui";
import { useAppData } from "../data/AppData";
import { describeError } from "../data/errors";

const CONFIRM_WORD = "BORRAR";

export function AccountPage() {
  const { api } = useAppData();
  const { signOut } = useAuth();
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [deleted, setDeleted] = useState(false);

  const exportData = async () => {
    setExporting(true);
    setError(null);
    try {
      const blob = await api.download("/v1/me/export");
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "mis-datos-financial-copilot.json";
      link.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(describeError(e));
    } finally {
      setExporting(false);
    }
  };

  const deleteAccount = async () => {
    if (confirmText !== CONFIRM_WORD) return;
    setDeleting(true);
    setError(null);
    try {
      await api.request("/v1/me", { method: "DELETE" });
      setConfirmOpen(false);
      setDeleted(true);
    } catch (e) {
      setError(describeError(e));
      setConfirmOpen(false);
    } finally {
      setDeleting(false);
    }
  };

  if (deleted) {
    return (
      <div className="stack narrow">
        <PageTitle>Borramos tu cuenta</PageTitle>
        <Alert tone="success">
          <p>Eliminamos tu perfil, metas, planes, escenarios y avances. Las copias de seguridad vencen en su plazo y, si se restauran, el borrado se vuelve a aplicar.</p>
        </Alert>
        <Button onClick={() => void signOut()}>Cerrar sesión</Button>
      </div>
    );
  }

  return (
    <div className="stack narrow">
      <PageTitle>Cuenta</PageTitle>
      {error && (
        <Alert tone="error">
          <p>{error}</p>
        </Alert>
      )}
      <section className="card" aria-labelledby="export-title">
        <h2 id="export-title">Descargar tus datos</h2>
        <p>Un archivo con tu perfil, metas, planes, escenarios, avances y el registro de acciones de tu cuenta.</p>
        <Button variant="secondary" onClick={() => void exportData()} pending={exporting} pendingLabel="Preparando archivo…">
          Descargar mis datos
        </Button>
      </section>
      <section className="card" aria-labelledby="session-title">
        <h2 id="session-title">Sesión</h2>
        <p>La sesión no se guarda en este navegador: al recargar o cerrar la pestaña tenés que volver a ingresar.</p>
        <Button variant="secondary" onClick={() => void signOut()}>
          Cerrar sesión
        </Button>
      </section>
      <section className="card danger-zone" aria-labelledby="delete-title">
        <h2 id="delete-title">Borrar tu cuenta</h2>
        <p>Borra todos tus datos financieros. No se puede deshacer.</p>
        <Button variant="danger" onClick={() => setConfirmOpen(true)}>
          Borrar mi cuenta
        </Button>
      </section>
      <ConfirmDialog
        open={confirmOpen}
        title="¿Borrar tu cuenta?"
        confirmLabel="Borrar definitivamente"
        danger
        pending={deleting}
        confirmDisabled={confirmText !== CONFIRM_WORD}
        onCancel={() => {
          setConfirmOpen(false);
          setConfirmText("");
        }}
        onConfirm={() => void deleteAccount()}
      >
        <p>Para confirmar, escribí {CONFIRM_WORD}.</p>
        <TextField label="Confirmación" value={confirmText} onChange={setConfirmText} autoComplete="off" />
      </ConfirmDialog>
    </div>
  );
}
