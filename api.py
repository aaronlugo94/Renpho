import os
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def root():
    return {"status": "ok", "mensaje": "Control Metabólico API"}

@app.get("/health")
def health():
    return {"status": "ok"}
