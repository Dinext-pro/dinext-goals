# Dinext Agent Navigation Stub

Общие агентные инструкции, навыки и правила для Dinext ведутся централизованно в sibling-репозитории `dinext-docs`. Этот файл в consumer-репозитории — указатель и **обязательный** порядок загрузки, а не краткая справка.

**Путь к central repo:** ниже предполагается типичный layout `frappe-bench/apps/<your_app>/` рядом с `frappe-bench/apps/dinext-docs/`. Если clone `dinext-docs` лежит иначе, подставьте фактический путь к корню репозитория `dinext-docs` вместо префикса `../dinext-docs/`.

## Обязательный порядок (до любой реализации / отладки / ревью)

1. Прочитать этот stub целиком.
2. Прочитать контракт доступа: `../dinext-docs/agents/ide/runtime-access.md`.
3. Прочитать реестр: `../dinext-docs/agents/registry/index.yaml` и открыть по задаче релевантные `content_path`.
4. Прочитать каноническое руководство-хаб: `../dinext-docs/agents/ide/agents/dinext-frappe-developer-guide.md`.
5. **Mandatory OpenSpec (до любых правок):** `../dinext-docs/agents/ide/rules/openspec-mandatory-workflow.md` и `../dinext-docs/agents/ide/skills/openspec-development-workflow/SKILL.md`. Проверить Store (`openspec doctor` / `openspec context`); lifecycle вести через slash-команды `/opsx-propose`, `/opsx-update`, `/opsx-apply`, `/opsx-sync`, `/opsx-archive` (локальные копии в `.cursor/commands/`, source — `dinext-docs`). Без готовых proposal/design/specs/tasks реализация, hotfix и commit запрещены. Исключений нет. Store: `../dinext-docs/process/development-management/openspec-store.md`.
6. По таблице навигации в hub открыть только релевантные topic assets: `../dinext-docs/agents/ide/guides/frappe/`, `../dinext-docs/agents/ide/skills/`; optional reference `../dinext-docs/agents/ide/reference/frappe/` — только при явной необходимости.
7. При необходимости — другие central rules и workflow предложений shared-артефактов: `../dinext-docs/agents/ide/rules/`, `../dinext-docs/agents/ide/proposals/README.md`.

**Не начинать** implementation, debug с исправлением, hotfix или review-fix в этом приложении, пока не выполнены шаги 2–5 (минимум, включая OpenSpec gate). После шага 4–5 нужно поднять именно релевантные topic assets из hub/registry, а не оставаться только на уровне заголовка. Пропуск central слоя после чтения stub — **нарушение процесса**, а не допустимый fallback; полный контракт и приоритеты см. в `runtime-access.md`.

## Приоритет

**Central Dinext layer** (реестр + runtime-access + developer guide + mandatory OpenSpec + опубликованные central skills/rules) имеет **операционный приоритет** над встроенными generic Cursor/Compound skills и глобальными workflow.

Локальные `.cursor/skills/` и `.cursor/rules/` — только **дополнение** к central слою, не замена.

## Анти-паттерны

- Считать этот stub или `dinext-docs` опциональной справкой и сразу уходить в generic skills.
- Прочитать stub, но не открыть registry, developer guide и OpenSpec gate перед работой.
- Начинать hotfix/багфикс/фичу без OpenSpec change в Store.
- Дублировать shared-артефакты или локальные `openspec/specs|changes` в этом репозитории.

## Дополнительные пути (после минимального набора)

- `../dinext-docs/agents/ide/guides/frappe/`
- `../dinext-docs/agents/ide/skills/`
- `../dinext-docs/agents/ide/reference/frappe/`
- `../dinext-docs/agents/ide/rules/`
- `../dinext-docs/agents/ide/proposals/README.md`
- `../dinext-docs/process/development-management/openspec-store.md`

## Локально в этом приложении допустимы только

- app-specific skills в `.cursor/skills/`, если они относятся только к этому приложению;
- app-specific rules в `.cursor/rules/`, если они относятся только к этому приложению;
- config-only OpenSpec pointer: `openspec/config.yaml` с единственной строкой `store: dinext-docs` (без локальных `openspec/specs` и `openspec/changes`);
- синхронизированные копии slash-команд `.cursor/commands/opsx-*.md` из `dinext-docs` (не править локально; sync: `python3 ../dinext-docs/scripts/sync_opsx_commands.py --apply`);
- опционально: скопировать в `.cursor/rules/` содержимое `../dinext-docs/agents/ide/navigation/consumer-always-apply-rule.mdc.example` (переименовать в `.mdc`), чтобы IDE поднимала central-first порядок автоматически.

Если нужный shared-артефакт отсутствует локально, не создавай его в этом репозитории. Добавляй или обновляй его в `dinext-docs`.

Если хочешь предложить изменение shared-артефакта (не product OpenSpec change), используй central proposal workflow через `../dinext-docs/agents/ide/proposals/inbox/`.

## Если central слой уже был пропущен в сессии

Останови текущую линию выполнения, догрузи файлы из шагов выше (включая OpenSpec rule/skill), при правках без change — создай/свяжи change в Store, переоцени уже сделанные шаги; не продолжай тот же workstream без явной переоценки. Подробнее: `../dinext-docs/agents/ide/runtime-access.md` и Recovery в `openspec-mandatory-workflow.md`.
