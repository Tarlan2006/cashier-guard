import { useEffect, useRef, useState } from "react";
import {
  BookOpen,
  Check,
  Copy,
  Cpu,
  ExternalLink,
  FileVideo2,
  Layers,
  Scale,
  Server,
  Terminal,
} from "lucide-react";
import type { Job, Rule } from "../api";

export type WorkspaceTab =
  | "workspace"
  | "regulations"
  | "api"
  | "architecture"
  | "settings"
  | "history"
  | "analytics"
  | "review-queue";

function verifiedRule(rule: Rule | null): rule is Rule {
  if (
    !rule ||
    rule.is_demo ||
    typeof rule.id !== "string" ||
    rule.id.startsWith("demo:") ||
    !rule.url
  )
    return false;
  try {
    const url = new URL(rule.url);
    return (
      ["http:", "https:"].includes(url.protocol) &&
      !url.username &&
      !url.password
    );
  } catch {
    return false;
  }
}

export function WorkspaceSections({
  tab,
  job,
}: {
  tab: Exclude<
    WorkspaceTab,
    "workspace" | "settings" | "history" | "analytics" | "review-queue"
  >;
  job: Job | null;
}) {
  const [copyStatus, setCopyStatus] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  const rules = [
    ...new Map(
      (job?.mode === "live" ? job.violations : [])
        .map((event) => event.rule)
        .filter(verifiedRule)
        .map((rule) => [rule.id, rule]),
    ).values(),
  ];

  async function copyJson() {
    if (!job) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(job, null, 2));
      setCopyStatus("Скопировано");
    } catch {
      setCopyStatus("Не удалось скопировать. Выделите текст JSON вручную.");
    }
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopyStatus(""), 3000);
  }

  if (tab === "regulations")
    return (
      <section className="section-stack" aria-labelledby="regulations-heading">
        <div className="section-intro">
          <BookOpen size={23} />
          <div>
            <h1 id="regulations-heading">Нормативы РК</h1>
            <p>Источники, на которые ссылается текущая проверка.</p>
          </div>
        </div>
        {rules.length ? (
          <div className="rules-grid">
            {rules.map((rule) => (
              <article className="source-card" key={rule.id}>
                <span className="source-section">{rule.section}</span>
                <h2>{rule.title}</h2>
                <p>{rule.document}</p>
                <a href={rule.url} target="_blank" rel="noreferrer">
                  Открыть источник
                  <ExternalLink size={14} />
                </a>
              </article>
            ))}
          </div>
        ) : (
          <div className="section-empty">
            <Scale size={32} />
            <h2>Источников пока нет</h2>
            <p>
              Здесь появятся ссылки из результата реального анализа. Вымышленные
              нормативы из демопроверок в этот раздел не включаются.
            </p>
          </div>
        )}
      </section>
    );

  if (tab === "api")
    return (
      <section className="section-stack" aria-labelledby="api-heading">
        <div className="section-intro">
          <Terminal size={23} />
          <div>
            <h1 id="api-heading">API сервиса</h1>
            <p>Запросы анализа и фактический ответ текущей проверки.</p>
          </div>
        </div>
        <div className="api-grid">
          <div className="api-description">
            <h2>REST API</h2>
            <div className="endpoint">
              <span>POST</span>
              <code>/api/v1/analyze</code>
            </div>
            <div className="endpoint">
              <span>GET</span>
              <code>/api/v1/jobs/{"{job_id}"}</code>
            </div>
            <div className="endpoint">
              <span>GET</span>
              <code>/api/v1/jobs</code>
            </div>
            <div className="endpoint">
              <span>DELETE</span>
              <code>/api/v1/jobs/{"{job_id}"}</code>
            </div>
            <div className="endpoint">
              <span>GET</span>
              <code>/api/v1/jobs/{"{job_id}"}/video</code>
            </div>
            <div className="endpoint">
              <span>PATCH</span>
              <code>
                /api/v1/jobs/{"{job_id}"}/events/{"{event_id}"}/review
              </code>
            </div>
            <div className="endpoint">
              <span>GET</span>
              <code>/api/v1/analytics</code>
            </div>
            <p>
              Авторизация — заголовок <code>X-API-Key</code>. Ключ доступа не
              включается в JSON результата.
            </p>
            <p>
              Ответ сохраняет режим сервиса, состояние обработки, события,
              таймкоды и доступные доказательства.
            </p>
          </div>
          <div className="json-panel">
            <div className="json-heading">
              <h2>JSON Response</h2>
              {job && (
                <button
                  className="button secondary"
                  onClick={() => void copyJson()}
                >
                  {copyStatus === "Скопировано" ? (
                    <Check size={15} />
                  ) : (
                    <Copy size={15} />
                  )}
                  {copyStatus === "Скопировано" ? "Скопировано" : "Копировать"}
                </button>
              )}
            </div>
            {job ? (
              <pre tabIndex={0} aria-label="JSON ответа сервиса">
                {JSON.stringify(job, null, 2)}
              </pre>
            ) : (
              <div className="json-empty">
                <Terminal size={27} />
                <p>
                  Ответ появится после отправки видео на анализ или
                  восстановления сохранённой проверки.
                </p>
              </div>
            )}
            <p className="copy-status" role="status">
              {copyStatus}
            </p>
          </div>
        </div>
      </section>
    );

  return (
    <section className="section-stack" aria-labelledby="architecture-heading">
      <div className="section-intro">
        <Cpu size={23} />
        <div>
          <h1 id="architecture-heading">Архитектура обработки</h1>
          <p>От локального видео к событиям и доказательствам.</p>
        </div>
      </div>
      <div className="architecture-panel">
        <ol className="pipeline-flow">
          <li>
            <FileVideo2 size={23} />
            <h2>Видеозапись</h2>
            <p>Выбор файла и загрузка с ключом доступа.</p>
          </li>
          <li>
            <Server size={23} />
            <h2>Подготовка</h2>
            <p>Проверка файла и преобразование в MP4 через FFmpeg.</p>
          </li>
          <li>
            <Cpu size={23} />
            <h2>ML1</h2>
            <p>Наблюдения, временные отметки и JPEG-кадры.</p>
          </li>
          <li>
            <Layers size={23} />
            <h2>ML2</h2>
            <p>Сопоставление наблюдений с каталогом правил.</p>
          </li>
          <li>
            <Scale size={23} />
            <h2>Проверка человеком</h2>
            <p>События, кадры и источники для принятия решения.</p>
          </li>
        </ol>
        <div className="architecture-note">
          <Server size={18} />
          <p>
            Новые проверки доступны только при готовом сервисе реального
            анализа. Интерфейс не заменяет ответ моделей демонстрационными
            событиями. Доступный порт модели сам по себе не подтверждает
            корректность анализа.
          </p>
        </div>
      </div>
    </section>
  );
}
