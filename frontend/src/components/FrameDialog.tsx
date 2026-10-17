import { useEffect, useRef, useState } from "react";
import { Minus, Plus, X } from "lucide-react";
import { timecode } from "../api";
import type { Frame } from "../api";

export function FrameDialog({
  frame,
  onClose,
}: {
  frame: Frame;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const [zoomed, setZoomed] = useState(false);
  useEffect(() => {
    const node = dialog.current;
    const previous =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    node?.showModal();
    closeButton.current?.focus();
    return () => {
      node?.close();
      previous?.focus();
    };
  }, []);
  return (
    <dialog
      ref={dialog}
      className="frame-dialog"
      aria-labelledby="frame-title"
      onKeyDown={(event) => {
        if (event.key !== "Tab" || !dialog.current) return;
        const controls = Array.from(
          dialog.current.querySelectorAll<HTMLElement>(
            'button:not([disabled]), [tabindex="0"]',
          ),
        ).filter((element) => element.getClientRects().length > 0);
        if (!controls.length) return;
        const first = controls[0];
        const last = controls[controls.length - 1];
        const active = document.activeElement;
        if (
          event.shiftKey &&
          (active === first || !dialog.current.contains(active))
        ) {
          event.preventDefault();
          last.focus();
        } else if (
          !event.shiftKey &&
          (active === last || !dialog.current.contains(active))
        ) {
          event.preventDefault();
          first.focus();
        }
      }}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
    >
      <div className="frame-toolbar">
        <div>
          <h2 id="frame-title">Кадр · {timecode(frame.timestamp_sec)}</h2>
          <p>Из загруженной записи</p>
        </div>
        <div>
          <button
            className="button secondary"
            aria-pressed={zoomed}
            onClick={() => setZoomed(!zoomed)}
          >
            {zoomed ? <Minus size={17} /> : <Plus size={17} />}
            {zoomed ? "Уместить" : "Увеличить 2×"}
          </button>
          <button
            ref={closeButton}
            autoFocus
            className="icon-button"
            onClick={onClose}
            aria-label="Закрыть просмотр кадра"
          >
            <X size={22} />
          </button>
        </div>
      </div>
      <div
        className={`frame-viewport ${zoomed ? "zoomed" : ""}`}
        tabIndex={0}
        aria-label="Область кадра. При увеличении используйте прокрутку."
      >
        <img
          src={`data:image/jpeg;base64,${frame.image_base64}`}
          alt={`Увеличенный кадр на отметке ${timecode(frame.timestamp_sec)}`}
        />
      </div>
      <p className="frame-help">
        Escape — закрыть. При увеличении прокручивайте изображение для просмотра
        деталей.
      </p>
    </dialog>
  );
}
