import os
import time
import requests
import pandas as pd
from sqlalchemy import create_engine

def main():
    # 1. Забираем всё из переменных окружения
    script_url = os.getenv("APPSCRIPT_URL")
    secret_token = os.getenv("APPSCRIPT_TOKEN")
    database_url = os.getenv("DATABASE_URL")
    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    sheet_name = os.getenv("SHEET_NAME")

    if not all([script_url, secret_token, database_url, spreadsheet_id, sheet_name]):
        raise ValueError("Не все переменные окружения заданы!")

    # 2. Запрос к Apps Script
    params = {
        "token": secret_token,
        "spreadsheet_id": spreadsheet_id,
        "sheet_name": sheet_name,
        "_": int(time.time()) # Защита от кэша
    }
    
    print(f"🔄 Запрос данных из листа '{sheet_name}'...")
    response = requests.get(script_url, params=params, timeout=120)
    response.raise_for_status()
    
    payload = response.json()
    if "error" in payload:
        raise Exception(f"Ошибка Apps Script: {payload['error']}")

    data_list = payload.get("data", [])
    if not data_list:
        print("⚠️ Данные пусты. Нечего выгружать.")
        return
        
    df = pd.DataFrame(data_list)
    print(f"📊 Получено строк: {len(df)}")

    # 3. Подключение к БД
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    engine = create_engine(database_url)

    # 4. Выгрузка в БД
    db_table_name = sheet_name.lower().replace(" ", "_").replace("-", "_")
    print(f"💾 Загрузка данных в таблицу '{db_table_name}'...")
    
    df.to_sql(
        name=db_table_name, 
        con=engine, 
        if_exists='replace', 
        index=False,
        chunksize=1000
    )
    print("✅ Успешно выгружено в базу данных!")

if __name__ == "__main__":
    main()
