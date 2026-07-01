#!/bin/bash

echo "=== Copygram Startup Script ==="

# Функция проверки наличия программы
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Проверяем наличие python3
if ! command_exists python3; then
    echo "❌ ОШИБКА: python3 не установлен. Пожалуйста, установите Python 3."
    exit 1
fi

# Проверяем наличие pip3
if ! command_exists pip3; then
    echo "❌ ОШИБКА: pip3 не установлен. Пожалуйста, установите pip для Python 3."
    exit 1
fi

echo ">> Установка и обновление зависимостей (requirements.txt)..."
pip3 install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "❌ ОШИБКА: Не удалось установить зависимости. Проверьте права доступа или файл requirements.txt"
    exit 1
fi

echo ">> Проверка корректности установки..."
# Пробуем импортировать ключевые библиотеки, чтобы убедиться, что они реально доступны интерпретатору
python3 -c "import telethon; import flet" >/dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "❌ ОШИБКА: Зависимости установились с ошибкой или интерпретатор их не видит (проверьте переменные окружения)."
    exit 1
fi

echo "✅ Зависимости в норме!"
echo ">> Запуск Copygram (CLI-версия)..."
echo "----------------------------------------"
python3 main_cli.py
