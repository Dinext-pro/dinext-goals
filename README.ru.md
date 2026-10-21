[English](README.md)

<!-- dinext-presentation:start -->
<p align="center">
  <a href="https://dinext.ru"><img src="docs/assets/readme/dinext-logo.png" alt="Dinext" width="128"></a>
</p>
<h1 align="center">Dinext Goals</h1>

<hr>

<p align="center">Настройка целей и показателей, кампании целей, контроль результатов через карты целей и согласования.</p>

<p align="center">
  <img src="docs/assets/readme/overview.png" alt="Пример карты целей из документации платформы Dinext." width="960">
</p>
<p align="center"><sub>Пример карты целей из документации платформы Dinext.</sub></p>

<p align="center">
  <a href="https://dinext.ru">Сайт</a> · <a href="https://docs.dinext.ru">Документация</a>
</p>
<!-- dinext-presentation:end -->

# Dinext Goals

Frappe-приложение для стека ERPNext Dinext. Каркас product app: модуль `Dinext Goals`, без DocType.

Репозиторий: `erpnext/dinext/dinext-goals`.

## Зависимости

- `dinext_common`
- `erpnext`

## Установка

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app https://dinext.gitlab.yandexcloud.net/erpnext/dinext/dinext-goals.git --branch develop
bench install-app dinext_goals
```
