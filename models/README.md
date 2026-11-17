# Модели

Модели в git не хранятся. Положите их в эту папку (или укажите другую папку в `MODELS_DIR` в `.env`):

```
models/
  Qwen2.5-3B-Instruct-Q4_K_M.gguf    <- языковая модель (имя файла = LLM_FILE в .env)
  bge-m3/                            <- модель эмбеддингов BAAI/bge-m3 (имя папки = EMB_MODEL_DIR)
    config.json
    pytorch_model.bin
    tokenizer.json
    sentencepiece.bpe.model
    colbert_linear.pt
    sparse_linear.pt
    ...
```

## Где взять

- **Qwen2.5-3B-Instruct-Q4_K_M.gguf** — например, с Hugging Face: `Qwen/Qwen2.5-3B-Instruct-GGUF` (~1.8 ГБ).
- **bge-m3** — `BAAI/bge-m3`. Если модель уже скачивалась через `huggingface_hub`, она лежит в
  `%USERPROFILE%\.cache\huggingface\hub\models--BAAI--bge-m3\snapshots\<hash>\`. Скопируйте содержимое
  этой папки в `models/bge-m3/`. Папку `onnx/` копировать не нужно.
  Скачать заново можно так:

  ```bash
  pip install huggingface_hub
  huggingface-cli download BAAI/bge-m3 --local-dir models/bge-m3 --exclude "onnx/*" "*.onnx*" "imgs/*"
  ```

Контейнеры подключают эту папку только на чтение и в интернет за моделями не ходят.
