from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def hello():
    return {"message": "백엔드 서버 작동 중!"}