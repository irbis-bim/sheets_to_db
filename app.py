import streamlit as st
import pandas as pd
import sqlalchemy
import os
import json
import re
import requests
import io

# --- НАСТРОЙКИ И ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ ---
DATABASE_URL = os.getenv("DATABASE_URL")
SHEETS_CONFIG_JSON = os.getenv("SHEETS_CONFIG", '{}')

try:
    SHEETS_CONFIG = json.loads(SHEETS_CONFIG_JSON)
except json.JSONDecodeError:
    st.error("Ошибка парсинга переменной SHEETS_CONFIG. Проверьте формат JSON.")
    st.stop()

if not DATABASE_URL:
    st.error("Переменная окружения DATABASE_URL не задана.")
    st.stop()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def extract_sheet_id(url):
    match = re.search(r'/d/(?:e/)?([a-zA-Z0-9-_]+)', url)
    return match.group(1) if match else None

def get_sheet_names(sheet_id):
    """Получает названия листов через скачивание метаданных XLSX."""
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            excel_file = pd.ExcelFile(io.BytesIO(resp.content))
            return excel_file.sheet_names
    except Exception as e:
        st.warning(f"Не удалось автоматически получить список листов: {e}")
    return None

def fetch_sheet_data(sheet_id, sheet_name):
    encoded_name = requests.utils.quote(sheet_name)
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={encoded_name}"
    
    resp = requests.get(url, timeout=15)
    if resp.status_code == 200:
        df = pd.read_csv(io.StringIO(resp.text))
        return df
    else:
        raise Exception(f"Ошибка при загрузке данных. Статус: {resp.status_code}")

# --- ИНТЕРФЕЙС STREAMLIT ---

st.set_page_config(page_title="Экспорт Google Sheets -> PostgreSQL", layout="wide")
st.title("Экспорт данных из чек-листов в базу данных")

st.sidebar.header("Настройки экспорта")

if not SHEETS_CONFIG:
    st.warning("Список таблиц пуст. Добавьте их в переменную окружения SHEETS_CONFIG.")
    st.stop()

selected_table_name = st.sidebar.selectbox("1. Выберите таблицу", list(SHEETS_CONFIG.keys()))
sheet_url = SHEETS_CONFIG[selected_table_name]
sheet_id = extract_sheet_id(sheet_url)

if not sheet_id:
    st.sidebar.error("Неверный формат ссылки на Google Sheets")
    st.stop()

# Автоматическое получение листов
available_sheets = get_sheet_names(sheet_id)

if available_sheets:
    selected_sheet = st.sidebar.selectbox("2. Выберите лист", available_sheets)
else:
    st.sidebar.warning("Не удалось получить список листов автоматически.")
    selected_sheet = st.sidebar.text_input("Введите имя листа вручную", value="Лист1")

# --- СКРЫТЫЕ НАСТРОЙКИ БД (НЕ ОТОБРАЖАЮТСЯ В ИНТЕРФЕЙСЕ) ---
db_schema = "check_list"
db_table_name = "checklist_details_new"

if st.sidebar.button("Начать экспорт"):
    with st.status(f"Экспорт листа '{selected_sheet}'...", expanded=True) as status:
        try:
            # Шаг 1: Чтение данных
            st.write("Подключение к Google Sheets и чтение данных...")
            df = fetch_sheet_data(sheet_id, selected_sheet)
            st.write(f"Успешно загружено строк: {len(df)}")
            
            if df.empty:
                st.warning("Лист пуст. Нечего экспортировать.")
                status.update(label="Экспорт прерван: лист пуст", state="warning")
                st.stop()

            # Шаг 2: Очистка и нормализация данных
            st.write("Очистка и подготовка данных...")
            
            # Удаляем строки, которые выглядят как разделители markdown
            df = df[~df.astype(str).apply(lambda x: x.str.contains(r'^\|?---\|?$', regex=True)).any(axis=1)]
            
            # Удаляем полностью пустые столбцы
            df = df.dropna(axis=1, how='all')
            
            # Приводим названия колонок к нижнему регистру и заменяем пробелы на подчеркивания
            df.columns = [str(col).strip().lower().replace(' ', '_') for col in df.columns]
            
            # ФИЛЬТР: Удаляем строки, где project_code выглядит как ссылка (артефакт парсинга Google)
            if 'project_code' in df.columns:
                df = df[~df['project_code'].astype(str).str.contains('http', na=False)]
            
            # ИСПРАВЛЕНИЕ ОШИБКИ: Преобразование запятых в точки для числовых колонок
            numeric_cols = ['check_type_num', 'check_id', 'score', 'criteria', 'total', 'checklist_id']
            
            for col in numeric_cols:
                if col in df.columns:
                    # Заменяем запятую на точку
                    df[col] = df[col].astype(str).str.replace(',', '.', regex=False)
                    # Преобразуем в числовой тип. errors='coerce' превратит нечисловые значения (например, "k.lod") в NULL
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # Заполняем NaN значениями None для корректной вставки NULL в PostgreSQL
            df = df.where(pd.notnull(df), None)
            
            st.write(f"Данные очищены. Готово к загрузке строк: {len(df)}")

            # Шаг 3: Подключение к БД
            st.write("🔌 Подключение к PostgreSQL...")
            engine = sqlalchemy.create_engine(DATABASE_URL)
            inspector = sqlalchemy.inspect(engine)
            
            if db_schema not in inspector.get_schema_names():
                st.error(f"Схема '{db_schema}' не найдена в БД!")
                status.update(label="Ошибка: схема не найдена", state="error")
                st.stop()
                
            if not inspector.has_table(db_table_name, schema=db_schema):
                st.error(f"Таблица '{db_table_name}' не найдена в схеме '{db_schema}'!")
                status.update(label="Ошибка: таблица не найдена", state="error")
                st.stop()
                
            # Фильтруем колонки: оставляем только те, что есть в БД
            db_columns = [c['name'] for c in inspector.get_columns(db_table_name, schema=db_schema)]
            
            # Находим пересечение колонок
            cols_to_insert = [c for c in df.columns if c in db_columns]
            df_filtered = df[cols_to_insert]
            
            if df_filtered.empty:
                st.error("Ни одна колонка из листа не совпадает со структурой таблицы в БД.")
                st.info(f"Ожидаемые колонки в БД: {', '.join(db_columns)}")
                status.update(label="Ошибка: несовпадение колонок", state="error")
                st.stop()
                
            st.write(f"Найдено совпадающих колонок: {len(cols_to_insert)} из {len(db_columns)}")

            # Шаг 4: Загрузка в БД
            st.write(f"Загрузка данных в PostgreSQL...")
            
            df_filtered.to_sql(
                name=db_table_name, 
                con=engine, 
                schema=db_schema,       
                if_exists='append',     
                index=False,            
                chunksize=1000          
            )
            
            st.write(f"Успешно добавлено {len(df_filtered)} строк!")
            status.update(label="Экспорт успешно завершен!", state="complete", expanded=False)

        except Exception as e:
            st.error(f"Произошла ошибка: {str(e)}")
            status.update(label="Экспорт завершен с ошибкой", state="error")

else:
    st.info("Выберите таблицу и лист в левой панели, затем нажмите **Начать экспорт**.")
