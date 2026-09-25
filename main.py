import os
import time
import requests
import pandas as pd
from sqlalchemy import create_engine
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI()

# Модель для валидации входящего запроса от фронтенда
class SyncRequest(BaseModel):
    sheet_name: str

def sync_sheets_to_postgres(sheet_name: str):
    # 1. СТРОГО берем всё из Environment Variables Render
    script_url = os.getenv("APPSCRIPT_URL")
    secret_token = os.getenv("APPSCRIPT_TOKEN")
    database_url = os.getenv("DATABASE_URL")
    
    if not all([script_url, secret_token, database_url]):
        raise ValueError("Не все переменные окружения (APPSCRIPT_URL, APPSCRIPT_TOKEN, DATABASE_URL) заданы в Render!")

    # 2. Формируем параметры для Apps Script
    # Используем params, чтобы requests сам корректно закодировал кириллицу или пробелы в имени листа
    params = {
        "token": secret_token,
        "sheet_name": sheet_name,
        "_": int(time.time()) # защита от кэша
    }
    
    response = requests.get(script_url, params=params, timeout=60)
    
    if response.status_code != 200:
        raise Exception(f"Apps Script вернул HTTP {response.status_code}")

    payload = response.json()
    
    if "error" in payload:
        raise Exception(f"Ошибка Apps Script: {payload['error']}")

    data_list = payload.get("data", [])
    if not data_list:
        return 0
        
    df = pd.DataFrame(data_list)

    # 3. Подключение к БД (Render отдает postgres://, SQLAlchemy требует postgresql://)
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    engine = create_engine(database_url)

    # 4. Выгрузка в БД
    # Имя таблицы в БД можно сделать таким же, как имя листа, или жестко задать.
    # Здесь мы используем имя листа, очищенное для БД (нижний регистр, без пробелов).
    db_table_name = sheet_name.lower().replace(" ", "_").replace("-", "_")
    
    df.to_sql(
        name=db_table_name, 
        con=engine, 
        if_exists='replace', 
        index=False,
        chunksize=1000
    )
    
    return len(df)

# Эндпоинт, который принимает JSON от фронтенда
@app.post("/api/sync-data")
def trigger_sync(request: SyncRequest):
    try:
        rows_count = sync_sheets_to_postgres(request.sheet_name)
        return JSONResponse(content={
            "status": "success", 
            "message": f"Успех! Из листа '{request.sheet_name}' выгружено строк: {rows_count}"
        })
    except Exception as e:
        print(f"CRITICAL SYNC ERROR: {str(e)}") 
        raise HTTPException(status_code=500, detail=str(e))
