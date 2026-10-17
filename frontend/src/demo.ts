export const DEMO_SCENARIOS = [
  { value: "violation", label: "Одно событие" },
  { value: "no_violation", label: "Нет событий" },
  { value: "multiple_events", label: "Несколько событий" },
  { value: "three_frames", label: "Три кадра у события" },
  { value: "long_text", label: "Длинные названия и описания" },
  { value: "demo_rule", label: "Вымышленный источник" },
  { value: "slow", label: "Медленная обработка" },
  { value: "ml_error", label: "Ошибка ML" },
  { value: "invalid_ml_response", label: "Некорректный ответ ML" },
] as const;
