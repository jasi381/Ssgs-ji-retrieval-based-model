import json
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

# Import the core logic from our local MCP server
from sggs_mcp.server import smart_search, get_ang, get_shabad

app = FastAPI(title="SGGS MCP Demo App")

# Allow CORS for local Next.js/Vite frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify the frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/search")
def search_api(q: str = Query(..., description="The query string")):
    try:
        # Call the MCP tool directly; it returns a JSON string
        result_json = smart_search(query=q, limit=10)
        return Response(content=result_json, media_type="application/json")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/ang/{ang}")
def ang_api(ang: int):
    try:
        result_json = get_ang(ang=ang)
        if result_json.startswith("Ang "): # Quick error check based on the tool's error format
            raise HTTPException(status_code=404, detail=result_json)
        return Response(content=result_json, media_type="application/json")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/shabad/{shabad_id}")
def shabad_api(shabad_id: str):
    try:
        result_json = get_shabad(shabad_id=shabad_id)
        if result_json.startswith("Shabad "):
            raise HTTPException(status_code=404, detail=result_json)
        return Response(content=result_json, media_type="application/json")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
