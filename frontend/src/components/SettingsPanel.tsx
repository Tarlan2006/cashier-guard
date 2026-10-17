import { useState } from "react";
import { Eye, EyeOff, KeyRound, Save, Settings, Trash2 } from "lucide-react";

export function SettingsPanel({
  savedKey,
  onSave,
  busy,
}: {
  savedKey: string;
  onSave: (key: string) => void;
  busy: boolean;
}) {
  const [draft, setDraft] = useState(savedKey);
  const [showKey, setShowKey] = useState(false);
  const [status, setStatus] = useState("");

  return (
    <section className="section-stack" aria-labelledby="settings-heading">
      <div className="section-intro">
        <Settings size={23} />
        <div>
          <h1 id="settings-heading">Настройки</h1>
          <p>Подключение сервиса проверки видео.</p>
        </div>
      </div>
      <form
        className="settings-panel"
        aria-labelledby="api-connection-heading"
        onSubmit={(event) => {
          event.preventDefault();
          if (busy || !draft.trim()) return;
          const next = draft.trim();
          onSave(next);
          setDraft(next);
          setShowKey(false);
          setStatus("Ключ сохранён");
        }}
      >
        <h2 id="api-connection-heading">Подключение API</h2>
        <p className="settings-description">
          Сохранённый ключ используется при загрузке видео и получении
          результатов.
        </p>
        <div className="key-field">
          <label htmlFor="api-key">
            <KeyRound size={16} />
            Ключ доступа к API
          </label>
          <div className="input-wrap">
            <input
              id="api-key"
              type={showKey ? "text" : "password"}
              value={draft}
              onChange={(event) => {
                setDraft(event.target.value);
                setStatus("");
              }}
              placeholder="Введите ключ сервиса"
              autoComplete="off"
              autoCapitalize="none"
              spellCheck={false}
              disabled={busy}
              aria-describedby="key-hint"
            />
            <button
              className="icon-button"
              aria-label={showKey ? "Скрыть ключ" : "Показать ключ"}
              aria-pressed={showKey}
              type="button"
              onClick={() => setShowKey(!showKey)}
            >
              {showKey ? <EyeOff size={19} /> : <Eye size={19} />}
            </button>
          </div>
          <small id="key-hint">
            Хранится в этой вкладке. Изменения применяются после сохранения.
          </small>
        </div>
        <div className="settings-actions">
          <button
            className="button primary"
            type="submit"
            disabled={busy || !draft.trim() || draft.trim() === savedKey}
          >
            <Save size={16} />
            Сохранить
          </button>
          <button
            className="button secondary"
            type="button"
            disabled={busy || (!savedKey && !draft)}
            onClick={() => {
              onSave("");
              setDraft("");
              setShowKey(false);
              setStatus("Ключ удалён");
            }}
          >
            <Trash2 size={16} />
            Удалить ключ
          </button>
        </div>
        {busy && (
          <p className="settings-status">
            Ключ можно изменить после завершения текущей проверки.
          </p>
        )}
        <p className="settings-status" role="status">
          {status}
        </p>
      </form>
    </section>
  );
}
