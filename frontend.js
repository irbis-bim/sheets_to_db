document.getElementById('syncButton').addEventListener('click', async () => {
    const button = document.getElementById('syncButton');
    const btnText = button.querySelector('.btn-text');
    const btnLoader = button.querySelector('.btn-loader');
    const resultMsg = document.getElementById('resultMessage');
    
    const urlInput = document.getElementById('sheetUrl').value.trim();
    const sheetName = document.getElementById('sheetName').value.trim();

    // 1. Валидация и извлечение ID таблицы из URL
    // Регулярка ищет строку между /d/ и /edit (или /htmlview)
    const match = urlInput.match(/\/spreadsheets\/d\/([a-zA-Z0-9-_]+)/);
    
    if (!match || !match[1]) {
        showResult('Ошибка: Неверный формат ссылки. Убедитесь, что это ссылка на Google Таблицу.', false);
        return;
    }
    
    const spreadsheetId = match[1]; // Вот он, наш ID!

    if (!sheetName) {
        showResult('Ошибка: Укажите имя листа.', false);
        return;
    }

    // 2. Блокируем кнопку и показываем лоадер
    button.disabled = true;
    btnText.style.display = 'none';
    btnLoader.style.display = 'inline';
    resultMsg.style.display = 'none';

    try {
        // 3. Отправляем запрос на наш бэкенд (Render)
        const response = await fetch('/api/sync-data', { 
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                spreadsheet_id: spreadsheetId, 
                sheet_name: sheetName 
            })
        });
        
        const result = await response.json();
        
        // 4. Обрабатываем ответ
        if (response.ok && result.status === 'success') {
            showResult(result.message, true);
        } else {
            // Если бэкенд вернул ошибку (например, нет прав на таблицу или лист не найден)
            showResult('Ошибка выгрузки: ' + (result.detail || 'Неизвестная ошибка'), false);
        }
    } catch (error) {
        showResult('Сетевая ошибка. Проверьте подключение к интернету.', false);
    } finally {
        // 5. Возвращаем кнопку в исходное состояние
        button.disabled = false;
        btnText.style.display = 'inline';
        btnLoader.style.display = 'none';
    }
});

// Вспомогательная функция для вывода красивых уведомлений
function showResult(message, isSuccess) {
    const resultMsg = document.getElementById('resultMessage');
    resultMsg.textContent = message;
    resultMsg.className = 'result-msg ' + (isSuccess ? 'success' : 'error');
}
