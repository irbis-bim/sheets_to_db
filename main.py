import os
import time
import requests
import pandas as pd
from sqlalchemy import create_engine
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI()

# Принимаем от фронта и ID таблицы, и имя листа
class SyncRequest(BaseModel):
    spreadsheet_id: str
    sheet_name: str

def sync_sheets_to_postgres(spreadsheet_id: str, sheet_name: str):
    script_url = os.getenv("APPSCRIPT_URL")
    secret_token = os.getenv("APPSCRIPT_TOKEN")
    database_url = os.getenv("DATABASE_URL")
    
    if not all([script_url, secret_token, database_url]):
        raise ValueError("Не все переменные окружения заданы в Render!")

    params = {
        "token": secret_token,
        "spreadsheet_id": spreadsheet_id,
        "sheet_name": sheet_name,
        "_": int(time.time())
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

    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    engine = create_engine(database_url)

    # Имя таблицы в БД = имя листа (очищенное)
    db_table_name = sheet_name.lower().replace(" ", "_").replace("-", "_")
    
    df.to_sql(
        name=db_table_name, 
        con=engine, 
        if_exists='replace', 
        index=False,
        chunksize=1000
    )
    
    return len(df)

@app.post("/api/sync-data")
def trigger_sync(request: SyncRequest):
    try:
        rows_count = sync_sheets_to_postgres(request.spreadsheet_id, request.sheet_name)
        return JSONResponse(content={
            "status": "success", 
            "message": f"Успех! Из листа '{request.sheet_name}' выгружено строк: {rows_count}"
        })
    except Exception as e:
        print(f"CRITICAL SYNC ERROR: {str(e)}") 
        raise HTTPException(status_code=500, detail=str(e))
